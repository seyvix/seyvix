"""Query parsing: tsquery construction, light stemming, metadata term variants, highlighting."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.search.schemas import SearchHighlightRange

MAX_TERMS = 16
_WORD_RE = re.compile(r"[^\W_]+")
_HIGHLIGHT_TERM_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё_]{2,}")
_CYRILLIC_RE = re.compile(r"[а-яё]")
_WEBSEARCH_RE = re.compile(r"\"|(?:^|\s)-\w|\s(?:or|OR)\s")
_LATIN_SUFFIXES = ("ing", "ed", "s")

GENERIC_NEW_TERMS = frozenset({"new", "latest", "fresh"})
_NEW_VARIANTS = frozenset(
    {
        "new",
        "latest",
        "fresh",
        "нов",
        "анонс",
        "announc",
        "релиз",
        "release",
        "update",
        "обнов",
        "апдейт",
        "выйдет",
    }
)
_GAME_VARIANTS = frozenset({"game", "games", "gaming", "video game", "игр"})


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    text: str
    terms: tuple[str, ...]
    websearch: bool

    @classmethod
    def parse(cls, text: str) -> ParsedQuery:
        seen: set[str] = set()
        terms: list[str] = []
        for match in _WORD_RE.finditer(text.casefold()):
            term = match.group(0)
            if term not in seen:
                seen.add(term)
                terms.append(term)
            if len(terms) >= MAX_TERMS:
                break
        return cls(text=text, terms=tuple(terms), websearch=bool(_WEBSEARCH_RE.search(text)))

    def strict_tsquery(self) -> str | None:
        """All terms (AND); the last one as a prefix so search-as-you-type works."""
        if not self.terms:
            return None
        *head, last = self.terms
        parts = [f"'{term}'" for term in head]
        parts.append(f"'{last}':*" if len(last) >= 2 else f"'{last}'")
        return " & ".join(parts)

    def loose_tsquery(self) -> str | None:
        """Any term (OR), each as a prefix of its light stem: catches inflections and words
        spread over several chunks. None when it would equal the strict query."""
        if not self.terms:
            return None
        parts = [f"'{stem}':*" for stem in dict.fromkeys(light_stem(t) for t in self.terms)]
        loose = " | ".join(parts)
        return None if loose == self.strict_tsquery() else loose


def light_stem(term: str) -> str:
    """Language-agnostic suffix trimming good enough for prefix matching (ru/en)."""
    if _CYRILLIC_RE.search(term):
        if len(term) >= 6:
            return term[:-2]
        if len(term) >= 4:
            return term[:-1]
        return term
    for suffix in _LATIN_SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= 3:
            return term[: -len(suffix)]
    return term


@dataclass(frozen=True, slots=True)
class TermGroup:
    variants: tuple[str, ...]
    generic: bool


def metadata_term_groups(query: str) -> list[TermGroup]:
    """Per-term substring variants (synonyms + Russian stem) for live-metadata matching."""
    groups: list[TermGroup] = []
    seen: set[str] = set()
    for raw in _HIGHLIGHT_TERM_RE.findall(query.casefold()):
        term = raw.strip("_")
        if not term or term in seen:
            continue
        seen.add(term)
        variants = {term}
        generic = False
        if _CYRILLIC_RE.search(term) and len(term) >= 4:
            variants.add(term[:-1])
        if term in GENERIC_NEW_TERMS or term.startswith("нов"):
            variants |= _NEW_VARIANTS
            generic = True
        if term in {"game", "games", "gaming"} or term.startswith("игр"):
            variants |= _GAME_VARIANTS
        groups.append(
            TermGroup(
                variants=tuple(sorted((v for v in variants if len(v) >= 2), key=len, reverse=True)),
                generic=generic,
            )
        )
        if len(groups) >= MAX_TERMS:
            break
    return groups


def metadata_score(query: str, groups: list[TermGroup], parts: list[tuple[str, float]]) -> float:
    """Weighted substring score over (text, weight) parts; 0 means no match.

    A whole-query hit triples the field weight; matching every term doubles the total; a
    query with specific terms must match at least one of them (generic words alone don't).
    """
    if not groups or not parts:
        return 0.0
    lowered_parts = [(text.casefold(), weight) for text, weight in parts if text]
    normalized_query = query.casefold().strip()
    has_specific = any(not group.generic for group in groups)
    matched_specific = False
    matched_groups = 0
    score = 0.0
    for group in groups:
        group_score = 0.0
        for lowered, weight in lowered_parts:
            if normalized_query and normalized_query in lowered:
                group_score = max(group_score, weight * 3)
            elif any(variant in lowered for variant in group.variants):
                group_score = max(group_score, weight)
        if group_score <= 0:
            continue
        matched_groups += 1
        score += group_score
        matched_specific = matched_specific or not group.generic
    if matched_groups == 0 or (has_specific and not matched_specific):
        return 0.0
    return score * 2 if matched_groups == len(groups) else score


def highlight_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in _HIGHLIGHT_TERM_RE.findall(query):
        normalized = term.casefold()
        if normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)
    return sorted(terms, key=len, reverse=True)


def highlight_ranges(text: str, terms: list[str]) -> list[SearchHighlightRange]:
    if not terms:
        return []
    lowered = text.casefold()
    raw: list[tuple[int, int]] = []
    for term in terms:
        start = lowered.find(term)
        while start != -1:
            raw.append((start, start + len(term)))
            start = lowered.find(term, start + len(term))
    ranges: list[SearchHighlightRange] = []
    occupied_until = -1
    for start, end in sorted(raw, key=lambda item: (item[0], -item[1])):
        if start >= occupied_until:
            ranges.append(SearchHighlightRange(start=start, end=end))
            occupied_until = end
    return ranges
