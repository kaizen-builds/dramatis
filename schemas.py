"""Tool schemas Dramatis shows to Hermes."""

OPEN_BOOK = {
    "name": "open_book",
    "description": (
        "Index a local EPUB the user already has and remember it as the open book. "
        "Returns the title, chapter count, and any saved reading position. "
        "Does not return chapter text, future chapter titles, or the publisher description. "
        "Call set_progress before questions when the saved position is still at the start."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Filesystem path to a .epub file the user selected.",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}

SET_PROGRESS = {
    "name": "set_progress",
    "description": (
        "Save how far the reader has gotten in the open book. "
        "chapter and chapter_number are 1-based (chapter 1 is the first spine item) "
        "and mean the reader has finished that chapter. chapter_index is 0-based and "
        "also inclusive. percent is 0-100 of the indexed text. "
        "If more than one is set, Dramatis keeps the earlier position. "
        "The saved position is remembered for this book."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "chapter": {
                "type": "integer",
                "minimum": 1,
                "description": "1-based chapter number the reader has finished.",
            },
            "chapter_number": {
                "type": "integer",
                "minimum": 1,
                "description": "Alias of chapter.",
            },
            "chapter_index": {
                "type": "integer",
                "minimum": 0,
                "description": "0-based spine index the reader has finished.",
            },
            "chapter_id": {
                "type": "string",
                "description": "Spine id of the last finished chapter.",
            },
            "percent": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "description": "Percent of indexed text the reader has passed, from 0 to 100.",
            },
        },
        "additionalProperties": False,
    },
}

WHO_IS = {
    "name": "who_is",
    "description": (
        "Look up a person using only text at or before the saved reading position. "
        "Resolves names, nicknames, and aliases that appear in that text. "
        "Returns a card with a first impression, later in-range additions, and one short quote. "
        "If the name is not in range, Dramatis has nothing about that yet and does not say "
        "whether it shows up afterward. Speak only from the returned card and quote."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name, nickname, or alias to look up, such as 'Pip' or 'Mira Vale'.",
            }
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

ASK_BOOK = {
    "name": "ask_book",
    "description": (
        "Retrieve short passages from the open book at or before the saved reading position, "
        "with chapter numbers. Later chapters are not opened and cannot appear. "
        "If nothing matches, say Dramatis has nothing about that yet. "
        "Answer only from the returned passages."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for in the text already read.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

LIST_CAST = {
    "name": "list_cast",
    "description": (
        "List people who appear at or before the saved reading position. "
        "Each card has a before field (first impression and aliases from the chapter "
        "where they appear) and an after field (aliases and facts added by later "
        "chapters that are still inside the position). People who show up only "
        "past the position are absent."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
