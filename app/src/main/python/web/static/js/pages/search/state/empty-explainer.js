// empty-explainer.js — 搜尋頁空狀態四行說明（CD-146a-16，spec-146a §6.2）。
// mergeState 分片（CD-146a-19 決定不做獨立 Alpine 元件），本檔**不得定義 init()**
// （FE-ALPINE-05：後定義的 init() 會覆蓋先前的，state-browse-dir.js 同一條約束的先例）。
// 資料載入（formatVariables／favoriteScannerLinked 的 fetch）放在 search-flow.js 既有的
// loadAppConfig() 裡（CD-146a-17），本檔只放純讀取的 method，且一律回傳純文字（不組 HTML
// 字串、不餵 x-html——CD-146a-16 事實訂正：window.t() 的 {param} 插值不 escape，動態值只能
// 走 x-text）。

import { buildNamingPreview } from '@/shared/naming-preview.js';

export function searchStateEmptyExplainer() {
    return {
        favoriteConfigured() {
            const folder = (this.appConfig && this.appConfig.search && this.appConfig.search.favorite_folder) || '';
            return !!folder.trim();
        },

        favoritePathDisplay() {
            const folder = (this.appConfig && this.appConfig.search && this.appConfig.search.favorite_folder) || '';
            // search.favorite_folder 是使用者輸入框當初打的原生路徑字串（非 file:/// URI，
            // 見 CD-146a-14 settings_link.py 現況註解「favorite 從 query param 取得（input
            // 即時值）」），pathToDisplay 對已是原生格式（Windows 反斜線/UNC/POSIX）的輸入是
            // no-op（頭部 file:/// 前綴不存在時 .replace 不匹配，後續判斷原樣通過），故可直接
            // 傳入，不需要先包一層 to_file_uri 往返。
            return window.pathToDisplay ? window.pathToDisplay(folder) : folder;
        },

        // 這一列消費**兩個各自獨立載入**的輸入（CD-146a-17：/api/config 與
        // /api/config/format-variables 平行發起、失敗隔離，其中一個掛掉不影響另一個）。
        // 「準備好了沒」由**消費端自己回答**，不要寫在樣板上——
        // 本 PR 已經漏過一次：`fc9667bc` 為了擋「第一幀用未載入的設定畫」只在樣板加了
        // `appConfig !== null`，而 `formatVariables` 是另一個輸入，沒人看 ⇒ config 到、
        // vars 沒到時，`namingPreviewExample()` 會把使用者的格式原樣吐出來、一個 token 都沒替換
        // （實測 `{actor}/[{num}][{maker}] {actor}-{title}{suffix}.mp4`），
        // 而前綴寫著「整理成：」⇒ 看起來像檔案真的會被改成一串大括號。
        // 以後這一列再多吃一個輸入，改的人就在隔壁幾行看得到這個函式。
        //
        // ⚠️ 用 `length > 0` 而不是 `!== null`：`search-flow.js` 在回應缺 `variables` 陣列時
        // 會寫成 `[]`，所以 `!== null` 會誤判成 ready。這條端點是寫死的 10 筆靜態清單
        // （`web/routers/config.py`，`test_format_variables_contract.py` 鎖 `len == 10`），
        // 不存在「合法回空」⇒ `length > 0` 是 fail-closed 的載入成功代理，不是資料量判斷。
        namingPreviewReady() {
            return this.appConfig !== null && (this.formatVariables || []).length > 0;
        },

        namingPreviewExample() {
            const scraper = (this.appConfig && this.appConfig.scraper) || {};
            const tokens = {};
            for (const v of this.formatVariables || []) {
                const name = v.name.slice(1, -1);
                tokens[name] = window.t('settings.var.' + name);
            }
            return buildNamingPreview({
                filenameFormat: scraper.filename_format,
                createFolder: scraper.create_folder,
                folderLayerList: scraper.create_folder ? (scraper.folder_layers || []) : [],
                formatVariables: this.formatVariables,
                tokens,
            });
        },
    };
}
