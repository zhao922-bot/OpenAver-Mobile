"""JavDB 的純函式 parser 與資料類別（175b-T2）。

只放「站方回應 dict → 我們的型別」的純函式；不放 provider class（T3／T4 才加），也不做任何傳輸。
頂層不得 import core.scraper／core.database（BE-PY-08）；core/scrapers/ 不得反向 import 本檔。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from core.logger import get_logger
from core.maker_mapping import load_name_mapping, load_search_aliases
from core.maker_names import maker_key_of
from core.name_match import fold
from core.scrapers import javdb_api
from core.scrapers.errors import SourceBlocked
from core.scrapers.javdb_api import MAX_PAGE, PAGE_SIZE
from core.scrapers.utils import strip_number_prefix
from core.search_providers.names import maker_names
from core.search_providers.pipeline import fetch_window, run_window
from core.search_providers.types import (
    Enriched,
    EntityRef,
    Kind,
    MakerSearchResult,
    Outcome,
    Page,
    Window,
    WorkItem,
)

logger = get_logger(__name__)

SOURCE = "javdb"
PAGE_SIZE_MAKER = 30  # 片商膠囊一頁 30 部（limit=None 的視窗）


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _id(v) -> str:
    """id 欄位：字串或整數皆收，其餘（None、bool、容器）視為缺。"""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (str, int)):
        return str(v).strip()
    return ""


def _opt_id(v) -> str | None:
    return _id(v) or None


# ---------------------------------------------------------------- 候選（type= 搜尋）
@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    name_zht: str
    other_name: str  # 不切分：接受規則（T3）自己處理
    videos_count: int
    type: int | None


def parse_candidates(rows) -> list[Candidate]:
    """候選列 → Candidate；非 dict／缺 id／缺 name 的列丟棄，不拋。"""
    out: list[Candidate] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        cid, name = _id(r.get("id")), _s(r.get("name"))
        if not cid or not name:
            continue
        vc = r.get("videos_count")
        t = r.get("type")
        out.append(
            Candidate(
                id=cid,
                name=name,
                name_zht=_s(r.get("name_zht")),
                other_name=_s(r.get("other_name")),
                videos_count=vc if isinstance(vc, int) and not isinstance(vc, bool) else 0,
                type=t if isinstance(t, int) and not isinstance(t, bool) else None,
            )
        )
    return out


# ---------------------------------------------------------------- 列表列
def parse_list_rows(rows) -> list[WorkItem]:
    """列表列 → WorkItem；非 dict／缺 id／缺 number 的列丟棄，不拋。

    標題一律日文原文：origin_title 空則退 title，再過 strip_number_prefix（與 to_video 同規則）。
    列表沒有女優 ⇒ actors=None（要靠 enrich 補）。
    """
    out: list[WorkItem] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        mid, number = _id(r.get("id")), _s(r.get("number"))
        if not mid or not number:
            continue
        title = _s(r.get("origin_title")) or _s(r.get("title"))
        out.append(
            WorkItem(
                number=number,
                title=strip_number_prefix(title, number),
                cover_url=_s(r.get("cover_url")) or _s(r.get("thumb_url")),
                date=_s(r.get("release_date")),
                actors=None,
                source=SOURCE,
                ref=mid,
            )
        )
    return out


def list_page(rows, page: int) -> Page:
    """一頁原始列 → Page。has_next 看「原始列數」是否滿頁（被丟棄的列也算站方給的）；total 恆 None。"""
    raw = rows if isinstance(rows, list) else []
    has_next = len(raw) >= PAGE_SIZE and page < MAX_PAGE
    return Page(parse_list_rows(raw), has_next, None)


# ---------------------------------------------------------------- 詳情事實
@dataclass(frozen=True)
class DetailFacts:
    maker_id: str | None
    series_id: str | None
    director_id: str | None
    publisher_id: str | None
    actor_ids: frozenset[str]
    origin_title: str
    title: str


def parse_detail_facts(movie) -> DetailFacts:
    """詳情 movie dict → DetailFacts；不做 belongs 判斷（T4 的 enrich）。非 dict 回全空。"""
    m = movie if isinstance(movie, dict) else {}
    actors = m.get("actors")
    ids = frozenset(
        a
        for a in (_id(x.get("id")) for x in (actors if isinstance(actors, list) else []) if isinstance(x, dict))
        if a
    )
    return DetailFacts(
        maker_id=_opt_id(m.get("maker_id")),
        series_id=_opt_id(m.get("series_id")),
        director_id=_opt_id(m.get("director_id")),
        publisher_id=_opt_id(m.get("publisher_id")),
        actor_ids=ids,
        origin_title=_s(m.get("origin_title")),
        title=_s(m.get("title")),
    )


# ---------------------------------------------------------------- 名字 → 實體（175b-T3）
_SPLIT = re.compile(r"[,、，/／]")
_SERIES_MIN_VIDEOS = 5
_RESOLVE_CACHE_MAX = 1024
_RESOLVE_CACHE: dict[tuple[str, str], EntityRef | None] = {}
_ALT_NAMES_CACHE: dict[tuple[str, str], tuple[str, ...]] = {}  # 與 _RESOLVE_CACHE 同鍵、同一次請求寫入（175d）
_SEARCH_TYPE = {
    Kind.ACTOR: "actor",
    Kind.SERIES: "series",
    Kind.DIRECTOR: "director",
    Kind.MAKER: "maker",
    Kind.CODE: "code",
}


def _sleep(seconds: float) -> None:
    """本檔唯一的 sleep 點（測試 patch 它）。"""
    time.sleep(seconds)


def _request_delay() -> float:
    import core.scraper as m  # 函式內 import：頂層不得 import core.scraper（BE-PY-08）

    return m.REQUEST_DELAY


def _paced(fn, *args, **kwargs):
    """序列階段的每次 JavDB 請求：完成後（含失敗）至少等 REQUEST_DELAY（I-A1：任兩次請求 ≥0.3 秒）。
    後置 sleep 同時保證「最後一次列表請求 → 第一批詳情」也有間隔。詳情階段的間隔由 pipeline 負責。"""
    try:
        return fn(*args, **kwargs)
    finally:
        _sleep(_request_delay())


def norm_number(number) -> str:
    return (number or "").upper().replace("-", "").strip() if isinstance(number, str) else ""


_LIST_FILTER = {
    Kind.ACTOR: "a",
    Kind.SERIES: "s",
    Kind.DIRECTOR: "d",
    Kind.MAKER: "m",
    Kind.CODE: "c",
}


def _partial_matches(items, want):
    """只留落在「與 JavBus 同一套展開」號碼集合內的列（換哪家回答結果一樣）。"""
    out = []
    for it in items:
        if norm_number(it.number) in want:
            out.append(it)
    return out


def _keep_newer(items):
    """同號異片（撞號）只留發行日較新者；保留首次出現的順序。"""
    best: dict[str, WorkItem] = {}
    for it in items:
        key = norm_number(it.number)
        prev = best.get(key)
        if prev is None or it.date > prev.date:
            best[key] = it
    return list(best.values())


def _clear_caches() -> None:
    _RESOLVE_CACHE.clear()
    _ALT_NAMES_CACHE.clear()


def clear_resolve_cache() -> None:
    _clear_caches()


def actor_alt_names(cand: Candidate) -> list[str]:
    """候選 → 可拿去別家比對的名字：name 永遠第一；other_name 切出的 token 丟純 ASCII（羅馬字／數字）者；
    name_zht 不納入；以 fold 去重保序。"""
    tokens = [cand.name, *_SPLIT.split(cand.other_name)]
    out: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(tokens):
        token = raw.strip()
        if i > 0 and token.isascii():
            continue
        key = fold(token)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _names(c: Candidate) -> list[str]:
    return [n for n in (c.name, c.name_zht, *_SPLIT.split(c.other_name)) if n]


def _largest(cands: list[Candidate]) -> Candidate:
    return max(cands, key=lambda c: c.videos_count)  # max 遇平手取先出現


def _pick_actor(cands: list[Candidate], qf: str) -> Candidate | None:
    pool = [c for c in cands if c.type == 0]
    exact = [c for c in pool if any(fold(n) == qf for n in _names(c))]
    if exact:
        return _largest(exact)
    if len(pool) == 1 and not any(qf in fold(n) for n in _names(pool[0])):
        return pool[0]
    return None


def _named_enough(c: Candidate, qf: str) -> bool:
    return fold(c.name) == qf and c.videos_count >= _SERIES_MIN_VIDEOS


def _pick_named(cands: list[Candidate], qf: str) -> Candidate | None:
    ok = [c for c in cands if _named_enough(c, qf)]
    return _largest(ok) if ok else None


def _pick_code(cands: list[Candidate], qf: str) -> Candidate | None:
    ok = [c for c in cands if fold(c.name) == qf]
    return _largest(ok) if ok else None


def _pick_maker(cands: list[Candidate], wanted: set[str]) -> Candidate | None:
    accepted = [
        c
        for c in cands
        if fold(c.name) in wanted and c.videos_count > 0
    ]
    if not accepted:
        return None
    return max(accepted, key=lambda c: c.videos_count)


def _maker_names(q: str) -> list[str]:
    """薄包裝：對照表從本模組的 load_* 取（既有測試 patch 的是這兩個名字），展開邏輯在 names.maker_names。"""
    return maker_names(q, name_mapping=load_name_mapping(), search_aliases=load_search_aliases())


def _sort_items_like_results(items):
    """串流 seed 順序＝回傳順序：視窗在 run_window 之前就依 sort_results_by_date 的鍵與方向排好。"""
    import core.scraper as m

    rows = [{"date": it.date, "number": it.number, "_item": it} for it in items]
    return [r["_item"] for r in m.sort_results_by_date(rows)]


class JavDBProvider:
    id = SOURCE
    capabilities = frozenset(
        {Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.MAKER, Kind.CODE, Kind.PARTIAL, Kind.KEYWORD}
    )
    supports_discovery = False
    # 補完詳情後依日期重排，串流順序≠最終順序（BE-DATA-20）
    fallback_streaming = False
    list_chunk = PAGE_SIZE

    def __init__(self, scraper=None):
        self._scraper_obj = scraper

    @property
    def _scraper(self):
        if self._scraper_obj is None:
            from core.scrapers.javdb import JavDBScraper  # 延後 import（BE-PY-08）

            self._scraper_obj = JavDBScraper()
        return self._scraper_obj

    def _proxies(self):
        return self._scraper._proxy_kwargs().get("proxies")

    def _search(self, search_type: str, q: str) -> list[Candidate]:
        proxies = self._proxies()
        rows = _paced(lambda: javdb_api.api_search_typed(search_type, q, proxies=proxies))
        return parse_candidates(rows)

    def _lookup(self, kind: Kind, q: str, qf: str) -> Candidate | None:
        if kind is Kind.MAKER:
            names = _maker_names(q)
            wanted = {fold(n) for n in names}
            for name in names:
                hit = _pick_maker(self._search("maker", name), wanted)
                if hit is not None:
                    return hit
            return None
        cands = self._search(_SEARCH_TYPE[kind], q)
        if kind is Kind.ACTOR:
            return _pick_actor(cands, qf)
        if kind is Kind.CODE:
            return _pick_code(cands, qf)
        return _pick_named(cands, qf)

    def resolve(self, kind: Kind, q: str) -> EntityRef | None:
        if kind not in _SEARCH_TYPE:
            return None
        qf = fold(q)
        if not qf:
            return None
        key = (kind.value, maker_key_of(q))
        if key in _RESOLVE_CACHE:
            return _RESOLVE_CACHE[key]
        cand = self._lookup(kind, q, qf)  # 例外原樣往外丟，不入快取（BE-PY-03）
        ref = None
        if cand is not None:
            ref = EntityRef(kind, cand.name if kind is Kind.CODE else cand.id, cand.name)
        if len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_MAX:
            _clear_caches()
        _RESOLVE_CACHE[key] = ref
        if kind is Kind.ACTOR:
            _ALT_NAMES_CACHE[key] = () if cand is None else tuple(actor_alt_names(cand))
        return ref

    def alt_names(self, kind: Kind, q: str) -> list[str]:
        """可選方法（175d）：女優的別名候選（日文正名＋other_name 非拉丁 token）；只支援 ACTOR，其餘 → []。
        與 resolve 共用同一次候選搜尋（不另發請求）。"""
        if kind is not Kind.ACTOR or not fold(q):
            return []
        key = (kind.value, maker_key_of(q))
        self.resolve(kind, q)  # 填滿兩份快取；例外原樣往外丟
        return list(_ALT_NAMES_CACHE.get(key, ()))

    # ------------------------------------------------------------ 清單
    def list_entity(self, ref: EntityRef, w: Window) -> Page:
        flag = _LIST_FILTER.get(ref.kind)
        if flag is None:
            raise ValueError(f"javdb list_entity: unsupported kind {ref.kind}")
        filter_by = f"0:{flag}:{ref.id}"
        proxies = self._proxies()

        def fetch_page(p: int) -> Page:
            rows = _paced(lambda: javdb_api.api_list_tags(filter_by, p, proxies=proxies))
            return list_page(rows, p)

        return fetch_window(PAGE_SIZE, fetch_page, w, max_page=MAX_PAGE)

    def search_keyword(self, q: str, w: Window) -> Page:
        proxies = self._proxies()

        def fetch_page(p: int) -> Page:
            rows = _paced(lambda: javdb_api.api_search_page(q, p, proxies=proxies))
            return list_page(rows, p)

        return fetch_window(PAGE_SIZE, fetch_page, w, max_page=MAX_PAGE)

    # ------------------------------------------------------------ 補詳情
    def _belongs(self, item: WorkItem, ref: EntityRef | None, facts: DetailFacts) -> bool | None:
        if ref is None:
            return None
        if ref.kind is Kind.ACTOR:
            return ref.id in facts.actor_ids
        if ref.kind is Kind.SERIES:
            return facts.series_id == ref.id
        if ref.kind is Kind.DIRECTOR:
            return facts.director_id == ref.id
        if ref.kind is Kind.MAKER:
            return facts.maker_id == ref.id
        if ref.kind is Kind.CODE:
            return norm_number(item.number).startswith(norm_number(ref.id))
        return None

    def enrich(self, item: WorkItem, ref: EntityRef | None) -> Enriched:
        """不自己 sleep：詳情間隔由 pipeline 負責（雙重 sleep 會砍半吞吐）。"""
        detail = javdb_api.api_movie_detail(item.ref, proxies=self._proxies())
        card = javdb_api.to_video(detail, item.number).to_legacy_dict()
        card["_source"] = SOURCE
        return Enriched(card, self._belongs(item, ref, parse_detail_facts(detail)))

    # ------------------------------------------------------------ 統一入口
    def run(self, kind: Kind, target: str, w: Window, *, status_callback=None, result_callback=None,
            discovery_only: bool = False) -> list[dict]:
        if kind not in (Kind.CODE, Kind.KEYWORD, Kind.PARTIAL):
            raise ValueError(f"javdb run: unsupported kind {kind}")
        if discovery_only:
            return []
        if status_callback:
            status_callback(SOURCE, "searching")
        if kind is Kind.CODE:
            cards = self._run_code(target, w, result_callback)
        elif kind is Kind.KEYWORD:
            cards = self._run_keyword(target, w, result_callback)
        else:
            cards = self._run_partial(target, w, result_callback)
        if not cards:
            return []
        if status_callback:
            status_callback("done", f"found:{len(cards)}")
        for card in cards:
            card["_source"] = SOURCE
        return cards

    def run_maker(self, maker_key, label, spellings, offset, *, limit=None, titles=None, today=None,
                  status_callback=None, result_callback=None, db_path=None) -> MakerSearchResult:
        """片商最新作品（175b-T8b）：resolve(MAKER, label) → list_entity 視窗 → run_window(guard)。

        titles／today／db_path／spellings 接受但不使用（正名／別名展開在 resolve 內）。limit=None ⇒ 視窗取 30。"""
        if status_callback:
            status_callback(SOURCE, "searching")
        try:
            ref = self.resolve(Kind.MAKER, label)
            if ref is None:
                return MakerSearchResult([], False, "maker_not_found")
            page = self.list_entity(ref, Window(offset, limit or PAGE_SIZE_MAKER))
        except Exception as err:
            logger.warning("javdb maker %s failed (%s%s)", maker_key, type(err).__name__,
                           "/blocked" if isinstance(err, SourceBlocked) else "")
            return MakerSearchResult([], False, "maker_unreachable")
        if not page.items:
            return MakerSearchResult([], False, "maker_empty")
        res = run_window(
            self,
            _sort_items_like_results(page.items),
            ref,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=True,
            breaker=True,
        )
        if res.outcome is Outcome.UNREACHABLE:
            return MakerSearchResult([], False, "maker_unreachable")
        if not res.cards:
            return MakerSearchResult([], False, "maker_not_found")
        cards = res.cards
        for card in cards:
            card["_source"] = SOURCE
        if status_callback:
            status_callback("done", f"found:{len(cards)}")
        return MakerSearchResult(cards, page.has_next, None)

    def _run_code(self, target, w, result_callback) -> list[dict]:
        ref = self.resolve(Kind.CODE, target.strip().upper())
        if ref is None:
            return []
        page = self.list_entity(ref, w)
        if not page.items:
            return []
        return run_window(
            self,
            _sort_items_like_results(page.items),
            ref,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=True,
            breaker=True,
        ).cards

    def _run_keyword(self, target, w, result_callback) -> list[dict]:
        page = self.search_keyword(target, w)
        if not page.items:
            return []
        return run_window(
            self,
            _sort_items_like_results(page.items),
            None,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=False,
            breaker=True,
        ).cards

    def _run_partial(self, target, w, result_callback) -> list[dict]:
        """局部搜尋：忽略 w.limit（relay 傳 Window(0,0)）、只取第 1 頁、客戶端只留與 JavBus 同一套展開的號碼。"""
        if w.offset > 0:
            return []
        import core.scraper as m

        expanded = m.expand_partial_number(target)
        # 查詢字＝展開結果共同的前綴（去掉最後一位數字）；不一致或為空就不查
        stems = {n[:-1] for n in expanded}
        if len(stems) != 1:
            return []
        query = stems.pop()
        proxies = self._proxies()
        rows = _paced(lambda: javdb_api.api_search_page(query, 1, proxies=proxies))
        want = {norm_number(n) for n in expanded}
        items = _keep_newer(_partial_matches(parse_list_rows(rows), want))
        if not items:
            return []
        return run_window(
            self,
            _sort_items_like_results(items),
            None,
            result_callback=result_callback,
            on_fail="degrade",
            delay=None,
            guard=False,
            breaker=True,
        ).cards
