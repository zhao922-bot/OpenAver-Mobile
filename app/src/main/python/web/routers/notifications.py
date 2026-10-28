"""
通知中心後端 buffer — 53b

module-level globals:
  _notifications: deque  最多 50 筆，最新的排前面（appendleft）
  _read_ids: set         已讀 id 集合
  _write_queue: Queue    write-behind 佇列（144-T1）
  _writer_thread: Thread 消費上面那個佇列、把通知寫進 SQLite 的 daemon thread

persistence（144-T1 / CD-144-1）：**記憶體是讀取的真理，DB 只做 write-behind 持久化。**
`emit_notification()` 維持同步、恆為記憶體操作（appendleft ＋ put_nowait），DB 寫入
全部由 writer thread 在背景做；`GET /api/notifications` 完全不碰 DB。這是為了保住
`emit_notification()` 的兩個既有契約——不阻塞 event loop、絕不拋例外——它有 async
上下文的呼叫點（`web/routers/scraper.py` 批次補完的 SSE），而那裡的外層就是 `raise`。

thread safety: 所有 _notifications / _read_ids 讀寫**必須**經 _lock (RLock)
保護。GIL 只保證單次 C-level op atomic，不保護「迭代 + membership check」「len + clear
+ clear」這類多步驟組合，也無法保證 GET handler 跟 emit 拿到一致的 snapshot
（見 plan-53b CD-53B-1）。
"""

from collections import deque
from typing import Optional
import queue
import threading
import uuid
import time

from fastapi import APIRouter

from core.logger import get_logger
from core.database import (
    insert_notification,
    mark_notifications_read,
    clear_all_notifications,
    load_recent_notifications,
)
# 🔴 用模組屬性存取而不是 `from ... import get_db_path`：測試會 monkeypatch
# `core.database.connection.get_db_path`，直接 import 進來的 binding 看不到那個替換。
from core.database import connection as _db_connection

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["notifications"])

_lock = threading.RLock()
_notifications: deque = deque(maxlen=50)
_read_ids: set = set()
_write_queue: queue.Queue = queue.Queue()
_writer_thread: Optional[threading.Thread] = None


def emit_notification(
    level: str,
    title_key: str,
    message: str = "",
    task_type: Optional[str] = None,
    url: Optional[str] = None,
) -> None:
    """後端各處呼叫此函式新增一筆通知。
    設計為極度輕量（只做 deque.appendleft 與 queue.put_nowait），不可拋出例外。
    level: "info" | "success" | "warn" | "error"
    """
    notif = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "level": level,
        "title_key": title_key,
        "message": message,
        "task_type": task_type,
        "url": url,
    }
    with _lock:
        # CD-144-2 的去重只比對**還沒被看過**的那幾筆。
        # 「已讀」＝使用者打開過通知抽屜（base.html 的 toggleDrawer 會打
        # POST /notifications/read 把當下全部標讀）——他已經看過這件事了，
        # 同一件事再發生一次就是**新消息**，不是重複。
        # 只比對記憶體 deque 會讓「定時整理失敗」這種每 12 小時重演一次的狀況
        # 在使用者讀掉第一則之後**永遠不再出聲**：toast 說「已開始」、側欄什麼都沒有、
        # 未讀角標也不亮，使用者以為排程在跑，其實每一輪都在失敗。
        # 這樣改之後「連續相同狀況只發一次」仍然成立——未讀清單裡恆為一則。
        # 去重**只管定時整理自己**。原始動機就只在這裡（每 12 小時重演一次的
        # 「定時整理失敗」不該塞滿抽屜），但這個函式是全站共用的：不收窄的話，
        # 從來沒開過定時整理的人也會受影響——連按兩次「產生影片列表」而中間沒開過
        # 通知抽屜時，第二次的「掃描開始」會被吃掉，使用者以為掃描沒跑
        # （main 上沒有去重，兩則都會出現）。
        if task_type == "auto_organize" and any(
            n["title_key"] == title_key
            and n["message"] == message
            and n["id"] not in _read_ids
            for n in _notifications
        ):
            return
        if len(_notifications) == _notifications.maxlen:
            evicted = _notifications[-1]
            _read_ids.discard(evicted["id"])
        _notifications.appendleft(notif)
        _write_queue.put_nowait({"op": "insert", **notif})
    logger.debug("[notif] emit level=%s title_key=%s", level, title_key)


