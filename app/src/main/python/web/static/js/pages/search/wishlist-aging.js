/**
 * wishlist-aging.js — 書籤「放多久了」分階純函式（spec-141 F9，CD-5/CD-6/CD-7）。
 * 純函式、零 DOM 依賴、現在時刻可注入（CD-6）。
 * 禁用 Date 建構子／Date.parse 解析字串（比照 release-window.js 檔頭
 * CD-124a-2 的地雷紀錄：SQLite 'YYYY-MM-DD HH:MM:SS' 非 ISO 格式，跨瀏覽器解析
 * 行為不保證一致）。改用 regex 抽取數值欄位餵 Date.UTC()（數值參數無時區歧義）。
 * 本檔零合法場景需要 Date 建構子或 Date.parse——「現在時刻」一律由呼叫端
 * 以 Date.now() 注入（CD-6），本檔自己不建構 Date 物件。
 */

const CREATED_AT_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/;
const RELEASE_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})/;

export const WISHLIST_AGING_THRESHOLD_DAYS = Object.freeze({ STAGE1: 14, STAGE2: 30 });

function parseUtcMs(re, str) {
    if (typeof str !== 'string') return null;
    const m = re.exec(str);
    if (!m) return null;
    const parts = m.slice(1).map(Number);
    return Date.UTC(parts[0], parts[1] - 1, parts[2], parts[3] || 0, parts[4] || 0, parts[5] || 0);
}

/**
 * ageDaysOf(createdAt, now) → number | null
 * 顯示用天數，與 classifyWishlistAging 共用同一套解析（CD-6：不得在消費端另開一套）。
 * @param {string} createdAt - 'YYYY-MM-DD HH:MM:SS'
 * @param {number|Date} now - epoch ms 或 Date
 */
export function ageDaysOf(createdAt, now) {
    const nowMs = now instanceof Date ? now.getTime() : now;
    const createdMs = parseUtcMs(CREATED_AT_RE, createdAt);
    if (createdMs == null) return null;
    return Math.floor((nowMs - createdMs) / 86400000);
}

/**
 * classifyWishlistAging(createdAt, releaseDate, now) → 0 | 1 | 2
 * @param {string} createdAt - 'YYYY-MM-DD HH:MM:SS'（wishlist.created_at 原始欄位）
 * @param {string} releaseDate - 'YYYY-MM-DD' 或 ''（wishlist.release_date 原始欄位）
 * @param {number|Date} now - 目前時刻（epoch ms 或 Date），CD-6 要求可注入
 */
export function classifyWishlistAging(createdAt, releaseDate, now) {
    const nowMs = now instanceof Date ? now.getTime() : now;
    if (releaseDate) {
        const releaseMs = parseUtcMs(RELEASE_DATE_RE, releaseDate);
        if (releaseMs != null && releaseMs > nowMs) return 0;
    }
    const ageDays = ageDaysOf(createdAt, now);
    if (ageDays == null) return 0;
    if (ageDays >= WISHLIST_AGING_THRESHOLD_DAYS.STAGE2) return 2;
    if (ageDays >= WISHLIST_AGING_THRESHOLD_DAYS.STAGE1) return 1;
    return 0;
}
