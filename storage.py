"""Durable Dramatis state.

Hermes installs call ``plugin_db('dramatis')`` and ``plugin_data_dir('dramatis')``.
Tests inject a connection and directory so they can run without Hermes.
Chapter bodies live in the data directory, one file per spine item. The manifest
stores offsets and file names only — not titles and not prose — so a gated read
can stop before it opens a later chapter.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

PLUGIN_NAME = "dramatis"  # catalog id; storage calls pass this literal below

_override_conn: sqlite3.Connection | None = None
_override_dir: Path | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    book_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chapter_count INTEGER NOT NULL,
    total_chars INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
    book_id TEXT PRIMARY KEY,
    end_offset INTEGER NOT NULL,
    chapter_number INTEGER,
    percent REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS open_books (
    conversation_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reader (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_book_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
    book_id TEXT NOT NULL,
    name_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    first_chapter INTEGER NOT NULL,
    PRIMARY KEY (book_id, name_key)
);
CREATE TABLE IF NOT EXISTS aliases (
    book_id TEXT NOT NULL,
    name_key TEXT NOT NULL,
    alias TEXT NOT NULL,
    source_chapter INTEGER NOT NULL,
    PRIMARY KEY (book_id, name_key, alias)
);
CREATE TABLE IF NOT EXISTS facts (
    book_id TEXT NOT NULL,
    name_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    source_chapter INTEGER NOT NULL,
    PRIMARY KEY (book_id, name_key, kind, text)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def data_root() -> Path:
    if _override_dir is not None:
        _override_dir.mkdir(parents=True, exist_ok=True)
        return _override_dir
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir("dramatis")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    if _override_conn is not None:
        ensure_schema(_override_conn)
        yield _override_conn
        _override_conn.commit()
        return
    from plugins.plugin_storage import plugin_db

    conn = plugin_db("dramatis")
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def book_dir(book_id: str) -> Path:
    return data_root() / "books" / book_id


def use_test_storage(conn: sqlite3.Connection, directory: Path) -> None:
    global _override_conn, _override_dir
    _override_conn = conn
    _override_dir = directory
    ensure_schema(conn)


def clear_test_storage() -> None:
    global _override_conn, _override_dir
    _override_conn = None
    _override_dir = None
