"""Spoiler-fence tests for Dramatis. They do not import Hermes."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_package():
    name = "dramatis_plugin"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


load_package()

from dramatis_plugin import cast, fixture_book, gate, storage, tools  # noqa: E402

LATER = (
    "Pip Is the Curator",
    "Ellis Vale",
    "burned the east wing",
    "Spoilers ahead",
    "one and the same",
)


class DramatisFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.conn = sqlite3.connect(root / "data.db")
        self.conn.row_factory = sqlite3.Row
        storage.use_test_storage(self.conn, root / "plugin-data")
        self.epub = fixture_book.build_epub(root / "the-glass-archive.epub")
        self.conv = "conv-a"

    def tearDown(self) -> None:
        storage.clear_test_storage()
        self.conn.close()
        self.tmp.cleanup()

    def _open(self, path: Path | None = None, conversation_id: str | None = None) -> dict:
        raw = tools.open_book(
            {"path": str(path or self.epub)},
            conversation_id=self.conv if conversation_id is None else conversation_id,
        )
        self.assertIsInstance(raw, str)
        return json.loads(raw)

    def _progress(self, conversation_id: str | None = None, **kwargs: object) -> dict:
        raw = tools.set_progress(
            kwargs,
            conversation_id=self.conv if conversation_id is None else conversation_id,
        )
        self.assertIsInstance(raw, str)
        return json.loads(raw)

    def _who(self, name: str, conversation_id: str | None = None, **extra: object) -> dict:
        raw = tools.who_is(
            {"name": name},
            conversation_id=self.conv if conversation_id is None else conversation_id,
            **extra,
        )
        self.assertIsInstance(raw, str)
        return json.loads(raw)

    def _ask(self, query: str, conversation_id: str | None = None) -> dict:
        raw = tools.ask_book(
            {"query": query},
            conversation_id=self.conv if conversation_id is None else conversation_id,
        )
        self.assertIsInstance(raw, str)
        return json.loads(raw)

    def _assert_no_later(self, payload: object, *extra_forbidden: str) -> None:
        blob = payload if isinstance(payload, str) else json.dumps(payload)
        folded = blob.casefold()
        for phrase in (*LATER, *extra_forbidden):
            self.assertNotIn(phrase.casefold(), folded, phrase)

    def test_open_book_indexes_locally_without_returning_text(self) -> None:
        raw = tools.open_book({"path": str(self.epub)}, conversation_id=self.conv)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["text_included"])
        self.assertEqual(payload["chapter_count"], 2)
        self.assertEqual(payload["title"], "The Glass Archive")
        self.assertEqual(payload["progress"]["revealed_chapters"], [])
        self.assertNotIn("green notebook", raw)
        self.assertNotIn("The Night Desk", raw)
        self._assert_no_later(raw)
        book_dir = storage.book_dir(payload["book_id"])
        manifest = (book_dir / "manifest.json").read_text(encoding="utf-8")
        self._assert_no_later(manifest, "the curator")
        later = (book_dir / "ch-002.txt").read_text(encoding="utf-8")
        self.assertIn("Pip Is the Curator", later)
        self.assertIn("Ellis Vale burned the east wing", later)
        self.assertIn("Spoilers ahead", fixture_book.OPF_DESCRIPTION)
        self.assertNotIn("Spoilers ahead", manifest)
        self.assertNotIn("Spoilers ahead", later)

    def test_gate_does_not_open_later_chapter_files(self) -> None:
        self._open()
        opened: list[str] = []
        real = gate._read_chapter

        def spy(path: Path) -> tuple[str, str]:
            opened.append(Path(path).name)
            return real(path)

        gate._read_chapter = spy
        try:
            progress = self._progress(chapter=1)
            self.assertEqual(
                [chapter["title"] for chapter in progress["progress"]["revealed_chapters"]],
                ["The Night Desk"],
            )
            pip = self._who("Pip")
            self.assertTrue(pip["ok"], pip)
            self.assertNotIn("ch-002.txt", opened)
            self.assertIn("ch-001.txt", opened)
        finally:
            gate._read_chapter = real

    def test_missing_later_file_still_answers_from_earlier_chapters(self) -> None:
        opened = self._open()
        later = storage.book_dir(opened["book_id"]) / "ch-002.txt"
        self.assertIn("the curator", later.read_text(encoding="utf-8").casefold())
        later.unlink()
        self._progress(chapter=1)
        pip = self._who("Pip")
        self.assertTrue(pip["ok"], pip)
        self.assertEqual(pip["card"]["name"], "Mira Vale")
        curator = self._who("the curator")
        self.assertTrue(curator["nothing_yet"])
        self._assert_no_later(curator)

    def test_same_question_early_and_late_differ(self) -> None:
        self._open()
        self._progress(chapter=1)
        early = self._who("the curator")
        self._progress(chapter=2)
        late = self._who("the curator")

        self.assertNotEqual(early, late)
        self.assertTrue(early["nothing_yet"])
        self.assertIn("nothing about that yet", early["message"].casefold())
        self.assertIsNone(early["card"])
        self._assert_no_later(early)
        self.assertNotIn("torn letter", json.dumps(early))

        self.assertTrue(late["ok"])
        self.assertEqual(late["card"]["name"], "Mira Vale")
        self.assertEqual(late["matched_as"].casefold(), "the curator")
        self.assertTrue(
            any(item["alias"] == "the curator" for item in late["card"]["after"]["aliases"])
        )
        self.assertTrue(
            any("brother" in item["text"] for item in late["card"]["after"]["facts"])
        )
        self.assertEqual(late["quote"]["chapter_number"], 2)
        self.assertIn("named Mira Vale the curator", late["quote"]["excerpt"])
        self.assertIn("night desk", late["card"]["before"]["impression"])

    def test_alias_behind_the_fence_resolves_and_later_alias_does_not(self) -> None:
        self._open()
        self._progress(chapter=1)
        pip = self._who("Pip")
        clerk = self._who("the night clerk")
        curator = self._who("curator")
        for payload in (pip, clerk):
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["card"]["name"], "Mira Vale")
            self.assertIn("Pip", payload["card"]["before"]["aliases"])
            self.assertIn("the night clerk", payload["card"]["before"]["aliases"])
            self.assertEqual(payload["card"]["after"]["aliases"], [])
            self.assertEqual(payload["card"]["after"]["facts"], [])
            self.assertEqual(payload["quote"]["chapter_number"], 1)
            self._assert_no_later(payload, "the curator")
        self.assertTrue(curator["nothing_yet"])
        unknown = self._who("Captain Bramble")
        future = self._who("Ellis Vale")
        self.assertEqual(
            unknown["message"].replace("Captain Bramble", "NAME"),
            future["message"].replace("Ellis Vale", "NAME"),
        )
        self.assertNotIn("brother", json.dumps(future).casefold())
        self.assertNotIn("east wing", json.dumps(future).casefold())

    def test_ask_book_cannot_return_later_chapter_text(self) -> None:
        opened = self._open()
        self._progress(chapter=1)
        early = self._ask("night desk")
        self.assertTrue(early["passages"])
        self.assertTrue(all(item["chapter_number"] == 1 for item in early["passages"]))
        self._assert_no_later(early, "the curator", "weather")
        gated = gate.open_gate(storage.book_dir(opened["book_id"]), early["progress"]["end_offset"])
        corpus = gated.corpus()
        self.assertNotIn("east wing", corpus)
        for passage in early["passages"]:
            self.assertIn(passage["excerpt"], corpus)

        missed = self._ask("east wing")
        self.assertEqual(missed["passages"], [])
        self.assertIn("nothing about that yet", missed["message"])
        self.assertNotIn("blamed the storm", json.dumps(missed))

        self._progress(chapter=2)
        late = self._ask("east wing")
        self.assertTrue(any("burned the east wing" in item["excerpt"] for item in late["passages"]))
        self.assertTrue(all(item["chapter_number"] == 2 for item in late["passages"]))

    def test_advancing_then_shrinking_hides_later_facts_but_keeps_the_row(self) -> None:
        self._open()
        self._progress(chapter=2)
        evolved = self._who("Mira Vale")
        self.assertTrue(any("brother" in item["text"] for item in evolved["card"]["after"]["facts"]))
        stored = self.conn.execute(
            "SELECT alias, source_chapter FROM aliases WHERE alias = ?",
            ("the curator",),
        ).fetchone()
        self.assertIsNotNone(stored)
        self.assertEqual(stored["source_chapter"], 1)

        self._progress(chapter=1)
        shrunk = self._who("Mira Vale")
        self.assertEqual(shrunk["card"]["before"]["impression"], evolved["card"]["before"]["impression"])
        self.assertEqual(shrunk["card"]["after"]["aliases"], [])
        self.assertEqual(shrunk["card"]["after"]["facts"], [])
        self.assertNotIn("the curator", shrunk["card"]["before"]["aliases"])
        self._assert_no_later(shrunk, "the curator")
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT alias FROM aliases WHERE alias = ?",
                ("the curator",),
            ).fetchone()
        )
        self.assertTrue(self._who("Ellis Vale")["nothing_yet"])
        listed = json.loads(tools.list_cast({}, conversation_id=self.conv))
        names = [card["name"] for card in listed["characters"]]
        self.assertEqual(names, ["Mira Vale", "Ned Poole"])

    def test_cast_command_shows_before_and_after(self) -> None:
        self._open()
        self._progress(chapter=1)
        early = tools.cast_command("", conversation_id=self.conv)
        self.assertIn("Dramatis — The Glass Archive", early)
        self.assertIn("before:", early)
        self.assertIn("after:", early)
        self.assertIn("Mira Vale", early)
        self.assertIn("nothing new behind this position", early)
        self._assert_no_later(early, "the curator")

        self._progress(chapter=2)
        late = tools.cast_command("", conversation_id=self.conv)
        self.assertIn("before:", late)
        self.assertIn("the curator (chapter 2)", late)
        self.assertIn("Ellis Vale is Mira's brother.", late)
        one = tools.cast_command("Pip", conversation_id=self.conv)
        self.assertIn("Mira Vale", one)
        self.assertIn("the curator", one)

    def test_chapter_number_percent_and_remembered_position(self) -> None:
        self._open()
        by_number = self._progress(chapter=1)
        by_index = self._progress(chapter_index=0)
        self.assertEqual(by_number["progress"]["end_offset"], by_index["progress"]["end_offset"])
        by_id = self._progress(chapter_id="night-desk")
        self.assertEqual(by_id["progress"]["through_chapter"], 1)

        hidden = self._progress(percent=0)
        self.assertTrue(self._who("Pip")["nothing_yet"])
        self.assertEqual(hidden["progress"]["through_chapter"], None)

        # A finished chapter and a percent of 0 together keep the earlier fence.
        self._progress(chapter=2, percent=0)
        self.assertTrue(self._who("the curator")["nothing_yet"])

        self._progress(chapter=2)
        self.assertTrue(self._who("the curator")["ok"])
        other = self._open(conversation_id="conv-b")
        self.assertTrue(other["restored_position"])
        self.assertEqual(other["progress"]["through_chapter"], 2)
        self.assertTrue(self._who("the curator", conversation_id="conv-b")["ok"])

        # A conversation that has not opened a book still resumes the last one.
        self.assertTrue(self._who("Pip", conversation_id="conv-new")["ok"])

    def test_conversation_id_not_session_id(self) -> None:
        second = Path(self.tmp.name) / "copy.epub"
        second.write_bytes(self.epub.read_bytes())
        self._open(conversation_id="alpha")
        self._progress(conversation_id="alpha", chapter=1)
        self._open(path=second, conversation_id="beta")
        self._progress(conversation_id="beta", chapter=2)

        early = self._who("the curator", conversation_id="alpha", session_id="shared")
        late = self._who("the curator", conversation_id="beta", session_id="shared")
        self.assertTrue(early["nothing_yet"])
        self.assertTrue(late["ok"])
        self.assertEqual(late["card"]["name"], "Mira Vale")

    def test_ned_is_not_pip(self) -> None:
        self._open()
        self._progress(chapter=1)
        ned = self._who("Ned Poole")
        self.assertEqual(ned["card"]["name"], "Ned Poole")
        self.assertNotIn("Pip", ned["card"]["before"]["aliases"])

    def test_register_matches_manifest(self) -> None:
        class Ctx:
            def __init__(self) -> None:
                self.tools: list[dict] = []
                self.commands: list[str] = []
                self.skills: list[str] = []

            def register_tool(self, **kwargs: object) -> None:
                self.tools.append(kwargs)

            def register_command(self, name: str, handler: object, description: str = "", args_hint: str = "") -> None:
                self.commands.append(name)
                self.handler = handler

            def register_skill(self, name: str, path: object) -> None:
                self.skills.append(name)

        ctx = Ctx()
        load_package().register(ctx)
        declared = _provides_tools((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
        registered = [tool["name"] for tool in ctx.tools]
        self.assertEqual(registered, declared)
        self.assertTrue(all(tool["toolset"] == "dramatis" for tool in ctx.tools))
        self.assertEqual(ctx.commands, ["cast"])
        self.assertEqual(ctx.skills, ["dramatis"])
        source = (ROOT / "storage.py").read_text(encoding="utf-8")
        self.assertIn('plugin_db("dramatis")', source)
        self.assertIn('plugin_data_dir("dramatis")', source)

    def test_ambiguous_name_lists_visible_people_only(self) -> None:
        def card(name: str, alias: str) -> cast.Card:
            return cast.Card(
                name=name,
                first_chapter_index=0,
                first_chapter_number=1,
                impression=name,
                impression_title="Chapter",
                quote=name,
                quote_chapter_index=0,
                quote_chapter_number=1,
                quote_title="Chapter",
                aliases=[cast.AliasHit(alias, 0, 1, name)],
            )

        matched = cast.match_card(
            [card("Mira Vale", "Pip"), card("Ned Poole", "Pip")],
            "Pip",
        )
        self.assertEqual(matched, ["Mira Vale", "Ned Poole"])

    def test_committed_fixture(self) -> None:
        path = ROOT / "fixtures" / "the-glass-archive.epub"
        self.assertTrue(path.is_file())
        from dramatis_plugin import epub

        book = epub.parse_epub(path)
        self.assertEqual([chapter.title for chapter in book.chapters], ["The Night Desk", "Pip Is the Curator"])
        self.assertIn("calls Mira Vale Pip", book.chapters[0].text)
        self.assertNotIn("curator", book.chapters[0].text.casefold())
        self.assertIn("named Mira Vale the curator", book.chapters[1].text)

    def test_search_only_accepts_gated_text(self) -> None:
        opened = self._open()
        self._progress(chapter=1)
        listed = json.loads(tools.list_cast({}, conversation_id=self.conv))
        gated = gate.open_gate(
            storage.book_dir(opened["book_id"]),
            listed["progress"]["end_offset"],
        )
        passages = cast.search_passages(gated, "east wing")
        self.assertEqual(passages, [])
        self.assertNotIn("east wing", gated.corpus())
        self.assertEqual(len(gated.chapters), 1)


def _provides_tools(text: str) -> list[str]:
    tools: list[str] = []
    grabbing = False
    for line in text.splitlines():
        if line.startswith("provides_tools:"):
            grabbing = True
            continue
        if not grabbing:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            tools.append(stripped[2:].strip())
        elif stripped:
            break
    return tools


if __name__ == "__main__":
    unittest.main()
