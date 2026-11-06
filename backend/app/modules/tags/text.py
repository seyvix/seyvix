"""Text helpers shared by tags and taxonomy: label slugs and match tokens."""

from __future__ import annotations

import re
import unicodedata

# Same transliteration as the web client (web/src/api/*.ts `slugify`) so client-side
# "find by slug" and server-side slugs agree for Cyrillic labels.
_CYRILLIC_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya",
    }
)  # fmt: skip
_NON_SLUG_RE = re.compile(r"[\W_]+", re.UNICODE)
_TOKEN_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_FILENAME_HEADING_RE = re.compile(r"[\w .()\-\u0400-\u04FF]+\.[A-Za-z0-9]{1,8}")


def slugify_label(value: str) -> str:
    """URL-safe slug for a human label. Cyrillic is transliterated, other scripts are kept.

    Returns "" when the label has no letters or digits.
    """
    lowered = value.strip().casefold().translate(_CYRILLIC_TRANSLIT)
    decomposed = unicodedata.normalize("NFKD", lowered)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_SLUG_RE.sub("-", without_marks).strip("-")


def match_tokens(text: str, *, min_length: int = 2, limit: int | None = None) -> list[str]:
    """Distinct case-folded word tokens in order of first appearance."""
    seen: dict[str, None] = {}
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold()
        if len(token) < min_length or token in seen:
            continue
        seen[token] = None
        if limit is not None and len(seen) >= limit:
            break
    return list(seen)


def looks_like_filename(line: str) -> bool:
    return bool(_FILENAME_HEADING_RE.fullmatch(line.strip().lstrip("#").strip()))


def strip_filename_heading(text: str) -> str:
    """Drop a leading `# report.pdf`-style heading that only repeats the file name."""
    lines = text.splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return ""
    if not looks_like_filename(lines[first]):
        return text
    del lines[first]
    return "\n".join(lines).strip()
