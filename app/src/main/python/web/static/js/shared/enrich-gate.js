/**
 * enrich-gate.js — 🔍 補資料鈕顯示條件單一所有者（CD-149b-9）。
 * 卡片（grid）與燈箱的 🔍 都呼叫這個函式，避免兩處各自寫一份同義布林條件而漂移。
 * 零 import、零 Alpine 依賴。
 */

export function shouldShowEnrichButton(video) {
    if (!video) return false;
    return !!video.number && (!video.has_cover || !video.has_nfo);
}
