"""core/multipart_group.py — 分集影片分組判斷的單一真理來源（feature/122，CD-122-2）。

依賴 `core.organizer`（`MULTIPART_TOKENS` / `_detect_multipart_token` /
`_strip_part_token`，**只 import，不重寫**——那三個原語是檔名組裝用途，本模組反過來
用它們判斷「哪些 DB 列屬於同一組」，兩件事故意不合併，見 CD-122-2）＋ `os.path`
（Zone 1 字串運算，同 `core/cover_layout.py` 先例：呼叫端已把 file:// URI 轉成 fs
path 才傳進來，不在此模組碰 URI，不違反 `path_utils.py` 的跨 Zone 轉換禁止清單）。

**唯一的例外是檔尾的 `resolve_group()`**：它是給 router 用的 DB-facing 組裝層
（repo 查詢 ＋ 資料夾 URI 前綴），URI 運算全部走 `core.path_utils` 的既有函式、
一行都不手搓。分組演算法本體（`group_rows` 以上）維持 Zone 1 純字串。

**單一真理來源（CD-122-2）**：任何需要判斷「這些 DB 列是不是同一組分集片」的地方
（列表序列化／單筆 refresh／刪除／播放頁接續），一律呼叫本模組的 `group_rows()` /
`resolve_group_for_path()`，不得各自重新推導比對邏輯。

**CD-122-10（Codex plan review 2026-08-20，P0）**：一組成立的條件是「成員數 >= 2
**且**每一個成員都帶 part token」；不成立時，bucket 內每一列各自單飛成單檔組
（`part_tokens=[]`）。反例：`ABC-123.mp4`（無 token）＋ `ABC-123-cd2.mp4` 必須回
兩個單檔組，不可把無 token 的那個當 part-1 併入。

**CD-122-13（Codex PR review 2026-08-20，P0）**：成組條件再加「**每個 part number
必須唯一**」。`ABC-123-cd1.mp4` ＋ `ABC-123-cd1.mkv`（同一片留兩種容器）剝 token 後
stem 相同、兩者都帶 token，只有這條擋得住——那是「同一片的兩個版本」不是「一片的兩段」，
spec §7 明文不做多版本合併。比對用 part **number** 而非 token 字面（`cd1` 與 `pt1`
都是第 1 段，同樣衝突）。

**CD-122-3**：分組比對鍵只在 `normalize_stem_key()` 內做「去除所有空白字元 +
lower()」；回傳給前端的顯示值（`part_tokens` 的 token 字面）不額外正規化。
"""

from dataclasses import dataclass
from typing import Callable, Generic, List, Optional, Tuple, TypeVar
import os
import re

from core.organizer import _detect_multipart_token, _strip_part_token
from core.path_utils import to_file_uri, uri_to_fs_path, uri_to_local_fs_path

T = TypeVar('T')  # 呼叫端的 row 型別（Video ORM 物件、或任意帶 path 的物件）


def normalize_stem_key(stem: str) -> str:
    """CD-122-3：剝 token 後的 stem 正規化比對鍵（去空白 + lower）。"""
    stripped = _strip_part_token(stem)
    return re.sub(r'\s+', '', stripped).lower()


def group_key(fs_path: str) -> Tuple[str, str]:
    """(資料夾, 正規化 stem)。

    fs_path 必須是 Zone 1 原生路徑（呼叫端已用 path_utils 轉換過），本函式內只做
    檔名尾端字串運算，不碰 file:// URI。
    """
    folder = os.path.dirname(fs_path)
    stem = os.path.splitext(os.path.basename(fs_path))[0]
    return (folder, normalize_stem_key(stem))