def _writer_loop(db_path) -> None:
    """背景 thread 迴圈：從 _write_queue 消費操作並持久化到 SQLite。

    `db_path` 在 `start_notification_persistence()` 啟動這條 thread 時就**定死**，
    不在消費的當下才去問 `get_db_path()`。這一條是承重的，不是防禦性寫法：

    「入列」與「真的寫下去」之間隔著不確定的時間，若寫入端在消費的**當下**才解析
    目標，那筆通知會落到「那一刻」的 DB，而不是「產生它時」的 DB。實測後果
    （144-T1 開發期）：測試 A 把 `get_db_path` 導到自己的 tmp 庫並啟動了 writer，
    測試 B 跑起來時 monkeypatch 已還原，writer 醒來就拿真實的 `output/openaver.db`
    去連，被 repo-write 守衛（`RepoWriteGuardViolation`，繼承 `BaseException`）擋下
    ——**thread 就此死亡，佇列從此只增不減，而 GET 只讀記憶體所以表面完全正常**。
    更糟的是那個例外是在別支測試執行到一半時、從非主執行緒、在 `mock.patch` 包住的
    `sqlite3.connect` 裡拋出的，連帶弄壞了 patch 的還原狀態，讓 1329 支不相干的測試
    在 `tmp_path` 上崩掉。

    生產環境路徑是常數，凍結與否行為相同——但「寫哪裡」這件事不該是時間的函數。
    """
    while True:
        item = _write_queue.get()
        if item is None:
            _write_queue.task_done()
            _drain_before_exit(db_path)
            break
        try:
            _apply_write(item, db_path)
        finally:
            _write_queue.task_done()


def _drain_before_exit(db_path) -> None:
    """讀到哨兵之後，**在同一條 thread 上**把佇列剩下的排空再退出。

    ⚠️ 這一段是承重的：writer 是靠哨兵結束的，而放哨兵與 writer 讀到哨兵之間
    仍然有 producer 在跑——run-now 那一輪的 detached task、掃描頁的縮圖預熱
    daemon thread（`web/routers/scanner.py:1535`）、scanner 的 `_work` daemon
    thread（`:283`）。它們在那個空隙 emit 的東西會排在哨兵**後面**。
    沒有這一段的話，那幾筆永遠沒有人消費，跟著 process 一起消失。

    🔴 **收尾一定要在 writer 自己這條 thread 上做，不可以由 shutdown 那一側接手。**
    曾經那樣做過（v0.15.13 Codex 二審的修法），結果是**兩個消費者吃同一個佇列、
    同時寫同一個 DB**：shutdown 那側可能先寫掉後面的 `clear`／`mark_read`，
    writer 卡住的那筆**較早的 insert** 稍後才落地 ⇒ 使用者按過「全部清空」再關 App，
    重開之後那則通知**又出現了**。少寫幾則只是少幾則；順序倒轉是寫出錯的狀態。
    消費者恆為一條 thread，順序倒轉就**結構上不可能**發生，不需要任何旗標或時間互斥。
    """
    while True:
        try:
            item = _write_queue.get_nowait()
        except queue.Empty:
            return
        try:
            if item is not None:  # 殘留的哨兵直接丟掉
                _apply_write(item, db_path)
        finally:
            _write_queue.task_done()


def _apply_write(item: dict, db_path) -> None:
    """把一筆佇列項目落到 DB。writer thread 與 shutdown 的收尾 flush 共用。

    失敗只記 warning：這裡是「盡力持久化」，任何一筆寫不進去都不該影響其他筆，
    更不該讓 shutdown 掛住。
    """
    try:
        op = item.get("op")
        if op == "insert":
            insert_notification(item, db_path=db_path)
        elif op == "mark_read":
            mark_notifications_read(item.get("ids", []), db_path=db_path)
        elif op == "clear":
            clear_all_notifications(db_path=db_path)
    except Exception:
        logger.warning("[notif] writer persistence error", exc_info=True)



