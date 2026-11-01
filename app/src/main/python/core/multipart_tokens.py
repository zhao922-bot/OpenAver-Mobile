"""Shared multipart filename token primitives.

The organizer, rename planner, and grouping layer must agree on which suffix
tokens identify multiple parts of the same work. Keep the vocabulary and regex
in one place so those callers cannot drift.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple


MULTIPART_TOKENS = frozenset({"cd", "dvd", "part", "pt", "disc"})

# Tokens accept one digit from 1-9. The leading and trailing guards prevent
# accidental matches inside ordinary words such as "apartment1".
MULTIPART_RE = re.compile(
    r"(?<![A-Za-z0-9])(cd|dvd|part|pt|disc)([1-9])(?![0-9])"
    r"(?=[-_.\s\[\]()]|$)",
    re.IGNORECASE,
)


def detect_multipart_token(filename: str) -> Optional[Tuple[str, int]]:
    """Return ``(token, part_number)`` for the last token in a filename."""
    if not filename:
        return None
    stem = os.path.splitext(filename)[0]
    matches = list(MULTIPART_RE.finditer(stem))
    if not matches:
        return None
    match = matches[-1]
    token = f"{match.group(1).lower()}{match.group(2)}"
    return token, int(match.group(2))


def strip_part_token(stem: str) -> str:
    """Remove the last multipart token and its leading separator."""
    if not stem:
        return stem
    matches = list(MULTIPART_RE.finditer(stem))
    if not matches:
        return stem
    match = matches[-1]
    start = match.start()
    if start > 0 and stem[start - 1] in "-_. \t([":
        start -= 1
    return stem[:start] + stem[match.end():]


def is_multipart_keyword(keyword: str) -> bool:
    """Return whether a suffix keyword is a complete multipart token."""
    if not keyword:
        return False
    stripped = keyword.lstrip("-_. ")
    if not stripped:
        return False
    return re.fullmatch(
        r"(cd|dvd|part|pt|disc)([1-9])",
        stripped,
        re.IGNORECASE,
    ) is not None
