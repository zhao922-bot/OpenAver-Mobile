"""Provider 註冊表（顯式表，非掃描）。

175a-T7 註冊 javbus／dmm；175b-T4b 註冊 javdb。值是無參數工廠，惰性建構（import 時不 new session、
也不 import 任何 provider 模組；BE-PY-08：頂層不得 import core.scraper／core.database）。

- new_provider：每次搜尋新建（不快取）——使用者改了代理／語言後下一次搜尋就生效。
- providers_for：順序∩註冊∩設定頁開關（三家一視同仁）∩能力。順序與開關在呼叫當下經 core.scraper 讀
  （既有測試 patch 的就是 core.scraper.get_all_source_ids_ordered／is_source_enabled）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from core.search_providers.types import Kind, Provider

def _make_javbus() -> Provider:
    from core.search_providers.javbus import JavBusProvider

    return JavBusProvider()


def _make_dmm() -> Provider:
    from core.search_providers.dmm import DMMProvider

    return DMMProvider()


def _make_javdb() -> Provider:
    from core.search_providers.javdb import JavDBProvider

    return JavDBProvider()


_REGISTRY: dict[str, Callable[[], Provider]] = {
    "javbus": _make_javbus,
    "dmm": _make_dmm,
    "javdb": _make_javdb,
}


def registered_ids() -> frozenset[str]:
    return frozenset(_REGISTRY)


def new_provider(provider_id: str) -> Provider:
    """呼叫工廠建一個新的 provider（不快取）。未註冊 ⇒ KeyError。"""
    return _REGISTRY[provider_id]()


def providers_for(kinds: Iterable[Kind], *, discovery_only: bool = False) -> list[Provider]:
    """回傳本次搜尋要依序詢問的新 provider 實例。

    鏈＝設定頁順序 ∩ 已註冊 ∩ is_source_enabled（三家都看設定頁開關）∩ 宣告了 kinds 任一能力
    （discovery_only 再 ∩ supports_discovery）。
    """
    import core.scraper as scraper

    wanted = frozenset(kinds)
    ordered = scraper.get_all_source_ids_ordered()
    chain: list[Provider] = []
    for pid in ordered:
        if pid not in _REGISTRY:
            continue
        if not scraper.is_source_enabled(pid):
            continue
        provider = new_provider(pid)
        if not (provider.capabilities & wanted):
            continue
        if discovery_only and not provider.supports_discovery:
            continue
        chain.append(provider)
    return chain
