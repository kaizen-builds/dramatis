"""Parse a local EPUB into spine-ordered chapter text.

Only the caller-selected file is read. Package description, subjects, and other
metadata that can spoil a book are dropped on the floor.
"""

from __future__ import annotations

import hashlib
import posixpath
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

MAX_EPUB_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED = 40 * 1024 * 1024
MAX_CHAPTERS = 300
MAX_CHAPTER_CHARS = 500_000
MAX_TOTAL_CHARS = 2_000_000

_HTML_TYPES = ("html", "xhtml")


@dataclass(frozen=True)
class ParsedChapter:
    chapter_id: str
    title: str
    paragraphs: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


@dataclass(frozen=True)
class ParsedBook:
    title: str
    chapters: tuple[ParsedChapter, ...]


class EpubError(ValueError):
    """The file is not a usable EPUB."""


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_epub(path: Path) -> ParsedBook:
    if not path.is_file():
        raise EpubError("path is not a file")
    if path.suffix.lower() != ".epub":
        raise EpubError("path must be a .epub file")
    size = path.stat().st_size
    if size > MAX_EPUB_BYTES:
        raise EpubError("epub is larger than Dramatis will index")
    with zipfile.ZipFile(path) as archive:
        _reject_oversized_archive(archive)
        opf_path = _opf_path(archive)
        root = ElementTree.fromstring(_read_member(archive, opf_path))
        title = _first_text(root, "title") or path.stem
        chapters = _chapters(archive, root, opf_path)
    if not chapters:
        raise EpubError("epub spine has no readable chapters")
    total = sum(len(chapter.text) for chapter in chapters)
    if total > MAX_TOTAL_CHARS:
        raise EpubError("epub text is larger than Dramatis will index")
    return ParsedBook(title=title.strip() or path.stem, chapters=tuple(chapters))


def _reject_oversized_archive(archive: zipfile.ZipFile) -> None:
    total = 0
    for info in archive.infolist():
        total += max(info.file_size, 0)
        if total > MAX_UNCOMPRESSED:
            raise EpubError("epub uncompressed size is too large")


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    safe = _safe_zip_name(name)
    try:
        data = archive.read(safe)
    except KeyError as exc:
        raise EpubError("epub is missing a spine file") from exc
    if len(data) > MAX_CHAPTER_CHARS * 4:
        raise EpubError("epub member is too large")
    return data


def _safe_zip_name(name: str) -> str:
    cleaned = name.replace("\\", "/").lstrip("/")
    parts = posixpath.normpath(cleaned).split("/")
    if not cleaned or any(part in {"", ".", ".."} for part in parts):
        raise EpubError("epub contains an unsafe path")
    return "/".join(parts)


def _opf_path(archive: zipfile.ZipFile) -> str:
    container_name = next(
        (
            info.filename
            for info in archive.infolist()
            if info.filename.replace("\\", "/").lower() == "meta-inf/container.xml"
        ),
        None,
    )
    if container_name is None:
        raise EpubError("epub is missing META-INF/container.xml")
    root = ElementTree.fromstring(_read_member(archive, container_name))
    for element in root.iter():
        if _local(element.tag) != "rootfile":
            continue
        full_path = element.attrib.get("full-path", "").strip()
        if full_path:
            return _safe_zip_name(unquote(full_path))
    raise EpubError("epub container has no rootfile")


def _chapters(
    archive: zipfile.ZipFile, root: ElementTree.Element, opf_path: str
) -> list[ParsedChapter]:
    manifest: dict[str, tuple[str, str]] = {}
    for element in root.iter():
        if _local(element.tag) != "item":
            continue
        item_id = element.attrib.get("id", "").strip()
        href = element.attrib.get("href", "").strip()
        media = element.attrib.get("media-type", "")
        if item_id and href:
            manifest[item_id] = (href, media)
    ordered: list[str] = []
    for element in root.iter():
        if _local(element.tag) != "itemref":
            continue
        item_id = element.attrib.get("idref", "").strip()
        if item_id:
            ordered.append(item_id)
    if len(ordered) > MAX_CHAPTERS:
        raise EpubError("epub has too many spine items")
    base = posixpath.dirname(_safe_zip_name(opf_path))
    chapters: list[ParsedChapter] = []
    for item_id in ordered:
        href_media = manifest.get(item_id)
        if href_media is None:
            continue
        href, media = href_media
        if not any(token in media.lower() for token in _HTML_TYPES):
            continue
        member = _join_href(base, href)
        title, paragraphs = _html_text(_decode(_read_member(archive, member)))
        if not paragraphs and not title:
            continue
        body = "\n\n".join(paragraphs)
        if len(body) > MAX_CHAPTER_CHARS:
            raise EpubError("a chapter is larger than Dramatis will index")
        chapters.append(
            ParsedChapter(
                chapter_id=item_id,
                title=title or f"Chapter {len(chapters) + 1}",
                paragraphs=tuple(paragraphs),
            )
        )
    return chapters


def _join_href(base: str, href: str) -> str:
    cleaned = unquote(href.split("#", 1)[0]).replace("\\", "/").strip()
    if not cleaned or cleaned.startswith("/"):
        raise EpubError("epub contains an unsafe path")
    joined = posixpath.normpath(posixpath.join(base, cleaned)) if base else posixpath.normpath(cleaned)
    return _safe_zip_name(joined)


def _first_text(root: ElementTree.Element, local_name: str) -> str:
    for element in root.iter():
        if _local(element.tag) == local_name and element.text:
            return " ".join(element.text.split())
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._in_title = False
        self._in_heading = False
        self._title_parts: list[str] = []
        self._heading_parts: list[str] = []
        self._buf: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "head"}:
            self._skip += 1
        if name == "title":
            self._in_title = True
            return
        if name in {"h1", "h2"} and self._skip == 0:
            self._flush()
            self._in_heading = True
        if name == "br" and self._skip == 0:
            self._buf.append(" ")
        if name in {"p", "div", "li", "blockquote", "tr"} and self._skip == 0:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"p", "div", "li", "blockquote", "tr", "h1", "h2"} and self._skip == 0:
            self._flush()
        if name in {"h1", "h2"}:
            self._in_heading = False
        if name == "title":
            self._in_title = False
        if name in {"script", "style", "head"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._skip or self._in_title:
            return
        if self._in_heading:
            self._heading_parts.append(data)
            return
        self._buf.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text:
            self.paragraphs.append(text)

    def finish(self) -> tuple[str, list[str]]:
        self._flush()
        heading = " ".join("".join(self._heading_parts).split())
        title = heading or " ".join("".join(self._title_parts).split())
        return title, self.paragraphs


def _html_text(markup: str) -> tuple[str, list[str]]:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return parser.finish()
