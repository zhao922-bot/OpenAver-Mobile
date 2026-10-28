"""接力（relay）：依鏈順序逐家詢問 provider，第一家非空即回（CD-175a-3）。

- 鏈由 registry.providers_for 決定；每次搜尋新建 provider。
- 例外（Exception）或空結果 ⇒ log 後換下一家；全無 ⇒ []。175a 中「查無」與「連不上」對使用者都是 []。
- 實體梯子（actress）：外圈 provider、內圈 ACTOR→SERIES→DIRECTOR→LABEL；任一 ref 命中走
  list_entity＋run_window(guard=True)，該家不再問 KEYWORD；梯子全空才 run(KEYWORD)（175a 對 JavBus／DMM 是空操作）。
- seed 規則（CD-175a-4 I-S3）：第一個發動的 provider 一律拿得到 callback（同今天 first_dispatched）；之後的 provider
  只有「尚未真的送出 seed（slot == -1 被轉送）且 fallback_streaming」才拿得到，否則 None（避免後備改變最終順序）。
- relay 自己不送 status 事件（唯一例外：宣告實體能力的 provider 的實體梯子，見 _entity_ladder）、不補 `_source`、不排序。
- 續頁（CD-175d-8）：回覆非空時把 token（cursor.py）寫進 meta['cursor']／meta['answered_by']；`offset>0` 時只讀請求帶來的
  cursor——缺／壞／k 與 mode 不符／p 不在鏈上 ⇒ 空、零 provider 呼叫；有效 ⇒ 只問 p，k=entity 直接用 token 內的 refs 與位置取頁，
  不 resolve、不別名展開、不換名。伺服器零答覆記憶（模組層沒有任何可變容器）。
頂層只准 stdlib、core.logger、core.scrapers.errors、core.search_providers.*（BE-PY-08）。
"""

from __future__ import annotations

from typing import NamedTuple

from core.logger import get_logger
from core.scrapers.errors import SourceBlocked
from core.search_providers import actor_names, registry
from core.search_providers import cursor as cursor_codec
from core.search_providers.pipeline import merge_windows, run_window
from core.search_providers.types import EntityRef, Kind, MakerSearchResult, Window

logger = get_logger(__name__)

_ENTITY_KINDS = (Kind.ACTOR, Kind.SERIES, Kind.DIRECTOR, Kind.LABEL)
_MODE_KIND = {"partial": Kind.PARTIAL, "prefix": Kind.CODE}


class _SeedGate:
    """包住呼叫端的 result_callback，只在 slot == -1 真的被轉送之後才記 seeded。"""

    def __init__(self, result_callback):
        self._cb = result_callback
        self.seeded = False
        self.callback = self._forward if result_callback is not None else None

    def _forward(self, slot, payload):
        self._cb(slot, payload)
        if slot == -1:
            self.seeded = True


def _streams_as_fallback(provider) -> bool:
    """後備（非第一個發動者）能否拿 callback：只有「串流順序＝最終順序」的 provider（fallback_streaming）。"""
    return bool(getattr(provider, "fallback_streaming", False))


_MAX_REFS = 4  # 一次搜尋最多取幾個實體代號（CD-175d-3）
_MAX_SWAP_NAMES = 3  # 換名候選最多取幾個（CD-175d-6）


class _LadderHit(NamedTuple):
    """實體梯子的命中結果：cards 為空時 refs／positions 一律是空 list（該家回答了「沒有」）。"""

    cards: list[dict]
    provider_id: str
    refs: list[EntityRef]
    positions: list[int]  # 與 refs 等長：該 ref 累計消耗位置，或 -1（耗盡）


def _no_cards(provider) -> _LadderHit:
    return _LadderHit([], provider.id, [], [])


def _is_all_kana(q: str) -> bool:
    """全假名（平假名／片假名含「ー」「・」、半形片假名含半形中點「･」U+FF65；空白略過，至少 1 個非空白字元）⇒ 不換名。"""
    chars = [ch for ch in q if not ch.isspace()]
    return bool(chars) and all("\u3040" <= ch <= "\u30ff" or "\uff65" <= ch <= "\uff9f" for ch in chars)


