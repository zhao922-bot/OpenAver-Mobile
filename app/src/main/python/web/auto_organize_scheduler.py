"""排程 loop：12 小時整理一次「我的最愛」資料夾（feature/144-auto-organize T5）。

web 層背景服務——呼叫 core.auto_organize.run_one_round()（T3，純同步，整輪丟
asyncio.to_thread）、core.auto_organize_state 的 cron 互斥（T4a）、
web.routers.notifications.emit_notification()（通知輸出）。

拆兩支（CD-144-6／plan T5 段落 2026-09-04 主 session 修正）：
  - enter_and_start(trigger) -> dict：同步、O(1)、立刻回應，run-now 端點呼叫它。
  - _run_round_body(trigger) -> None：真正跑一輪，不回傳任何東西，結果全走通知。

🚫 POST /auto-organize/run-now 絕不可 await 整輪跑完——一輪是分鐘等級，掛著
   會讓反向代理／瀏覽器逾時砍線，見 enter_and_start() docstring。
🚫 enter_cron() 必須是最先執行的一步，資料夾解析／探測／run_one_round 整段
   都要在 exit_cron() 的保護範圍內（見 _round_guard() / _prepare_and_run()）。
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time

from core import auto_organize_state
from core.auto_organize import run_one_round
from core.config import AUTO_ORGANIZE_INTERVAL_HOURS, load_config
from core.favorite_scan import resolve_favorite_folder
from core.logger import get_logger
from core.wishlist_reconcile import format_wishlist_removed_message
from web.routers.notifications import emit_notification

logger = get_logger(__name__)

_LOOP_POLL_INTERVAL_S = 300  # 5 分鐘醒來看一次是否到期（spec §F6）
_FOLDER_EXISTS_TIMEOUT_S = 5.0  # 照 core/source_reachability.py _EXISTS_WAIT_S 樣板

_next_due_at: float = 0.0  # 0.0＝尚未排過；重啟後從零計時（D9，不補跑）
_round_task = None  # asyncio.create_task 回傳值強引用槽位（event loop 只持 weak ref）


def reset_due_time() -> None:
    """單一入口：_run_round_body() 正常結尾與 POST /auto-organize/config 端點共用。

    避免各自算一次到期時間而漂移（T5 設計決策 5）。
    """
    global _next_due_at
    _next_due_at = time.time() + AUTO_ORGANIZE_INTERVAL_HOURS * 3600


def _is_due() -> bool:
    global _next_due_at
    if _next_due_at == 0.0:
        reset_due_time()  # loop 第一次醒來：從現在起算一個間隔，不補跑
        return False
    return time.time() >= _next_due_at


async def auto_organize_loop() -> None:
    """lifespan 掛的常駐背景 task；每 5 分鐘判一次「到期了沒」。"""
    while True:
        await asyncio.sleep(_LOOP_POLL_INTERVAL_S)
        # 🔴 try 的範圍必須從**讀 config 那一行就開始**，不是只包住那一輪：
        # `while True` 外沒有這一層的話，一次未預期的例外就會讓整條排程**靜默停止**
        # ——App 還開著、開關還亮著、側欄什麼都不會說，使用者要好幾天後才會發現
        # 「它怎麼都沒動」，而且只有重啟 App 才救得回來。
        # 讀 config 那一行同樣要包住（PR review 指出第一版只包了那一輪、漏掉這裡）：
        # `config.json` 被外部程序改壞、或磁碟一時 I/O 錯誤，都會從那一行拋出來，
        # 那跟「一輪炸了」是同一類洞，只是觸發點不同。
        entered = False
        try:
            config = await asyncio.to_thread(load_config)
            enabled = config.get("search", {}).get("auto_organize", {}).get("enabled", False)
            if not enabled or not _is_due():
                continue
            if auto_organize_state.enter_cron("schedule"):
                entered = True
                # `_round_guard()` 已經在 finally 釋放 running，這裡只負責讓 loop 活下去。
                await _run_round_body("schedule")
        except Exception:
            logger.exception("[auto_organize] 這一輪失敗，排程繼續")
            # 🔴 **只有真的開跑過那一輪才重置到期時間**（PR review 指出）：
            # 「一輪炸了」重置是對的——否則每 5 分鐘重試一次，把一次失敗放大成連續轟炸。
            # 但「連設定都讀不到」是另一回事：那個到期窗**根本沒被消耗**，
            # 下一次 5 分鐘輪詢本來就會重試；在這裡重置等於因為一次磁碟抖動
            # 就把排程整整推走 12 小時，恢復之後還要再等半天才會動。
            if entered:
                emit_notification(
                    "error", "notif.auto_organize_failed", task_type="auto_organize",
                )
                reset_due_time()


def enter_and_start(trigger: str) -> dict:
    """同步、O(1)、立刻返回 —— run-now 端點呼叫它。

    絕不可讓呼叫端 await 整輪跑完：一輪是分鐘等級，① 反向代理／瀏覽器常在
    60 秒切斷連線；② 區網模式從別台裝置連進來更容易被中間層砍掉；③ 面板
    spinner 會轉好幾分鐘，使用者關掉分頁就再也拿不到回應（輪照跑，畫面卻
    什麼都沒說）。enter_cron() 是純記憶體 O(1)，先同步取、再把輪丟進背景
    task，同時拿到「立刻可信的『在跑了沒』答案」與「不阻塞的請求」。
    """
    global _round_task
    if not auto_organize_state.enter_cron(trigger):
        return {"success": False, "reason": "already_running"}
    _round_task = asyncio.create_task(_run_round_body_guarded(trigger))
    return {"success": True, "reason": None}


async def _run_round_body_guarded(trigger: str) -> None:
    """v0.15.13 P2-2：`enter_and_start()` 專用的 detached-task wrapper。

    這支端點已經先回應 `{"success": True}`（前端顯示「已開始，完成後側欄會有
    通知」），呼叫端不 await 這個 task。`_run_round_body()` 本身沒有 try/except
    ——它同時被 `auto_organize_loop()` 呼叫，那條路徑已經在 loop 那層包了自己
    的 try（見上方註解），若在 `_run_round_body()` 內部加 try 會讓 loop 那層的
    行為也跟著變（例外會在這裡被吃掉，loop 就看不到、`reset_due_time()` 的
    節流邏輯會跟著錯）。所以錯誤處理只包在這一層、只用於 run-now 這條路徑。

    沒有這一層的話：資料夾解析／檔案 I/O／DB／`run_one_round()` 任一處拋例外，
    這個 detached task 沒人 await，例外會變成 asyncio 的
    "Task exception was never retrieved" 日誌噪音，而使用者側——已經被告知
    「已開始」——側欄永遠不會出現任何東西，只能一直等下去。
    """
    try:
        await _run_round_body(trigger)
    except Exception:
        logger.exception("[auto_organize] run-now 背景執行例外，本輪未完成")
        emit_notification(
            "error", "notif.auto_organize_failed", task_type="auto_organize",
        )


@contextlib.asynccontextmanager
async def _round_guard():
    """exit_cron() 的唯一釋放點；涵蓋 _prepare_and_run() 整段（DoD-5）。"""
    try:
        yield
    finally:
        auto_organize_state.exit_cron()


async def _prepare_and_run(trigger: str) -> dict:
    """資料夾解析 ＋ 探測 ＋ run_one_round 整段——_round_guard() 保護的主體。

    回傳 run_one_round() 的 schema；資料夾連不到時回傳哨兵形狀
    ``{"folder_unreachable": True, "folder": <path>}``（不含其餘 run_one_round 鍵）。
    """
    config = await asyncio.to_thread(load_config)
    # 拿到執行權之後**再問一次開關**（Codex PR#181 六審 P3）。
    # 沒有這一句的話有一個很窄的空檔會漏掉：loop 在 :69 讀到「開著」，使用者接著撥掉開關，
    # 此時 `request_abort()` 看到「沒有任何一輪在跑」⇒ 什麼都不做；然後 loop 進場，
    # `enter_cron()` 又把中止旗標清成 0 ⇒ **畫面說已經關了，整輪照樣搬檔改名跑完。**
    # 這是「撥掉開關＝叫停」那個承諾剩下的最後一個縫，修法選最低風險的那一種：
    # 不加旗標、不加鎖，只是拿這份**已經讀進來的**設定多問一句（race 修法階梯的第一階）。
    # 只對 schedule 生效——「立刻執行一次」在開關關著時本來就該按得動。
    if trigger == "schedule" and not config.get("search", {}).get(
        "auto_organize", {}
    ).get("enabled", False):
        return {"scheduling_disabled": True}
    configured = (config.get('search', {}).get('favorite_folder') or '').strip()
    if not configured:
        return {"folder_not_configured": True}
    folder = await asyncio.to_thread(resolve_favorite_folder, config)
    try:
        # 🔴 `asyncio.wait_for` 是承重的，不是裝飾：`asyncio.to_thread` 自己**永遠不會**
        # 拋 TimeoutError，少了 wait_for 這一層，NAS 睡著時 `os.path.exists()` 會卡在
        # 那條 worker thread 上幾十秒到幾分鐘，整個排程 task 跟著掛住——spec §F6 明文
        # 要避免的就是這件事。逾時＝當作「連不到」，走下面那則黃色通知。
        exists = await asyncio.wait_for(
            asyncio.to_thread(os.path.exists, folder),
            timeout=_FOLDER_EXISTS_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        exists = False
    if not exists:
        return {"folder_unreachable": True, "folder": folder}
    result = await asyncio.to_thread(
        run_one_round, config,
        should_abort=auto_organize_state.should_abort,
        on_file_start=auto_organize_state.set_current_number,
    )
    result.setdefault("folder", folder)  # readonly 分支的通知要用（run_one_round 不回這個鍵）
    return result


async def _run_round_body(trigger: str) -> None:
    """真正跑一輪；不回傳任何東西，所有結果一律走 emit_notification()。"""
    async with _round_guard():
        result = await _prepare_and_run(trigger)

    if result.get("scheduling_disabled"):
        # 使用者自己關掉的，安靜收工——這裡發通知只會變成噪音。
        # 到期時間不重置：重新打開開關時 `update_auto_organize_config()` 會重置。
        return

    if result.get("folder_not_configured"):
        emit_notification(
            "warn", "notif.auto_organize_folder_not_set", task_type="auto_organize",
        )
        reset_due_time()
        return

    if result.get("folder_unreachable"):
        emit_notification(
            "warn", "notif.auto_organize_folder_unreachable",
            message=result["folder"], task_type="auto_organize",
        )
        reset_due_time()
        return

    if result.get("readonly"):
        emit_notification(
            "warn", "notif.auto_organize_readonly",
            message=result.get("folder", ""), task_type="auto_organize",
        )
        reset_due_time()
        return

    _emit_round_summary(result)

    if result.get("wishlist_reconcile_failed"):
        # 摘要已經發出去了（整理結果是真的），這則只說「對帳那一步失敗」。
        # 沿用另外三個呼叫點的同一個 key（scanner/scraper/wishlist）。
        emit_notification(
            "warn", "notif.wishlist_reconcile_failed", task_type="wishlist_reconcile",
        )

    wishlist_removed = result.get("wishlist_removed") or []
    if wishlist_removed:
        emit_notification(
            "info", "notif.wishlist_auto_removed",
            message=format_wishlist_removed_message(wishlist_removed),
            task_type="wishlist_reconcile",
        )

    reset_due_time()


def _emit_round_summary(result: dict) -> None:
    """事件數門檻（CD-144-3）與中止分支（spec §F5）都在這裡判斷。

    事件數 = len(added) + len(cover_missing) + len(failed) + newly_recorded。
    aborted_after 非 None 且 > 0 → 發「處理 N 部後因手動操作中止」，已完成
    那幾部的帳列在同一則裡；aborted_after == 0 或 None → 不進這個分支，
    退回事件數門檻（會因為 added/failed/cover_missing 皆空而判 0，不發）。
    """
    aborted_after = result.get("aborted_after")
    if aborted_after is not None and aborted_after > 0:
        message = _format_summary_message(result, aborted_after=aborted_after)
        emit_notification("warn", "notif.auto_organize_aborted", message=message,
                           task_type="auto_organize")
        return

    event_count = (
        len(result["added"]) + len(result["cover_missing"]) + len(result["failed"])
        + result["newly_recorded"]
    )
    if event_count == 0:
        return

    level = "warn" if (result["failed"] or result["cover_missing"]) else "success"
    message = _format_summary_message(result)
    emit_notification(level, "notif.auto_organize_summary", message=message,
                       task_type="auto_organize")


def _format_summary_message(result: dict, *, aborted_after: int | None = None) -> str:
    """組裝摘要文案（spec §F5：新增/失敗/缺封面/略過各自 5 部內列出番號，其餘寫「及其他 N 部」）。

    title_key（notif.auto_organize_summary／notif.auto_organize_aborted）已經是
    「自動整理」的靜態標籤，這裡的 message 只放動態內容，不重複前綴（比照
    notif.wishlist_auto_removed 現有的 title/message 分工）。
    """
    added = result["added"]
    cover_missing = result["cover_missing"]
    failed = result["failed"]
    duplicate_numbers = [item["number"] for item in result["skipped"]["duplicate"]]

    if aborted_after:
        header = f"處理 {aborted_after} 部後因手動操作中止"
    else:
        parts = [f"新增 {len(added)} 部"]
        if failed:
            parts.append(f"失敗 {len(failed)} 部")
        if cover_missing:
            parts.append(f"缺封面 {len(cover_missing)} 部")
        if duplicate_numbers:
            parts.append(f"略過 {len(duplicate_numbers)} 部")
        header = "、".join(parts)

    def _fmt(numbers: list) -> str:
        shown = numbers[:5]
        rest = len(numbers) - len(shown)
        text = "、".join(shown)
        if rest > 0:
            text += f"，及其他 {rest} 部"
        return text

    detail = []
    if added:
        detail.append(f"新增：{_fmt(added)}")
    if failed:
        detail.append(f"失敗：{_fmt(failed)}")
    if cover_missing:
        detail.append(f"缺封面：{_fmt(cover_missing)}")
    if duplicate_numbers:
        detail.append(f"目標已存在：{_fmt(duplicate_numbers)}")

    message = header
    if detail:
        message += "（" + "；".join(detail) + "）"

    logger.info("[auto_organize] %s", message)
    return message
