"""atomic_write.py — 共用、無狀態的原子寫檔 primitive（CD-113d-1/2）。

收斂 core.config / core.thumbnail_cache / web.routers.actress 三處各自手寫的
「同目錄 mkstemp → 拿到開著的 fh → 關 fd → os.replace → 例外時清 temp」骨架
（core.actress_photo 的第四處在 T2 一併接進來——它原本用固定可預測的 temp 檔名，
換成本 primitive 的 mkstemp 才順帶修掉同一位女優並發下載互撞暫存檔，CD-113d-4）。
只做這一件事：鎖策略、成功後清舊 sibling 檔、失敗語意（拋例外 vs 回 False）、
dest 在哪，全部留給呼叫端決定（spec §2.5 / D-8）。

本模組是全庫**唯一**准許出現裸 `os.replace` / `tempfile.mkstemp` 的地方
（`tests/unit/test_atomic_write_boundary_guard.py` 機械守住這條邊界）。因此
「檔案原子落地」這一類的原語都住這裡，目前兩支，**用途不同不可混用**：

- `atomic_write()`：**產生新內容**（mkstemp → 呼叫端寫 → replace 落地），
  失敗時 `dest` 逐位元組不變。
- `atomic_move()`（144-T0 / CD-144-15）：**搬一個已經在磁碟上的檔案**，
  沒有暫存檔、沒有內容產生，成功後 `src` 消失，失敗時什麼都不清理。
"""
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator, Optional, Union
import errno
import os          # 🔴 必須是屬性存取形式：禁 `from os import replace`
import shutil
import tempfile    # 🔴 同上：禁 `from tempfile import mkstemp`


@contextmanager
def atomic_write(
    dest: Union[Path, str],
    *,
    mode: str = "wb",
    encoding: Optional[str] = None,
    suffix: str = ".tmp",
    fsync: bool = False,
) -> Iterator[IO]:
    """Yield an open file handle whose content lands at `dest` atomically.

    Mechanics (the part every caller must share): create the temp file in
    `dest.parent` via `tempfile.mkstemp` — same directory means same volume,
    without which `os.replace` fails with `EXDEV` — hand the caller the open
    handle, close the fd, then `os.replace(tmp, dest)`. The fd is closed
    *before* the replace because Windows refuses to replace a file that is
    still open (`BE-ENV-01`).

    Two failure paths, both handled identically: the caller's block raises
    while writing, or `os.replace` itself fails (on Windows it is not
    guaranteed to succeed — antivirus and the thumbnail cache hold handles).
    Either way the temp file is removed, `dest` is left **byte-for-byte
    untouched**, and the original exception propagates unchanged.

    `dest.parent` must already exist — creating it is the caller's business,
    because whether a missing directory is an error or a routine first write
    differs per caller. `suffix` reaches `mkstemp` verbatim; pass the real
    extension when something downstream sniffs the temp name.

    ``fsync=True`` flushes and ``os.fsync``s the temp fd before replace
    (opt-in for data-root marker durability; default stays off for NAS/HDD
    batch callers — TASK-153b-T6 / O1).

    Deliberately NOT here (spec-113 §2.5 — each stays with the caller):
    locking, deleting old sibling files after a successful write, turning
    failures into a `False` return, and deciding where `dest` is.
    """
    dest = Path(dest)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=suffix)
    tmp = Path(tmp)
    try:
        # 🔴 os.fdopen 自己包一層 try（Codex PR review P2）：mkstemp 回傳的 fd
        # 在這一行之前完全由這個函式擁有；若呼叫端傳了無效的 mode/encoding 組合
        # （例如 mode="wb" 又給 encoding="utf-8"），fdopen 會在「接管 fd」之前
        # 就拋 ValueError——此時外層的 `with` 從未成立，fd 不會被 with 關閉。
        # 若讓這個例外直接落進下面的 except，只會 unlink(tmp)，fd 仍開著：
        # 重複觸發會耗盡 fd（Windows 上開著的 handle 還會擋 unlink，temp 檔留底）。
        # 明確在這裡關閉 fd、原樣重拋，讓 fd 的生命週期不論哪條路徑都有人收尾。
        try:
            f = os.fdopen(fd, mode, encoding=encoding)
        except BaseException:
            os.close(fd)
            raise
        with f:
            yield f
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        # fd 已由上面的 with 關閉 → 安全 replace（Windows file-lock 前提）
        os.replace(tmp, dest)
    except BaseException:
        # 路徑 1：區塊內使用者程式碼拋例外；路徑 2：os.replace 自己拋例外
        # （BE-ENV-01：Windows 防毒/縮圖快取會擋，不是必成功）。
        # 兩條路徑都落在這個 except，行為一致：清 temp、不動 dest、原例外往上傳。
        #
        # 🔴 必須是 BaseException 而非 Exception（Stage 2 pre-merge review P2）：
        # KeyboardInterrupt / SystemExit 不是 Exception 的子類。這不是形式主義——
        # T2 為了改用本 primitive，把 actress_photo.download_actress_photo 原本的
        # `finally: tmp.unlink()`（finally 對 BaseException 照樣執行）整段刪掉；
        # 只收 Exception 就等於在 Ctrl-C 這條路上比修改前更差，而且 mkstemp 的隨機
        # 檔名不被該函式的 `{safe_name}.*` 清舊檔 glob 命中 → 沒有任何程式碼會再碰它。
        # 裸 `raise` 原樣重拋，呼叫端的例外／回 False 語意完全不變。
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def create_staging_file(
    dest_dir: Union[Path, str],
    *,
    suffix: str = ".tmp",
) -> Path:
    """在 `dest_dir` 內用 mkstemp 建一個空暫存檔，回傳其 Path。

    呼叫端擁有這個路徑：成功時用 `atomic_move(tmp, dest)` 落地，失敗時自行
    `unlink`。fd 在回傳前已關閉。本函式存在的理由是把裸 `tempfile.mkstemp`
    收斂在本模組（邊界守衛要求），讓需要「先寫／驗證再 replace」的呼叫端
    （例如 data_layout 的 config copy）不必自己碰 mkstemp。
    """
    fd, tmp = tempfile.mkstemp(dir=str(dest_dir), suffix=suffix)
    os.close(fd)
    return Path(tmp)