class _ActorNames:
    """女優名稱組（CD-175d-2、-6）：建構零 I/O；別名組惰性讀、整次搜尋只讀一次；換名結果整次搜尋只算一次。

    groups(provider) 依優先序逐組產生名稱組（list[str]）；呼叫端取第一個產生 ref 的組。"""

    def __init__(self, q: str, chain):
        self._q = q
        self._chain = chain  # providers_for 的未過濾結果
        self._aliases = None
        self._base = None
        self._cands = None  # None＝尚未問過換名者；失敗記為 []

    @property
    def q(self) -> str:
        return self._q

    def base(self) -> list[str]:
        if self._base is None:
            if self._aliases is None:
                self._aliases = actor_names.load_alias_groups()  # 模組屬性呼叫，測試 patch 才攔得到
            self._base = actor_names.expand_actor_names(self._q, self._aliases)
        return self._base

    def groups(self, provider):
        swap_first = actor_names.needs_swap_first(self._q)
        if swap_first:
            yield from self._swap_groups(provider)
        yield self.base()
        if not swap_first:
            yield from self._swap_groups(provider)

    def _swapper(self, asked):
        for p in self._chain:
            if p.id != asked.id and callable(getattr(p, "alt_names", None)):
                return p
        return None

    def _candidates(self, swapper) -> list[str]:
        if self._cands is None:
            tried = self.base()
            try:
                found = swapper.alt_names(Kind.ACTOR, self._q)
                self._cands = actor_names.swap_candidates(found, tried, _MAX_SWAP_NAMES)
            except Exception as swap_err:
                logger.warning("actor name swap failed: %s (%s)", swapper.id, type(swap_err).__name__)
                self._cands = []
        return self._cands

    def _swap_groups(self, asked):
        if _is_all_kana(self._q):
            return
        swapper = self._swapper(asked)
        if swapper is None:
            return
        for cand in self._candidates(swapper):
            yield actor_names.expand_actor_names(cand, self._aliases)


def _single_ref(provider, kind: Kind, name: str) -> list[EntityRef]:
    ref = provider.resolve(kind, name)
    return [ref] if ref is not None else []


def _resolve_refs(provider, kind: Kind, names: list[str]) -> list[EntityRef]:
    """一組名字 → 實體參照（去重保序，上限 _MAX_REFS；湊滿後不再問後面的名字）。"""
    resolve_all = getattr(provider, "resolve_all", None)
    refs: list[EntityRef] = []
    seen: set = set()
    for name in names:
        found = resolve_all(kind, name) if callable(resolve_all) else _single_ref(provider, kind, name)
        for ref in found:
            key = (ref.kind, ref.id)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
        if len(refs) >= _MAX_REFS:
            break
    return refs[:_MAX_REFS]


def _actor_refs(provider, names: _ActorNames) -> list[EntityRef]:
    """依名稱組優先序，第一個產生 ≥1 個 ref 的組勝出，後面的組不再問（I-X3）。"""
    hit: list[EntityRef] = []
    for group in names.groups(provider):
        hit = _resolve_refs(provider, Kind.ACTOR, group)
        if hit:
            break
    return hit


def _kind_refs(provider, kind: Kind, names: _ActorNames) -> list[EntityRef]:
    if kind is Kind.ACTOR:
        return _actor_refs(provider, names)
    return _resolve_refs(provider, kind, [names.q])  # SERIES／DIRECTOR／LABEL 不展開別名、不換名


def _answer_window(provider, refs, w: Window, cb, status_callback) -> _LadderHit:
    """refs（≥1 個）→ 一個視窗的卡片。單 ref 與 175c 同一行呼叫（不經 merge_windows）；多 ref 歸併後逐部以 origin 補詳情。"""
    if len(refs) == 1:
        page = provider.list_entity(refs[0], w)
        items = page.items
        positions = [w.offset + len(page.items) if page.has_next else -1]
    else:
        merged = merge_windows(provider, refs, [0] * len(refs), w.limit)
        items, positions = merged.items, merged.new_positions
    res = run_window(provider, items, refs[0], result_callback=cb, guard=True)
    if not res.cards:
        return _no_cards(provider)
    if status_callback is not None:
        status_callback("done", f"found:{len(res.cards)}")
    return _LadderHit(res.cards, provider.id, list(refs), positions)


