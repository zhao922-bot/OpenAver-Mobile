/**
 * tutorial-step3-card.js — 新手引導第 3 步模擬卡（CD-146a-3）。
 *
 * 純函式：吃一個 translator（測試可注入 spy，生產環境傳 window.t），輸出 HTML 字串。
 * 三個詞（缺 NFO／缺封面／一鍵補完）與真卡片（scanner.html + state-batch.js）
 * 消費同一組 i18n key，不新建 tutorial 專屬字串——這是 spec §2.2 驗收「改
 * scanner.stats.missing_nfo_prefix 兩處同時變」的唯一機械保證來源。
 * 數字固定 13／11（spec §2.2／§5，不讀真實片庫）。
 * 整塊包在 `.tutorial-mock-card`（tutorial.css 設 pointer-events:none，
 * 同時滿足「不可點」與「不亮 hover」）。
 * 外層 div 必須帶 `ds-gallery-composition` class（CD-146a-3 事實訂正）——
 * `.nfo-update-row`／`.nfo-badge`／`.btn-nfo-update` 的樣式全寫在
 * `:is(#ds-gallery-components, .ds-gallery-composition) .xxx` 作用域選擇器裡
 * （theme.css:1376/1390/1403，tailwind.css 同形狀），overlay 掛在 document.body
 * 下不在這個作用域內，少了這個 class 卡片會渲染出來但完全沒有樣式。
 * 兩段文字之間的分隔一律用半形空格（' '，U+0020），不得用全形空格（U+3000）——
 * 真卡片（scanner.html 缺失列，155b-T4 起每段拆成可點數字）在畫面上也是半形間隔。
 */
export function buildStep3MockCard(t) {
    return (
        '<div class="tutorial-mock-card ds-gallery-composition">' +
        '<div class="nfo-update-row">' +
        '<span class="nfo-badge">' +
        '<i class="bi bi-file-earmark-x"></i> ' +
        t('scanner.stats.missing_nfo_prefix') + ' 13' + t('scanner.stats.missing_suffix') + ' ' +
        t('scanner.stats.missing_cover_prefix') + ' 11' + t('scanner.stats.missing_suffix') +
        '</span>' +
        '<button class="btn-nfo-update" type="button" disabled tabindex="-1" aria-hidden="true">' +
        '<i class="bi bi-file-earmark-plus"></i> ' + t('scanner.stats.missing_enrich_idle') +
        '</button>' +
        '</div>' +
        '</div>'
    );
}
