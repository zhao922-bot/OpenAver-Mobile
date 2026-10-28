/**
 * release-window.js — 發售日比對層（TASK-124a-T1，純函式，零 UI）。
 *
 * 六支純函式，無副作用、無外部依賴（不 import 任何模組）。全程用整數 YYYYMM
 * 比較，禁用 Date/new Date()/Date.parse()（CD-124a-2：時區與月份轉換是地雷坑，
 * 純字串/整數解析不受時區影響）。
 *
 * 契約總覽（詳見 spec-124a §4.3／§4.4、plan-124a §0/§2）：
 * - parseReleaseKey：影片端取值，`video.release_date` → YYYYMM 整數。
 * - parseEndpoint：pill 端點取值，`pill.value`/`pill.value2` 這種使用者/持久化層
 *   寫下的字面 → { y, m }。**走嚴格形狀**：`^(\d{4})(?:-(\d{2}))?$`，月份必須
 *   恰兩位（Opus 對 card 的裁決，覆蓋 card 原文「月份允許 1 或 2 位」）——
 *   composeEndpoint 永遠 zero-pad，系統本身不會產生 '2023-9' 這種形狀；容忍
 *   一位月份等於製造一種只有手改 localStorage 才生得出的畸形資料。
 * - expandPill：spec §4.3 表的唯一實作，把 pill 展開成 { lo, hi } 比對區間。
 * - matchesReleasePill：per-video 判斷 key 是否落在 [lo, hi]（含端點）。
 * - composeEndpoint：T2 狀態機提交時，把使用者填的數字組成 pill 端點字面。
 * - videoYearRange：spec §4.9 資料範圍提示，取全庫 videos 算 min/max 年份。
 */

// 影片端：只取前 7 字 'YYYY-MM'，DD（若存在）不進比對。無需 $ 錨定字尾——
// 'YYYY-MM-DD' 這種較長字面本來就該只取前綴，這是取值語意的一部分，不是寬鬆。
var RELEASE_KEY_RE = /^(\d{4})-(\d{2})/;

// pill 端點：嚴格形狀，年份恰四位、月份（若存在）恰兩位，見檔頭說明。
var ENDPOINT_RE = /^(\d{4})(?:-(\d{2}))?$/;

// 影片端（年份-only）：與後端 _RELEASE_RE 年份規則一致（無尾錨）。
var RELEASE_YEAR_RE = /^(19\d{2}|20\d{2}|21\d{2})/;

/**
 * parseReleaseKey(releaseDate) → number | null
 * 影片端取值：'2024-09-09' → 202409；只有年份／畸形字串／非字串 → null。
 */
export function parseReleaseKey(releaseDate) {
    if (typeof releaseDate !== 'string') return null;
    var m = RELEASE_KEY_RE.exec(releaseDate);
    if (!m) return null;
    var month = parseInt(m[2], 10);
    if (month < 1 || month > 12) return null;
    return parseInt(m[1], 10) * 100 + month;
}

/**
 * parseReleaseYearOnly(releaseDate) → number | null
 * 影片端年份-only 取值：與後端 _RELEASE_RE 同規則，'2015' → 2015；非字串／非合法年份 → null。
 */
export function parseReleaseYearOnly(releaseDate) {
    if (typeof releaseDate !== 'string') return null;
    var m = RELEASE_YEAR_RE.exec(releaseDate);
    if (!m) return null;
    return parseInt(m[1], 10);
}

/**
 * parseEndpoint(token) → { y: number, m: number|null } | null
 * pill 端點取值：'2023' → {y:2023, m:null}；'2023-09' → {y:2023, m:9}；
 * 形狀不符（含月份非恰兩位）→ null。
 */
export function parseEndpoint(token) {
    if (typeof token !== 'string') return null;
    var m = ENDPOINT_RE.exec(token);
    if (!m) return null;
    var year = parseInt(m[1], 10);
    if (m[2] === undefined) return { y: year, m: null };
    var month = parseInt(m[2], 10);
    if (month < 1 || month > 12) return null;
    return { y: year, m: month };
}

// 內部輔助：同一個 parseEndpoint 結果，依「取下界」或「取上界」展開成 YYYYMM。
// 「'=' 缺月＝整年」不是額外規則，是 lo/hi 各自對同一個 token 展開的自然結果。
function _lo(parsed) { return parsed.y * 100 + (parsed.m == null ? 1 : parsed.m); }
function _hi(parsed) { return parsed.y * 100 + (parsed.m == null ? 12 : parsed.m); }

/**
 * expandPill(pill) → { lo: number, hi: number } | null
 * spec §4.3 展開規則表的唯一實作。pill.op 不在四值白名單內、或
 * parseEndpoint 任一端失敗 → null（fail-closed）。
 *
 * lo > hi 的 range 誠實回傳（不對調），對調是 T2 _commitReleaseEditor() 的事。
 */
export function expandPill(pill) {
    if (!pill) return null;
    var op = pill.op;
    if (op === '=') {
        var eq = parseEndpoint(pill.value);
        if (!eq) return null;
        return { lo: _lo(eq), hi: _hi(eq) };
    }
    if (op === '<=') {
        var le = parseEndpoint(pill.value);
        if (!le) return null;
        return { lo: -Infinity, hi: _hi(le) };
    }
    if (op === '>=') {
        var ge = parseEndpoint(pill.value);
        if (!ge) return null;
        return { lo: _lo(ge), hi: Infinity };
    }
    if (op === 'range') {
        var loEnd = parseEndpoint(pill.value);
        var hiEnd = parseEndpoint(pill.value2);
        if (!loEnd || !hiEnd) return null;
        return { lo: _lo(loEnd), hi: _hi(hiEnd) };
    }
    return null;  // 未知 op：fail-closed，不當作任何一種既有 op 處理
}

/**
 * matchesReleasePill(video, w) → boolean
 * w 為 expandPill() 的回傳值。w 為 null、或 video 解析不出年月 → false（fail-closed）。
 */
export function matchesReleasePill(video, w) {
    if (!w) return false;
    var key = parseReleaseKey(video && video.release_date);
    if (key != null) {
        return key >= w.lo && key <= w.hi;
    }
    var y = parseReleaseYearOnly(video && video.release_date);
    if (y == null) return false;
    return w.lo <= y * 100 + 1 && w.hi >= y * 100 + 12;
}

/**
 * composeEndpoint(year, month) → string | null
 * T2 狀態機提交時，把使用者填的數字組成 pill 端點字面。年份不 pad（CD-124a-10），
 * 月份 zero-pad 到兩位。輸入雖已過 T2 的 _releaseEndpoint() 驗證，本函式仍自行防禦。
 */
export function composeEndpoint(year, month) {
    if (!Number.isInteger(year) || year < 1000 || year > 9999) return null;
    if (month == null) return String(year);
    if (!Number.isInteger(month) || month < 1 || month > 12) return null;
    var mm = month < 10 ? '0' + month : String(month);
    return year + '-' + mm;
}

/**
 * videoYearRange(videos) → { min: number, max: number } | null
 * spec §4.9 資料範圍提示。videos 非陣列、空陣列、或全部解析不出年月 → null。
 */
export function videoYearRange(videos) {
    if (!Array.isArray(videos)) return null;
    var min = null;
    var max = null;
    for (var i = 0; i < videos.length; i++) {
        var key = parseReleaseKey(videos[i] && videos[i].release_date);
        if (key == null) continue;
        var year = Math.floor(key / 100);
        if (min == null || year < min) min = year;
        if (max == null || year > max) max = year;
    }
    if (min == null) return null;
    return { min: min, max: max };
}
