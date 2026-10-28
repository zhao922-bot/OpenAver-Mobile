"""JavBus 爬蟲（自建 requests + BeautifulSoup）"""
import re
from typing import Optional
from typing import NamedTuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from .errors import SourceBlocked, SourceUnreachable
from .models import Video, Actress
from .utils import rate_limit, strip_number_prefix
from core.logger import get_logger
from core.name_match import fold
from core.source_probe import ProbePlan, ProbeTarget

logger = get_logger(__name__)

FIELD_LABELS = {
    "zh-tw": {
        "number": "識別碼", "date": "發行日期", "duration": "長度",
        "director": "導演", "maker": "製作商", "label": "發行商",
        "series": "系列", "tags": "類別", "actresses": "演員",
    },
    "ja": {
        "number": "品番", "date": "発売日", "duration": "収録時間",
        "director": "監督", "maker": "メーカー", "label": "レーベル",
        "series": "シリーズ", "tags": "ジャンル", "actresses": "出演者",
    },
    "en": {
        "number": "ID", "date": "Release Date", "duration": "Length",
        "director": "Director", "maker": "Studio", "label": "Label",
        "series": "Series", "tags": "Genre", "actresses": "JAV Idols",
    },
}

LANG_PREFIX = {"zh-tw": "", "ja": "/ja", "en": "/en"}

# --- 片商頁能力（173-T3，plan CD-173-6／CD-173-7）---
JAVBUS_LIST_PAGE_SIZE = 30

_STUDIO_HREF_RE = re.compile(r"^(?:https?://[^/]+)?(?:/(?:ja|en))?(?:/(uncensored))?/studio/([0-9A-Za-z]+)/?(?:[?#].*)?$")

# --- 名稱→實體（175c-T3）---
_STAR_HREF_RE = re.compile(r"^(?:https?://[^/]+)?(?:/(?:ja|en))?(/uncensored)?/star/([0-9A-Za-z]+)/?(?:[?#].*)?$")
_ENTITY_HREF_RE = re.compile(r"^(?:https?://[^/]+)?(?:/(?:ja|en))?/(series|director|label)/([0-9A-Za-z]+)/?(?:[?#].*)?$")
# fetch_entity_link 的搜尋 type：series 走一般搜尋（type=5 對系列名實測全 404，175c-T3 活站探針 G1 負例）、director 2、label 4
_ENTITY_SEARCH_TYPE = {"series": 0, "director": 2, "label": 4}


class StudioVote(NamedTuple):
    """單樣本投票：kind ∈ {'censored','uncensored'}、studio_id 為 JavBus 片商代號。"""
    kind: str
    studio_id: str


class ListCard(NamedTuple):
    """清單頁單張卡：番號／標題／封面縮圖／發行日。cover 是站方相對路徑原樣（如 /pics/thumb/…）；缺值為空字串。"""
    number: str
    title: str
    cover: str
    date: str


class StarCard(NamedTuple):
    """searchstar 候選單張卡：id 為 `star/<id>`（有碼）或 `uncensored/star/<id>`（無碼）；uncensored 另看按鈕字樣「無修正」。"""
    id: str
    name: str
    uncensored: bool


# 單樣本的另外兩種結果：Miss 只留 HTTP 404；其餘一切看不懂的都是 Unreachable（BE-PY-03）
STUDIO_MISS = "studio_miss"
STUDIO_UNREACHABLE = "studio_unreachable"

LIST_PARSE = "list_parse"
LIST_END = "list_end"
LIST_BLOCKED = "list_blocked"
LIST_UNREADABLE = "list_unreadable"


def parse_studio_href(href: str):
    """href → (kind, studio_id)；/label/、/series/ 與空字串回 None。"""
    m = _STUDIO_HREF_RE.match(href or "")
    if not m:
        return None
    return ("uncensored" if m.group(1) else "censored", m.group(2))


def classify(status: int, has_info: bool, hrefs: list):
    """詳情頁單樣本分類：StudioVote／STUDIO_MISS／STUDIO_UNREACHABLE。"""
    if status == 404:
        return STUDIO_MISS
    if status != 200 or not has_info:
        return STUDIO_UNREACHABLE
    votes = [v for v in (parse_studio_href(h) for h in hrefs) if v]
    return StudioVote(*votes[0]) if votes else STUDIO_UNREACHABLE