def part_info(fs_path: str) -> Tuple[Optional[str], int]:
    """(token 字面, 段號) 一次解析。

    `part_token()` / `part_number()` 是它的兩個單欄位包裝，保留給只要一半的呼叫端；
    `group_rows()` 走這一支，因為它兩個都要，而 `_detect_multipart_token()` 是
    regex 掃描、且那個迴圈跑遍整個片庫（/simplify 效率條目）。
    """
    match = _detect_multipart_token(os.path.basename(fs_path))
    if match:
        return match[0], match[1]
    return None, 1  # 單檔片（無 token）視為 part 1


def part_number(fs_path: str) -> int:
    """單檔片（無 token）視為 part 1。"""
    return part_info(fs_path)[1]


def part_token(fs_path: str) -> Optional[str]:
    """回傳原始 token 字面（已是小寫，如 'cd1'），無 token 回 None。"""
    return part_info(fs_path)[0]


@dataclass
class VideoGroup(Generic[T]):
    """一組分集片（或單檔片）。

    members: 依 part_number 升冪排序，長度 >= 1；members[0] 恆為 part-1
             （單檔片時就是它自己）。
    part_tokens: 對應 members 的 token 字面（如 ['cd1', 'cd2']）；單檔片為 []。
    """
    members: List[T]
    part_tokens: List[str]


def group_rows(rows: List[T], fs_path_of: Callable[[T], str]) -> List['VideoGroup[T]']:
    """把 rows 依「同資料夾 + 剝 token 後正規化 stem 相同」分桶，再依 CD-122-10 判定
    每個桶是否成組。

    Args:
        rows: 任意物件列表（Video ORM 或 dict-like），只要求可用 fs_path_of(row)
            取得 Zone 1 fs path。
        fs_path_of: Callable[[T], str] — 呼叫端負責把 row 換成 Zone 1 fs path
            （showcase.py 用 `uri_to_local_fs_path(v.path, path_mappings)`）。

    Returns:
        groups，組內 members 依 part_number 升冪排列；組間順序＝第一次見到該 key
        的順序（呼叫端若要整體排序，序列化前再排 videos 陣列，不影響分組正確性）。
    """
    # bucket 內存 (row, fs_path)：`fs_path_of` 是呼叫端的 URI→FS 轉換
    # （`uri_to_local_fs_path`，含 unquote ＋ normalize ＋ path_mapping 反查），
    # 而這個迴圈跑遍整個片庫（`GET /api/showcase/videos` 每次載入都跑一遍 2000+ 列），
    # 所以每列只轉一次、後面全部重用（/simplify 效率條目）。
    buckets: dict = {}
    order: List[Tuple[str, str]] = []
    for row in rows:
        fs_path = fs_path_of(row)
        key = group_key(fs_path)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append((row, fs_path))

    groups: List[VideoGroup] = []
    for key in order:
        # parsed: [(row, token, number)]，每列的 token/段號也只解析一次（同上）。
        parsed = [(r, *part_info(fs_path)) for r, fs_path in buckets[key]]
        members = [r for r, _, _ in parsed]
        tokens = [t for _, t, _ in parsed]

        # CD-122-10（P0）：一組成立的條件是「成員 >= 2 且每一個成員都帶 part token」。
        # 不成立 → bucket 內每一列各自單飛成單檔組。少了這條，
        # `ABC-123.mp4`（無 token）＋ `ABC-123-cd2.mp4` 會被誤併，無 token 那個
        # 被當 part-1、part_tokens 出現 None，且刪除會一次移除兩列。
        #
        # CD-122-13（Codex PR review P0，2026-08-20）：**再加「每個 part number 必須唯一」**。
        # 少了這條，`ABC-123-cd1.mp4` ＋ `ABC-123-cd1.mkv`（同一片留兩種容器，收藏者常見
        # 的「原檔 ＋ 相容版」擺法）會被誤併成「同一片的兩段」：剝 token 後 stem 相同、
        # 兩者都帶 token，現行條件擋不住。後果是另一個容器版本從瀏覽頁消失、播放頁把同一段
        # 連播兩次，而刪除那張卡會一次移除兩列 DB——`user_tags` 還能靠 NFO 重掃回來，
        # 但**手動封面裁切座標（auto_focal / crop_mode）只存在 DB、不進 NFO**，
        # 使用者得重新框一次。
        # 比對用 part **number** 而非 token 字面：`cd1` 與 `pt1` 字面不同但都是第 1 段，
        # 同樣是衝突（這條順手把 Codex 沒點名的同款漏洞一起堵掉）。
        part_numbers = [n for _, _, n in parsed]
        if (len(members) < 2
                or not all(tokens)
                or len(set(part_numbers)) != len(part_numbers)):
            for row in members:
                groups.append(VideoGroup(members=[row], part_tokens=[]))
            continue

        order_pairs = sorted(parsed, key=lambda p: p[2])
        groups.append(VideoGroup(
            members=[m for m, _, _ in order_pairs],
            part_tokens=[t for _, t, _ in order_pairs],
        ))
    return groups