def _entity_ladder(provider, names: _ActorNames, w: Window, cb, status_callback=None) -> _LadderHit | None:
    """None＝梯子沒有任何 ref 命中（呼叫端改問 KEYWORD）；_LadderHit＝命中了（cards 可為空；該家不再問 KEYWORD）。

    可觀測：只有宣告了實體能力的 provider 才送 status（第一次進入實體 kind 前 searching、有卡時 done）；
    不宣告實體能力者（JavBus／DMM）梯子是空操作、零事件。"""
    announced = False
    for kind in _ENTITY_KINDS:
        if kind not in provider.capabilities:
            continue
        if not announced and status_callback is not None:
            status_callback(provider.id, "searching")
        announced = True
        try:
            refs = _kind_refs(provider, kind, names)
            if refs:
                return _answer_window(provider, refs, w, cb, status_callback)
        except Exception as err:
            logger.warning(
                "entity ladder failed: %s/%s (%s%s)",
                provider.id, kind.value, type(err).__name__, "/blocked" if isinstance(err, SourceBlocked) else "",
            )
            return _no_cards(provider)
    return None


def _run_keyword(provider, mode, q, w, status_callback, cb, discovery_only) -> list[dict]:
    kind = Kind.KEYWORD if mode == "actress" else _MODE_KIND[mode]
    return provider.run(
        kind, q, w, status_callback=status_callback, result_callback=cb, discovery_only=discovery_only
    )


def _ask(provider, mode, q, w, status_callback, cb, discovery_only, names=None) -> _LadderHit:
    """一家 provider 的回答。梯子命中的 refs／positions 會原樣帶出（供寫 token）；KEYWORD／前綴／局部的 refs 為空。"""
    if mode == "actress" and not discovery_only:
        hit = _entity_ladder(provider, names, w, cb, status_callback)
        if hit is not None:
            return hit
    cards = _run_keyword(provider, mode, q, w, status_callback, cb, discovery_only)
    return _LadderHit(cards, provider.id, [], [])


# ---------------------------------------------------------------- 續頁 token（CD-175d-8）
def _token_of(hit: _LadderHit) -> str:
    if hit.refs:
        refs = tuple((ref.kind.value, ref.id, pos) for ref, pos in zip(hit.refs, hit.positions, strict=True))
        return cursor_codec.encode(cursor_codec.Token(hit.provider_id, cursor_codec.KIND_ENTITY, refs))
    return cursor_codec.encode(cursor_codec.Token(hit.provider_id, cursor_codec.KIND_KEYWORD))


def _publish(meta, provider_id: str, cards, token: str) -> None:
    """非空回覆才寫 meta；空回覆不寫（否則載入更多會被釘在沒回答過的那一家）。"""
    if meta is None or not cards:
        return
    meta["cursor"] = token
    meta["answered_by"] = provider_id


def _allowed_token_kinds(mode: str) -> tuple[str, ...]:
    """k 與呼叫 mode 不符 ⇒ 無效（Q1）：prefix／partial 只收 keyword；actress 收 entity｜keyword。"""
    if mode == "actress":
        return (cursor_codec.KIND_ENTITY, cursor_codec.KIND_KEYWORD)
    return (cursor_codec.KIND_KEYWORD,)


def _decode_pin(mode, cursor):
    token = cursor_codec.decode(cursor)
    return token if token is not None and token.k in _allowed_token_kinds(mode) else None


