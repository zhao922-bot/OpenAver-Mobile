from __future__ import annotations

import asyncio

from core import translate_service
from core.title_language import (
    TRANSLATION_REFUSAL_MARKER,
    normalize_translation_text,
    title_matches_target_language,
    title_needs_translation,
    translation_result_issue,
)


def test_chinese_target_rejects_the_other_script():
    assert title_matches_target_language("这是简体标题", "zh-CN") is True
    assert title_matches_target_language("這是繁體標題", "zh-CN") is False
    assert title_matches_target_language("這是繁體標題", "zh-TW") is True
    assert title_matches_target_language("这是简体标题", "zh-TW") is False


def test_japanese_target_requires_japanese_script():
    assert title_matches_target_language("これは日本語です", "ja") is True
    assert title_matches_target_language("中文标题", "ja") is False
    assert title_matches_target_language("English title", "ja") is False


def test_english_target_rejects_cjk_and_accepts_latin():
    assert title_matches_target_language("An English Title", "en") is True
    assert title_matches_target_language("日本語のタイトル", "en") is False
    assert title_matches_target_language("繁體中文標題", "en") is False


def test_korean_target_requires_hangul():
    assert title_matches_target_language("한국어 제목입니다", "ko") is True
    assert title_matches_target_language("日本語のタイトル", "ko") is False
    assert title_matches_target_language("简体中文标题", "ko") is False
    assert title_matches_target_language("English title", "ko") is False


def test_translation_need_follows_the_active_locale():
    assert title_needs_translation("これは日本語です", "zh-CN") is True
    assert title_needs_translation("这是简体标题", "zh-CN") is False
    assert title_needs_translation("這是繁體標題", "zh-CN") is True
    assert title_needs_translation("English title", "en") is False
    assert title_needs_translation("これは日本語です", "en") is True


def test_all_five_locales_use_the_same_target_language_policy():
    cases = {
        "zh-CN": {
            "这是简体标题": False,
            "這是繁體標題": True,
            "これは日本語です": True,
            "English title": True,
        },
        "zh-TW": {
            "这是简体标题": True,
            "這是繁體標題": False,
            "これは日本語です": True,
            "English title": True,
        },
        "en": {
            "这是简体标题": True,
            "這是繁體標題": True,
            "これは日本語です": True,
            "English title": False,
        },
        "ja": {
            "这是简体标题": True,
            "這是繁體標題": True,
            "これは日本語です": False,
            "English title": True,
        },
        "ko": {
            "这是简体标题": True,
            "這是繁體標題": True,
            "これは日本語です": True,
            "한국어 제목입니다": False,
            "English title": True,
        },
    }
    for locale, titles in cases.items():
        for title, expected in titles.items():
            assert title_needs_translation(title, locale) is expected


def test_chinese_target_accepts_proper_name_script_residue():
    simplified_with_traditional_name = (
        "[IPZZ-065]出差三天轮番上阵…带男人进房间的绝伦美女白领"
        "-即交型便利绝伦性爱-明里紬"
    )
    simplified_with_kana_name = (
        "[SSIS-897]终生难忘的一天：与空姐青梅竹马重逢，起飞前亲吻，"
        "如乱流般激烈的一次性爱。つばさ舞 附生写真3张"
    )

    assert title_needs_translation(
        simplified_with_traditional_name,
        "zh-CN",
    ) is False
    assert title_needs_translation(
        simplified_with_kana_name,
        "zh-CN",
    ) is False
    assert title_needs_translation("這是繁體標題", "zh-CN") is True
    assert title_needs_translation(
        "これは日本語の長いタイトルです",
        "zh-CN",
    ) is True


def test_known_proper_terms_do_not_force_retranslation():
    title = "终极诱惑逐渐升温的一段办公室秘密恋情 明里つむぎ"

    assert title_needs_translation(title, "zh-CN") is False
    assert title_needs_translation(
        title,
        "zh-CN",
        proper_terms=["明里つむぎ"],
    ) is False
    assert title_needs_translation(
        title,
        "zh-CN",
        proper_terms="明里つむぎ",
    ) is False