def resolve_group_for_path(
    target_uri: str,
    candidates: List[T],
    fs_path_of: Callable[[T], str],
    uri_of: Callable[[T], str],
) -> Optional['VideoGroup[T]']:
    """在 candidates 裡找出包含 target_uri 的組；找不到回 None（不拋例外）。

    **兩個取值函式的分工是定死的，不得合併成一個**：
      - `fs_path_of(row)` → Zone 1 原生 fs 路徑，**只**餵給 `group_key()`（分組運算）
      - `uri_of(row)`     → DB key 的 file:/// URI，**只**用來與 target_uri 比對身分

    Why 分兩個：分組必須在 fs path 上做（`group_key` 是檔名尾端字串運算，且
    `path_utils.py` 禁止在別處手搓 URI）；而呼叫端握有的、前端送上來的是 DB key
    URI。用同一個函式兼差會逼出「到底該傳哪一種」的二義性。
    """
    for group in group_rows(candidates, fs_path_of):
        if any(uri_of(m) == target_uri for m in group.members):
            return group
    return None


def folder_uri_prefix(folder_fs: str, path_mappings: dict = None) -> str:
    r"""資料夾 fs 路徑 → 用來做 `LIKE prefix%` 的 file:/// 前綴（保證正好一個結尾斜線）。

    **`+ "/"` 不可以無條件加**（grok Stage 1 review P3，2026-08-20）：磁碟機根目錄的
    `to_file_uri()` 本身就以斜線結尾（`D:\` → `file:///D:/`），再加一個會變成
    `file:///D://`，`get_by_folder_uri_prefix()` 的 LIKE 從此一列都對不上。
    後果是「片庫直接放在 D:\ 根目錄」的使用者，瀏覽頁仍然合併成一張卡（列表走的是
    另一條查法，比對 FS dirname），但**刪除只移除第 1 段**——重整後那張卡又冒出來；
    播放頁也不會接續下一段。同一形狀在 Unix 根目錄（`/`）成立。
    """
    uri = to_file_uri(folder_fs, path_mappings)
    return uri if uri.endswith("/") else uri + "/"