def _continue_entity(provider, pin, w: Window, cb, status_callback) -> _LadderHit:
    """k=entity 的續頁：refs 與位置全來自 token（不用 w.offset），不 resolve、不別名展開、不換名。"""
    refs = [EntityRef(Kind(kind), rid, "") for kind, rid, _ in pin.refs]
    positions = [pos for _, _, pos in pin.refs]
    if all(pos < 0 for pos in positions):
        return _no_cards(provider)
    if len(refs) == 1:
        page = provider.list_entity(refs[0], Window(positions[0], w.limit))
        items = page.items
        new_positions = [positions[0] + len(items) if page.has_next else -1]
    else:
        merged = merge_windows(provider, refs, positions, w.limit)
        items, new_positions = merged.items, merged.new_positions
    res = run_window(provider, items, refs[0], result_callback=cb, guard=True)
    if not res.cards:
        return _no_cards(provider)
    if status_callback is not None:
        status_callback("done", f"found:{len(res.cards)}")
    return _LadderHit(res.cards, provider.id, refs, new_positions)


def _continue_search(pin, mode, q, w, providers, status_callback, result_callback, discovery_only, meta) -> list[dict]:
    """offset>0 且 token 有效：鏈過濾成 [p]；p 不在鏈上、或被釘的那一家例外 ⇒ []（沒有更多，絕不換家）。"""
    provider = next((p for p in providers if p.id == pin.p), None)
    if provider is None:
        return []
    cb = _SeedGate(result_callback).callback
    try:
        if pin.k == cursor_codec.KIND_ENTITY:
            hit = _continue_entity(provider, pin, w, cb, status_callback)
        else:
            cards = _run_keyword(provider, mode, q, w, status_callback, cb, discovery_only)
            hit = _LadderHit(cards, provider.id, [], [])
    except Exception as exc:
        logger.warning(
            "relay: pinned %s failed on load-more (%s%s)",
            provider.id, type(exc).__name__, "/blocked" if isinstance(exc, SourceBlocked) else "",
        )
        return []
    _publish(meta, hit.provider_id, hit.cards, _token_of(hit))
    return hit.cards


def search_by_intent(mode, q, w, *, status_callback=None, result_callback=None, discovery_only=False,
                     cursor=None, meta=None) -> list[dict]:
    """mode ∈ partial／prefix／actress；其他 ⇒ ValueError。cursor／meta 見模組說明（僅 offset>0 才讀 cursor）。"""
    if mode == "actress":
        kinds = {Kind.KEYWORD, *_ENTITY_KINDS}
    elif mode in _MODE_KIND:
        kinds = {_MODE_KIND[mode]}
    else:
        raise ValueError(f"unknown search mode: {mode!r}")
    pin = _decode_pin(mode, cursor) if w.offset > 0 else None
    if w.offset > 0 and pin is None:
        return []
    providers = registry.providers_for(kinds, discovery_only=discovery_only)
    if pin is not None:
        return _continue_search(pin, mode, q, w, providers, status_callback, result_callback, discovery_only, meta)
    chain_ids = [p.id for p in providers]
    names = _ActorNames(q, providers) if mode == "actress" else None
    gate = _SeedGate(result_callback)
    for index, provider in enumerate(providers):
        provider_id = provider.id
        if not callable(getattr(provider, "run", None)):
            raise TypeError(f"provider {provider_id!r} has no run()")
        cb = None if gate.seeded or (index and not _streams_as_fallback(provider)) else gate.callback
        try:
            hit = _ask(provider, mode, q, w, status_callback, cb, discovery_only, names)
        except Exception as exc:
            logger.warning(
                "relay: %s failed (%s%s), trying next of %s",
                provider_id, type(exc).__name__, "/blocked" if isinstance(exc, SourceBlocked) else "", chain_ids,
            )
            continue
        _publish(meta, provider_id, hit.cards, _token_of(hit))
        if hit.cards:
            return hit.cards
    return []


def _merge_maker_codes(codes: list[str | None]) -> str:
    """全鏈都換不出答案時的彙整：有連不上 ⇒ unreachable；全部 no_sample ⇒ no_sample；其餘 not_found。"""
    if "maker_unreachable" in codes:
        return "maker_unreachable"
    if codes and all(c == "maker_no_sample" for c in codes):
        return "maker_no_sample"
    return "maker_not_found"