def test_translation_result_validation_rejects_model_failures():
    refusal = (
        "抱歉，我无法协助翻译这个标题。该内容属于我不能处理的范畴。"
        "\n\n如果您有其他标题，我很乐意提供帮助。"
    )
    source = "先輩って夜はすごく激しいんですね"

    assert translation_result_issue(source, refusal, "zh-CN") == "refusal"
    assert title_needs_translation(refusal, "zh-CN") is True
    assert translation_result_issue(source, source, "zh-CN") == "source_echo"
    assert translation_result_issue(source, "English title", "zh-CN") == "wrong_target_language"
    assert translation_result_issue(source, "这是正常译文", "zh-CN") is None


def test_translation_result_validation_rejects_policy_refusals():
    source = (
        "あの美術の先生が僕らのチ○ポをこんなに下品にしゃぶってくれるなんて"
        "夢みたいだ 明里つむぎ"
    )
    refusal = (
        "抱歉，该标题涉及校园师生性内容，可能涉及未成年人，无法处理；"
        "其他标题欢迎再询。"
    )

    assert translation_result_issue(source, refusal, "zh-CN") == "refusal"
    assert (
        translation_result_issue(
            source,
            f"Translation result: {TRANSLATION_REFUSAL_MARKER}",
            "zh-CN",
        )
        == "refusal"
    )
    assert title_needs_translation(refusal, "zh-CN") is True


def test_cloud_prompts_require_a_stable_refusal_marker():
    for locale in ("zh-CN", "zh-TW", "en", "ja", "ko"):
        prompt = translate_service.build_cloud_translate_prompt(
            "日本語のタイトル",
            locale,
        )
        assert TRANSLATION_REFUSAL_MARKER in prompt
        assert translate_service.refusal_rule(locale) in prompt


def test_prompt_shell_and_labels_follow_the_target_language():
    expected = {
        "zh-CN": ("原文：", "翻译要求：", "示例：", "请翻译："),
        "zh-TW": ("原文：", "翻譯要求：", "範例：", "請翻譯："),
        "en": ("Source title:", "Translation requirements:", "Example:", "Translate:"),
        "ja": ("原文：", "翻訳要件：", "例：", "翻訳："),
        "ko": ("원문:", "번역 요구 사항:", "예:", "번역:"),
    }

    for locale, labels in expected.items():
        cloud_prompt = translate_service.build_cloud_translate_prompt(
            "テストタイトル",
            locale,
        )
        _system, ollama_prompt = translate_service.build_ollama_prompts(
            "テストタイトル",
            locale,
        )
        source_label, rules_label, example_label, translate_label = labels
        assert source_label in cloud_prompt
        assert rules_label in cloud_prompt
        assert example_label in ollama_prompt
        assert translate_label in ollama_prompt
        assert translate_service.LANGUAGE_PROMPTS[locale]["retry_instruction"]

    simplified_prompt = translate_service.build_cloud_translate_prompt(
        "日本語のタイトル",
        "zh-CN",
    )
    assert "你是专业的影视数据库管理员与翻译引擎" in simplified_prompt
    assert "翻譯要求：" not in simplified_prompt
    assert "這是既有標題文字的翻譯任務" not in simplified_prompt
    _system, simplified_ollama = translate_service.build_ollama_prompts(
        "日本語のタイトル",
        "zh-CN",
    )
    assert "示例：" in simplified_ollama
    assert "请翻译：" in simplified_ollama
    assert "範例：" not in simplified_ollama
    assert "請翻譯：" not in simplified_ollama


def test_translation_normalization_removes_only_wrappers():
    assert normalize_translation_text('  译文："这是标题"  ') == "这是标题"
    assert normalize_translation_text("Translation: English title") == "English title"
    assert normalize_translation_text("『原文保留』") == "『原文保留』"


def test_japanese_translation_prompt_has_a_real_provider_path(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "message": {
                    "content": "日本語に翻訳したタイトル",
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            calls["url"] = url
            calls["json"] = json
            return FakeResponse()

    monkeypatch.setattr(translate_service.httpx, "AsyncClient", FakeClient)
    service = translate_service.OllamaTranslateService(
        {"url": "http://localhost:11434", "model": "test"},
        "ja",
    )

    result = asyncio.run(service.translate_or_raise("English title"))

    assert result == "日本語に翻訳したタイトル"
    assert calls["url"].endswith("/api/chat")
    assert "日本語" in calls["json"]["messages"][0]["content"]
