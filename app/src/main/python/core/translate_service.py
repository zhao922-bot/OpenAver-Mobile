"""
翻譯服務抽象層 - 支援多個提供商

設計模式：策略模式
目的：解耦翻譯邏輯，便於擴展新提供商（Gemini）

使用方式：
    from core.translate_service import create_translate_service
    
    config = {"provider": "ollama", "ollama": {"url": "http://localhost:11434"}}
    service = create_translate_service(config)
    
    # 單片翻譯
    result = await service.translate_single("日文標題")
    
    # 批次翻譯
    results = await service.translate_batch(["標題1", "標題2", ...])
"""

from abc import ABC, abstractmethod
from core.logger import get_logger

logger = get_logger(__name__)
from typing import List, Dict, Optional
from core.ai_services.connections import provider_base_url, requires_api_key

import httpx
import re

from core import gemini_client, openai_client
from core.anthropic_client import (
    DEFAULT_CLAUDE_MODEL,
    request_translation,
)
from core.cloud_translate import CLOUD_TRANSLATE_TIMEOUT, TranslateError, build_error
from core.title_language import (
    TRANSLATION_REFUSAL_MARKER,
    normalize_translation_text,
    plot_translation_result_issue,
    translation_result_issue,
)


PLOT_TRANSLATE_TIMEOUT = 180
PLOT_MAX_TOKENS = 4096


# ============ 語言 Prompt 模板 ============

