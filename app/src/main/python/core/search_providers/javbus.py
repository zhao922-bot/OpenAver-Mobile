"""JavBus 的 Provider（175a-T4）：把 scraper.py 的四條搜尋流程原封包入。

行為與事件序與搬家前逐一相同（離線 A/B 40 題 ALL SAME 為守門）。
頂層不得 import core.scraper／core.database（BE-PY-08）；core.scraper 的名字一律在呼叫當下取
（既有測試 patch 的是 core.scraper.*）。取頁一律經 pipeline.fetch_window、詳情一律經 pipeline.run_window。
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from core.logger import get_logger
from core.name_match import fold
from core.scrapers.javbus import JAVBUS_LIST_PAGE_SIZE, JavBusScraper
from core.search_providers.pipeline import fetch_window, run_window
from core.search_providers.types import (
    MAKER_RESOLUTION_ERRORS,
    Enriched,
    EntityRef,
    Kind,
    MakerSearchResult,
    Page,
    Window,
    WorkItem,
)

logger = get_logger(__name__)

PAGE_SIZE = 30
SOURCE = "javbus"


def _stub(number: str) -> WorkItem:
    return WorkItem(number, "", "", "", None, SOURCE)


def _stubs(numbers) -> list[dict]:
    return [{"number": n, "title": ""} for n in numbers]


def _take_window(fetch_ids, w: Window) -> tuple[Page, bool]:
    """JavBus 清單的唯一取頁入口：fetch_ids(page_no) -> list[str]。回 (fetch_window 算好的 Page, 是否曾取回任何 id)。

    「曾取回」另外記：切片後為空（offset 落在該頁筆數之後）與「完全沒有 id」今天的事件不同。
    404 當尾端（fetch_ids 回 []）；被擋／看不懂／逾時由 scraper 往外丟，這裡不吞。
    """
    seen = []

    def fetch_page(page_no):
        ids = fetch_ids(page_no)
        if ids:
            seen.append(True)
        return Page([_stub(n) for n in ids or []], has_next=True)

    return fetch_window(PAGE_SIZE, fetch_page, w), bool(seen)


def _take_code_window(scraper, prefix, w: Window) -> tuple[Page, bool]:
    """CODE（前綴）的一個視窗：先問一般搜尋；整段沒有任何 id（站方 404）才對同一視窗改問無碼區。

    無狀態、不記哪些前綴是無碼；被擋／看不懂／逾時直接往外丟，不會走到無碼區。
    """
    page, got_any = _take_window(lambda p: scraper.get_ids_from_search(prefix, page=p, search_type=1), w)
    if got_any:
        return page, got_any
    return _take_window(lambda p: scraper.get_ids_from_search(prefix, page=p, search_type=1, uncensored=True), w)


def _progress_hook(status_callback, total):
    """前綴的 details:k/N：每部（含失敗）各一次，依真實完成順序，先於該部 result-item。"""
    if status_callback is None:
        return None
    done = 0

    def on_item_done(slot, ok):
        nonlocal done
        done += 1
        status_callback("javbus", f"details:{done}/{total}")

    return on_item_done


def _entry_item(card) -> WorkItem:
    """實體清單頁的一張卡 → WorkItem；封面相對路徑補成絕對網址，演員列表沒給（None，靠 enrich 補）。"""
    cover = card.cover
    if cover and not cover.startswith("http"):
        cover = JavBusScraper.BASE_URL + cover
    return WorkItem(card.number, card.title, cover, card.date, None, SOURCE, ref=card.number)


def _entity_page(scraper, entity_id: str, page_no: int) -> Page:
    cards = scraper.get_entries_from_entity(entity_id, page_no)
    return Page([_entry_item(card) for card in cards], has_next=len(cards) >= PAGE_SIZE)


def _belongs(video, ref: EntityRef) -> bool:
    """詳情頁的連結代號是否含該實體（ref.id 最後一段代號）；缺該類的鍵 → False（不是 None）。"""
    code = ref.id.rsplit("/", 1)[-1]
    return code in video.entity_ids.get(_ENTITY_KEY[ref.kind], ())


def _detail_window(provider, numbers, result_callback, on_item_done=None) -> list[dict]:
    """對一批番號抓詳情：失敗／無 title 就丟、不斷路、不加延遲（與今天相同）。"""
    return run_window(
        provider,
        [_stub(n) for n in numbers],
        None,
        result_callback=result_callback,
        on_item_done=on_item_done,
        on_fail="drop",
        delay=0,
        breaker=False,
        guard=False,
    ).cards


def _sorted(cards):
    import core.scraper as m

    return m.sort_results_by_date(cards)


# ---------------------------------------------------------------- 名稱→實體（175c-T3，plan CD-175c-3）
_RESOLVE_CACHE_MAX = 1024
_RESOLVE_CACHE: dict[tuple[str, str], tuple[EntityRef, ...]] = {}
_ENTITY_SEGMENT = {Kind.SERIES: "series", Kind.DIRECTOR: "director", Kind.LABEL: "label"}
# 實體 kind → Video.entity_ids 的鍵（守衛 belongs 與實體清單的 kind 範圍共用這一張表）
_ENTITY_KEY = {Kind.ACTOR: "actors", Kind.DIRECTOR: "director", Kind.SERIES: "series", Kind.LABEL: "label"}


def clear_resolve_cache() -> None:
    _RESOLVE_CACHE.clear()


def _same_name(candidate, wanted) -> bool:
    """名稱精確相等（fold 後）。子字串不算：站方 searchstar 回的是子字串候選（三上→三上悠亜…）。"""
    return fold(candidate) == fold(wanted)


def _pick_stars(cards, wanted):
    """searchstar 候選中同名者：有碼、無碼各取頁面順序第一筆，有碼在前（最多 2 筆）；沒有同名 → []。"""
    exact = [c for c in cards if _same_name(c.name, wanted)]
    censored = [c for c in exact if not c.uncensored][:1]
    uncensored = [c for c in exact if c.uncensored][:1]
    return censored + uncensored


def _resolve_cached(kind: Kind, name: str, lookup) -> tuple[EntityRef, ...]:
    """(kind, 折疊名) → 結果 tuple 的模組層快取（空 tuple＝確定查無）；只記確定結果，lookup 的例外原樣往外丟、不入快取（BE-PY-03）。"""
    key = (kind.value, fold(name))
    if key in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[key]
    refs = tuple(lookup())
    if len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_MAX:
        _RESOLVE_CACHE.clear()
    _RESOLVE_CACHE[key] = refs
    return refs


_PROBE_PREFIXES = 2
_PROBE_MAX_REQUESTS = 4
_PROBE_SAMPLES = 5


def _prefix_of(number):
    m = re.match(r"^([A-Za-z]+)", number or "")
    return m.group(1).upper() if m else ""


def _probe_titles(scraper_mod, maker_key, spellings, titles, today, db_path):
    """片庫沒樣本且對照表沒這家 → 用 prefix_mapping 的前綴搜幾個番號當樣本（記憶體內合成 title，不寫片庫）。

    回 (titles, spellings)；不需要探針就原樣回。搜尋丟例外 → 回 None（呼叫端回 maker_unreachable，不寫表）。
    """
    from core.database import maker_javbus_map
    from core.maker_latest import pick_samples
    from core.maker_mapping import load_prefix_mapping
    from core.maker_names import maker_key_of

    mapped = maker_javbus_map.get_mapping(maker_key, db_path=db_path)
    if mapped is not None:
        return titles, spellings
    scraper = scraper_mod.JavBusScraper()
    if pick_samples(titles, today, spellings=set(spellings), validate=scraper.validate_number):
        return titles, spellings
    keys = {maker_key} | {maker_key_of(s) for s in spellings}
    chosen = sorted((p, v) for p, v in load_prefix_mapping().items() if maker_key_of(v) in keys)
    synthetic, extra = [], []
    for i, (prefix, value) in enumerate(chosen[:_PROBE_MAX_REQUESTS]):
        if i >= _PROBE_PREFIXES and synthetic:
            break
        try:
            ids = scraper.get_ids_from_search(prefix, page=1, search_type=1)
        except Exception as e:
            logger.error("maker %s probe %s failed: %s: %s", maker_key, prefix, type(e).__name__, e)
            return None
        kept = [
            number for number in ids
            if _prefix_of(number) == prefix
        ]
        for number in kept[:_PROBE_SAMPLES - len(synthetic)]:
            synthetic.append(SimpleNamespace(maker=value, number=number, release_date=None))
            extra.append(value)
    return list(titles) + synthetic, list(dict.fromkeys([*spellings, *extra]))


class JavBusProvider:
    id = SOURCE
    capabilities = frozenset({Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL, Kind.MAKER, Kind.CODE,
                              Kind.PARTIAL, Kind.KEYWORD})
    supports_discovery = True
    fallback_streaming = False  # 補完詳情後 _sorted（日期）重排，串流順序≠最終順序
    list_chunk = PAGE_SIZE

    # ------------------------------------------------------------ Protocol
    def resolve(self, kind: Kind, name: str) -> EntityRef | None:
        """女優／系列／導演／label 名稱 → 站上同一個實體（有碼優先的第一筆）；MAKER／CODE／PARTIAL／KEYWORD 與空白輸入 → None（0 請求）。

        一律走 /ja（與 UI 語言無關）；傳輸只經 search_stars／fetch_entity_link 兩個方法名。例外原樣往外丟。
        """
        refs = self.resolve_all(kind, name)
        return refs[0] if refs else None

    def resolve_all(self, kind: Kind, name: str) -> list[EntityRef]:
        """可選方法（175d）：女優 → 同名的有碼／無碼代號（有碼在前，最多 2 筆）；系列／導演／label ≤1 筆；其餘與空白 → []（0 請求）。"""
        if (kind is not Kind.ACTOR and kind not in _ENTITY_SEGMENT) or not fold(name):
            return []
        return list(_resolve_cached(kind, name, lambda: self._lookup(kind, name)))

    def _lookup(self, kind: Kind, name: str) -> tuple[EntityRef, ...]:
        scraper = self._entity_scraper()
        if kind is Kind.ACTOR:
            return tuple(EntityRef(Kind.ACTOR, s.id, s.name) for s in _pick_stars(scraper.search_stars(name), name))
        found = scraper.fetch_entity_link(name, _ENTITY_SEGMENT[kind])
        return () if found is None else (EntityRef(kind, found[0], found[1]),)

    def list_entity(self, ref: EntityRef, w: Window) -> Page:
        if ref.kind is Kind.CODE:
            return _take_code_window(self._scraper(), ref.id, w)[0]
        if ref.kind is Kind.PARTIAL:
            import core.scraper as m

            numbers = m.expand_partial_number(ref.id) if w.offset <= 0 else []
            return Page([_stub(n) for n in numbers])
        if ref.kind in _ENTITY_KEY:
            scraper = self._entity_scraper()  # 固定 /ja，與 UI 語言無關（實體代號與名稱以日文站為準）
            return fetch_window(PAGE_SIZE, lambda p: _entity_page(scraper, ref.id, p), w)
        raise NotImplementedError(f"javbus list_entity: {ref.kind}")

    def search_keyword(self, q: str, w: Window) -> Page:
        scraper = self._scraper()
        return _take_window(lambda p: scraper.get_ids_from_search(q, page=p), w)[0]

    def enrich(self, item: WorkItem, ref: EntityRef | None) -> Enriched:
        if ref is not None and ref.kind in _ENTITY_KEY:
            return self._enrich_entity(item, ref)
        import core.scraper as m

        data = m.search_jav(item.number, SOURCE)
        if data and data.get("title"):
            return Enriched(card=data, belongs=None)
        return Enriched(card=None)

    def _enrich_entity(self, item: WorkItem, ref: EntityRef) -> Enriched:
        """實體清單的詳情＋守衛事實。用 UI 語系的 scraper（卡片 tags 不變日文），卡片後處理與舊路徑共用 build_card。

        例外與舊路徑同寬：吞掉記 log、card=None（該部在清單裡降級顯示，不整批失敗）。belongs 由原 video 算。
        """
        import core.scraper as m

        number = m.normalize_number(item.number)
        try:
            video = self._scraper().search(number)
        except Exception as e:
            logger.info("[Search] %s 例外 %s: %s", number, type(e).__name__, e)
            return Enriched(card=None)
        if not (video and video.title):
            return Enriched(card=None)
        return Enriched(card=m.build_card(video, number), belongs=_belongs(video, ref))

    # ------------------------------------------------------------ 統一入口
    def run(self, kind: Kind, target: str, w: Window, *, status_callback=None, result_callback=None,
            discovery_only: bool = False) -> list[dict]:
        if kind is Kind.KEYWORD:
            return self.run_keyword(target, w.limit, w.offset, status_callback, result_callback, discovery_only)
        if kind is Kind.PARTIAL:
            if w.offset > 0:
                return []
            return self.run_partial(target, status_callback, result_callback, discovery_only)
        if kind is Kind.CODE:
            return self.run_prefix(target, w.limit, w.offset, status_callback, result_callback, discovery_only)
        raise ValueError(f"javbus run: unsupported kind {kind}")

    # ------------------------------------------------------------ 四條舊流程
    def run_partial(self, partial, status_callback, result_callback, discovery_only):
        """局部搜尋"""
        import core.scraper as m

        candidates = m.expand_partial_number(partial)
        if status_callback:
            status_callback("javbus", "searching")
        if discovery_only:
            if candidates and result_callback:
                result_callback(-1, candidates)
            if status_callback:
                status_callback("done", f"found:{len(candidates)}")
            return _stubs(candidates)
        results = _detail_window(self, candidates, result_callback)
        if status_callback:
            status_callback("done", f"found:{len(results)}")
        return _sorted(results)

    def run_prefix(self, prefix, limit, offset, status_callback, result_callback, discovery_only):
        """前綴搜尋"""
        results: list[dict] = []
        prefix = prefix.strip().upper()
        if status_callback:
            status_callback("javbus", "searching")
        try:
            scraper = self._scraper()
            page, got_any = _take_code_window(scraper, prefix, Window(offset, limit))
            numbers = [i.number for i in page.items]
            if not got_any:
                if status_callback:
                    status_callback("javbus", "found:0")
                return []
            if status_callback:
                status_callback("javbus", f"found:{len(numbers)}")
            if discovery_only:
                if status_callback:
                    status_callback("done", f"found:{len(numbers)}")
                return _stubs(numbers)
            if status_callback:
                status_callback("javbus", "fetching_details")
            results = _detail_window(self, numbers, result_callback, _progress_hook(status_callback, len(numbers)))
        except Exception as e:
            logger.error("search_prefix failed: %s", e)
        if status_callback:
            status_callback("done", f"found:{len(results)}")
        return _sorted(results)

    def run_keyword(self, name, limit, offset, status_callback, result_callback, discovery_only=False, *,
                    ids_provider=None):
        """JavBus keyword search；ids_provider（173）取代「取番號那一步」，簽名 (scraper, page) -> ids。"""
        try:
            if status_callback:
                status_callback("javbus", "searching")
            scraper = self._scraper()
            def fetch_ids(p):
                if ids_provider is None:
                    return scraper.get_ids_from_search(name, page=p)
                return ids_provider(scraper, p)

            page, got_any = _take_window(fetch_ids, Window(offset, limit))
            numbers = [i.number for i in page.items]
            if got_any:
                if status_callback:
                    status_callback("javbus", f"found:{len(numbers)}")
                if discovery_only:
                    if status_callback:
                        status_callback("done", f"found:{len(numbers)}")
                    return _stubs(numbers)
                results = _detail_window(self, numbers, result_callback)
                if status_callback:
                    status_callback("done", f"found:{len(results)}")
                return _sorted(results)
        except Exception as e:
            logger.error("_javbus_keyword_search failed: %s", e)
        return []

    def run_maker(self, maker_key, label, spellings, offset, *, titles, today, status_callback=None,
                  result_callback=None, db_path=None, limit=None) -> MakerSearchResult:
        """片商最新作品（JavBus 片商頁，一次一頁 30 部，發行日新到舊）。不攔 resolve_maker_studio 的未預期例外。

        limit=None＝173 原樣（offset 須 30 的倍數、單頁）；給了 limit＝視窗模式（175b-T8a，offset 任意＋前綴探針）。
        """
        import core.scraper as m

        if limit is not None:
            return self._run_maker_window(maker_key, label, spellings, offset, limit, titles=titles, today=today,
                                          status_callback=status_callback, result_callback=result_callback,
                                          db_path=db_path)

        if offset < 0 or offset % JAVBUS_LIST_PAGE_SIZE:
            raise ValueError(f"offset must be a non-negative multiple of {JAVBUS_LIST_PAGE_SIZE}: {offset}")
        if status_callback:
            status_callback("javbus", "searching")
        resolution = m.resolve_maker_studio(maker_key, label, spellings, titles, today=today, db_path=db_path)
        if resolution.status != "found":
            code = MAKER_RESOLUTION_ERRORS.get(resolution.status, "maker_unreachable")
            return MakerSearchResult([], False, code)

        ref = (resolution.kind, resolution.studio_id)
        request_page = offset // JAVBUS_LIST_PAGE_SIZE + 1
        counts: dict[int, int] = {}
        errors: list[BaseException] = []

        def ids_provider(scraper, page):
            if page != request_page:
                return []
            try:
                ids = scraper.get_ids_from_studio(ref, page)
            except Exception as e:
                errors.append(e)
                raise
            counts[page] = len(ids)
            return ids

        results = self.run_keyword(
            label, JAVBUS_LIST_PAGE_SIZE, offset, status_callback, result_callback, ids_provider=ids_provider)
        if errors:
            logger.error("maker %s list failed: %s: %s", maker_key, type(errors[0]).__name__, errors[0])
            return MakerSearchResult([], False, "maker_unreachable")
        if not counts.get(request_page):
            logger.info("maker %s page %d empty", maker_key, request_page)
            return MakerSearchResult([], False, "maker_empty")
        return MakerSearchResult(results, counts.get(request_page, 0) >= JAVBUS_LIST_PAGE_SIZE, None)

    def _run_maker_window(self, maker_key, label, spellings, offset, limit, *, titles, today, status_callback,
                          result_callback, db_path) -> MakerSearchResult:
        """視窗模式：任意 (offset, limit)；對照表沒這家且片庫沒樣本時先做前綴探針。"""
        import core.scraper as m

        if offset < 0 or limit <= 0:
            raise ValueError(f"offset/limit out of range: {offset}, {limit}")
        if status_callback:
            status_callback("javbus", "searching")
        probed = _probe_titles(m, maker_key, spellings, titles, today, db_path)
        if probed is None:
            return MakerSearchResult([], False, "maker_unreachable")
        titles, spellings = probed
        resolution = m.resolve_maker_studio(maker_key, label, spellings, titles, today=today, db_path=db_path)
        if resolution.status != "found":
            code = MAKER_RESOLUTION_ERRORS.get(resolution.status, "maker_unreachable")
            return MakerSearchResult([], False, code)

        ref = (resolution.kind, resolution.studio_id)
        first_page = offset // JAVBUS_LIST_PAGE_SIZE + 1
        skip = offset % JAVBUS_LIST_PAGE_SIZE
        counts: dict[int, int] = {}
        errors: list[BaseException] = []

        def ids_provider(scraper, page):
            if page > first_page and counts.get(page - 1, 0) < JAVBUS_LIST_PAGE_SIZE:
                return []  # 前一頁不滿 30 ＝已到末頁，不再發請求
            try:
                ids = scraper.get_ids_from_studio(ref, page)
            except Exception as e:
                errors.append(e)
                raise
            counts[page] = len(ids)
            return ids

        results = self.run_keyword(
            label, limit, offset, status_callback, result_callback, ids_provider=ids_provider)
        if errors:
            logger.error("maker %s list failed: %s: %s", maker_key, type(errors[0]).__name__, errors[0])
            return MakerSearchResult([], False, "maker_unreachable")
        fetched = sum(counts.values())
        if fetched <= skip:
            logger.info("maker %s window at %d empty", maker_key, offset)
            return MakerSearchResult([], False, "maker_empty")
        has_more = fetched > skip + limit or counts[max(counts)] >= JAVBUS_LIST_PAGE_SIZE
        return MakerSearchResult(results, has_more, None)

    # ------------------------------------------------------------ 內部
    def _scraper(self):
        import core.scraper as m

        return m.JavBusScraper(lang=m.get_javbus_lang())

    def _entity_scraper(self):
        """名稱→實體的 scraper：固定 /ja（站上原文名稱；不隨 UI 語言變，否則比對全落空）。"""
        import core.scraper as m

        return m.JavBusScraper(lang="ja")