def classify_list_response(status: int, has_waterfall: bool) -> str:
    """片商列表頁分類：404 才是尾端；200 無 #waterfall 是看不懂；其餘非 200 是被擋。"""
    if status != 200:
        return LIST_END if status == 404 else LIST_BLOCKED
    return LIST_PARSE if has_waterfall else LIST_UNREADABLE


class JavBusScraper(BaseScraper):
    """
    JavBus 爬蟲（自建 requests + BeautifulSoup）

    優點：
    - 封面無浮水印
    - 不依賴第三方 jvav 套件
    - 支援多語言（zh-tw / ja / en）

    注意：
    - 封面只有右半邊（裁切版）
    """

    BASE_URL = "https://www.javbus.com"
    SAMPLE_NUMBER = "SONE-205"

    def __init__(self, config=None, lang: str = "zh-tw"):
        super().__init__(config)
        self.lang = lang
        self._session = self._new_session()
        # [反爬設計，非技術債——請勿「修好」成共用 config UA]（spec-103 §3.7）
        # 下面 5 個 header 是刻意搭配的成套組合，共同構成一個內部一致的完整
        # 瀏覽器指紋（Safari on macOS）。其他走 self.config.user_agent 的來源
        # （javdb/avsox/d2pass/fc2/heyzo/dmm）用的共用預設值只到
        # "AppleWebKit/537.36"、缺 Chrome/Safari 尾段，不像真實瀏覽器——本檔
        # 硬編碼一組完整 UA 是刻意選擇，不是漏接共用機制。改走共用 UA 或拆散
        # 這組 header 有回歸風險，且違反「scraper 不動」共識。
        # 注意 Accept-Language 是固定值（headers 只在 __init__ 設一次），不隨
        # self.lang 變動——self.lang 管的是 URL prefix 與 FIELD_LABELS 解析字典
        # （_get_lang_prefix / _get_labels），與送出的語言偏好 header 無關。
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.5 Safari/605.1.15"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })

    def probe_plan(self, timeout):
        """測試連線：打樣本詳情頁（沿用成套 Safari header，樣本頁 404 也算站台有回應）。"""
        url = f"{self.BASE_URL}{self._get_lang_prefix()}/{self.SAMPLE_NUMBER}"

        def send():
            return self._session.get(url, timeout=timeout, stream=True)
        return ProbePlan([ProbeTarget('www.javbus.com', send, ok_404=True)])

    def _get_source_name(self) -> str:
        return "javbus"

    def _get_lang_prefix(self) -> str:
        return LANG_PREFIX.get(self.lang, "")

    def _get_labels(self) -> dict:
        return FIELD_LABELS.get(self.lang, FIELD_LABELS["zh-tw"])

    def search(self, number: str) -> Optional[Video]:
        """
        搜尋影片資訊

        Args:
            number: 番號（如 SNOS-143）

        Returns:
            Video 物件或 None

        Raises:
            ValueError: 番號格式錯誤
            TimeoutError: 請求超時
        """
        number = self.normalize_number(number)

        if not self.validate_number(number):
            raise ValueError(f"Invalid number format: {number}")

        prefix = self._get_lang_prefix()
        url = f"{self.BASE_URL}{prefix}/{number}"

        try:
            resp = self._session.get(url, timeout=self.config.timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise TimeoutError(f"Request timed out for {number}") from e

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_detail_page(soup, number, url)

    def _parse_detail_page(self, soup, number: str, detail_url: str) -> Optional[Video]:
        """解析詳情頁 HTML，回傳 Video 物件。"""
        # 驗證是詳情頁（必須有 info 區塊）
        info = soup.find(class_="col-md-3 info")
        if not info:
            return None

        labels = self._get_labels()

        # Title — 優先用 h3，次用 bigImage img title
        title_elem = soup.find("h3")
        title = title_elem.get_text(strip=True) if title_elem else ""
        if not title:
            big_image = soup.find(class_="bigImage")
            if big_image:
                img = big_image.find("img", {"title": True})
                if img:
                    title = img.get("title", "")
        # 剝除番號前綴（兩條路徑都可能帶番號，統一在此處理）
        title = strip_number_prefix(title, number)

        # Cover URL
        big_image = soup.find(class_="bigImage")
        cover_url = ""
        if big_image:
            cover_url = big_image.get("href", "")
            if cover_url and not cover_url.startswith("http"):
                cover_url = self.BASE_URL + cover_url

        # Parse info <p> tags
        paragraphs = info.find_all("p")
        parsed = self._parse_info_paragraphs(paragraphs, labels)

        # Duration → int
        duration = None
        if parsed.get("duration"):
            m = re.search(r"(\d+)", parsed["duration"])
            if m:
                duration = int(m.group(1))

        # Actresses — 去重
        actresses = []
        seen_names: set[str] = set()
        for actress_name in parsed.get("actresses", []):
            if actress_name and actress_name not in seen_names:
                seen_names.add(actress_name)
                actresses.append(Actress(name=actress_name))

        # Sample images
        sample_section = (
            soup.find(id="sample-waterfall")
            or soup.find(class_="sample-waterfall")
        )
        sample_images = []
        if sample_section:
            for a in sample_section.find_all("a", href=True):
                img_url = a["href"]
                if not img_url.startswith("http"):
                    img_url = self.BASE_URL + img_url
                sample_images.append(img_url)

        video = Video(
            number=number,
            title=title,
            actresses=actresses,
            date=parsed.get("date", ""),
            maker=parsed.get("maker", ""),
            cover_url=cover_url,
            tags=parsed.get("tags", []),
            source=self.source_name,
            detail_url=detail_url,
            director=parsed.get("director", ""),
            duration=duration,
            label=parsed.get("label", ""),
            series=parsed.get("series", ""),
            sample_images=sample_images,
            entity_ids=self._parse_entity_ids(info),
        )

        rate_limit(self.config.delay)
        return video

    def _parse_info_paragraphs(self, paragraphs, labels: dict) -> dict:
        """
        解析 info 區塊的 <p> 標籤，用欄位名 mapping 辨識。

        Returns:
            dict 包含 date, duration, director, maker, label, series, tags, actresses
        """
        result: dict = {
            "date": "", "duration": "", "director": "", "maker": "",
            "label": "", "series": "", "tags": [], "actresses": [],
        }

        i = 0
        while i < len(paragraphs):
            p = paragraphs[i]
            text = p.get_text(strip=True)

            # 單值欄位：找到 label 後，取 <a> 文字或剝除 label 前綴
            for field in ("date", "director", "maker", "label", "series"):
                lbl = labels[field]
                if lbl in text:
                    a = p.find("a")
                    if a:
                        result[field] = a.get_text(strip=True)
                    else:
                        value = text
                        for char in (lbl, ":", "："):
                            value = value.replace(char, "")
                        result[field] = value.strip()
                    break

            # Duration — 保留整段文字（供後續 regex 提取數字）
            if labels["duration"] in text:
                result["duration"] = text

            # Tags — 在同 <p> 或下一個 <p> 找 <a>
            if labels["tags"] in text:
                tag_links = p.find_all("a")
                if not tag_links and i + 1 < len(paragraphs):
                    tag_links = paragraphs[i + 1].find_all("a")
                    i += 1  # skip next
                result["tags"] = [
                    a.get_text(strip=True) for a in tag_links
                    if a.get_text(strip=True)
                ]

            # Actresses — 同 tags，fallback 到下一個 <p>
            if labels["actresses"] in text:
                actress_links = p.find_all("a")
                if not actress_links and i + 1 < len(paragraphs):
                    actress_links = paragraphs[i + 1].find_all("a")
                    i += 1
                result["actresses"] = [
                    a.get_text(strip=True) for a in actress_links
                    if a.get_text(strip=True)
                ]

            i += 1

        return result

    @staticmethod
    def _parse_entity_ids(info) -> dict[str, list[str]]:
        """詳情頁 info 區塊內的實體連結代號（女優／導演／系列／label）；去重保序、無該類不出鍵。

        只掃 `div.col-md-3.info` 內的 a[href]（頁面別處的 avatar-waterfall 另有一份女優連結，不算）。
        href 的 /ja、/en、無前綴皆認；片商（studio）與類別（genre）連結不收。
        重用 `_STAR_HREF_RE`／`_ENTITY_HREF_RE`（與名稱→實體同一份判斷）。
        """
        ids: dict[str, list[str]] = {}
        for a in info.find_all("a", href=True):
            href = a["href"].strip()
            m = _STAR_HREF_RE.match(href)
            if m:
                key, code = "actors", m.group(2)
            else:
                m = _ENTITY_HREF_RE.match(href)
                if not m:
                    continue
                key, code = m.group(1), m.group(2)
            bucket = ids.setdefault(key, [])
            if code not in bucket:
                bucket.append(code)
        return ids

    @staticmethod
    def _plus_join(keyword: str) -> str:
        """空白（含全形 U+3000）→ 單一 `+`，首尾空白先去掉；不用 %20（站方對 %20 回 403）。
        一般搜尋與 searchstar 共用這一份。"""
        return re.sub(r"\s+", "+", keyword.strip())

    def _build_search_url(self, keyword: str, page: int = 1, search_type: int = 0,
                          uncensored: bool = False) -> str:
        """
        組建搜尋 URL。

        URL 格式：
          第 1 頁：/search/{keyword}
          第 N 頁：/search/{keyword}/{N}
          前綴搜尋：上述 URL 後加 &type=1
          無碼區：/uncensored 接在語系前綴之後（{語系前綴}/uncensored/search/…），其餘同上

        注意：`&type=1` 是 JavBus 的原生非標準 path-suffix 格式（commit 35-T3
        Playwright 實測確認），**不是** 標準 query string——勿「修正」成 `?type=1`。
        `/search/` 端點仍可用（2026-08-29 實測 `get_ids_from_search("SONE")` 回 30 筆）；
        `search_type=1` 的 path-suffix 過濾是否生效另論，勿改成標準 query string。
        """
        prefix = self._get_lang_prefix()
        section = "/uncensored" if uncensored else ""
        base = f"{self.BASE_URL}{prefix}{section}/search/{self._plus_join(keyword)}"
        if page > 1:
            base += f"/{page}"
        if search_type > 0:
            base += f"&type={search_type}"
        return base

    def _parse_list_cards(self, soup) -> list[ListCard]:
        """從清單頁（搜尋結果／片商頁）解析卡片。

        a.movie-box：第一個 <date> 是番號、第二個是發行日；img[src] 是封面縮圖（相對路徑原樣）、
        img[title] 是標題。無 <date> 的卡片退 href 最後一段當番號；有 <date> 但番號為空則丟棄（不退 href）。
        """
        waterfall = soup.find(id="waterfall")
        if not waterfall:
            return []
        cards = []
        for card in waterfall.find_all("a", class_="movie-box"):
            dates = card.find_all("date")
            if dates:
                number = dates[0].get_text(strip=True)
            else:
                number = card.get("href", "").rstrip("/").split("/")[-1]
            if not number:
                continue
            date = dates[1].get_text(strip=True) if len(dates) > 1 else ""
            img = card.find("img")
            cover = img.get("src", "") if img else ""
            title = img.get("title", "") if img else ""
            cards.append(ListCard(number, title, cover, date))
        return cards

    def _parse_search_ids(self, soup) -> list[str]:
        """從搜尋結果頁解析番號列表。"""
        return [c.number for c in self._parse_list_cards(soup)]

    def _get_list(self, url: str):
        """作品清單 GET（搜尋、片商頁）：先把 session jar 的 existmag 設為 all，再送出。

        站方在 session 的第一個回應就 Set-Cookie: existmag=mag，所以每次請求前都要覆蓋同格 cookie
        （domain＋path 與站方 cookie 同格才會覆蓋）；只設一次或 per-request cookies= 都會與它並存而失效。
        不在這裡映射例外、不節流：搜尋與片商兩條路徑各自維持今天的例外型別。
        """
        self._session.cookies.set("existmag", "all", domain=urlparse(self.BASE_URL).hostname, path="/")
        return self._session.get(url, timeout=self.config.timeout)

    def _ids_from_list_response(self, resp, url: str) -> list[str]:
        """清單回應 → 番號列表。404（頁碼超界／無結果）回 []；看不懂或被擋一律丟例外，絕不回 []。"""
        has_wf = self._has_waterfall(resp.text) if resp.status_code == 200 else False
        verdict = classify_list_response(resp.status_code, has_wf)
        if verdict == LIST_END:
            return []
        if verdict == LIST_BLOCKED:
            raise SourceBlocked(f"JavBus list HTTP {resp.status_code}: {url}")
        if verdict == LIST_UNREADABLE:
            raise SourceUnreachable(f"JavBus list unreadable (no #waterfall): {url}")
        return self._parse_search_ids(BeautifulSoup(resp.text, "html.parser"))

    def get_ids_from_search(self, keyword: str, page: int = 1, search_type: int = 0,
                            uncensored: bool = False) -> list[str]:
        """
        輕量版搜尋：只回傳番號列表，不 fetch 每筆詳情。

        Args:
            keyword: 搜尋關鍵字或前綴
            page: 頁碼（從 1 開始）
            search_type: 0=一般搜尋，1=前綴搜尋（&type=1，JavBus 原生格式）
            uncensored: True=改問無碼區（/uncensored/search/…；站方一般搜尋對無碼前綴回 404，如 HEYZO）

        Returns:
            番號列表（list[str]）；404（無結果／頁碼超界）回 []

        Raises:
            TimeoutError: 請求超時
            SourceBlocked: 非 200 非 404（403／429／503…）
            SourceUnreachable: 200 但沒有 #waterfall（看不懂）
        """
        url = self._build_search_url(keyword, page, search_type, uncensored)
        try:
            resp = self._get_list(url)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise TimeoutError(f"Search request timed out for keyword: {keyword}") from e
        return self._ids_from_list_response(resp, url)

    def _fetch_by_id(self, id_str: str) -> Optional[Video]:
        """直接用 ID 取得影片資訊（繞過 validate_number，支援 variant ID 如 SONE-001_2026-03-20）"""
        prefix = self._get_lang_prefix()
        url = f"{self.BASE_URL}{prefix}/{id_str}"

        try:
            resp = self._session.get(url, timeout=self.config.timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise TimeoutError(f"Request timed out for {id_str}") from e

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        # 用 id_str 的 base part（去掉日期後綴）作為 number
        base_number = id_str.split('_')[0]
        return self._parse_detail_page(soup, base_number, url)

    def search_by_keyword(self, keyword: str, limit: int = 20, page: int = 1) -> list[Video]:
        """
        關鍵字搜尋，回傳 Video 列表。

        先呼叫 get_ids_from_search 取番號列表，再逐一呼叫 search() 取完整詳情。
        單筆 search 失敗（ValueError / TimeoutError）時跳過，不中斷整體。

        Args:
            keyword: 搜尋關鍵字
            limit: 最大結果數
            page: 搜尋結果頁碼

        Returns:
            Video 列表

        注意：production pipeline（`core/search_providers/javbus.py` 的
        `JavBusProvider.run_keyword`；`core.scraper._javbus_keyword_search` 只剩 shim）不呼叫此方法。
        該路徑改用 `get_ids_from_search` 取 ID 列表後，以 ThreadPoolExecutor 平行呼叫
        `search_jav`，速度更快。本方法是 BaseScraper 介面（@abstractmethod）的循序參考
        實作，非 dead code、非 deprecated，但非主路徑——僅 smoke 測試與單元測試直呼。
        """
        try:
            ids = self.get_ids_from_search(keyword, page=page)
        except (TimeoutError, requests.ConnectionError, SourceBlocked, SourceUnreachable):
            return []
        results: list[Video] = []
        for num_id in ids[:limit]:
            try:
                video = self.search(num_id)
                if video:
                    results.append(video)
            except (ValueError, TimeoutError, requests.ConnectionError):
                continue
        return results

    # ---------- 片商頁能力（173-T3）----------

    def build_studio_url(self, ref, page: int = 1) -> str:
        """ref=(kind, studio_id) → 片商作品列表網址，第 2 頁起附 /{page}。"""
        kind, studio_id = ref
        seg = "uncensored/" if kind == "uncensored" else ""
        url = f"{self.BASE_URL}{self._get_lang_prefix()}/{seg}studio/{studio_id}"
        if page > 1:
            url += f"/{page}"
        return url

    def _extract_studio_info(self, html: str):
        """站方 HTML → (有無 info 區塊, 區塊內所有 href)。單測以替身取代。"""
        info = BeautifulSoup(html, "html.parser").select_one("div.col-md-3.info")
        if info is None:
            return False, []
        return True, [a["href"] for a in info.find_all("a", href=True)]

    def _has_waterfall(self, html: str) -> bool:
        """站方 HTML → 有無 #waterfall。單測以替身取代。"""
        return BeautifulSoup(html, "html.parser").find(id="waterfall") is not None

    def fetch_studio_sample(self, number: str):
        """取一部片的詳情頁，認出片商代號。回 StudioVote／STUDIO_MISS／STUDIO_UNREACHABLE。"""
        number = self.normalize_number(number)
        url = f"{self.BASE_URL}{self._get_lang_prefix()}/{number}"
        rate_limit(self.config.delay)
        try:
            resp = self._session.get(url, timeout=self.config.timeout)
        except requests.RequestException as e:
            logger.error("JavBus studio sample %s failed: %s: %s", number, type(e).__name__, e)
            return STUDIO_UNREACHABLE
        has_info, hrefs = (False, [])
        if resp.status_code == 200:
            has_info, hrefs = self._extract_studio_info(resp.text)
        return classify(resp.status_code, has_info, hrefs)

    def get_ids_from_studio(self, ref, page: int = 1) -> list[str]:
        """片商列表單頁番號。404（頁碼超界）回 []；看不懂或被擋一律丟例外，絕不回 []。"""
        url = self.build_studio_url(ref, page)
        try:
            resp = self._get_list(url)
        except requests.RequestException as exc:
            raise SourceUnreachable(f"JavBus studio list request failed: {url}") from exc
        return self._ids_from_list_response(resp, url)

    # ---------- 名稱→實體（175c-T3）----------

    def _list_soup(self, resp, url: str):
        """清單類回應 → 可解析的 soup；404（無結果）回 None。

        分類與 `_ids_from_list_response` 相同（被擋→SourceBlocked；200 無 #waterfall→SourceUnreachable），
        絕不把擋下或看不懂變成「沒有」。200＋#waterfall 零卡回 soup（呼叫端解出零張卡＝空）。
        """
        soup = BeautifulSoup(resp.text, "html.parser") if resp.status_code == 200 else None
        has_wf = soup is not None and soup.find(id="waterfall") is not None
        verdict = classify_list_response(resp.status_code, has_wf)
        if verdict == LIST_END:
            return None
        if verdict == LIST_BLOCKED:
            raise SourceBlocked(f"JavBus list HTTP {resp.status_code}: {url}")
        if verdict == LIST_UNREADABLE:
            raise SourceUnreachable(f"JavBus list unreadable (no #waterfall): {url}")
        return soup

    @staticmethod
    def _parse_star_cards(soup) -> list[StarCard]:
        """searchstar 頁 → 候選卡。a.avatar-box：href 取 star id、img[title] 取名稱、按鈕字樣「無修正」＝無碼記錄。缺名稱或缺 id 的卡丟棄。"""
        cards = []
        for a in soup.find(id="waterfall").find_all("a", class_="avatar-box"):
            m = _STAR_HREF_RE.match((a.get("href") or "").strip())
            img = a.find("img")
            name = ((img.get("title") if img else "") or "").strip()
            if not m or not name:
                continue
            label = a.select_one("span.mleft") or a
            uncensored = bool(m.group(1)) or "無修正" in label.get_text()
            cards.append(StarCard(("uncensored/" if m.group(1) else "") + "star/" + m.group(2), name, uncensored))
        return cards

    def search_stars(self, name: str) -> list[StarCard]:
        """女優名 → searchstar 候選卡（子字串候選也會回來，精確比對是呼叫端的事）。

        404／200＋零卡 → []；被擋（403／429／503…）→ SourceBlocked；200 無 #waterfall → SourceUnreachable。
        不吞 requests 例外、不 rate_limit、不帶 existmag（searchstar 不是作品清單）。
        """
        if not fold(name):
            return []
        url = f"{self.BASE_URL}{self._get_lang_prefix()}/searchstar/{self._plus_join(name)}"
        resp = self._session.get(url, timeout=self.config.timeout)
        soup = self._list_soup(resp, url)
        return [] if soup is None else self._parse_star_cards(soup)

    def fetch_entity_link(self, name: str, segment: str):
        """名稱 → 站上實體 (id, 連結文字)|None。segment ∈ {"series","director","label"}。

        三段：① 搜尋（series 一般搜尋、director type=2、label type=4；`get_ids_from_search`，T2 行為照舊）
        ② 只看第一張卡的番號 → 詳情頁 ③ 詳情頁 `div.col-md-3.info` 內該 segment 的連結，
        連結文字 fold 後與輸入相等才收。搜尋無卡 → None（1 個請求）；其餘最多 2 個請求。
        搜尋是子字串搜尋且回的是影片，不能當實體清單，詳情頁連結才有 id 與精確名稱（plan CD-175c-3）。
        """
        if segment not in _ENTITY_SEARCH_TYPE:
            raise ValueError(f"unknown entity segment: {segment!r}")
        wanted = fold(name)
        if not wanted:
            return None
        ids = self.get_ids_from_search(name, page=1, search_type=_ENTITY_SEARCH_TYPE[segment])
        if not ids:
            return None
        return self._entity_link_from_detail(ids[0], segment, wanted)

    def _entity_link_from_detail(self, number: str, segment: str, wanted: str):
        """詳情頁 → 該 segment 連結 (id, 連結文字)|None。404／沒有這種連結／文字不符 → None；擋下與看不懂丟例外。"""
        url = f"{self.BASE_URL}{self._get_lang_prefix()}/{number}"
        resp = self._session.get(url, timeout=self.config.timeout)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SourceBlocked(f"JavBus detail HTTP {resp.status_code}: {url}")
        info = BeautifulSoup(resp.text, "html.parser").select_one("div.col-md-3.info")
        if info is None:
            raise SourceUnreachable(f"JavBus detail unreadable (no info block): {url}")
        for a in info.find_all("a", href=True):
            m = _ENTITY_HREF_RE.match(a["href"].strip())
            text = a.get_text(strip=True)
            if m and m.group(1) == segment and fold(text) == wanted:
                return f"{segment}/{m.group(2)}", text
        return None

    # ---------- 實體清單（175c-T4）----------

    def get_entries_from_entity(self, entity_id: str, page: int = 1) -> list[ListCard]:
        """實體頁（女優／系列／導演／label）單頁作品卡。entity_id 形如 `star/okq`、`uncensored/star/23f`、`series/rvz`。

        URL＝<BASE_URL><語系前綴>/<entity_id>，第 N≥2 頁尾綴 `/<N>`。走 `_get_list`（帶 existmag=all，否則近期無磁鏈新片缺席）。
        404（頁碼超界）→ []；被擋（403／429／503…）→ SourceBlocked；200 無 #waterfall → SourceUnreachable；
        requests 例外 → SourceUnreachable。絕不把擋下或看不懂變成 []（BE-PY-03）。
        """
        url = f"{self.BASE_URL}{self._get_lang_prefix()}/{entity_id}"
        if page > 1:
            url += f"/{page}"
        try:
            resp = self._get_list(url)
        except requests.RequestException as exc:
            raise SourceUnreachable(f"JavBus entity page request failed: {url}") from exc
        soup = self._list_soup(resp, url)
        return [] if soup is None else self._parse_list_cards(soup)
