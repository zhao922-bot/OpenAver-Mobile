"""
POST /api/access/verify — PIN 閘門唯一登入入口（TASK-114a-T3）。

三段順序（CD-114a-13）：鎖外固定延遲 → `await asyncio.to_thread(attempt_pin, ...)`
（T1 的原子入口，鎖內完成「決策 → 比對 → 更新重試狀態 → 成功則建票 + 更新
cache」）→ 鎖外只寫 `Set-Cookie`。成功與失敗（含任何畸形輸入）回應逐位元組
相同（除 `Set-Cookie`）——重用 T2 的 `render_access_gate_page`，不新增第二
份 HTML。

延遲不可搬到 `attempt_pin` 之後：這是 CD-114a-13 v4 修正的那個 P1——若順序
寫成「驗證 → 延遲 → 建票」，一個帶舊 PIN 的請求可能在主人於本機改 PIN
（觸發 `revoke_all()`）之後才建票，讓已撤銷的認證設定底下仍多出一張存活的
票（`core/access_auth.py` 模組 docstring 的 `CD-114a-13-inv` 記的就是這條）。
T1 已把「比對」與「建票」焊在同一個鎖內同時完成，不存在「先驗證、稍後才建
票」的中間態——T3 唯一要守住的規則是：延遲確實排在呼叫 `attempt_pin` 之
前執行。

本端點不判斷來源位址（middleware 的 `_AUTH_ALLOWLIST` 已放行它對任何來源
永遠可達），也不揭露進 `GET /api/capabilities`（憑證驗證端點本身不該被
包裝成 AI 可呼叫的 tool——見 TASK-114a-T3 card 的 DoD 段落）。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictBool, StrictStr

from core.access_auth import attempt_pin, get_auth_settings, load_snapshot, set_auth, snapshot, verify_ticket
from core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/access", tags=["access"])

_VERIFY_DELAY_SECONDS = 1.0
_COOKIE_MAX_AGE_SECONDS = 10 * 365 * 24 * 3600  # 十年（CD-114a-6）


class AccessSettingsRequest(BaseModel):
    enabled: StrictBool
    pin: StrictStr


async def _fixed_delay() -> None:
    """鎖外固定延遲接縫——handler 唯一呼叫的延遲入口，模組層級可 patch。

    測試 patch 使用端 `web.routers.access._fixed_delay`，不是 `asyncio.sleep`
    本身（BE-TEST-01：patch 使用端不 patch 定義端）。禁止阻塞式同步睡眠
    （CD-114a-10）——`asyncio.sleep` 不阻塞 event loop，同步睡眠會。
    """
    await asyncio.sleep(_VERIFY_DELAY_SECONDS)


@router.post("/verify")
async def verify_pin(request: Request) -> Response:
    """PIN 閘門唯一登入入口。

    永遠回 200 + 偽裝頁本體（`render_access_gate_page`）；僅在 `attempt_pin`
    回傳有效票時額外帶 `Set-Cookie`。任何畸形輸入（非 JSON、非物件、缺欄
    位、型別錯誤）都不得讓這一層拋例外——一個 500 會洩漏「這裡真的在跑程
    式碼」，交給 `attempt_pin` 內部的 `_is_valid_pin_format` 統一當一次
    PIN 錯誤處理、計入重試限制。

    `attempt_pin` 本身的例外（DB 寫入失敗，例如磁碟滿、檔案被鎖）另外用
    獨立的 try/except 接住，**不與 body 解析併成同一段**——語意不同：畸形
    輸入是「一次失敗的嘗試，要計入重試限制」；DB 爆掉是「這次嘗試根本沒
    發生」，fail-closed 回偽裝頁、不帶 cookie，同 T2 冷載失敗的處理方式，
    不讓例外冒穿成 Starlette 500（那本身就是另一種洩漏——未認證訪客看到
    的東西必須永遠長一樣）。
    """
    from web.app import render_access_gate_page  # 延遲 import，避免循環依賴（同 motion_lab.py:25 先例）

    await _fixed_delay()

    # 只有「真 JSON 請求」才算一次嘗試（Codex PR#129 round-2 P3，defense-in-depth）。
    #
    # 跨站的簡單表單 POST 只送得出 text/plain、urlencoded 或 multipart——送不出
    # application/json 而不觸發 CORS preflight，而本服務沒有任何 CORS 標頭，
    # preflight 一定被瀏覽器擋掉。不擋的話：使用者只要在同一台裝置上開到一個惡意
    # 網頁，那頁就能對這支（allowlist、免認證可達的）端點自動連打五次，把**全域**
    # 重試鎖打開，讓全家人一分鐘內都進不去，重複觸發可拉到一小時——攻擊者完全不需
    # 要知道密碼，也讀不到任何回應。這在 spec §1.2 的威脅模型之外（惡意網頁不是
    # 對手），所以是 P3，但擋它只要一次字串比對。
    #
    # 回應形狀與「密碼錯誤」完全相同（同一張偽裝頁、無 cookie），且刻意擺在
    # _fixed_delay() **之後**——否則提前回傳會讓這條路徑比正常嘗試快一截，
    # 反而開一條可跨站量測的時間側通道。
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        return render_access_gate_page(request)

    try:
        data = await request.json()
    except Exception:
        data = None
    candidate = data.get("pin") if isinstance(data, dict) else None

    try:
        token = await asyncio.to_thread(attempt_pin, candidate)
    except Exception:
        # fail-closed：DB 寫入失敗（磁碟滿／檔案被鎖）視同這次嘗試沒發生，
        # 不得讓例外冒泡成 500——那會讓未認證訪客看到跟平常不一樣的東西。
        logger.exception("verify_pin: attempt_pin failed, fail-closed to masked page")
        token = None

    response = render_access_gate_page(request)
    if token is not None:
        response.set_cookie(
            "sid",
            token,
            max_age=_COOKIE_MAX_AGE_SECONDS,
            path="/",
            httponly=True,
            samesite="lax",
        )
    return response


@router.get("/settings")
def get_access_settings(raw_request: Request) -> dict:
    """R4 之外：GET 無 loopback 限制，任何能打到這支端點的呼叫者
    （loopback，或已通過 PIN 驗證的遠端持票人）都能看到 enabled 狀態；
    PIN 真值只給 loopback 或已登入（cookie／bearer）的呼叫者；
    reveal 由 web 層判斷，core 層不判斷位址或票證。"""
    # 延遲 import，避免與 web.app → access router 的循環依賴（同 verify_pin /
    # motion_lab.py 先例）。PLC2701 仍以 noqa 標明跨模組私有名依賴理由。
    from web.app import _bearer_token, _is_loopback_host  # noqa: PLC2701 — 與 middleware 共用判斷

    _client = raw_request.client
    _client_host = _client.host if _client else None
    snap = snapshot() or load_snapshot()
    authed = verify_ticket(raw_request.cookies.get("sid")) or verify_ticket(_bearer_token(raw_request))
    reveal = _is_loopback_host(_client_host) or authed
    can_edit = not snap.enabled or _is_loopback_host(_client_host) or authed
    result = get_auth_settings(reveal)
    return {
        "success": True,
        "enabled": result["enabled"],
        "pin": result["pin"],
        "pin_revealed": reveal,
        "can_edit": can_edit,
    }


@router.put("/settings")
def update_access_settings(request: AccessSettingsRequest, raw_request: Request):
    # 延遲 import，避免與 web.app → access router 的循環依賴（同 get_access_settings）。
    from web.app import _bearer_token, _is_loopback_host  # noqa: PLC2701 — 與 middleware 共用判斷

    _client = raw_request.client
    _client_host = _client.host if _client else None
    snap = snapshot() or load_snapshot()
    authed = verify_ticket(raw_request.cookies.get("sid")) or verify_ticket(_bearer_token(raw_request))
    if _is_loopback_host(_client_host):
        pass
    elif authed:
        pass
    elif not snap.enabled:
        pass
    else:
        return JSONResponse(status_code=403, content={
            "success": False, "reason": "need_login",
            "error": "請先登入",
        })
    try:
        set_auth(request.enabled, request.pin)
    except ValueError:
        return JSONResponse(status_code=400, content={
            "success": False, "reason": "invalid_pin",
            "error": "密碼必須是 4 位英文或數字",
        })
    if request.enabled:
        # 首次設定與已登入者改密碼共用：set_auth 撤銷了所有票，重發一張讓呼叫端不被登出。
        token = attempt_pin(request.pin)
        response = JSONResponse({"success": True})
        if token is not None:
            response.set_cookie(
                "sid",
                token,
                max_age=_COOKIE_MAX_AGE_SECONDS,
                path="/",
                httponly=True,
                samesite="lax",
            )
        return response
    return {"success": True}
