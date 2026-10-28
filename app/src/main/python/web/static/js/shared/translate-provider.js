/**
 * 缺值視為 ollama，與 `pages/settings/state-config.js` 的 `|| 'ollama'` 一致；新增雲端引擎不必改呼叫端
 */
export function isCloudTranslateProvider(provider) {
    return (provider || 'ollama') !== 'ollama';
}

/**
 * 雲端翻譯失敗原因 → 單片 toast 的 i18n key；未知／缺值回通用 translate_failed
 */
export function translateFailureToastKey(reason) {
    if (reason === 'blocked') return 'search.toast.translate_blocked';
    if (reason === 'rate_limited') return 'search.toast.translate_rate_limited';
    return 'search.toast.translate_failed';
}

/**
 * 「全部翻譯」結束 toast 全文；blocked／limited 為 failed 的子集，>0 才附後綴（blocked 在前）
 */
export function translateAllSummary(t, { success, failed, blocked, limited }) {
    let msg = t('search.toast.translate_batch_done', { success, failed });
    if (blocked > 0) msg += t('search.toast.translate_batch_blocked_suffix', { blocked });
    if (limited > 0) msg += t('search.toast.translate_batch_limited_suffix', { limited });
    return msg;
}
