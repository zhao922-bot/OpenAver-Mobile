"""Target-language checks for library title translation."""

from __future__ import annotations

from core.i18n import normalize_locale
from core.title_language_data import (
    SIMPLIFIED_ONLY_CHARS,
    TRADITIONAL_ONLY_CHARS,
)


def _is_han(character: str) -> bool:
    code = ord(character)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
    )


def _is_kana(character: str) -> bool:
    code = ord(character)
    return 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF


def _has_latin_letter(text: str) -> bool:
    return any(
        "A" <= character <= "Z"
        or "a" <= character <= "z"
        or 0x00C0 <= ord(character) <= 0x024F
        for character in text
    )


def _has_han(text: str) -> bool:
    return any(_is_han(character) for character in text)


def _has_kana(text: str) -> bool:
    return any(_is_kana(character) for character in text)


def title_matches_target_language(title: str, locale: str | None) -> bool:
    """Return whether *title* is already written in the active UI language.

    Han-only titles are treated as Chinese when they contain no character that
    OpenCC maps exclusively in the other Chinese script. Japanese titles are
    identified by kana, while English titles must contain Latin text and no
    CJK script. Ambiguous punctuation and number fragments never qualify.
    """
    text = str(title or "").strip()
    if not text:
        return False
    target = normalize_locale(locale)
    has_han = _has_han(text)
    has_kana = _has_kana(text)

    if target == "en":
        return _has_latin_letter(text) and not has_han and not has_kana
    if target == "ja":
        return has_kana
    if has_kana or not has_han:
        return False
    if target == "zh-CN":
        return not any(
            character in TRADITIONAL_ONLY_CHARS
            for character in text
        )
    if target == "zh-TW":
        return not any(
            character in SIMPLIFIED_ONLY_CHARS
            for character in text
        )
    return False


def title_needs_translation(title: str, locale: str | None) -> bool:
    """Return whether the title is not in the active target language."""
    text = str(title or "").strip()
    return bool(text and not title_matches_target_language(text, locale))
