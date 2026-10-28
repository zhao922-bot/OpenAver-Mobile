"""自訂來源的請求目標守衛：只放行公網位址（fail-closed）。判準在 core.public_target。"""

from core.custom_source.errors import BlockedTarget
from core.public_target import check_public

GUARD_REASONS = frozenset({"bad_scheme", "bad_url", "bad_host", "bad_authority", "non_ascii_host", "non_public", "unresolvable"})

_MESSAGES = {
    ("bad_url", None): "網址格式不正確",
    ("bad_scheme", None): "只允許 http／https",
    ("bad_host", "missing_host"): "網址沒有主機名稱",
    ("non_ascii_host", None): "主機名稱含非 ASCII 字元，請改用 punycode（xn--）",
    ("bad_authority", None): "網址的主機段格式不正確",
    ("bad_host", "blocked_name"): "不允許的主機名稱",
    ("non_public", None): "目標不是公網位址",
    ("unresolvable", None): "無法解析目標主機",
}


def check(url):
    """通過回 None；違規拋 BlockedTarget。訊息為固定文字，不含 URL 任何部分。"""
    v = check_public(url)
    if v is not None:
        raise BlockedTarget(v.reason, _MESSAGES[(v.reason, v.detail)])
    return None
