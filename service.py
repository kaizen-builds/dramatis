"""Orchestration for Dramatis tools.

Retrieval always goes through ``open_gate``. Handlers serialize the gated
result and never attach the rest of the book.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import cast, epub, gate, storage
from .epub import EpubError

_LIMIT = (
    "Dramatis answers only from text up to the saved position. "
    "It cannot block the model's pretraining or earlier chat."
)
_NOTHING = (
    "Dramatis only has text up to your position, and it has nothing about that yet."
)


def open_book(path_value: object, conversation_id: str) -> dict:
    if not isinstance(path_value, str) or not path_value.strip():
        return _error("path must be the filesystem path of an EPUB")
    path = Path(path_value).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        return _error(f"could not read that path: {exc.__class__.__name__}")
    if path.suffix.lower() != ".epub" or not path.is_file():
        return _error("path must be an existing .epub file")
    try:
        content_hash = epub.file_hash(path)
    except OSError as exc:
        return _error(f"could not read that EPUB: {exc.__class__.__name__}")

    book_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:32]
    directory = storage.book_dir(book_id)
    previous_hash = _stored_hash(book_id)
    manifest_path = directory / "manifest.json"
    if previous_hash == content_hash and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        title = str(manifest["title"])
        chapter_count = int(manifest["chapter_count"])
    else:
        try:
            parsed = epub.parse_epub(path)
        except EpubError as exc:
            return _error(str(exc))
        except OSError as exc:
            return _error(f"could not read that EPUB: {exc.__class__.__name__}")
        chapters = [
            {
                "index": index,
                "number": index + 1,
                "id": chapter.chapter_id,
                "title": chapter.title,
                "text": chapter.text,
            }
            for index, chapter in enumerate(parsed.chapters)
        ]
        manifest = gate.write_index(
            directory,
            book_id=book_id,
            title=parsed.title,
            path=str(path),
            content_hash=content_hash,
            chapters=chapters,
        )
        title = parsed.title
        chapter_count = len(parsed.chapters)
        with storage.connection() as conn:
            if previous_hash is not None and previous_hash != content_hash:
                _drop_cards(conn, book_id)
            conn.execute(
                """
                INSERT INTO books (book_id, path, title, content_hash, chapter_count, total_chars, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    path = excluded.path,
                    title = excluded.title,
                    content_hash = excluded.content_hash,
                    chapter_count = excluded.chapter_count,
                    total_chars = excluded.total_chars,
                    updated_at = excluded.updated_at
                """,
                (
                    book_id,
                    str(path),
                    title,
                    content_hash,
                    int(manifest["chapter_count"]),
                    int(manifest["total_chars"]),
                    storage.now(),
                ),
            )
            _clamp_progress(conn, book_id, int(manifest["total_chars"]))
    _remember_open(book_id, conversation_id)
    restored = _progress_offset(book_id) > 0
    payload = {
        "ok": True,
        "book_id": book_id,
        "title": title,
        "path": str(path),
        "chapter_count": chapter_count,
        "progress": _fence_payload(book_id),
        "restored_position": restored,
        "indexed_locally": True,
        "text_included": False,
        "limit": _LIMIT,
    }
    if restored:
        through = payload["progress"]["through_chapter"]
        payload["message"] = (
            f"Reopened {title}. Saved position restored"
            + (f" through chapter {through}." if through else ".")
        )
    else:
        payload["message"] = (
            f"Indexed {chapter_count} chapters of {title} locally. "
            "No chapter text was returned. Set a chapter number or percent before asking questions."
        )
    return payload


def set_progress(args: dict, conversation_id: str) -> dict:
    book_id = _active_book_id(conversation_id)
    if book_id is None:
        return _error("No book is open. Open a local EPUB with open_book first.")
    manifest = _manifest(book_id)
    try:
        end_offset, chapter_number = _resolve_fence(args, manifest)
    except ValueError as exc:
        return _error(str(exc))
    percent = _percent(end_offset, int(manifest["total_chars"]))
    with storage.connection() as conn:
        conn.execute(
            """
            INSERT INTO progress (book_id, end_offset, chapter_number, percent, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                end_offset = excluded.end_offset,
                chapter_number = excluded.chapter_number,
                percent = excluded.percent,
                updated_at = excluded.updated_at
            """,
            (book_id, end_offset, chapter_number, percent, storage.now()),
        )
        _touch_reader(conn, book_id)
    fence = _fence_payload(book_id)
    return {
        "ok": True,
        "book_id": book_id,
        "title": manifest["title"],
        "progress": fence,
        "message": "Position saved. Answers use only text up to this point.",
        "limit": _LIMIT,
    }


def who_is(name: object, conversation_id: str) -> dict:
    if not isinstance(name, str) or not name.strip():
        return _error("name must be a non-empty string")
    query = " ".join(name.split())
    if len(query) > 80:
        return _error("name is too long")
    gated = _gated_for(conversation_id)
    if isinstance(gated, dict):
        return gated
    cards = cast.cards_from_gate(gated)
    _persist(gated.book_id, cards)
    matched = cast.match_card(cards, query)
    fence = _fence_from_gated(gated)
    if isinstance(matched, list):
        names = ", ".join(matched)
        return {
            "ok": True,
            "nothing_yet": False,
            "ambiguous": True,
            "names": matched,
            "message": f"More than one person in range uses that name: {names}.",
            "card": None,
            "quote": None,
            "progress": fence,
            "guidance": "Ask which person, using the full name from this list.",
            "limit": _LIMIT,
        }
    if matched is None:
        return {
            "ok": False,
            "nothing_yet": True,
            "name": query,
            "message": f'{_NOTHING} Nothing in range mentions "{query}".',
            "card": None,
            "quote": None,
            "progress": fence,
            "guidance": (
                "Say that Dramatis has nothing about that yet. "
                "Do not add whether the name shows up past the saved position."
            ),
            "limit": _LIMIT,
        }
    card, label = matched
    excerpt, chapter_index, chapter_number, title = cast.quote_for(card, label)
    if not title:
        title = _title_for(gated, chapter_index)
    return {
        "ok": True,
        "nothing_yet": False,
        "book_title": gated.title,
        "matched_as": label,
        "card": _card_payload(card),
        "quote": {
            "chapter_index": chapter_index,
            "chapter_number": chapter_number,
            "chapter_title": title,
            "excerpt": excerpt,
        },
        "progress": fence,
        "guidance": "Speak from this card and quote. Leave out facts that are not listed.",
        "limit": _LIMIT,
    }


def ask_book(query: object, conversation_id: str) -> dict:
    if not isinstance(query, str) or not query.strip():
        return _error("query must be a non-empty string")
    text = " ".join(query.split())
    if len(text) > 200:
        return _error("query is too long")
    gated = _gated_for(conversation_id)
    if isinstance(gated, dict):
        return gated
    passages = cast.search_passages(gated, text)
    message = None if passages else _NOTHING
    return {
        "ok": True,
        "query": text,
        "passages": passages,
        "message": message,
        "progress": _fence_from_gated(gated),
        "guidance": (
            "Answer only from these passages. They stop at the saved position. "
            "If passages is empty, say Dramatis has nothing about that yet."
        ),
        "limit": _LIMIT,
    }


def list_cast(conversation_id: str) -> dict:
    gated = _gated_for(conversation_id)
    if isinstance(gated, dict):
        return gated
    cards = cast.cards_from_gate(gated)
    _persist(gated.book_id, cards)
    return {
        "ok": True,
        "book_title": gated.title,
        "characters": [_card_payload(card) for card in cards],
        "progress": _fence_from_gated(gated),
        "limit": _LIMIT,
    }


def cast_text(raw_args: str, conversation_id: str) -> str:
    focus = " ".join((raw_args or "").split())
    if focus:
        payload = who_is(focus, conversation_id)
        return _format_one(payload)
    payload = list_cast(conversation_id)
    if not payload.get("ok"):
        return str(payload.get("error") or payload.get("message") or "Dramatis has no open book.")
    progress = payload["progress"]
    through = progress.get("through_chapter")
    lines = [
        f"Dramatis — {payload['book_title']}",
        (
            f"Read through chapter {through} of {progress['chapter_count']}."
            if through
            else "Reading position is at the start of the book. No chapters are in range yet."
        ),
        "",
    ]
    characters = payload["characters"]
    if not characters:
        lines.append("No one is in range yet.")
        return "\n".join(lines).rstrip() + "\n"
    for card in characters:
        lines.extend(_format_card_lines(card))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_one(payload: dict) -> str:
    if payload.get("nothing_yet"):
        return str(payload["message"])
    if not payload.get("ok"):
        return str(payload.get("error") or "Dramatis could not look that up.")
    lines = [f"Dramatis — {payload['book_title']}", ""]
    lines.extend(_format_card_lines(payload["card"]))
    quote = payload.get("quote") or {}
    if quote.get("excerpt"):
        lines.append(
            f'  quote (chapter {quote["chapter_number"]}): "{quote["excerpt"]}"'
        )
    return "\n".join(lines).rstrip() + "\n"


def _format_card_lines(card: dict) -> list[str]:
    before = card["before"]
    after = card["after"]
    alias_text = ", ".join(before["aliases"]) if before["aliases"] else "(none)"
    if after["aliases"] or after["facts"]:
        bits = [f"{item['alias']} (chapter {item['chapter_number']})" for item in after["aliases"]]
        bits.extend(item["text"] for item in after["facts"])
        after_text = "; ".join(bits)
    else:
        after_text = "nothing new behind this position"
    return [
        card["name"],
        f"  before: {before['impression']}",
        f"  aliases: {alias_text}",
        f"  after: {after_text}",
    ]


def _card_payload(card: cast.Card) -> dict:
    return {
        "name": card.name,
        "first_seen_chapter": card.first_chapter_number,
        "before": {
            "chapter_number": card.first_chapter_number,
            "chapter_title": card.impression_title,
            "impression": card.impression,
            "aliases": card.aliases_before(),
        },
        "after": {
            "aliases": [
                {
                    "alias": hit.alias,
                    "chapter_number": hit.chapter_number,
                    "chapter_index": hit.chapter_index,
                    "excerpt": hit.excerpt,
                }
                for hit in card.aliases_after()
            ],
            "facts": [
                {
                    "text": hit.text,
                    "kind": hit.kind,
                    "chapter_number": hit.chapter_number,
                    "chapter_index": hit.chapter_index,
                }
                for hit in card.facts_after()
            ],
        },
    }


def _persist(book_id: str, cards: list[cast.Card]) -> None:
    with storage.connection() as conn:
        for card in cards:
            key = card.name.casefold()
            conn.execute(
                """
                INSERT INTO characters (book_id, name_key, display_name, first_chapter)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(book_id, name_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    first_chapter = MIN(characters.first_chapter, excluded.first_chapter)
                """,
                (book_id, key, card.name, card.first_chapter_index),
            )
            for hit in card.aliases:
                conn.execute(
                    """
                    INSERT INTO aliases (book_id, name_key, alias, source_chapter)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(book_id, name_key, alias) DO NOTHING
                    """,
                    (book_id, key, hit.alias, hit.chapter_index),
                )
            if card.impression:
                conn.execute(
                    """
                    INSERT INTO facts (book_id, name_key, kind, text, source_chapter)
                    VALUES (?, ?, 'impression', ?, ?)
                    ON CONFLICT(book_id, name_key, kind, text) DO NOTHING
                    """,
                    (book_id, key, card.impression, card.first_chapter_index),
                )
            for fact in card.facts:
                conn.execute(
                    """
                    INSERT INTO facts (book_id, name_key, kind, text, source_chapter)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(book_id, name_key, kind, text) DO NOTHING
                    """,
                    (book_id, key, fact.kind, fact.text, fact.chapter_index),
                )


def _gated_for(conversation_id: str):
    book_id = _active_book_id(conversation_id)
    if book_id is None:
        return _error("No book is open. Open a local EPUB with open_book first.")
    try:
        return gate.open_gate(storage.book_dir(book_id), _progress_offset(book_id))
    except OSError as exc:
        return _error(f"saved book index could not be read: {exc.__class__.__name__}")


def _fence_payload(book_id: str) -> dict:
    gated = gate.open_gate(storage.book_dir(book_id), _progress_offset(book_id))
    return _fence_from_gated(gated)


def _fence_from_gated(gated: gate.GatedBook) -> dict:
    through = None
    for chapter in gated.chapters:
        if chapter.fully_included:
            through = chapter.number
    return {
        "percent_read": _percent(gated.end_offset, gated.total_chars),
        "end_offset": gated.end_offset,
        "total_characters": gated.total_chars,
        "through_chapter": through,
        "chapter_count": gated.chapter_count,
        "revealed_chapters": [
            {
                "number": chapter.number,
                "index": chapter.index,
                "id": chapter.chapter_id,
                "title": chapter.title,
                "complete": chapter.fully_included,
            }
            for chapter in gated.chapters
        ],
    }


def _title_for(gated: gate.GatedBook, chapter_index: int) -> str:
    for chapter in gated.chapters:
        if chapter.index == chapter_index:
            return chapter.title
    return ""


def _resolve_fence(args: dict, manifest: dict) -> tuple[int, int | None]:
    chapters = list(manifest["chapters"])
    total = int(manifest["total_chars"])
    ends: list[int] = []
    for key in ("chapter", "chapter_number"):
        if key in args and args[key] is not None:
            number = _as_int(args[key])
            if number is None:
                raise ValueError(f"{key} must be a chapter number")
            if number < 1:
                raise ValueError("chapter numbers start at 1")
            if number > len(chapters):
                raise ValueError(f"this book has {len(chapters)} chapters")
            ends.append(int(chapters[number - 1]["end"]))
    if args.get("chapter_index") is not None:
        index = _as_int(args.get("chapter_index"))
        if index is None or index < 0 or index >= len(chapters):
            raise ValueError("chapter_index is outside this book")
        ends.append(int(chapters[index]["end"]))
    if args.get("chapter_id") not in (None, ""):
        chapter_id = str(args.get("chapter_id")).strip()
        record = next((item for item in chapters if item["id"] == chapter_id), None)
        if record is None:
            raise ValueError("chapter_id is not in this book")
        ends.append(int(record["end"]))
    if args.get("percent") is not None:
        percent = _as_float(args.get("percent"))
        if percent is None or percent < 0 or percent > 100:
            raise ValueError("percent must be between 0 and 100")
        ends.append(_offset_for_percent(percent, total))
    if not ends:
        raise ValueError("set chapter, chapter_index, chapter_id, or percent")
    end_offset = min(ends)
    through = None
    for record in chapters:
        if int(record["end"]) <= end_offset:
            through = int(record["number"])
    return end_offset, through


def _offset_for_percent(percent: float, total: int) -> int:
    if percent <= 0 or total <= 0:
        return 0
    if percent >= 100:
        return total
    return min(total, max(0, int(round(percent / 100 * total))))


def _percent(end_offset: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100 * end_offset / total, 2)


def _remember_open(book_id: str, conversation_id: str) -> None:
    with storage.connection() as conn:
        conn.execute(
            """
            INSERT INTO open_books (conversation_id, book_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                book_id = excluded.book_id,
                updated_at = excluded.updated_at
            """,
            (conversation_id, book_id, storage.now()),
        )
        _touch_reader(conn, book_id)


def _touch_reader(conn, book_id: str) -> None:
    conn.execute(
        """
        INSERT INTO reader (id, last_book_id, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_book_id = excluded.last_book_id,
            updated_at = excluded.updated_at
        """,
        (book_id, storage.now()),
    )


def _active_book_id(conversation_id: str) -> str | None:
    with storage.connection() as conn:
        row = conn.execute(
            "SELECT book_id FROM open_books WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is not None:
            return str(row["book_id"])
        last = conn.execute("SELECT last_book_id FROM reader WHERE id = 1").fetchone()
        if last is None:
            return None
        return str(last["last_book_id"])


def _progress_offset(book_id: str) -> int:
    with storage.connection() as conn:
        row = conn.execute(
            "SELECT end_offset FROM progress WHERE book_id = ?",
            (book_id,),
        ).fetchone()
    if row is None:
        return 0
    return int(row["end_offset"])


def _stored_hash(book_id: str) -> str | None:
    with storage.connection() as conn:
        row = conn.execute(
            "SELECT content_hash FROM books WHERE book_id = ?",
            (book_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row["content_hash"])


def _manifest(book_id: str) -> dict:
    path = storage.book_dir(book_id) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _clamp_progress(conn, book_id: str, total: int) -> None:
    row = conn.execute(
        "SELECT end_offset FROM progress WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    if row is None:
        return
    end_offset = min(int(row["end_offset"]), total)
    conn.execute(
        "UPDATE progress SET end_offset = ?, percent = ?, updated_at = ? WHERE book_id = ?",
        (end_offset, _percent(end_offset, total), storage.now(), book_id),
    )


def _drop_cards(conn, book_id: str) -> None:
    conn.execute("DELETE FROM characters WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM aliases WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM facts WHERE book_id = ?", (book_id,))


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _error(message: str) -> dict:
    return {"ok": False, "error": message}
