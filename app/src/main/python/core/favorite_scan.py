"""core/favorite_scan.py — 我的最愛資料夾列檔邏輯（spec-144 T3）。

從 web/routers/search.py 的 get_favorite_files()（733-747 平台分支、762-786
列檔迴圈）與 _filter_files_sync()（880-885 NFO 快取）搬出的純函式，供 web 層
與 core/auto_organize.py 共用——core 不可 import web，方向只能是「web 呼叫
core」（BE-LINT-01）。兩個既有呼叫點都改呼叫這裡，回應形狀與行為零改動。
"""
import os
from pathlib import Path

from core.path_utils import expand_env_vars, get_environment
from core.video_extensions import ZERO_SIZE_EXTENSIONS, get_video_extensions


def resolve_favorite_folder(config: dict) -> str:
    """算出最愛資料夾的實際路徑（純計算，對應原 733-747）。"""
    original_folder = config.get('search', {}).get('favorite_folder', '').strip()
    if not original_folder:
        if os.environ.get("OPENAVER_STANDALONE") != "1":
            return ""
        if get_environment() == 'wsl':
            return expand_env_vars('%USERPROFILE%\\Downloads')
        return str(Path.home() / "Downloads")
    return expand_env_vars(original_folder)


def list_favorite_video_files(folder: str, config: dict) -> list:
    """列出資料夾第一層符合副檔名白名單與 min_size_mb 的檔案路徑（對應原 762-786）。

    PermissionError 原樣往外拋，不在此吞掉——呼叫端（get_favorite_files()）
    要拿它組出既有的「無權限讀取資料夾」錯誤回應，吞掉會讓那個錯誤訊息消失。
    """
    folder_path = Path(folder)
    video_exts = get_video_extensions(config)
    min_size_mb = config.get("gallery", {}).get("min_size_mb", 0)
    min_size_bytes = min_size_mb * 1024 * 1024

    files = []
    for f in folder_path.iterdir():
        # 單一檔案問不到就跳過它，不讓整輪陣亡。無人值守時代價不對等：
        # 這一輪整個作廢，排程要再等 12 小時（run-now 則變成一則「定時整理失敗」）。
        #
        # 這個 try 實際接住的是兩種情況——**不是**「檔案不見了」（那個 is_file() 自己就吞了）：
        #   ① `Path.is_file()` 只吞「可忽略」的 OSError（ENOENT/ENOTDIR/ELOOP…，見 CPython
        #      pathlib._ignore_error）；**PermissionError／EIO／ESTALE 會被它原樣往外拋**
        #      ——Windows 上被下載器獨佔的檔、NAS 那條連線正好斷掉的檔都走這條。
        #   ② is_file() 與下面量大小那次 stat() 之間的窗口：過了第一關才被下載器搬走。
        #
        # 資料夾層級的 PermissionError 不受影響——那是 iterdir() 自己在 for 那一行拋的，
        # 落不進這個 try，呼叫端照樣組得出「無權限讀取資料夾」的錯誤回應（有反向鎖守著）。
        try:
            if not f.is_file():
                continue
            if f.suffix.lower() not in video_exts:
                continue
            suffix = f.suffix.lower()
            if min_size_bytes > 0 and suffix not in ZERO_SIZE_EXTENSIONS and f.stat().st_size < min_size_bytes:
                continue
        except OSError:
            continue
        files.append(str(f))
    return files


def detect_nfo(paths: list, *, strict: bool = False) -> dict:
    """對每個路徑判斷旁邊有沒有同 stem 的 .nfo（對應原 880-885 nfo_stem_cache）。

    paths 是呼叫端已經正規化好的路徑字串；回傳 dict 用同一個字串當 key，
    呼叫端逐一 `nfo_map[path]` 取值。

    `strict`：**列不到目錄時要不要把「不知道」說出來**（Codex PR #181 二審 P0）。

    - `strict=False`（預設，手動清單那條路用）：列不到就當成「這夾沒有 .nfo」。
      這是 `main` 就有的行為，逐字搬過來未改——手動路徑的後果只是清單上少了
      「已有 NFO」的標記，**下一步還要人按下去**，沒有任何東西會自己動。
    - `strict=True`（自動整理那條路用）：列不到就把 `OSError` 往外拋。
      無人值守時「不知道」**不可以**被讀成「沒有 NFO」：那會讓整夾已經刮好的片
      被當成沒刮過重跑一輪，而 `organize_file` 在「不建資料夾 ＋ 檔名已經是正規格式」
      的設定下 `file_path == target_path`，搬移那段整段跳過（`core/organizer.py:1247`）
      ⇒ 原子佔位**根本不會被觸發** ⇒ 直接往下把封面重下一次、把 NFO 整份重寫
      （`:1279` / `:1333`），使用者手動編過的欄位就這樣沒了。
    """
    nfo_stem_cache = {}
    result = {}
    for path_str in paths:
        p = Path(path_str)
        parent = p.parent
        if parent not in nfo_stem_cache:
            try:
                nfo_stem_cache[parent] = {
                    s.stem.lower()
                    for s in parent.iterdir()
                    if s.suffix.lower() == ".nfo" and s.is_file()
                }
            except (OSError, PermissionError):
                if strict:
                    raise
                nfo_stem_cache[parent] = set()
        result[path_str] = p.stem.lower() in nfo_stem_cache[parent]
    return result
