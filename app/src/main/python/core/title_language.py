"""Target-language checks for library title translation."""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.i18n import normalize_locale
from core.title_language_data import (
    SIMPLIFIED_ONLY_CHARS,
    TRADITIONAL_ONLY_CHARS,
)

_KANA_RATIO_FOR_JAPANESE = 0.18
_LATIN_RATIO_FOR_ENGLISH = 0.65
_SCRIPT_MARKER_RATIO = 0.12
_JAPANESE_GRAMMAR_RE = re.compile(
    r"(?:の|を|は|が|に|で|と|へ|から|まで|より|です|ます|して|する|した|しない|される)"
)
_TRANSLATION_LABEL_RE = re.compile(
    r"^(?:译文|譯文|翻译|翻譯|翻訳|번역|translation|output)\s*[:：]\s*",
    re.IGNORECASE,
)
_ZERO_WIDTH_RE = re.compile(r"[\ufeff\u200b\u200c\u200d]")
TRANSLATION_REFUSAL_MARKER = "__OPENAVER_TRANSLATION_REFUSED__"


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


def _is_hangul(character: str) -> bool:
    code = ord(character)
    return (
        0x1100 <= code <= 0x11FF
        or 0x3130 <= code <= 0x318F
        or 0xA960 <= code <= 0xA97F
        or 0xAC00 <= code <= 0xD7AF
        or 0xD7B0 <= code <= 0xD7FF
    )


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


def _has_hangul(text: str) -> bool:
    return any(_is_hangul(character) for character in text)


