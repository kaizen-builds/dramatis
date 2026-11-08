"""Character cards built only from a gated view of the book.

``cards_from_gate`` never receives chapter text past the fence. Aliases are
attached only when the visible sentence names the person explicitly, plus a
first name taken from a full name already seen in that same view.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gate import GatedBook, GatedChapter

# Two-word names only. A following nickname ("Mira Vale Pip") stays a separate alias.
_FULL_NAME = re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b")
_CALLS_NAMED = re.compile(
    r"\bcalls\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s+([A-Z][a-z]+)\b"
)
_KNOW_AS = re.compile(
    r"\bknow\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s+as\s+(the\s+[a-z]+(?:\s+[a-z]+)?)\b",
    re.IGNORECASE,
)
_NAMED_THE = re.compile(
    r"\bnamed\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(the\s+[a-z]+(?:\s+[a-z]+)?)\b",
    re.IGNORECASE,
)
_RELATION = re.compile(
    r"\b(brother|sister|mother|father|parent|son|daughter|husband|wife|uncle|aunt|cousin|friend|mentor|rival|spouse)s?\b",
    re.IGNORECASE,
)
_NOT_A_NAME = {"the", "a", "an", "and"}
_PLACE_LAST = {
    "archive",
    "desk",
    "room",
    "gallery",
    "wing",
    "street",
    "hall",
    "library",
    "gate",
    "door",
    "house",
    "road",
    "lane",
    "bridge",
    "square",
    "garden",
    "tower",
    "station",
    "chapter",
}


@dataclass(frozen=True)
class Sentence:
    chapter_index: int
    chapter_number: int
    chapter_title: str
    text: str


@dataclass
class AliasHit:
    alias: str
    chapter_index: int
    chapter_number: int
    excerpt: str


@dataclass
class FactHit:
    text: str
    chapter_index: int
    chapter_number: int
    kind: str


@dataclass
class Card:
    name: str
    first_chapter_index: int
    first_chapter_number: int
    impression: str
    impression_title: str
    quote: str
    quote_chapter_index: int
    quote_chapter_number: int
    quote_title: str
    aliases: list[AliasHit] = field(default_factory=list)
    facts: list[FactHit] = field(default_factory=list)

    def aliases_before(self) -> list[str]:
        return _unique(
            hit.alias
            for hit in self.aliases
            if hit.chapter_index <= self.first_chapter_index
        )

    def aliases_after(self) -> list[AliasHit]:
        return [hit for hit in self.aliases if hit.chapter_index > self.first_chapter_index]

    def facts_after(self) -> list[FactHit]:
        return [hit for hit in self.facts if hit.chapter_index > self.first_chapter_index]


def cards_from_gate(gated: GatedBook) -> list[Card]:
    sentences = _sentences(gated)
    people: dict[str, Card] = {}
    order: list[str] = []

    def person_for(name: str, sentence: Sentence) -> Card:
        key = name.casefold()
        card = people.get(key)
        if card is None:
            card = Card(
                name=name,
                first_chapter_index=sentence.chapter_index,
                first_chapter_number=sentence.chapter_number,
                impression=sentence.text,
                impression_title=sentence.chapter_title,
                quote=sentence.text,
                quote_chapter_index=sentence.chapter_index,
                quote_chapter_number=sentence.chapter_number,
                quote_title=sentence.chapter_title,
            )
            first = name.split()[0]
            card.aliases.append(
                AliasHit(
                    alias=first,
                    chapter_index=sentence.chapter_index,
                    chapter_number=sentence.chapter_number,
                    excerpt=sentence.text,
                )
            )
            people[key] = card
            order.append(key)
        return card

    for sentence in sentences:
        for match in _FULL_NAME.finditer(sentence.text):
            name = match.group(1)
            if _is_place(name) or name.split()[0].casefold() in _NOT_A_NAME:
                continue
            person_for(name, sentence)
        for pattern in (_CALLS_NAMED, _KNOW_AS, _NAMED_THE):
            found = pattern.search(sentence.text)
            if not found:
                continue
            target_name, alias = found.group(1), _clean_alias(found.group(2))
            if _is_place(target_name) or not alias:
                continue
            card = person_for(target_name, sentence)
            _add_alias(card, alias, sentence)

    for sentence in sentences:
        mentioned = [
            people[key]
            for key in order
            if _mentions(sentence.text, people[key])
        ]
        if not mentioned or not _RELATION.search(sentence.text):
            continue
        for card in mentioned:
            if any(fact.text == sentence.text for fact in card.facts):
                continue
            card.facts.append(
                FactHit(
                    text=sentence.text,
                    chapter_index=sentence.chapter_index,
                    chapter_number=sentence.chapter_number,
                    kind="relationship",
                )
            )
    return [people[key] for key in order]


def match_card(cards: list[Card], query: str) -> tuple[Card, str] | list[str] | None:
    """One card, a list of display names when several match, or None."""
    needle = _norm(query)
    if not needle:
        return None
    exact: list[tuple[Card, str]] = []
    for card in cards:
        labels = [card.name, *(hit.alias for hit in card.aliases)]
        for label in labels:
            if _norm(label) == needle:
                exact.append((card, label))
                break
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return [card.name for card, _label in exact]
    article: list[tuple[Card, str]] = []
    for card in cards:
        for hit in card.aliases:
            alias = _norm(hit.alias)
            if alias == f"the {needle}":
                article.append((card, hit.alias))
                break
    if len(article) == 1:
        return article[0]
    if len(article) > 1:
        return [card.name for card, _label in article]
    return None


def quote_for(card: Card, matched_label: str) -> tuple[str, int, int, str]:
    """Ground the reply in the line that justifies the name the reader used."""
    for hit in card.aliases:
        if _norm(hit.alias) == _norm(matched_label) and hit.chapter_index > card.first_chapter_index:
            return hit.excerpt, hit.chapter_index, hit.chapter_number, ""
    return (
        card.impression,
        card.first_chapter_index,
        card.first_chapter_number,
        card.impression_title,
    )


def _add_alias(card: Card, alias: str, sentence: Sentence) -> None:
    if _norm(alias) == _norm(card.name):
        return
    if any(_norm(hit.alias) == _norm(alias) for hit in card.aliases):
        return
    card.aliases.append(
        AliasHit(
            alias=alias,
            chapter_index=sentence.chapter_index,
            chapter_number=sentence.chapter_number,
            excerpt=sentence.text,
        )
    )


def _mentions(text: str, card: Card) -> bool:
    labels = [card.name, *(hit.alias for hit in card.aliases)]
    return any(
        re.search(rf"\b{re.escape(label)}\b", text, re.IGNORECASE) for label in labels
    )


def _sentences(gated: GatedBook) -> list[Sentence]:
    found: list[Sentence] = []
    for chapter in gated.chapters:
        for piece in _split_sentences(chapter.text):
            found.append(
                Sentence(
                    chapter_index=chapter.index,
                    chapter_number=chapter.number,
                    chapter_title=chapter.title,
                    text=piece,
                )
            )
    return found


def _split_sentences(text: str) -> list[str]:
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        flat = " ".join(paragraph.split())
        if not flat:
            continue
        parts = re.split(r"(?<=[.!?])\s+", flat)
        pieces.extend(part for part in parts if part)
    return pieces


def _is_place(name: str) -> bool:
    last = name.split()[-1].casefold()
    return last in _PLACE_LAST


def _clean_alias(alias: str) -> str:
    return " ".join(alias.split())


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def search_passages(gated: GatedBook, query: str, limit: int = 5) -> list[dict[str, object]]:
    """Score sentences inside the gate. There is no other text to score."""
    terms = _terms(query)
    if not terms:
        return []
    phrase = " ".join(query.split()).casefold()
    hits: list[tuple[int, int, GatedChapter, str]] = []
    for chapter in gated.chapters:
        for sentence in _split_sentences(chapter.text):
            folded = sentence.casefold()
            score = sum(1 for term in terms if term in _terms(sentence))
            if phrase and phrase in folded:
                score += 2
            if score <= 0:
                continue
            hits.append((score, chapter.index, chapter, sentence))
    hits.sort(key=lambda item: (-item[0], item[1], item[3]))
    passages: list[dict[str, object]] = []
    seen: set[str] = set()
    for score, _index, chapter, sentence in hits:
        if sentence in seen:
            continue
        seen.add(sentence)
        excerpt = sentence if len(sentence) <= 320 else sentence[:317].rstrip() + "..."
        passages.append(
            {
                "chapter_index": chapter.index,
                "chapter_number": chapter.number,
                "chapter_id": chapter.chapter_id,
                "chapter_title": chapter.title,
                "excerpt": excerpt,
                "score": score,
            }
        )
        if len(passages) >= limit:
            break
    return passages


_STOP = {
    "a",
    "an",
    "the",
    "of",
    "and",
    "or",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "was",
    "what",
    "who",
    "did",
    "does",
    "about",
    "her",
    "his",
    "their",
}


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.casefold())
    return [word for word in words if len(word) > 2 and word not in _STOP]