LANGUAGE_PROMPTS = {
    "zh-TW": {
        "name": "繁體中文",
        "cloud_intro": "你是專業的影視資料庫管理員與翻譯引擎。這是既有標題文字的翻譯任務。",
        "source_label": "原文：",
        "rules_label": "翻譯要求：",
        "ollama_system": "你是多語言影視標題翻譯機。自動辨識原文語言，統一到繁體中文輸出。禁止輸出日文假名或其他語言的未翻譯內容（人名、品牌名除外）。保留原意，不新增內容。",
        "ollama_example": "義父の隣で夫に電話させながら人妻を寝取る → 在公公旁邊讓人妻一邊打電話給丈夫一邊被睡走",
        "ollama_example_label": "範例：",
        "ollama_translate_label": "請翻譯：",
        "gemini_instruction": "請自動辨識以下標題的原文語言，並翻譯為繁體中文",
        "gemini_rules": "1. 這是純粹的資料庫標題翻譯任務，不生成新內容\n2. 輸出必須是繁體中文，不能保留未翻譯的其他語言內容\n3. 保持簡潔，不超過50字\n4. 只輸出翻譯結果，不要額外說明\n5. 人名、品牌名保留原文",
        "retry_instruction": "只輸出最終譯文本身。不要評論、解釋、道歉，也不要輸出任何前綴。",
        "plot_cloud_intro": "你是專業的影視資料翻譯引擎。這是影片簡介的完整翻譯任務。",
        "plot_instruction": "將以下影片簡介完整翻譯為繁體中文",
        "plot_rules": "1. 逐句完整翻譯，不得概括、刪減或改寫劇情\n2. 保留原有段落、換行與標點結構\n3. 人名、品牌名與作品名保留原文\n4. 只輸出譯文，不添加標題、說明或註釋\n5. 不限制字數，不得截斷原文",
        "plot_ollama_system": "你是多語言影視簡介翻譯機。請將輸入完整翻譯為繁體中文，逐句保留原意、段落和換行；不得概括、刪減、續寫或添加說明。只輸出譯文。",
        "plot_label": "請完整翻譯：",
    },
    "zh-CN": {
        "name": "簡體中文",
        "cloud_intro": "你是专业的影视数据库管理员与翻译引擎。这是既有标题文字的翻译任务。",
        "source_label": "原文：",
        "rules_label": "翻译要求：",
        "ollama_system": "你是多语言影视标题翻译机。自动识别原文语言，统一到简体中文输出。禁止输出日文假名或其他语言的未翻译内容（人名、品牌名除外）。保留原意，不新增内容。",
        "ollama_example": "義父の隣で夫に電話させながら人妻を寝取る → 在公公旁边让人妻一边打电话给丈夫一边被睡走",
        "ollama_example_label": "示例：",
        "ollama_translate_label": "请翻译：",
        "gemini_instruction": "请自动识别以下标题的原文语言，并翻译为简体中文",
        "gemini_rules": "1. 这是纯粹的资料库标题翻译任务，不生成新内容\n2. 输出必须是简体中文，不能保留未翻译的其他语言内容\n3. 保持简洁，不超过50字\n4. 只输出翻译结果，不要额外说明\n5. 人名、品牌名保留原文",
        "retry_instruction": "只输出最终译文本身。不要评论、解释、道歉，也不要输出任何前缀。",
        "plot_cloud_intro": "你是专业的影视资料翻译引擎。这是视频简介的完整翻译任务。",
        "plot_instruction": "将以下视频简介完整翻译为简体中文",
        "plot_rules": "1. 逐句完整翻译，不得概括、删减或改写剧情\n2. 保留原有段落、换行与标点结构\n3. 人名、品牌名与作品名保留原文\n4. 只输出译文，不添加标题、说明或注释\n5. 不限制字数，不得截断原文",
        "plot_ollama_system": "你是多语言影视简介翻译机。请将输入完整翻译为简体中文，逐句保留原意、段落和换行；不得概括、删减、续写或添加说明。只输出译文。",
        "plot_label": "请完整翻译：",
    },
    "en": {
        "name": "English",
        "cloud_intro": "You are a professional audiovisual database administrator and translation engine. This is a translation task for an existing title.",
        "source_label": "Source title:",
        "rules_label": "Translation requirements:",
        "ollama_system": "You translate audiovisual database titles from any source language into natural English. Do not leave untranslated CJK text except proper nouns. Preserve meaning and do not add content.",
        "ollama_example": "義父の隣で夫に電話させながら人妻を寝取る → Seducing a Married Woman While She Calls Her Husband Next to Her Father-in-Law",
        "ollama_example_label": "Example:",
        "ollama_translate_label": "Translate:",
        "gemini_instruction": "Detect the source language and translate the following title into English",
        "gemini_rules": "1. This is a database title translation task, do not generate new content\n2. Output must be natural English with no untranslated CJK text except proper nouns\n3. Keep it concise, under 80 characters\n4. Output only the translation, no explanations",
        "retry_instruction": "Output only the final translation. Do not comment, explain, apologize, or add any prefix.",
        "plot_cloud_intro": "You are a professional audiovisual translation engine. This is a complete synopsis translation task.",
        "plot_instruction": "Translate the following video synopsis completely into natural English",
        "plot_rules": "1. Translate every sentence completely; do not summarize, omit, or invent details\n2. Preserve the original paragraphs, line breaks, and punctuation structure\n3. Keep names, brands, and work titles unchanged\n4. Output only the translation, with no heading, note, or explanation\n5. Do not impose a character limit and do not truncate the source",
        "plot_ollama_system": "You translate multilingual video synopses into English. Preserve every sentence, paragraph, and line break; never summarize, omit, continue, or explain. Output only the translation.",
        "plot_label": "Translate completely:",
    },
    "ja": {
        "name": "日本語",
        "cloud_intro": "あなたはプロの映像データベース管理者兼翻訳エンジンです。既存のタイトルを翻訳するタスクです。",
        "source_label": "原文：",
        "rules_label": "翻訳要件：",
        "ollama_system": "あなたは多言語の映像タイトル翻訳機です。原文の言語を自動判定し、自然な日本語へ翻訳してください。固有名詞以外の未翻訳文字を残さず、内容を追加しないでください。",
        "ollama_example": "在公公旁边让人妻一边打电话给丈夫一边被睡走 → 義父の隣で夫に電話させながら人妻を寝取る",
        "ollama_example_label": "例：",
        "ollama_translate_label": "翻訳：",
        "gemini_instruction": "次のタイトルの原文言語を判定し、日本語に翻訳してください",
        "gemini_rules": "1. データベース用タイトルの翻訳だけを行い、新しい内容を生成しない\n2. 固有名詞以外は未翻訳の外国語を残さず、自然な日本語にする\n3. 50文字以内を目安に簡潔にする\n4. 翻訳結果だけを出力し、説明を加えない",
        "retry_instruction": "最終的な翻訳だけを出力してください。コメント、説明、謝罪、接頭辞は一切付けないでください。",
        "plot_cloud_intro": "あなたはプロの映像資料翻訳エンジンです。これは作品紹介文の完全翻訳タスクです。",
        "plot_instruction": "次の作品紹介文を自然な日本語へ完全に翻訳してください",
        "plot_rules": "1. 全文を一文ずつ完全に翻訳し、要約・省略・内容の追加をしない\n2. 元の段落、改行、句読点の構成を保つ\n3. 人名、ブランド名、作品名は原文のまま残す\n4. 見出し、説明、注釈を付けず、翻訳だけを出力する\n5. 文字数制限を設けず、原文を途中で切らない",
        "plot_ollama_system": "あなたは多言語の映像作品紹介文を翻訳するエンジンです。全文を一文ずつ日本語に翻訳し、段落と改行を保ってください。要約、省略、内容の追加、説明は禁止です。翻訳だけを出力してください。",
        "plot_label": "完全に翻訳：",
    },
    "ko": {
        "name": "한국어",
        "cloud_intro": "당신은 전문 영상 데이터베이스 관리자이자 번역 엔진입니다. 기존 제목을 번역하는 작업입니다.",
        "source_label": "원문:",
        "rules_label": "번역 요구 사항:",
        "ollama_system": "당신은 다국어 영상 제목 번역기입니다. 원문 언어를 자동으로 감지하여 자연스러운 한국어로 번역하세요. 고유명사 외의 미번역 문자를 남기지 말고 내용을 추가하지 마세요.",
        "ollama_example": "義父の隣で夫に電話させながら人妻を寝取る → 시아버지 옆에서 남편과 통화하게 하면서 유부녀를 빼앗다",
        "ollama_example_label": "예:",
        "ollama_translate_label": "번역:",
        "gemini_instruction": "다음 제목의 원문 언어를 감지하고 자연스러운 한국어로 번역하세요",
        "gemini_rules": "1. 데이터베이스 제목 번역만 수행하고 새로운 내용을 만들지 마세요\n2. 고유명사 외에는 미번역 외국어를 남기지 말고 자연스러운 한국어로 작성하세요\n3. 50자 이내를 기준으로 간결하게 작성하세요\n4. 번역 결과만 출력하고 설명을 덧붙이지 마세요",
        "retry_instruction": "최종 번역만 출력하세요. 설명, 사과, 접두사 또는 주석을 붙이지 마세요.",
        "plot_cloud_intro": "당신은 전문 영상 자료 번역 엔진입니다. 영상 소개문 전체를 번역하는 작업입니다.",
        "plot_instruction": "다음 영상 소개문 전체를 자연스러운 한국어로 번역하세요",
        "plot_rules": "1. 모든 문장을 완전히 번역하고 요약·생략·내용 추가를 하지 마세요\n2. 원문의 문단, 줄바꿈, 문장부호 구조를 유지하세요\n3. 인명, 브랜드명, 작품명은 원문 그대로 두세요\n4. 제목, 설명, 주석 없이 번역문만 출력하세요\n5. 글자 수를 제한하거나 원문을 중간에서 자르지 마세요",
        "plot_ollama_system": "당신은 여러 언어의 영상 소개문을 번역합니다. 모든 문장을 한국어로 완전히 번역하고 문단과 줄바꿈을 유지하세요. 요약, 생략, 내용 추가, 설명은 금지합니다. 번역문만 출력하세요.",
        "plot_label": "전체 번역:",
    },
}

