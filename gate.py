"""Structural reading fence.

``open_gate`` is the only way retrieval is allowed to see book text. It reads
the manifest (offsets and filenames, no prose) and opens a chapter file only
when that chapter begins at or before the saved position. Later files are not
opened, and their text is not copied into the returned view.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GatedChapter:
    index: int
    number: int
    chapter_id: str
    title: str
    text: str
    fully_included: bool


@dataclass(frozen=True)
class GatedBook:
    """Text the reader has reached. Later chapters are not on this object."""

    book_id: str
    title: str
    chapters: tuple[GatedChapter, ...]
    end_offset: int
    total_chars: int
    chapter_count: int

    def corpus(self) -> str:
        return "\n\n".join(chapter.text for chapter in self.chapters if chapter.text)


def open_gate(book_dir: Path, end_offset: int) -> GatedBook:
    manifest = json.loads((book_dir / "manifest.json").read_text(encoding="utf-8"))
    total = int(manifest["total_chars"])
    stop = max(0, min(int(end_offset), total))
    visible: list[GatedChapter] = []
    for raw in manifest["chapters"]:
        start = int(raw["start"])
        end = int(raw["end"])
        if stop <= start:
            break
        title, body = _read_chapter(book_dir / str(raw["file"]))
        if end <= stop:
            text = body
            full = True
        else:
            text = body[: stop - start]
            full = False
        visible.append(
            GatedChapter(
                index=int(raw["index"]),
                number=int(raw["number"]),
                chapter_id=str(raw["id"]),
                title=title,
                text=text,
                fully_included=full,
            )
        )
        if not full:
            break
    return GatedBook(
        book_id=str(manifest["book_id"]),
        title=str(manifest["title"]),
        chapters=tuple(visible),
        end_offset=stop,
        total_chars=total,
        chapter_count=int(manifest["chapter_count"]),
    )


def write_index(
    book_dir: Path,
    *,
    book_id: str,
    title: str,
    path: str,
    content_hash: str,
    chapters: list[dict[str, object]],
) -> dict[str, object]:
    """Write one file per chapter and a manifest without titles or prose."""
    book_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    cursor = 0
    for chapter in chapters:
        body = str(chapter["text"])
        start = cursor
        end = start + len(body)
        cursor = end
        filename = f"ch-{int(chapter['number']):03d}.txt"
        payload = f"{chapter['title']}\n\n{body}"
        (book_dir / filename).write_text(payload, encoding="utf-8")
        records.append(
            {
                "index": int(chapter["index"]),
                "number": int(chapter["number"]),
                "id": str(chapter["id"]),
                "start": start,
                "end": end,
                "file": filename,
            }
        )
    manifest = {
        "book_id": book_id,
        "title": title,
        "path": path,
        "content_hash": content_hash,
        "chapter_count": len(records),
        "total_chars": cursor,
        "chapters": records,
    }
    (book_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _read_chapter(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    if "\n\n" not in raw:
        return raw.strip(), ""
    title, body = raw.split("\n\n", 1)
    return title.strip(), body.strip()
