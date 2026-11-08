# Dramatis

Dramatis is a spoiler-safe reading companion for [Hermes Agent](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins). You open an EPUB you already have, set how far you have read, and ask who someone is or what happened. The answer is built only from text at or before that position, with a short quote from the book.

Catalog id: `dramatis`. Display name: Dramatis.

Dramatis does not call Gemini or OpenAI. It does not draw portraits, send books to a device, or download books. Hermes speaks from the passages the tools return, using the model you already run.

## Install

From a local checkout:

```bash
hermes plugins install /absolute/path/to/dramatis --enable
```

From a git repository, once this project has a public remote:

```bash
hermes plugins install OWNER/REPO --enable
```

Pin a full 40-character commit when you want the install to stay put:

```bash
hermes plugins install OWNER/REPO --ref <40-character-sha> --enable
```

Python dependencies: none. EPUB parsing uses the standard library. They are declared as an empty list in `pyproject.toml`, which is the Hermes plugin dependency file.

## Open a book and set your place

Ask Hermes to open a file on disk, then say which chapter you have finished. Chapter numbers start at 1.

- `open_book` indexes the EPUB by spine item and remembers it. The tool result is the title, the chapter count, and any saved position. It does not include chapter text or later chapter titles.
- `set_progress` saves the fence. Pass `chapter` (1-based, finished through that chapter), `chapter_index` (0-based), `chapter_id`, or `percent` (0–100). If you pass more than one, Dramatis keeps the earlier position.
- The last book and its position are remembered. Opening the same file again restores the position. A new conversation that has not opened a book resumes the last one.
- `who_is` resolves a name, nickname, or alias that appears in range, and returns a card plus one quote.
- `ask_book` returns short passages in range, with chapter numbers.
- `list_cast` and `/cast` list people in range.

Each card has two fields:

- **before** — the first impression and the aliases from the chapter where the person appears.
- **after** — aliases and facts added by later chapters that are still behind your position. Empty until those chapters are in range.

Moving the position backward hides `after` again. The rows stay in local storage, but the tools do not read the later chapter files, so those facts are not returned.

## 90-second demo

The fixture is an original two-chapter story, `fixtures/the-glass-archive.epub` (rebuild it with `python3 fixture_book.py`). Chapter 1 introduces Mira Vale. The porter calls her Pip, and readers know her as the night clerk. Chapter 2 is the first time the book calls her the curator, and the first time it mentions her brother. No copyrighted novel is included.

Ask Hermes to use the tools. The same question at two positions:

**You:** Open `fixtures/the-glass-archive.epub`. I have finished chapter 1.

**You:** Who is the curator?

Dramatis has not opened chapter 2. `who_is` returns no card:

> Dramatis only has text up to your position, and it has nothing about that yet. Nothing in range mentions "the curator".

That refusal does not say whether the name shows up later.

**You:** Who is Pip?

Pip is already in chapter 1, so the card is Mira Vale. The quote is from chapter 1, *The Night Desk*: "Mira Vale keeps the night desk at the Glass Archive." Aliases in range: Mira, Pip, the night clerk. `after` is empty.

`/cast` at chapter 1:

```text
Dramatis — The Glass Archive
Read through chapter 1 of 2.

Mira Vale
  before: Mira Vale keeps the night desk at the Glass Archive.
  aliases: Mira, Pip, the night clerk
  after: nothing new behind this position

Ned Poole
  before: Ned Poole sweeps the night desk and says little.
  aliases: Ned
  after: nothing new behind this position
```

**You:** I have finished chapter 2. Who is the curator?

The same question now resolves. The curator is Mira Vale. The quote is from chapter 2: "A torn letter named Mira Vale the curator." `before` is unchanged. `after` adds the alias and the relationship `Ellis Vale is Mira's brother.`

`/cast` at chapter 2:

```text
Dramatis — The Glass Archive
Read through chapter 2 of 2.

Mira Vale
  before: Mira Vale keeps the night desk at the Glass Archive.
  aliases: Mira, Pip, the night clerk
  after: the curator (chapter 2); Ellis Vale is Mira's brother.

Ned Poole
  before: Ned Poole sweeps the night desk and says little.
  aliases: Ned
  after: nothing new behind this position

Ellis Vale
  before: Ellis Vale is Mira's brother.
  aliases: Ellis
  after: nothing new behind this position
```

**You:** Put me back on chapter 1. Who is the curator?

The answer is the first one again: nothing about that yet. `/cast Pip` shows Mira's first impression and an empty `after`. Ellis is not on the list.

Side by side, "Who is the curator?":

| Finished through | What Dramatis returns |
| --- | --- |
| Chapter 1 | Nothing in range. No card, no quote, no brother, no later chapter title. |
| Chapter 2 | Mira Vale, alias "the curator", quote from chapter 2, and the brother fact in `after`. |

## How the fence works

Chapters are stored as separate files under Hermes's plugin data directory. The manifest records offsets and filenames, not prose and not chapter titles. A question opens a chapter file only when that chapter starts at or before the saved position, then stops. Later files are not read, so they cannot appear in a tool result. Publisher description metadata is dropped while indexing and is not stored.

Shrinking the position does not delete saved cards. It stops opening the later files, so aliases and facts that exist only in those files disappear from the card until you advance again.

## Tests

No Hermes install is required:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover a name that appears only after the fence, an alias that is already in range (Pip, the night clerk), an alias that is not (the curator), `ask_book` refusing later-chapter text, a card that gains an `after` field when you advance, and that field going empty again when you move back. They also check that a gated read does not open the later chapter file.

## Disclosure

Dramatis reads the EPUB path you give it and writes the extracted chapter text, reading position, and character cards on disk. With Hermes running, that data lives in the active profile's plugin storage (`plugin-data/dramatis/` and the `dramatis` SQLite database from `plugin_db`). It does not read API keys, `.env` files, or Hermes credential stores. It does not make network calls.

Dramatis can only fence the text it returns. It cannot stop Hermes's pretrained knowledge, or anything already said in the chat, from spoiling a well-known book. For a famous novel, treat the tool result as the grounded answer and expect the model may still know the plot.

`/cast` is the cast view: before and after, in the chat. This plugin does not ship a Desktop pane.