_REFUSAL_RULES = {
    "zh-CN": (
        "如果因安全策略、内容限制、政策原因或任何其他原因无法翻译，"
        f"不要解释、道歉或说明原因，只输出 {TRANSLATION_REFUSAL_MARKER}"
    ),
    "zh-TW": (
        "如果因安全策略、內容限制、政策原因或任何其他原因無法翻譯，"
        f"不要解釋、道歉或說明原因，只輸出 {TRANSLATION_REFUSAL_MARKER}"
    ),
    "en": (
        "If you cannot translate because of safety rules, content limits, "
        "policy restrictions, or any other reason, do not explain or apologize; "
        f"output only {TRANSLATION_REFUSAL_MARKER}"
    ),
    "ja": (
        "安全ポリシー、コンテンツ制限、その他の理由で翻訳できない場合は、"
        "説明や謝罪をせず、"
        f"{TRANSLATION_REFUSAL_MARKER} だけを出力してください"
    ),
    "ko": (
        "안전 정책, 콘텐츠 제한 또는 기타 이유로 번역할 수 없다면 "
        "설명하거나 사과하지 말고 "
        f"{TRANSLATION_REFUSAL_MARKER}만 출력하세요"
    ),
}


def refusal_rule(target_language: str) -> str:
    return _REFUSAL_RULES.get(
        target_language,
        _REFUSAL_RULES["zh-CN"],
    )


