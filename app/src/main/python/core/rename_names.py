"""Filename normalization primitives shared by rename planning."""

from __future__ import annotations

import os
import re
from pathlib import Path

from core.multipart_tokens import detect_multipart_token, strip_part_token
from core.scrapers.utils import extract_number, normalize_number_impl


SIDECAR_EXTENSIONS = frozenset({
    ".nfo", ".jpg", ".jpeg", ".png", ".webp",
    ".srt", ".ass", ".ssa", ".vtt", ".strm",
})
SIDECAR_SEPARATORS = frozenset(" .-_[(【")
LEADING_SEPARATORS = " \t\u3000-_＿－"
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_COMPONENT_BYTES = 255
TRUNCATION_MARKER = "..."
PORTABLE_FILENAME_REPLACEMENTS = str.maketrans({
    "<": "＜",
    ">": "＞",
    ":": "：",
    '"': "＂",
    "/": "／",
    "\\": "＼",
    "|": "｜",
    "?": "？",
    "*": "＊",
})


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).casefold()


def _number_pattern(number: str) -> re.Pattern[str]:
    escaped = re.escape(number)
    flexible = escaped.replace(r"\-", r"[\s_-]*")
    return re.compile(
        rf"(?<![A-Za-z0-9]){flexible}(?![0-9])",
        re.IGNORECASE,
    )


def multipart_token(stem: str) -> str | None:
    """Return the last multipart suffix token such as ``cd1``."""
    match = detect_multipart_token(stem)
    return match[0] if match else None


def _strip_multipart_token(stem: str) -> str:
    return strip_part_token(stem)


def _append_multipart_token(stem: str, token: str | None) -> str:
    if not token:
        return stem
    return f"{_strip_multipart_token(stem).rstrip(' .-_')}-{token}"


def canonicalize_stem(stem: str, number_hint: str | None = None) -> tuple[str, str | None, str]:
    """Return (new_stem, number, reason). The original title body is preserved."""
    token = multipart_token(stem)
    canonical_input = _strip_multipart_token(stem) if token else stem
    number = extract_number(canonical_input) or number_hint
    if number:
        number = normalize_number_impl(str(number))
    if not number:
        return stem, None, "no_number"

    match = _number_pattern(number).search(canonical_input)
    if match is None:
        return stem, number, "number_not_located"

    title = canonical_input[match.end():].lstrip(LEADING_SEPARATORS)
    canonical = number if not title else f"{number} {title}"
    if canonical.endswith(TRUNCATION_MARKER):
        # Preserve the safety marker so a preview that truncated a name is
        # stable when the user opens it again.
        canonical = (
            canonical[:-len(TRUNCATION_MARKER)].rstrip(" .")
            + TRUNCATION_MARKER
        )
    else:
        canonical = canonical.rstrip(" .")
    if not canonical:
        return stem, number, "empty_name"
    canonical = _append_multipart_token(canonical, token)
    if canonical == stem:
        return stem, number, "unchanged"
    return canonical, number, "rename"


def canonicalize_source_stem(
    number: str | None,
    title: str | None,
    part_token: str | None = None,
) -> tuple[str | None, str | None, str]:
    """Build `NUMBER TITLE` from one selected metadata source."""
    if not number:
        return None, None, "no_number"
    normalized = normalize_number_impl(str(number))
    cleaned = str(title or "").translate(PORTABLE_FILENAME_REPLACEMENTS)
    cleaned = "".join(
        character
        for character in cleaned
        if character >= " " and character != "\x7f"
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    if not cleaned:
        return None, normalized, "empty_title"

    match = _number_pattern(normalized).match(cleaned)
    if match:
        cleaned = cleaned[match.end():].lstrip(LEADING_SEPARATORS)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    if not cleaned:
        return None, normalized, "empty_title"
    return (
        _append_multipart_token(f"{normalized} {cleaned}", part_token),
        normalized,
        "source_title",
    )


def _sidecar_matches(old_stem: str, name: str) -> bool:
    if not name.startswith(old_stem):
        return False
    if name == old_stem:
        return False
    return name[len(old_stem)] in SIDECAR_SEPARATORS


def _operation_kind(name: str, video_extensions: set[str]) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".nfo":
        return "nfo"
    if suffix == ".srt" or suffix == ".ass" or suffix == ".ssa" or suffix == ".vtt":
        return "subtitle"
    if suffix in IMAGE_EXTENSIONS:
        lower = name.lower()
        if "-poster." in lower:
            return "poster"
        if "-fanart." in lower:
            return "fanart"
        return "cover"
    if suffix == ".strm":
        return "strm"
    if suffix in video_extensions:
        return "video"
    return "sidecar"


def _utf8_len(value: str) -> int:
    return len(value.encode("utf-8"))


def _truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    used = 0
    output = []
    for character in value:
        size = len(character.encode("utf-8"))
        if used + size > max_bytes:
            break
        output.append(character)
        used += size
    return "".join(output)


def _fit_filename_stem(
    stem: str,
    suffix_bytes: int,
    *,
    max_name_bytes: int = MAX_COMPONENT_BYTES,
) -> str | None:
    """Fit a shared stem while keeping the number and a visible ellipsis."""
    budget = max_name_bytes - suffix_bytes
    if _utf8_len(stem) <= budget:
        return stem
    prefix_match = re.match(r"^([A-Z0-9]+(?:-[A-Z0-9]+)* )", stem, re.IGNORECASE)
    prefix = prefix_match.group(1) if prefix_match else ""
    body = stem[len(prefix):]
    marker_bytes = len(TRUNCATION_MARKER.encode("ascii"))
    body_budget = budget - _utf8_len(prefix) - marker_bytes
    if body_budget < 0:
        return None
    body = _truncate_utf8(body, body_budget).rstrip(" .-_")
    return f"{prefix}{body}{TRUNCATION_MARKER}"


def _sidecar_suffix(name: str, stems: list[str]) -> str | None:
    for stem in sorted(set(stems), key=_utf8_len, reverse=True):
        if _sidecar_matches(stem, name):
            return name[len(stem):]
    lower = name.lower()
    for marker in ("-poster.", "-fanart."):
        position = lower.rfind(marker)
        if position >= 0:
            return name[position:]
    suffix = Path(name).suffix
    if suffix.lower() in IMAGE_EXTENSIONS | {".nfo", ".strm"}:
        return suffix
    subtitle = re.search(
        r"(?:\.[A-Za-z0-9_-]{2,10})*\.(?:srt|ass|ssa|vtt)$",
        name,
        re.IGNORECASE,
    )
    return subtitle.group(0) if subtitle else None


def _find_repair_video(
    expected_path: Path,
    number: str | None,
    video_extensions: set[str],
) -> Path | None:
    """Find a unique same-number video when MTP/FUSE truncated its filename."""
    if not number:
        return None
    try:
        if not expected_path.parent.is_dir():
            return None
    except OSError:
        return None
    normalized = normalize_number_impl(str(number))
    matches = []
    try:
        children = expected_path.parent.iterdir()
        for child in children:
            if not child.is_file() or child.suffix.lower() not in video_extensions:
                continue
            candidate_number = extract_number(child.name)
            if candidate_number and normalize_number_impl(candidate_number) == normalized:
                matches.append(child)
    except OSError:
        return None
    return matches[0] if len(matches) == 1 else None
