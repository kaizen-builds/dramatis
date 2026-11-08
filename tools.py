"""Tool handlers. Each one returns a JSON string and never raises."""

from __future__ import annotations

import json
import logging
from typing import Any

from . import service

logger = logging.getLogger(__name__)


def open_book(args: dict, **kwargs: Any) -> str:
    try:
        if not isinstance(args, dict):
            return _fail("arguments must be an object")
        return _dump(service.open_book(args.get("path"), _conversation_id(kwargs)))
    except Exception as exc:
        logger.exception("open_book failed")
        return _fail(f"open_book failed: {exc.__class__.__name__}")


def set_progress(args: dict, **kwargs: Any) -> str:
    try:
        if not isinstance(args, dict):
            return _fail("arguments must be an object")
        return _dump(service.set_progress(args, _conversation_id(kwargs)))
    except Exception as exc:
        logger.exception("set_progress failed")
        return _fail(f"set_progress failed: {exc.__class__.__name__}")


def who_is(args: dict, **kwargs: Any) -> str:
    try:
        if not isinstance(args, dict):
            return _fail("arguments must be an object")
        return _dump(service.who_is(args.get("name"), _conversation_id(kwargs)))
    except Exception as exc:
        logger.exception("who_is failed")
        return _fail(f"who_is failed: {exc.__class__.__name__}")


def ask_book(args: dict, **kwargs: Any) -> str:
    try:
        if not isinstance(args, dict):
            return _fail("arguments must be an object")
        return _dump(service.ask_book(args.get("query"), _conversation_id(kwargs)))
    except Exception as exc:
        logger.exception("ask_book failed")
        return _fail(f"ask_book failed: {exc.__class__.__name__}")


def list_cast(args: dict, **kwargs: Any) -> str:
    try:
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _fail("arguments must be an object")
        return _dump(service.list_cast(_conversation_id(kwargs)))
    except Exception as exc:
        logger.exception("list_cast failed")
        return _fail(f"list_cast failed: {exc.__class__.__name__}")


def cast_command(raw_args: str, **kwargs: Any) -> str:
    """Slash command /cast. Returns text for the chat, not JSON."""
    try:
        return service.cast_text(raw_args or "", _conversation_id(kwargs))
    except Exception as exc:
        logger.exception("cast command failed")
        return f"Dramatis could not list cards ({exc.__class__.__name__})."


def _conversation_id(kwargs: dict) -> str:
    value = kwargs.get("conversation_id")
    if isinstance(value, str):
        return value.strip()
    return ""


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fail(message: str) -> str:
    return _dump({"ok": False, "error": message})