def build_ollama_prompts(title: str, target_language: str) -> tuple[str, str]:
    """Build provider-specific Ollama messages in the selected target language."""
    lang_data = LANGUAGE_PROMPTS.get(target_language, LANGUAGE_PROMPTS["zh-CN"])
    system_msg = (
        f"{lang_data['ollama_system']}\n"
        f"{refusal_rule(target_language)}"
    )
    prompt = (
        f"{lang_data['ollama_example_label']}{lang_data['ollama_example']}"
        "\n\n"
        f"{lang_data['ollama_translate_label']}{title}"
    )
    return system_msg, prompt


def build_cloud_plot_translate_prompt(
    plot: str,
    target_language: str,
) -> str:
    """Build a full-synopsis prompt that never applies the title length cap."""
    lang_data = LANGUAGE_PROMPTS.get(
        target_language,
        LANGUAGE_PROMPTS["zh-CN"],
    )
    return f"""{lang_data['plot_cloud_intro']}
{lang_data['plot_instruction']}

{lang_data['source_label']}
{plot}

{lang_data['rules_label']}
{lang_data['plot_rules']}
{refusal_rule(target_language)}
"""


def build_ollama_plot_prompts(
    plot: str,
    target_language: str,
) -> tuple[str, str]:
    """Build provider-specific Ollama messages for complete synopsis translation."""
    lang_data = LANGUAGE_PROMPTS.get(
        target_language,
        LANGUAGE_PROMPTS["zh-CN"],
    )
    system_msg = (
        f"{lang_data['plot_ollama_system']}\n"
        f"{refusal_rule(target_language)}"
    )
    prompt = f"{lang_data['plot_label']}{plot}"
    return system_msg, prompt


