/**
 * autoOrganizePanel — 搜尋頁「自動整理」popover（TASK-144-T7）
 *
 * 獨立 Alpine.data() 元件（照 help-popover.js 形狀）。不加 Alpine.store。
 */

/**
 * 獨立元件不在 mergeState 裡，拿不到 `this.showToast`。
 * 逐字照 `web/static/js/shared/state-toast.js` 的既有做法直接打 store——
 * **不新增 `window.toast` 這個全域**：全站現在沒有這個符號，為了一個面板生一個
 * 跨頁全域，等於在 `Alpine.store('toast')` 之外開第二條 toast 路徑。
 */
function showToast(msg, type = 'success', duration = 2500) {
    Alpine.store('toast').show(msg, type, duration);
}

export function autoOrganizePanel() {
    return {
        open: false,
        enabled: false,
        folderPath: '',
        folderIsSet: false,
        resolvedFolder: '',
        loading: false,
        running: false,

        /**
         * **同步**、零網路請求：初始的 enabled 由伺服器 render 進 data 屬性。
         *
         * 這一步必須是同步的——Alpine 在處理其餘 directive 之前先跑 init()，
         * 所以按鈕的 `:class` 第一次求值時 enabled 就已經是對的，**不會先畫成
         * btn-outline 再跳成 btn-accent**。改成 async fetch 的話每次進搜尋頁
         * 都會閃一下，而且每次都多一個請求（那正是本卡砍掉 Alpine.store 想省掉的東西）。
         */
        init() {
            this.enabled = this.$el.dataset.autoOrganizeEnabled === '1';
        },

        /** 開面板只發**一個**請求：status 端點一次回完面板要的六個欄位。 */
        async openPanel() {
            this.open = true;
            await this._loadStatus();
        },

        closePanel() {
            this.open = false;
        },

        /**
         * @param {boolean} enabled 使用者撥到的位置
         * @param {HTMLInputElement} [el] 那顆 checkbox 本身
         *
         * ⚠️ 失敗時**必須連 DOM 一起還原**，只把 `this.enabled` 指回舊值是不夠的：
         * 綁定是 `:checked="enabled"`，而使用者點擊當下瀏覽器已經把 checkbox 翻過去了；
         * 把 `enabled` 指回 `prev` 時**值根本沒有變化**，Alpine 不會重跑那個綁定，
         * 開關就停在使用者撥過去的位置——畫面說「開著」，後端其實是關的。
         * （T7 CDP 驗收實測到：撥之前 checked=true，失敗後停在 false。
         *   node:test 只看得到 `panel.enabled`，看不到這個。）
         *
         * ⚠️ 連點兩下會發兩個並行請求、回應順序不保證，存到後端的值可能不是使用者
         * 最後點的那一下——套用 `runNow()` 已經在用的 `loading` 早退。早退這條**必須**
         * 把 checkbox 的 DOM 狀態拉回 `this.enabled`：瀏覽器在使用者點擊當下已經把
         * `checked` 翻過去了，而 `:checked="enabled"` 這個值若沒變化 Alpine 不會重跑
         * 綁定（Proxy 的 hasChanged），所以不能只 `return`。
         */
        async setEnabled(enabled, el) {
            if (this.loading) {
                if (el) el.checked = this.enabled;
                return;
            }
            this.loading = true;
            const prev = this.enabled;
            const restore = () => {
                this.enabled = prev;
                if (el) el.checked = prev;
            };
            try {
                const resp = await fetch('/api/search/auto-organize/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: !!enabled }),
                });
                const data = await resp.json();
                if (data && data.success) {
                    this.enabled = !!enabled;
                } else {
                    restore();
                    showToast(window.t('search.auto_organize.config_failed'), 'error');
                }
            } catch (_e) {
                restore();
                showToast(window.t('search.auto_organize.config_failed'), 'error');
            } finally {
                this.loading = false;
            }
        },

        async runNow() {
            if (!this.folderIsSet || this.loading) return;
            this.loading = true;
            try {
                const resp = await fetch('/api/search/auto-organize/run-now', {
                    method: 'POST',
                });
                const data = await resp.json();
                if (data && data.success) {
                    // 毫秒級返回；輪在背景跑——絕不可寫「已完成」
                    showToast(window.t('search.auto_organize.run_now_started'), 'success');
                } else {
                    showToast(window.t('search.auto_organize.run_now_busy'), 'warning');
                }
            } catch (_e) {
                showToast(window.t('search.auto_organize.config_failed'), 'error');
            } finally {
                this.loading = false;
            }
        },

        async useResolvedFolder() {
            try {
                const resp = await fetch('/api/search/auto-organize/use-resolved-folder', {
                    method: 'POST',
                });
                const data = await resp.json();
                if (data && data.success) {
                    this.folderIsSet = true;
                    this.folderPath = data.folder || this.folderPath;
                    // 就地解鎖；不關面板、不重整
                } else {
                    showToast(window.t('search.auto_organize.config_failed'), 'error');
                }
            } catch (_e) {
                showToast(window.t('search.auto_organize.config_failed'), 'error');
            }
        },

        displayFolderPath() {
            const raw = this.folderPath || '';
            if (typeof window.pathToDisplay === 'function') {
                return window.pathToDisplay(raw);
            }
            return raw;
        },

        async _loadStatus() {
            try {
                const resp = await fetch('/api/search/auto-organize/status');
                const data = await resp.json();
                this.running = !!data.running;
                this.enabled = !!data.enabled;
                this.folderIsSet = !!data.folder_is_set;
                this.resolvedFolder = data.resolved_folder || '';
                // 已設定就顯示設定值；還沒設就顯示「按下去會變成什麼」的候選值，
                // 兩者同源於後端的 resolve_favorite_folder()，所以灰字與實際生效值保證一致。
                this.folderPath = data.folder_is_set
                    ? (data.folder || '')
                    : this.resolvedFolder;
            } catch (_e) {
                // 失敗不擋面板開合：面板照樣展開，只是欄位停在目前值
            }
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('autoOrganizePanel', autoOrganizePanel);
});