def resolve_groups_bulk(
    repo,
    target_uris: List[str],
    path_mappings: dict,
) -> dict:
    """批次版 `resolve_group()`：**同一個資料夾只查一次 DB、只分組一次**。

    Why：`resolve_group()` 每呼叫一次就 `get_by_folder_uri_prefix()` ＋ 對整個資料夾
    重跑 `group_rows()`。批次端點若逐路徑呼叫它，**扁平擺法**（整個片庫平鋪在同一層）
    會把「全資料夾分組」重跑 N 次。用 owner 真實片庫實測（單一資料夾 1966 部）：
    47.6 ms/次（查詢 27.4 ＋ 分組 24.4），500 路徑 ≈ 24 秒、300 路徑 ≈ 14 秒——
    使用者叫 AI「把某片商的片全部加精選」就會等十幾秒且沒有任何進度回饋。
    （同一形狀的前一半——迴圈內重複 `load_config()`——已於 TASK-123-T2 §D 修掉。）

    **語意與逐一呼叫 `resolve_group(repo, uri, path_mappings)` 完全相同**：同樣的資料夾
    前綴、同樣的 `group_rows()`、同樣以 DB-key URI 做身分比對；差別只在把重複工作攤掉。
    因此**不改變任何共享語意**，也不需要呼叫端配合。

    Args:
        repo: `VideoRepository`（只用到 `get_by_folder_uri_prefix()`，duck-typed）。
        target_uris: 要反解的 DB-key URI 清單（可含重複）。
        path_mappings: gallery 設定的跨機器路徑映射。

    Returns:
        `{target_uri: VideoGroup | None}`。重複輸入只解析一次；找不到組的 key 對到
        `None`（與 `resolve_group()` 一致，不拋例外）。**不吞 DB 例外**（同 CD-122-6）。
    """
    out: dict = {}
    folder_index_cache: dict = {}   # folder prefix -> {member DB-key URI: VideoGroup}
    for target_uri in target_uris:
        if target_uri in out:
            continue
        folder_fs = os.path.dirname(uri_to_fs_path(target_uri))  # uri-no-reverse: 只取 dirname 拼前綴，隨即 to_file_uri 回 DB namespace，不做磁碟 I/O（同 resolve_group）
        prefix = folder_uri_prefix(folder_fs, path_mappings)
        index = folder_index_cache.get(prefix)
        if index is None:
            index = {}
            rows = repo.get_by_folder_uri_prefix(prefix)
            for group in group_rows(rows, lambda r: uri_to_local_fs_path(r.path, path_mappings)):
                for member in group.members:
                    index[member.path] = group
            folder_index_cache[prefix] = index
        out[target_uri] = index.get(target_uri)
    return out


def resolve_group(
    repo,
    target_uri: str,
    path_mappings: dict,
    folder_source_uri: Optional[str] = None,
) -> Optional['VideoGroup']:
    """給 router 用的一站式反解：從 DB 撈同資料夾候選列，回 target_uri 所屬的組。

    這是三個呼叫端（列表單筆 refresh / 刪除 / 播放頁接續）**共用的組裝層**——
    在它存在之前，同樣的 8 行（算資料夾 URI 前綴 → `get_by_folder_uri_prefix()` →
    `resolve_group_for_path()` ＋ 兩個 lambda）在 `showcase.py` 與 `scanner.py`
    抄了三份，三份的 try/except 位置還各自漂移（/simplify reuse 條目）。

    Args:
        repo: `VideoRepository`（只用到 `get_by_folder_uri_prefix()`，duck-typed，
            本模組不 import `core.database`）。
        target_uri: 要反解的 DB-key URI（身分比對用）。
        path_mappings: gallery 設定的跨機器路徑映射。
        folder_source_uri: 要掃哪個資料夾。**預設 None ＝ 用 target_uri 自己**；
            呼叫端手上若有 DB 查回的列，傳 `row.path` 比傳使用者送上來的字面更可靠。

    Returns:
        `VideoGroup` 或 None（找不到組不拋例外——fail-safe 由呼叫端決定怎麼退）。
        **本函式不吞 DB 例外**：repo 真的壞掉照樣往上拋，由各呼叫端依自己的
        語意決定要 500 還是退回單檔（CD-122-6 的分工）。
    """
    source_uri = target_uri if folder_source_uri is None else folder_source_uri
    folder_fs = os.path.dirname(uri_to_fs_path(source_uri))  # uri-no-reverse: 只取 dirname 拼前綴，隨即 to_file_uri 回 DB namespace，不做磁碟 I/O
    return resolve_group_for_path(
        target_uri=target_uri,
        candidates=repo.get_by_folder_uri_prefix(folder_uri_prefix(folder_fs, path_mappings)),
        fs_path_of=lambda r: uri_to_local_fs_path(r.path, path_mappings),
        uri_of=lambda r: r.path,
    )
