"""
web/routers/cf.py — TASK-70-T6
================================
CF transport 控制端點（與 scraper router 語意正交）。

端點：
  GET  /api/cf/status?key=javlibrary  — poll loop 用：transport 是否就緒
  POST /api/cf/abandon?key=javlibrary — 前端逾時/取消；後端 emit 通知
"""
from fastapi import APIRouter, Request

from core import cf_handoff
from core.cf_transport import get_cf_transport, CfTransportUnavailable
from core.logger import get_logger
from web.routers.notifications import emit_notification
from web.shell_identity import cf_availability_here

logger = get_logger(__name__)

router = APIRouter(prefix="/api/cf", tags=["cf"])


@router.get("/status")
def cf_status(key: str = "javlibrary") -> dict:
    """poll loop 用：transport 是否就緒。key 通用，不寫死 javlibrary。"""
    t = get_cf_transport()
    if t is None:
        return {"ready": False, "unavailable": True}
    try:
        return {"ready": bool(t.is_ready(key))}
    except CfTransportUnavailable:
        logger.warning("cf_status: transport dead (window closed) key=%s", key)
        return {"ready": False, "unavailable": True}
    except Exception:
        logger.exception("cf_status: is_ready(key=%s) 失敗", key)
        return {"ready": False}


@router.get("/availability")
def cf_availability(request: Request) -> dict:
    """灰化的 CF 膠囊按下時，頁面重查「這台殼現在可不可用」（168d-fix-T2 CD-4）。

    純記憶體讀取，與 SSR 同一份規則；**不得**呼叫 is_ready／submit（那會派工給殼並最多等 10 秒）。
    """
    return cf_availability_here(request)


@router.post("/abandon")
def cf_abandon(key: str = "javlibrary") -> dict:
    """前端 poll 逾時/取消時呼叫；後端代 emit_notification（前端無直接通道）。"""
    # 依 key 分流；兩站共用來源中立文案 key（zh_TW 已去掉站名）。未知 key 仍用同一則，
    # 避免落到「javlibrary 專屬」語意。
    _title_by_key = {
        "javlibrary": "notif.jl_cf_timeout",
        "fc-javten": "notif.jl_cf_timeout",
    }
    # 168d CD-168d-12：這台殼剛失聯（無殼／殼過期／領不到工作）→ 告訴使用者重開殼，
    # 不是「自己沒點驗證」。key 參數是站台代號；殼身分是 current_key——兩個東西。
    lost = cf_handoff.consume_failure_here(cf_handoff.current_key.get()) == "shell_lost"
    emit_notification(
        "warn",
        "notif.cf_shell_lost" if lost else _title_by_key.get(key, "notif.jl_cf_timeout"),
        task_type="cf_abandon",
    )
    return {"ok": True}