def atomic_move(src: Union[Path, str], dest: Union[Path, str]) -> None:
    """把 `src` 這個**已經存在的檔案**搬到 `dest`，覆蓋 `dest` 的既有內容。

    與同檔的 `atomic_write()` 是**兩種不同的東西，不要混用**：
    `atomic_write()` 是「產生新內容」——mkstemp 一個暫存檔、讓呼叫端寫進去、
    再 `os.replace` 落地，失敗時 `dest` 逐位元組不變。
    `atomic_move()` 是「搬一個已經在磁碟上的檔案」——沒有暫存檔、沒有內容產生，
    而且**成功後 `src` 會消失**。兩者的失敗保證也不同，見下方「失敗語意」。

    `os.replace` 而不是 `shutil.move`（CD-144-15，真 Windows 實測）：
    `shutil.move` 內部第一步是 `os.rename`，而 Windows 的 `os.rename` 對**已存在**
    的目標拋 `FileExistsError`（POSIX 是靜默覆蓋）→ 落進它的 `except OSError` →
    改走 `copy2` **整份讀寫位元組**再 `unlink`。呼叫端若事先用 `O_CREAT|O_EXCL`
    佔下了目標檔名（`core.organizer.organize_file` 正是如此），目標就「永遠已存在」，
    於是 Windows 上每一次搬移都從瞬間 rename 退化成完整複製——60MB 實測 21.6ms
    vs 0.4ms（54 倍），15GB 的影片在慢碟或 SMB 上是數秒到數分鐘的實體複製。
    `os.replace` 在兩個平台都是「靜默覆蓋、原子、只動 metadata」，正是這裡要的語意。

    **跨檔案系統**（`EXDEV`）：`os.replace` 只在同一個檔案系統內成立。真的跨檔案
    系統時（來源夾底下正好有掛載點）退回 `copy2` ＋ `unlink`——那就是 `shutil.move`
    本來會做的事，行為與本函式出現之前完全相同，不是新增的風險。
    `EXDEV` 以外的 `OSError` **原樣往外拋，絕不吞掉**（磁碟已滿、真正的權限問題
    不該被偽裝成一次「跨檔案系統搬移」，那會多做一次無謂的整份複製並掩蓋真因）。

    **失敗語意**：本函式**不清理任何東西**，例外原樣往上傳。呼叫端若已經佔下
    `dest`，那個佔位檔就留在原地——這是刻意的：在跨程序情境下沒有辦法安全判斷
    「這個殘留是不是我剛佔的位子」，自動清掉再重試會製造一個更隱蔽的競態
    （把另一個程序**已經搬完的**成品當成孤兒刪掉）。留下的 0 byte 佔位檔使用者
    看得見、刪得掉，遠比一次看不見、救不回的覆蓋好（CD-144-15、spec-144 §5）。
    `BE-ENV-01`（Windows 防毒／檔案總管持有 handle 讓 `os.replace` 拋
    `PermissionError`）走的也是這條路：原樣往外拋，由呼叫端的既有 except 處理。
    """
    try:
        os.replace(src, dest)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        shutil.copy2(src, dest)
        os.unlink(src)
