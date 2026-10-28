"""本機（loopback）判斷的全庫唯一所有者（TASK-114a-T6-a／168d-T1）。

`web.app._is_loopback_host` 與 `core.proxy_policy` 都委派這裡；任何新的
allow-direction「client／host 是不是本機」判斷不得手寫，一律呼叫 `is_loopback_host()`
（`tests/unit/test_loopback_delegation_guard.py` 守著）。
"""
import ipaddress


def is_loopback_host(host):
    """判斷 `host` 是否為本機（`/api/trigger-update` 三層護欄 CD-110b-5 用）。

    與 `_LOOPBACK_HOSTS`（web/app.py）的關係：`_LOOPBACK_HOSTS` 是 middleware 的**短路
    名單**，只收兩個精確字面值，回答的是「要不要跳過讀 config」——這裡**不動它**。
    本函式回答的是另一個問題：「這個 client／Origin host 是不是本機」，用
    `ipaddress.is_loopback` 額外涵蓋 `127.0.0.0/8` 其餘位址、IPv4-mapped IPv6
    （`::ffff:127.0.0.1`），並加收 `localhost` 字面（純位址比對會漏它）。兩者
    判斷的集合都只可能來自本機，所以本函式是 `_LOOPBACK_HOSTS` 的**嚴格超集**，
    超集不製造安全缺口；反過來若本函式比 `_LOOPBACK_HOSTS` 更窄，才會出現
    「middleware 放行但端點誤拒」的桌面自鎖風險。
    """
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    # IPv4-mapped IPv6（`::ffff:127.0.0.1`）必須先解回 IPv4 才判得對：
    # 實測 `ipaddress.ip_address('::ffff:127.0.0.1').is_loopback` 是 **False**
    # （`is_loopback` 只認 `::1`）。dual-stack socket 上的 uvicorn 有機會把本機
    # 連線的 peer 回報成這個形式，不解就會把桌面版自己鎖在門外——那是 plan-110b
    # §4 風險表列為「最嚴重」的那一條。解回 IPv4 後 `127.0.0.1` 正常判 True。
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return addr.is_loopback
