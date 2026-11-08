"""Dramatis — spoiler-safe reading companion for Hermes."""

from __future__ import annotations

import logging
from pathlib import Path

from . import schemas, tools

logger = logging.getLogger(__name__)

TOOLSET = "dramatis"


def register(ctx) -> None:
    """Register Dramatis tools, the /cast command, and a short skill."""
    ctx.register_tool(
        name="open_book",
        toolset=TOOLSET,
        schema=schemas.OPEN_BOOK,
        handler=tools.open_book,
    )
    ctx.register_tool(
        name="set_progress",
        toolset=TOOLSET,
        schema=schemas.SET_PROGRESS,
        handler=tools.set_progress,
    )
    ctx.register_tool(
        name="who_is",
        toolset=TOOLSET,
        schema=schemas.WHO_IS,
        handler=tools.who_is,
    )
    ctx.register_tool(
        name="ask_book",
        toolset=TOOLSET,
        schema=schemas.ASK_BOOK,
        handler=tools.ask_book,
    )
    ctx.register_tool(
        name="list_cast",
        toolset=TOOLSET,
        schema=schemas.LIST_CAST,
        handler=tools.list_cast,
    )
    ctx.register_command(
        "cast",
        handler=tools.cast_command,
        description="List Dramatis cards for the open book, with before and after",
        args_hint="[name]",
    )
    skill = Path(__file__).resolve().parent / "skills" / "dramatis" / "SKILL.md"
    if skill.is_file():
        ctx.register_skill("dramatis", skill)
    logger.debug("dramatis: registered tools and /cast")