def _maker_token(provider_id: str) -> str:
    return cursor_codec.encode(cursor_codec.Token(provider_id, cursor_codec.KIND_MAKER))


def _maker_pin(cursor):
    token = cursor_codec.decode(cursor)
    return token if token is not None and token.k == cursor_codec.KIND_MAKER else None


def _maker_chain(offset, cursor):
    """回 (providers 或 None, 終點結果或 None)。offset>0 ⇒ 只認有效 maker token：缺／壞／p 不在鏈上 ⇒ maker_unreachable。"""
    providers = registry.providers_for({Kind.MAKER})
    if offset > 0:
        pin = _maker_pin(cursor)
        providers = [p for p in providers if pin is not None and p.id == pin.p]
        if not providers:
            return None, MakerSearchResult([], False, "maker_unreachable")
    if not providers:
        return None, MakerSearchResult([], False, "maker_not_found")
    return providers, None


def search_maker(maker_key, label, spellings, offset, *, limit=None, titles, today, status_callback=None,
                 result_callback=None, db_path=None, cursor=None, meta=None) -> MakerSearchResult:
    """片商最新作品的接力（175b-T8b）：鏈＝providers_for({MAKER})，逐家 run_maker。

    I-M2（同一份清單不得中途換家）：非空 ⇒ 回；maker_empty ⇒ 終點；offset>0 的 unreachable／例外 ⇒ 終點；
    其餘（not_found／no_sample／offset==0 的 unreachable／例外）記下並換下一家。
    offset>0 只問 cursor（k=maker）裡的那一家（CD-175d-8）；cursor 缺／壞 ⇒ maker_unreachable、零呼叫。
    非空回覆寫 meta['cursor']／meta['answered_by']。"""
    providers, ended = _maker_chain(offset, cursor)
    if ended is not None:
        return ended
    chain_ids = [p.id for p in providers]
    gate = _SeedGate(result_callback)
    codes: list[str | None] = []
    for index, provider in enumerate(providers):
        run_maker = getattr(provider, "run_maker", None)
        if not callable(run_maker):
            raise TypeError(f"provider {provider.id!r} has no run_maker()")
        cb = None if gate.seeded or (index and not _streams_as_fallback(provider)) else gate.callback
        try:
            res = run_maker(maker_key, label, spellings, offset, limit=limit, titles=titles, today=today,
                            status_callback=status_callback, result_callback=cb, db_path=db_path)
        except Exception as exc:
            logger.warning(
                "relay maker: %s failed (%s%s), chain %s",
                provider.id, type(exc).__name__, "/blocked" if isinstance(exc, SourceBlocked) else "", chain_ids,
            )
            if offset > 0:
                return MakerSearchResult([], False, "maker_unreachable")
            codes.append("maker_unreachable")
            continue
        _publish(meta, provider.id, res.results, _maker_token(provider.id))
        if res.results:
            return res
        if res.error_code is None:
            return res  # 認得、也列出了（詳情全缺）：同 maker_empty，終點（173 行為不變）
        if res.error_code == "maker_empty":
            return res
        if res.error_code == "maker_unreachable" and offset > 0:
            return res
        codes.append(res.error_code)
    return MakerSearchResult([], False, _merge_maker_codes(codes))


class MakerCapsulePolicy(NamedTuple):
    enabled: bool  # 鏈上有任何一家做得到片商 ⇒ 顯示膠囊列
    use_not_found_map: bool  # 只有鏈恰為 javbus 時，才信 maker_javbus_map 的「沒有這家」去藏膠囊


def maker_capsule_policy() -> MakerCapsulePolicy:
    """膠囊列的後端狀態（175b-T8c，CD-175b-3）。"""
    ids = [p.id for p in registry.providers_for({Kind.MAKER})]
    enabled = bool(ids)
    use_not_found_map = ids == ["javbus"]
    return MakerCapsulePolicy(enabled, use_not_found_map)