class TranslateService(ABC):
    """翻譯服務抽象基類"""

    target_language = "zh-CN"

    def _validate_result(
        self,
        source: str,
        translated: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Reject refusals, source echoes, and output in the wrong language."""
        cleaned = normalize_translation_text(translated)
        proper_terms = (context or {}).get("actors") or ()
        issue = translation_result_issue(
            source,
            cleaned,
            self.target_language,
            proper_terms=proper_terms,
        )
        if issue is not None:
            kind = "refused" if issue == "refusal" else "invalid_response"
            raise build_error(
                "Translation",
                kind,
                None,
                issue,
                issue,
            )
        return cleaned

    def _validate_plot_result(
        self,
        source: str,
        translated: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Validate a complete synopsis without applying title-only limits."""
        cleaned = normalize_translation_text(translated)
        proper_terms = (context or {}).get("actors") or ()
        issue = plot_translation_result_issue(
            source,
            cleaned,
            self.target_language,
            proper_terms=proper_terms,
        )
        if issue is not None:
            kind = "refused" if issue == "refusal" else "invalid_response"
            raise build_error(
                "PlotTranslation",
                kind,
                None,
                issue,
                issue,
            )
        return cleaned

    @abstractmethod
    async def translate_single(self, title: str, context: Optional[Dict] = None) -> str:
        """
        翻譯單個標題

        Args:
            title: 日文標題
            context: 上下文信息（演員、番號等），可選

        Returns:
            繁體中文翻譯
        """
        pass

    async def translate_or_raise(self, title: str, context: Optional[Dict] = None) -> str:
        """翻譯單個標題；失敗拋 TranslateError（供 API 層分辨原因）。

        預設實作包 translate_single：回空字串視為 empty_response。
        """
        result = await self.translate_single(title, context)
        if not result:
            raise TranslateError("empty_response", None, "", "translation is empty")
        return self._validate_result(title, result, context)

    async def translate_plot_or_raise(
        self,
        plot: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Translate a full synopsis with a larger output budget."""
        system_msg, prompt = build_ollama_plot_prompts(
            plot,
            self.target_language,
        )
        try:
            async with httpx.AsyncClient(
                timeout=PLOT_TRANSLATE_TIMEOUT
            ) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/chat",
                    **({"headers": {"Authorization": f"Bearer {self.api_key}"}} if self.api_key else {}),
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                        "options": {
                            "num_predict": PLOT_MAX_TOKENS,
                            "temperature": 0.2,
                        },
                    },
                )
            if resp.status_code != 200:
                raise Exception(f"Ollama API error: {resp.status_code}")
            data = resp.json()
            result = data.get("message", {}).get("content", "").strip()
            result = self._clean_output(result)
        except TranslateError:
            raise
        except (httpx.LocalProtocolError, UnicodeEncodeError):
            raise build_error(
                "Ollama", "auth_failed", None, "invalid_api_key_format", "API Key has an invalid format"
            ) from None
        except httpx.TimeoutException as e:
            raise build_error(
                "Ollama",
                "connection_timeout",
                None,
                type(e).__name__,
                "request timed out",
            ) from None
        except httpx.ConnectError as e:
            raise build_error(
                "Ollama",
                "connection_failed",
                None,
                type(e).__name__,
                "cannot connect",
            ) from None
        except Exception as e:
            raise build_error(
                "Ollama",
                "api_error",
                None,
                type(e).__name__,
                str(e),
            ) from None
        return self._validate_plot_result(plot, result, context)

    @abstractmethod
    async def translate_batch(self, titles: List[str], context: Optional[Dict] = None) -> List[str]:
        """
        批次翻譯多個標題

        Args:
            titles: 日文標題列表
            context: 上下文信息，可選

        Returns:
            繁體中文翻譯列表（長度必須與輸入一致）
        """
        pass


class OllamaTranslateService(TranslateService):
    """Ollama 翻譯服務實現"""

    def __init__(self, config: Dict, target_language: str = "zh-CN"):
        """
        初始化 Ollama 服務

        Args:
            config: Ollama 配置字典
                {
                    "url": "http://localhost:11434",
                    "model": "qwen3:8b"  # 所有翻譯都用此模型
                }
            target_language: 目標語言代碼（zh-TW / zh-CN / en / ja）
        """
        self.ollama_url = provider_base_url("ollama", config)
        self.api_key = config.get("api_key", "")
        self.model = config.get("model") or "qwen3:8b"
        self.target_language = target_language

    async def translate_or_raise(self, title: str, context: Optional[Dict] = None) -> str:
        """Translate one title; failures raise TranslateError."""
        system_msg, prompt = build_ollama_prompts(
            title,
            self.target_language,
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/chat",
                    **({"headers": {"Authorization": f"Bearer {self.api_key}"}} if self.api_key else {}),
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "options": {
                            "num_predict": 500,
                            "temperature": 0.3
                        }
                    }
                )

            if resp.status_code != 200:
                raise Exception(f"Ollama API error: {resp.status_code}")

            data = resp.json()
            result = data.get("message", {}).get("content", "").strip()

            # 清理輸出
            result = self._clean_output(result)
        except TranslateError:
            raise
        except (httpx.LocalProtocolError, UnicodeEncodeError):
            raise build_error(
                "Ollama", "auth_failed", None, "invalid_api_key_format", "API Key has an invalid format"
            ) from None
        except httpx.TimeoutException as e:
            raise build_error(
                "Ollama", "connection_timeout", None, type(e).__name__, "request timed out"
            ) from None
        except httpx.ConnectError as e:
            raise build_error(
                "Ollama", "connection_failed", None, type(e).__name__, "cannot connect"
            ) from None
        except Exception as e:
            raise build_error(
                "Ollama", "api_error", None, type(e).__name__, str(e)
            ) from None

        return self._validate_result(title, result, context)

    async def translate_single(self, title: str, context: Optional[Dict] = None) -> str:
        """
        單片翻譯

        適用場景：用戶查看第 1 片時立即翻譯；任何失敗回空字串。
        """
        try:
            return await self.translate_or_raise(title, context)
        except TranslateError as e:
            logger.error(f"[Ollama] Single translation failed: {e}")
            return ""

    async def translate_batch(self, titles: List[str], context: Optional[Dict] = None) -> List[str]:
        """
        批次翻譯 - 逐片翻譯確保穩定性

        適用場景：後台翻譯第 2-10 片
        """
        if not titles:
            return []

        results = []
        for title in titles:
            result = await self.translate_single(title, context)
            results.append(result)

        return results

    def _clean_output(self, text: str) -> str:
        """清理翻譯輸出"""
        text = text.strip().strip('"').strip("'")
        text = re.sub(r'^翻譯[：:]\s*', '', text)
        text = re.sub(r'^中文[：:]\s*', '', text)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return text.strip()

    def _parse_batch_output(self, content: str) -> List[str]:
        """解析批次翻譯輸出"""
        translations = []
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 移除編號前綴（支援 1. / 1) / 1、）
            match = re.match(r'^\d+[.)、]\s*(.+)$', line)
            if match:
                text = match.group(1).strip()
                translations.append(self._clean_output(text))
            elif line and not re.match(r'^[\d.)、\s]+$', line):
                # 沒有編號但有內容的行也接受
                translations.append(self._clean_output(line))
        return translations


class GeminiTranslateService(TranslateService):
    """Google Gemini API 翻譯服務實現"""

    def __init__(self, config: Dict, target_language: str = "zh-CN"):
        """
        初始化 Gemini 服務

        Args:
            config: Gemini 配置字典
                {
                    "api_key": "AIza...",
                    "model": "gemini-flash-lite-latest"
                }
            target_language: 目標語言代碼（zh-TW / zh-CN / en / ja）
        """
        self.api_key = config.get("api_key", "")
        self.base_url = provider_base_url("gemini", config)
        self.model = config.get("model", "gemini-flash-lite-latest")
        self.target_language = target_language

        if not self.api_key and requires_api_key("gemini", self.base_url):
            raise ValueError("Gemini API Key is required")

    async def translate_or_raise(self, title: str, context: Optional[Dict] = None) -> str:
        """Translate one title; failures raise TranslateError."""
        prompt = build_cloud_translate_prompt(title, self.target_language)

        try:
            result = await gemini_client.request_translation(
                self.api_key,
                self.model,
                prompt,
                timeout=CLOUD_TRANSLATE_TIMEOUT,
                base_url=self.base_url,
            )
            return self._validate_result(title, result, context)
        except TranslateError:
            raise
        except Exception as e:
            # 只記型別名：例外字串可能含金鑰
            raise build_error(
                "Gemini", "api_error", None, type(e).__name__, "translation request failed"
            ) from None

    async def translate_plot_or_raise(
        self,
        plot: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Translate a full synopsis; failures raise TranslateError."""
        prompt = build_cloud_plot_translate_prompt(
            plot,
            self.target_language,
        )
        try:
            result = await gemini_client.request_translation(
                self.api_key,
                self.model,
                prompt,
                timeout=PLOT_TRANSLATE_TIMEOUT,
                base_url=self.base_url,
            )
            return self._validate_plot_result(plot, result, context)
        except TranslateError:
            raise
        except Exception as e:
            raise build_error(
                "Gemini",
                "api_error",
                None,
                type(e).__name__,
                "plot translation request failed",
            ) from None

    async def translate_single(self, title: str, context: Optional[Dict] = None) -> str:
        """單片翻譯（用戶手動點擊）；任何失敗回空字串。"""
        try:
            return await self.translate_or_raise(title, context)
        except TranslateError:
            return ""

    async def translate_batch(self, titles: List[str], context: Optional[Dict] = None) -> List[str]:
        """
        批次翻譯 - Gemini 逐片翻譯避免安全過濾

        Gemini 一次翻譯多個 AV 標題容易觸發安全過濾，
        因此改為循環調用 translate_single()，每次只翻譯一片。

        適用場景：批次翻譯 10 片
        性能：約 8.7 秒 / 10 片（比原方案慢，但穩定可用）
        """
        if not titles:
            return []

        # 逐片翻譯，避免安全過濾
        results = []
        for title in titles:
            result = await self.translate_single(title, context)
            results.append(result)

        return results


class OpenAICompatibleTranslateService(TranslateService):
    """OpenAI Compatible API 翻譯服務實現（支援 OpenAI、Perplexity、OpenRouter、本地 LLM 等）"""

    def __init__(self, config: Dict, target_language: str = "zh-CN"):
        """
        初始化 OpenAI Compatible 服務

        Args:
            config: OpenAI Compatible 配置字典
                {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-xxx",  # 可為空（本地 LLM 不需要）
                    "model": "gpt-4o-mini"
                }
            target_language: 目標語言代碼（zh-TW / zh-CN / en / ja）
        """
        self.base_url = (config.get("base_url") or "").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model") or "gpt-4o-mini"
        self.target_language = target_language

    async def translate_or_raise(self, title: str, context: Optional[Dict] = None) -> str:
        """Translate one title; failures raise TranslateError."""
        prompt = build_cloud_translate_prompt(title, self.target_language)
        lang_data = LANGUAGE_PROMPTS.get(
            self.target_language,
            LANGUAGE_PROMPTS["zh-CN"],
        )

        try:
            result = await openai_client.request_translation(
                self.base_url,
                self.api_key,
                self.model,
                prompt,
                timeout=CLOUD_TRANSLATE_TIMEOUT,
            )
            try:
                return self._validate_result(title, result, context)
            except TranslateError as first_error:
                if first_error.kind not in ("refused", "invalid_response"):
                    raise
                retry_prompt = (
                    f"{prompt}\n"
                    f"{lang_data['retry_instruction']}\n"
                    f"{refusal_rule(self.target_language)}"
                )
                retried = await openai_client.request_translation(
                    self.base_url,
                    self.api_key,
                    self.model,
                    retry_prompt,
                    timeout=CLOUD_TRANSLATE_TIMEOUT,
                )
                return self._validate_result(title, retried, context)
        except TranslateError:
            raise
        except Exception as e:
            # 只記型別名：例外字串可能含金鑰
            raise build_error(
                "OpenAI", "api_error", None, type(e).__name__, "translation request failed"
            ) from None

    async def translate_plot_or_raise(
        self,
        plot: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Translate a full synopsis and retry one rejected/invalid response."""
        prompt = build_cloud_plot_translate_prompt(
            plot,
            self.target_language,
        )
        lang_data = LANGUAGE_PROMPTS.get(
            self.target_language,
            LANGUAGE_PROMPTS["zh-CN"],
        )
        try:
            result = await openai_client.request_translation(
                self.base_url,
                self.api_key,
                self.model,
                prompt,
                timeout=PLOT_TRANSLATE_TIMEOUT,
            )
            try:
                return self._validate_plot_result(plot, result, context)
            except TranslateError as first_error:
                if first_error.kind not in ("refused", "invalid_response"):
                    raise
                retry_prompt = (
                    f"{prompt}\n"
                    f"{lang_data['retry_instruction']}\n"
                    f"{refusal_rule(self.target_language)}"
                )
                retried = await openai_client.request_translation(
                    self.base_url,
                    self.api_key,
                    self.model,
                    retry_prompt,
                    timeout=PLOT_TRANSLATE_TIMEOUT,
                )
                return self._validate_plot_result(plot, retried, context)
        except TranslateError:
            raise
        except Exception as e:
            raise build_error(
                "OpenAI",
                "api_error",
                None,
                type(e).__name__,
                "plot translation request failed",
            ) from None

    async def translate_single(self, title: str, context: Optional[Dict] = None) -> str:
        """單片翻譯；任何失敗回空字串。"""
        try:
            return await self.translate_or_raise(title, context)
        except TranslateError:
            return ""

    async def translate_batch(self, titles: List[str], context: Optional[Dict] = None) -> List[str]:
        """
        批次翻譯 - 逐片翻譯確保穩定性
        """
        if not titles:
            return []

        results = []
        for title in titles:
            result = await self.translate_single(title, context)
            results.append(result)

        return results


def build_cloud_translate_prompt(title: str, target_language: str) -> str:
    """Build a cloud prompt that translates from any detected source language."""
    lang_data = LANGUAGE_PROMPTS.get(target_language, LANGUAGE_PROMPTS["zh-CN"])
    refusal = refusal_rule(target_language)
    return f"""{lang_data['cloud_intro']}
{lang_data['gemini_instruction']}

{lang_data['source_label']}
{title}

{lang_data['rules_label']}
{lang_data['gemini_rules']}
{refusal}
"""


class ClaudeTranslateService(TranslateService):
    """Anthropic Claude Messages API 翻譯服務"""

    def __init__(self, config: Dict, target_language: str = "zh-CN"):
        """
        Args:
            config: Claude 配置字典
                {
                    "api_key": "sk-ant-...",
                    "model": "claude-haiku-5-5"
                }
            target_language: 目標語言代碼（zh-TW / zh-CN / en / ja）
        """
        self.api_key = config.get("api_key", "")
        self.base_url = provider_base_url("claude", config)
        self.model = config.get("model") or DEFAULT_CLAUDE_MODEL
        self.target_language = target_language

        if not self.api_key and requires_api_key("claude", self.base_url):
            raise ValueError("Claude API Key is required")

    async def translate_or_raise(self, title: str, context: Optional[Dict] = None) -> str:
        """Translate one title; failures raise TranslateError."""
        prompt = build_cloud_translate_prompt(title, self.target_language)

        try:
            result = await request_translation(
                self.api_key,
                self.model,
                prompt,
                timeout=30,
                base_url=self.base_url,
            )
            return self._validate_result(title, result, context)
        except TranslateError:
            raise
        except Exception as e:
            # 只記型別名：例外字串可能含金鑰
            raise build_error(
                "Claude", "api_error", None, type(e).__name__, "translation request failed"
            ) from None

    async def translate_plot_or_raise(
        self,
        plot: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Translate a full synopsis with a synopsis-specific token budget."""
        prompt = build_cloud_plot_translate_prompt(
            plot,
            self.target_language,
        )
        try:
            result = await request_translation(
                self.api_key,
                self.model,
                prompt,
                timeout=PLOT_TRANSLATE_TIMEOUT,
                base_url=self.base_url,
                max_tokens=PLOT_MAX_TOKENS,
            )
            return self._validate_plot_result(plot, result, context)
        except TranslateError:
            raise
        except Exception as e:
            raise build_error(
                "Claude",
                "api_error",
                None,
                type(e).__name__,
                "plot translation request failed",
            ) from None

    async def translate_single(self, title: str, context: Optional[Dict] = None) -> str:
        """單片翻譯；任何失敗回空字串。"""
        try:
            return await self.translate_or_raise(title, context)
        except TranslateError:
            return ""

    async def translate_batch(self, titles: List[str], context: Optional[Dict] = None) -> List[str]:
        """批次翻譯 - 逐片呼叫 translate_single。"""
        if not titles:
            return []

        results = []
        for title in titles:
            result = await self.translate_single(title, context)
            results.append(result)

        return results


def create_translate_service(config: Dict, target_language: str = "zh-CN") -> TranslateService:
    """
    創建翻譯服務實例（工廠函數）

    Args:
        config: translate 配置字典
            {
                "provider": "ollama" | "gemini" | "openai" | "claude",
                "ollama": {...},
                "gemini": {...},
                "claude": {...},
                "openai": {...}
            }
        target_language: 目標語言代碼（zh-TW / zh-CN / en / ja），預設 zh-CN

    Returns:
        TranslateService 實例

    Raises:
        ValueError: 未知的 provider 或配置錯誤
    """
    provider = config.get("provider", "ollama")

    if provider == "ollama":
        ollama_config = config.get("ollama", {})
        return OllamaTranslateService(ollama_config, target_language)

    elif provider == "gemini":
        gemini_config = config.get("gemini", {})
        return GeminiTranslateService(gemini_config, target_language)

    elif provider == "openai":
        openai_config = config.get("openai", {})
        return OpenAICompatibleTranslateService(openai_config, target_language)

    elif provider == "openai_official":
        official_config = config.get("openai_official", {}) or {}
        return OpenAICompatibleTranslateService(
            {
                "base_url": provider_base_url("openai_official", official_config),
                "api_key": official_config.get("api_key", ""),
                "model": official_config.get("model", ""),
            },
            target_language,
        )

    elif provider == "claude":
        claude_config = config.get("claude", {})
        return ClaudeTranslateService(claude_config, target_language)

    else:
        raise ValueError(f"Unknown translate provider: {provider}")
