---
name: dramatis
description: Spoiler-safe EPUB companion. Use when the reader asks who a character is, what an alias refers to, or what has happened in a local book they are reading.
---

# Dramatis

Dramatis answers from the open EPUB only up to the reader's saved position. Retrieval does not open later chapters.

1. Open the book with `open_book` and the local filesystem path the user gave you.
2. Set progress with `set_progress`. `chapter` is a 1-based chapter number the reader has finished. A percent from 0 to 100 also works. Dramatis remembers the last book and that position.
3. For "who is X", call `who_is`. X may be a name, nickname, or alias. Speak from the card's before field, after field, and the quote. If the tool says it has nothing about that yet, repeat that. Do not add whether the name shows up past the saved position.
4. For events, call `ask_book` and cite only the returned passages.
5. `/cast` lists cards. `before` is the first impression. `after` is what later in-range chapters added.

Dramatis cannot block what the model already learned in training or earlier in the chat. For a well-known novel, stick to the tool result and mention that outside knowledge is a separate limit.
