"""Original two-chapter EPUB used by the Dramatis demo and tests.

The story is fictional. Chapter 1 introduces Mira Vale under a nickname and a
job title. Chapter 2 is the first place those pages call her "the curator" and
the first place her brother appears. Nothing here is from a copyrighted novel.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

TITLE = "The Glass Archive"
# Kept in the OPF description on purpose. Dramatis must not return it.
OPF_DESCRIPTION = (
    "Spoilers ahead: Pip is the curator, and Ellis Vale burned the east wing."
)

CHAPTERS: list[dict[str, object]] = [
    {
        "id": "night-desk",
        "title": "The Night Desk",
        "paragraphs": [
            "Mira Vale keeps the night desk at the Glass Archive.",
            "The porter calls Mira Vale Pip when he takes her coat.",
            "Readers know Mira Vale as the night clerk.",
            "Pip writes each cracked lens in a green notebook and drinks tea from a blue tin.",
            "Ned Poole sweeps the night desk and says little.",
        ],
    },
    {
        "id": "letter-room",
        "title": "Pip Is the Curator",
        "paragraphs": [
            "A torn letter named Mira Vale the curator.",
            "The night clerk and the curator are one and the same.",
            "Ellis Vale is Mira's brother.",
            "Ellis Vale burned the east wing and blamed the storm.",
            "Ned Poole still sweeps the night desk and talks about the weather.",
        ],
    },
]

# Phrases that exist only in chapter 2 or in the OPF description.
LATER_ONLY = (
    "Pip Is the Curator",
    "the curator",
    "Ellis Vale",
    "Mira's brother",
    "burned the east wing",
    "Spoilers ahead",
)


def _xhtml(title: str, paragraphs: list[str]) -> str:
    body = "\n".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        f"<head><title>{escape(title)}</title></head>\n"
        "<body>\n"
        f"<h1>{escape(title)}</h1>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _opf() -> str:
    items = []
    spine = []
    for chapter in CHAPTERS:
        chapter_id = str(chapter["id"])
        href = f"{chapter_id}.xhtml"
        items.append(
            f'<item id="{chapter_id}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{chapter_id}"/>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'unique-identifier="book-id" version="3.0">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"<dc:identifier id=\"book-id\">dramatis-fixture-glass-archive</dc:identifier>\n"
        f"<dc:title>{escape(TITLE)}</dc:title>\n"
        "<dc:creator>L. Pembroke</dc:creator>\n"
        "<dc:language>en</dc:language>\n"
        f"<dc:description>{escape(OPF_DESCRIPTION)}</dc:description>\n"
        "</metadata>\n"
        "<manifest>\n"
        + "\n".join(items)
        + "\n</manifest>\n<spine>\n"
        + "\n".join(spine)
        + "\n</spine>\n</package>\n"
    )


def _container() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '<rootfiles>\n'
        '<rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        "</rootfiles>\n</container>\n"
    )


def build_epub(path: Path) -> Path:
    """Write the fixture EPUB. The mimetype entry is stored uncompressed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, "application/epub+zip")
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("OEBPS/content.opf", _opf())
        for chapter in CHAPTERS:
            chapter_id = str(chapter["id"])
            paragraphs = [str(item) for item in chapter["paragraphs"]]  # type: ignore[union-attr]
            archive.writestr(
                f"OEBPS/{chapter_id}.xhtml",
                _xhtml(str(chapter["title"]), paragraphs),
            )
    return path


def main() -> None:
    destination = Path(__file__).resolve().parent / "fixtures" / "the-glass-archive.epub"
    build_epub(destination)
    print(destination)


if __name__ == "__main__":
    main()
