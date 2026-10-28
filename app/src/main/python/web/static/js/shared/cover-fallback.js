/**
 * cover-fallback.js — preview_cover_url → cover 的 error-time fallback 決策（TASK-113c-T7/T8）
 *
 * 放 `shared/` 的理由（T8）：`_rescrape_modal.html` 由 search 與 showcase 共用，
 * 對應的 `shared/state-rescrape.js` 不能 import `pages/`（層次反轉，本庫零先例）。
 * 把決策留在 `pages/search/` 就只剩「模板內聯」或「複製一份」兩條路，兩條都是把
 * 同一個決策散成第二份——正是 spec-113 在治的病。所以純函式搬來 `shared/`，
 * `pages/` 與 `shared/` 兩邊都 import 它，方向正確（shared ← pages）。
 *
 * 三顆函式自 T7 起逐字元未變（T8 DoD-5：純搬家，零行為變更）。
 */

// TASK-113c-T7（Opus 審核裁決 2）：回傳「原始圖片 URL」，不是 proxy URL——proxy 包裹
// 留在各呼叫點自行處理（與既有 search-flow.js::resolveStagingCoverUrl 契約一致）。
// 契約：`_previewFailed` 為 truthy → 只用 cover（preview 已知失敗，不再嘗試）；
// 否則沿用既有 `preview_cover_url || cover` 優先序（FE-JS-01：|| 對空字串 fallback 是
// 刻意行為，preview_cover_url 恆為字串，非 null/undefined）。
export function resolveResultCoverUrl(result) {
    if (!result) return '';
    if (result._previewFailed) return result.cover || '';
    return result.preview_cover_url || result.cover || '';
}

// TASK-113c-T7：決定「這次 preview 失敗要不要觸發 cover fallback」。
// 只有「還沒 fallback 過」且「preview/cover 都存在且不同」才值得換——已經在用 cover
// （_previewFailed 已 true）、沒有 cover 可退、或 preview 跟 cover 根本是同一個 URL，
// 都應該落回既有 PHASE 1/2 行為（cache-bust 重試／直接 latch）。
// TASK-113c-T7（Sonnet review P2）：這一發 `@error` 是不是「已經切走的那一張」遲到的？
// 燈箱／detail 的 `<img>` 都是**單一元素跨候選重用**，使用者按下一張時，上一張還在飛的
// 請求失敗後才回來。舊碼寫的是頁面層 boolean（切走即被重置，寫錯了也無害）；本 task 改
// 寫的是**跟著資料走的持久旗標** `_previewFailed`——寫到錯的候選上，那一筆會整個 session
// 停在 cover、明明 preview 是好的。所以持久旗標必須配 stale guard。
// `expectedRawUrl` 為空（如女優燈箱無影片）→ 不判 stale，交給呼叫端既有分支處理。
export function isStaleCoverError(actualSrc, expectedRawUrl) {
    if (!expectedRawUrl || !actualSrc) return false;
    return actualSrc !== `/api/proxy-image?url=${encodeURIComponent(expectedRawUrl)}`;
}

export function shouldFallbackToCover(result) {
    if (!result || result._previewFailed) return false;
    const preview = result.preview_cover_url;
    const cover = result.cover;
    return !!preview && !!cover && preview !== cover;
}