def start_notification_persistence() -> None:
    """啟動通知持久化：從 DB 載回最近 50 筆通知，並啟動背景 writer thread。

    **失敗一律不擴散。** 讀不到通知歷史時只記一行 warning、以純記憶體模式運作，
    絕不讓它拖垮 App 啟動——lifespan 裡的鄰居（`backfill_readonly_nfo_mtime`、
    `source_reachability`）都是這個形狀，而「側欄的歷史通知」比那兩者都不重要。
    載不回來就不啟動 writer：讀不到的庫多半也寫不進去。
    """
    global _writer_thread
    with _lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return
        try:
            db_path = _db_connection.get_db_path()
            rows = load_recent_notifications(limit=50, db_path=db_path)
        except Exception:
            logger.warning(
                "[notif] 通知持久化啟動失敗，本次以純記憶體模式運作", exc_info=True
            )
            return
        _notifications.clear()
        _read_ids.clear()
        _notifications.extend(rows)
        for r in rows:
            if r.get("is_read"):
                _read_ids.add(r["id"])

        _writer_thread = threading.Thread(
            target=_writer_loop,
            args=(db_path,),
            name="NotificationWriter",
            daemon=True,
        )
        _writer_thread.start()


def stop_notification_persistence(timeout: float = 2.0) -> None:
    """停掉 writer thread（哨兵 ＋ join）。

    兩個呼叫端：
    - 測試 teardown：「模擬重啟」那類測試會把活著的 thread 指標設成 `None` 再開一條，
      舊的那條變成孤兒、繼續消費同一個 module-level 佇列——兩位 reviewer 都指出過。
    - `web/app.py` 的 lifespan shutdown（v0.15.13 P2-1）：writer thread 是 daemon，
      process 結束時會被直接砍掉而不 drain，佇列裡還沒寫進 DB 的通知會消失
      （關掉 App 之後，最後那幾則通知「不在了」）。shutdown 呼叫時走
      `asyncio.to_thread()` 包住，因為這支函式本身是同步阻塞的 `thread.join()`。
    """
    global _writer_thread
    with _lock:
        thread = _writer_thread
        _writer_thread = None
    if thread is not None and thread.is_alive():
        _write_queue.put_nowait(None)
        thread.join(timeout=timeout)


def _calc_highest_unread_level(items: list, read_ids: set) -> Optional[str]:
    """計算未讀通知中最高嚴重度。"""
    level_order = {"error": 3, "warn": 2, "success": 1, "info": 0}
    highest = None
    highest_score = -1
    for item in items:
        if item["id"] not in read_ids:
            score = level_order.get(item["level"], 0)
            if score > highest_score:
                highest_score = score
                highest = item["level"]
    return highest


@router.get("/notifications")
async def get_notifications():
    """查詢 buffer 所有通知 + 未讀摘要。"""
    with _lock:
        items = list(_notifications)
        read_snapshot = set(_read_ids)
    enriched = [
        {**item, "is_read": item["id"] in read_snapshot}
        for item in items
    ]
    unread_count = sum(1 for item in items if item["id"] not in read_snapshot)
    highest = _calc_highest_unread_level(items, read_snapshot)
    return {
        "items": enriched,
        "unread_count": unread_count,
        "highest_unread_level": highest,
    }


@router.post("/notifications/read")
async def mark_all_read():
    """把目前 buffer 裡所有通知標為已讀。"""
    marked_ids = []
    with _lock:
        for item in _notifications:
            if item["id"] not in _read_ids:
                _read_ids.add(item["id"])
                marked_ids.append(item["id"])
        if marked_ids:
            _write_queue.put_nowait({"op": "mark_read", "ids": marked_ids})
    return {"ok": True, "marked_count": len(marked_ids)}


@router.delete("/notifications")
async def clear_notifications():
    """清空 buffer 所有記錄，同時清空 _read_ids。

    UX 註解：F6 決議——通知是 ephemeral notification buffer cleanup，
    手機通知抽屜般直接清空，不需確認。前端 UI 不彈 confirm。
    """
    with _lock:
        count = len(_notifications)
        _notifications.clear()
        _read_ids.clear()
        _write_queue.put_nowait({"op": "clear"})
    return {"ok": True, "cleared_count": count}