def _strip_proper_terms(text: str, proper_terms: Iterable[str] | None) -> str:
    cleaned = text
    values = (
        [proper_terms]
        if isinstance(proper_terms, str)
        else (proper_terms or ())
    )
    for term in sorted(
        {
            str(value or "").strip()
            for value in values
            if str(value or "").strip()
        },
        key=len,
        reverse=True,
    ):
        cleaned = re.sub(re.escape(term), "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _looks_japanese(text: str) -> bool:
    han_count = sum(_is_han(character) for character in text)
    kana_count = sum(_is_kana(character) for character in text)
    script_total = han_count + kana_count
    if not kana_count or not script_total:
        return False
    kana_ratio = kana_count / script_total
    return (
        kana_ratio >= _KANA_RATIO_FOR_JAPANESE
        or (
            kana_count >= 1
            and kana_ratio >= 0.05
            and _JAPANESE_GRAMMAR_RE.search(text) is not None
        )
    )


def _is_refusal_text(text: str) -> bool:
    """Detect common model refusal/explanatory responses without matching titles."""
    folded = text.casefold()
    if TRANSLATION_REFUSAL_MARKER.casefold() in folded:
        return True

    prefix = folded[:280]
    checks = (
        r"(?:抱歉|对不起|對不起|不好意思).{0,60}(?:无法|無法|不能|不便|恕不)"
        r".{0,40}(?:协助|協助|翻译|翻譯|提供)",
        r"^(?:抱歉|对不起|對不起|不好意思)[^。！？\n]{0,120}"
        r"(?:标题|標題|内容|內容|请求|請求|title|request).{0,100}"
        r"(?:无法|無法|不能|不便).{0,40}"
        r"(?:处理|處理|翻译|翻譯|协助|協助|提供|回答|回覆|回应|回應"
        r"|help|translate|process)",
        r"^(?:抱歉|对不起|對不起|不好意思)[^。！？\n]{0,100}"
        r"(?:无法|無法|不能|不便).{0,40}"
        r"(?:处理|處理|翻译|翻譯|协助|協助|提供|回答|回覆|回应|回應)"
        r".{0,80}(?:其他|other).{0,40}"
        r"(?:标题|標題|title|询问|詢問|问|問)",
        r"(?:我|本模型|人工智能|ai).{0,30}(?:无法|無法|不能)"
        r".{0,30}(?:协助|協助|翻译|翻譯|完成)",
        r"(?:i am sorry|i'm sorry|sorry).{0,100}"
        r"(?:cannot|can't|can not|unable|not able)",
        r"(?:as an ai|i am an ai|i'm an ai).{0,120}",
        r"(?:申し訳|すみません).{0,80}(?:できません|対応できません|お答えできません)",
        r"(?:aiとして|私はai).{0,100}(?:できません|対応できません)",
        r"(?:죄송|미안).{0,100}(?:번역|처리|제공|도와).{0,50}"
        r"(?:수 없|불가|어렵)",
        r"(?:해당|이).{0,30}(?:제목|요청|내용).{0,100}"
        r"(?:번역|처리|제공).{0,50}(?:수 없|불가|어렵)",
        r"(?:ai|인공지능).{0,80}(?:수 없|불가|어렵)",
    )
    return any(re.search(pattern, prefix, re.IGNORECASE | re.DOTALL) for pattern in checks)


def _comparison_key(text: str) -> str:
    return "".join(
        character.casefold()
        for character in text
        if character.isalnum()
        or _is_han(character)
        or _is_kana(character)
        or _is_hangul(character)
    )


def normalize_translation_text(text: str) -> str:
    """Normalize common model wrappers while leaving the translated title intact."""
    cleaned = _ZERO_WIDTH_RE.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.strip()
    for _ in range(3):
        previous = cleaned
        cleaned = cleaned.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'", "“", "”", "「", "」"}:
            cleaned = cleaned[1:-1].strip()
        cleaned = _TRANSLATION_LABEL_RE.sub("", cleaned).strip()
        if cleaned == previous:
            break
    return cleaned


def title_matches_target_language(
    title: str,
    locale: str | None,
    proper_terms: Iterable[str] | None = None,
) -> bool:
    """Return whether *title* is already written in the active UI language.

    Script balance matters more than a single character: proper names often
    retain a traditional glyph or short kana sequence inside an otherwise
    translated title. Callers can pass known actor/brand names so those terms
    are ignored completely.
    """
    text = normalize_translation_text(title)
    if not text:
        return False
    if _is_refusal_text(text) or "\n\n" in text:
        return False

    script_text = _strip_proper_terms(text, proper_terms)
    if not script_text:
        script_text = text
    target = normalize_locale(locale)
    han_count = sum(_is_han(character) for character in script_text)
    kana_count = sum(_is_kana(character) for character in script_text)
    hangul_count = sum(_is_hangul(character) for character in script_text)
    latin_count = sum(
        "A" <= character <= "Z"
        or "a" <= character <= "z"
        or 0x00C0 <= ord(character) <= 0x024F
        for character in script_text
    )
    script_total = han_count + kana_count + hangul_count + latin_count

    if target == "en":
        return bool(
            latin_count
            and script_total
            and latin_count / script_total >= _LATIN_RATIO_FOR_ENGLISH
            and not _looks_japanese(script_text)
        )
    if target == "ja":
        return _looks_japanese(script_text)
    if target == "ko":
        return bool(
            hangul_count
            and script_total
            and hangul_count / script_total >= _SCRIPT_MARKER_RATIO
            and not _looks_japanese(script_text)
        )
    if _has_hangul(script_text):
        return False
    if not han_count or _looks_japanese(script_text):
        return False

    simplified_count = sum(
        character in SIMPLIFIED_ONLY_CHARS for character in script_text
    )
    traditional_count = sum(
        character in TRADITIONAL_ONLY_CHARS for character in script_text
    )
    marker_ratio = max(simplified_count, traditional_count) / han_count
    if target == "zh-CN":
        return not (
            traditional_count > simplified_count
            and marker_ratio >= _SCRIPT_MARKER_RATIO
        )
    if target == "zh-TW":
        return not (
            simplified_count > traditional_count
            and marker_ratio >= _SCRIPT_MARKER_RATIO
        )
    return False


def title_needs_translation(
    title: str,
    locale: str | None,
    proper_terms: Iterable[str] | None = None,
) -> bool:
    """Return whether the title is not in the active target language."""
    text = str(title or "").strip()
    return bool(
        text
        and not title_matches_target_language(text, locale, proper_terms)
    )


def translation_result_issue(
    source: str,
    translated: str,
    locale: str | None,
    proper_terms: Iterable[str] | None = None,
) -> str | None:
    """Return a stable failure code when a model result is not a usable title."""
    source_text = normalize_translation_text(source)
    result = normalize_translation_text(translated)
    if not result:
        return "empty_response"
    if _is_refusal_text(result):
        return "refusal"
    if "\n\n" in result:
        return "explanatory_response"
    if len(result) > max(400, len(source_text) * 3):
        return "explanatory_response"
    if _comparison_key(result) == _comparison_key(source_text):
        return "source_echo"
    if not title_matches_target_language(result, locale, proper_terms):
        return "wrong_target_language"
    return None


def plot_needs_translation(
    text: str,
    locale: str | None,
    proper_terms: Iterable[str] | None = None,
) -> bool:
    """Return whether a multi-paragraph synopsis is outside the target language."""
    value = normalize_translation_text(text)
    if not value:
        return False
    single_space = re.sub(r"\s+", " ", value).strip()
    return not title_matches_target_language(
        single_space,
        locale,
        proper_terms,
    )


def plot_translation_result_issue(
    source: str,
    translated: str,
    locale: str | None,
    proper_terms: Iterable[str] | None = None,
) -> str | None:
    """Validate a full synopsis translation without rejecting paragraphs.

    The title validator intentionally rejects blank lines and long outputs.
    A synopsis must allow both while still detecting refusals, source echoes,
    and output in the wrong target language.
    """
    source_text = normalize_translation_text(source)
    result = normalize_translation_text(translated)
    if not result:
        return "empty_response"
    if _is_refusal_text(result):
        return "refusal"
    if len(result) > max(1200, len(source_text) * 5):
        return "explanatory_response"
    if _comparison_key(result) == _comparison_key(source_text):
        return "source_echo"
    language_sample = re.sub(r"\s+", " ", result).strip()
    if not title_matches_target_language(
        language_sample,
        locale,
        proper_terms,
    ):
        return "wrong_target_language"
    return None
