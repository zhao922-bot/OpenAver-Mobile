import { copyText } from '@/shared/clipboard.js';
import { dirPath } from '@/shared/dir-path.js';

let _dragTimeoutHandle = null;

// TASK-138-T3（CD-A2）：逾時門檻需 > 瀏覽器原生 dragover 心跳間隔（WHATWG 規範值 350ms）。
// 目前實測值與安全餘裕見 plan-138.md「CD-A2」。兩頁常數值與本注解必須逐字相同（CD-A5）。
// 必須 export——測試要 import 這個常數本身去驅動 mock.timers.tick()，不得在測試檔裡另抄一份數字。
export const DRAG_OVERLAY_TIMEOUT_MS = 1200; // 待 T3 實測覆核（見「驗證方式」CD-A2 量測步驟）

export function stateScan() {
    return {
        dirPath,
        // ===== Data State =====
        directories: [],
        shellMode: '',
        config: {},
        configDirty: false,

        // ===== Folder Dirty Check =====
        folderSnapshot: null,
        pendingNavigationUrl: '',
        dirtyCheckModalOpen: false,

        // ===== TASK-90b-T1: Readonly Confirm Modal =====
        readonlyConfirmModalOpen: false,
        readonlyConfirmTargetIdx: null,

        // ===== Drag-drop State =====
        showDragOverlay: false,

        // ===== Stats State =====
        statsVisible: false,
        statTotal: 0,
        statLastRun: '',
        maintenanceExpanded: false,
        clearCacheModalOpen: false,
        clearCacheLoading: false,

        // ===== Manual Input State =====
        manualInputVisible: false,
        manualPath: '',

        // ===== T3.6: Copy Logs Fail Modal =====
        copyFailModalOpen: false,
        copyFailDump: '',

        // ===== T7b: State Machine =====
        state: 'idle',  // idle | generating | nfoUpdating | tagSourcePreviewing | tagSourceUpdating | renamePreviewing | jellyfinUpdating | enriching | done | error | cancelled

        // ===== T7b: Progress =====
        progressStatus: '',
        progressCurrent: 0,
        progressTotal: 0,
        taskKind: '',
        taskStartedAt: 0,
        taskEndedAt: 0,
        taskClockTick: 0,
        taskTimer: null,
        taskCurrentItem: '',
        taskSuccessCount: 0,
        taskFailedCount: 0,
        taskSkippedCount: 0,
        taskChangedCount: 0,
        taskEtaSeconds: 0,
        taskSummaryText: '',
        taskFailedItems: [],

        // ===== T7b: Log System =====
        logHtml: '',           // 日誌 HTML（用於 restoreLogs）
        logBatch: [],          // 批次佇列
        logTimer: null,        // 批次計時器

        // ===== T7d: Log Terminal 增強 =====
        logEntries: [],        // [{level, message, timestamp}] 結構化陣列
        logFilter: 'all',      // 'all' | 'error' | 'warn' 篩選條件
        logPanelExpanded: false,

        // ===== T7b: Done Actions =====
        outputPath: '',        // 輸出路徑（供複製）

        // ===== T7b: NFO Update =====
        nfoNeedUpdateCount: 0,
        nfoUpdatePaths: [],
        nfoUpdateItems: [],
        nfoUpdateVisible: false,
        nfoSelectedPaths: [],
        nfoPreviewPage: 1,

        // ===== r16: Batch tag source update =====
        tagSourceUpdateSource: 'auto',
        tagSourceConfirmModalOpen: false,
        tagSourcePreviewSource: '',
        tagSourcePreviewSourceLabel: '',
        tagSourcePreviewData: null,
        tagSourcePreviewNumbers: [],
        tagSourcePreviewPage: 1,
        tagSourcePreviewOnly: false,
        tagSourceBackupEnabled: true,

        // ===== r18: NFO confirmation =====
        nfoUpdateConfirmModalOpen: false,
        nfoUpdateBackupEnabled: true,

        // ===== T6d: Jellyfin Image Update =====
        jellyfinImageCount: 0,
        jellyfinItems: [],
        jellyfinImageVisible: false,
        jellyfinCheckState: 'idle',   // T2(40c): 'idle' | 'checking' | 'done'
        _jellyfinCheckController: null,

        // ===== T7b: EventSource 管理 =====
        eventSource: null,

        // ===== Computed Properties =====
        get isFolderDirty() {
            if (!this.folderSnapshot) return false;
            return JSON.stringify(this.directories) !== this.folderSnapshot;
        },

        // GET /api/config 的 response-only 解析值（不入 saveConfig payload）
        resolvedGalleryOutputPath: '',

        get outputPathDisplay() {
            // 後端解析出的實際路徑；空字串＝尚未 loadConfig，不回退字面 'output'
            const outputDir = this.resolvedGalleryOutputPath || this.config.gallery?.output_dir || '';
            const outputFilename = this.config.gallery?.output_filename || 'gallery_output.html';
            return `${outputDir}/${outputFilename}`;
        },

        // ===== T7b: Computed Properties =====
        get progressPercent() {
            if (this.progressTotal === 0) return 0;
            return (this.progressCurrent / this.progressTotal) * 100;
        },

        get progressPercentRounded() {
            return Math.round(this.progressPercent);
        },

        get progressMetaText() {
            if (this.progressTotal <= 0) return '';
            return `${this.progressCurrent} / ${this.progressTotal} · ${this.progressPercentRounded}%`;
        },

        get taskSuccessDisplay() {
            return this.taskKind === 'enrich' ? this.missingEnrichSuccess : this.taskSuccessCount;
        },

        get taskFailedDisplay() {
            return this.taskKind === 'enrich' ? this.missingEnrichFailed : this.taskFailedCount;
        },

        get taskElapsedText() {
            if (!this.taskStartedAt) return '';
            const end = this.isGenerating
                ? (this.taskClockTick || Date.now())
                : (this.taskEndedAt || Date.now());
            return this._formatDuration(Math.max(0, Math.floor((end - this.taskStartedAt) / 1000)));
        },

        get taskEtaText() {
            if (!this.isGenerating || !['nfo-update', 'tag-preview', 'tag-update', 'rename-preview', 'enrich'].includes(this.taskKind)) {
                return '';
            }
            let seconds = this.taskEtaSeconds;
            if (!seconds && this.progressCurrent > 0 && this.progressTotal > this.progressCurrent && this.taskStartedAt) {
                const elapsed = Math.max(1, ((this.taskClockTick || Date.now()) - this.taskStartedAt) / 1000);
                seconds = Math.round((elapsed / this.progressCurrent) * (this.progressTotal - this.progressCurrent));
            }
            return seconds > 0 ? window.t('scanner.task.eta_value', { time: this._formatDuration(seconds) }) : '';
        },

        get taskPanelVisible() {
            return this.state !== 'idle' && (this.taskKind !== '' || this.logHtml !== '');
        },

        get taskCanRetry() {
            return !this.isGenerating
                && this.taskFailedItems.length > 0
                && ['nfo-update', 'tag-preview', 'tag-update', 'jellyfin-update'].includes(this.taskKind);
        },

        get maintenanceSummaryText() {
            const nfo = this.nfoNeedUpdateCount || 0;
            const missing = (this.missingBothCount || 0) + (this.missingNfoCount || 0) + (this.missingCoverCount || 0);
            const images = this.jellyfinImageCount || 0;
            return window.t('scanner.stats.maintenance_summary', { nfo, missing, images });
        },

        get tagSourcePreviewChangedItems() {
            const items = this.tagSourcePreviewData?.items || [];
            return items.filter(item => item.status === 'changed');
        },

        get tagSourcePreviewFailureItems() {
            return this.tagSourcePreviewData?.failed_items || [];
        },

        get tagSourcePreviewChangedCount() {
            return this.tagSourcePreviewData?.changed || 0;
        },

        get tagSourcePreviewPageSize() {
            return 6;
        },

        get tagSourcePreviewPageCount() {
            return Math.max(
                1,
                Math.ceil(this.tagSourcePreviewChangedItems.length / this.tagSourcePreviewPageSize)
            );
        },

        get tagSourcePreviewPageItems() {
            const start = (this.tagSourcePreviewPage - 1) * this.tagSourcePreviewPageSize;
            return this.tagSourcePreviewChangedItems.slice(start, start + this.tagSourcePreviewPageSize);
        },

        get tagSourceSelectedChangedCount() {
            const changed = new Set(this.tagSourcePreviewChangedItems.map((item) => item.number));
            return [...new Set(this.tagSourcePreviewNumbers)].filter((number) => changed.has(number)).length;
        },

        get tagSourceConfirmButtonDisabled() {
            return this.isGenerating
                || this.tagSourcePreviewOnly
                || this.tagSourceSelectedChangedCount === 0;
        },

        get nfoUpdatePageSize() {
            return 6;
        },

        get nfoUpdatePageCount() {
            return Math.max(1, Math.ceil(this.nfoUpdateItems.length / this.nfoUpdatePageSize));
        },

        get nfoUpdatePageItems() {
            const start = (this.nfoPreviewPage - 1) * this.nfoUpdatePageSize;
            return this.nfoUpdateItems.slice(start, start + this.nfoUpdatePageSize);
        },

        get nfoSelectedCount() {
            return new Set(this.nfoSelectedPaths).size;
        },

        get nfoUpdateConfirmDisabled() {
            return this.isGenerating || this.nfoSelectedCount === 0;
        },

        get isGenerating() {
            return this.state === 'generating' || this.state === 'nfoUpdating'
                || this.state === 'tagSourcePreviewing'
                || this.state === 'tagSourceUpdating'
                || this.state === 'renamePreviewing'
                || this.state === 'jellyfinUpdating' || this.state === 'enriching';
        },

        get isBusy() {
            // 用於按鈕 disabled：generating/nfoUpdating 時鎖定
            return this.isGenerating;
        },

        get progressSectionVisible() {
            // state 非 idle 時顯示，或有恢復的 logs 時也顯示
            return this.state !== 'idle' || this.logHtml !== '';
        },

        get doneActionsVisible() {
            return this.state === 'done' && this.outputPath !== '';
        },

        get tagSourceOptions() {
            const options = [{
                id: 'auto',
                display_name: window.t('scanner.stats.tag_source_auto'),
            }];
            const seen = new Set(['auto']);
            const rows = (this.config.sources || [])
                .filter((source) => source
                    && source.enabled
                    && !source.manual_only
                    && !String(source.id || '').startsWith('custom:'))
                .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
            for (const source of rows) {
                if (!source.id || seen.has(source.id)) continue;
                seen.add(source.id);
                options.push({
                    id: source.id,
                    display_name: source.type === 'metatube'
                        ? (source.display_name_raw || source.id)
                        : (source.display_name_key || source.id),
                });
            }
            return options;
        },

        get selectedTagSourceLabel() {
            const selected = this.tagSourceOptions.find(
                (source) => source.id === this.tagSourceUpdateSource
            );
            return selected ? selected.display_name : this.tagSourceUpdateSource;
        },

        get tagSourceModalSourceLabel() {
            return this.tagSourcePreviewSourceLabel || this.selectedTagSourceLabel;
        },

        get tagSourceUpdateButtonDisabled() {
            return this.isBusy || !this.tagSourceUpdateSource || this.statTotal === 0;
        },

        get tagSourceUpdateButtonText() {
            if (this.state === 'tagSourceUpdating') {
                return '<span class="loading loading-spinner loading-sm"></span> '
                    + window.t('scanner.stats.tag_source_updating');
            }
            if (this.state === 'tagSourcePreviewing') {
                return '<i class="bi bi-hourglass-split"></i> '
                    + window.t('scanner.stats.tag_source_preview_update_btn');
            }
            return '<i class="bi bi-tags"></i> '
                + window.t('scanner.stats.tag_source_preview_update_btn');
        },

        get tagSourcePreviewButtonText() {
            if (this.state === 'tagSourcePreviewing') {
                return '<span class="loading loading-spinner loading-sm"></span> '
                    + window.t('scanner.stats.tag_source_previewing');
            }
            return '<i class="bi bi-eye"></i> '
                + window.t('scanner.stats.tag_source_preview_btn');
        },

        get generateButtonText() {
            if (this.state === 'generating') {
                return '<span class="loading loading-spinner loading-sm"></span> ' + window.t('scanner.stats.generate_loading');
            }
            return '<i class="bi bi-play-fill"></i> ' + window.t('scanner.stats.generate_idle');
        },

        get nfoUpdateButtonText() {
            if (this.state === 'nfoUpdating') {
                return '<span class="loading loading-spinner loading-sm"></span> ' + window.t('scanner.stats.nfo_loading');
            }
            if (this.nfoNeedUpdateCount > 0) {
                return '<i class="bi bi-magic"></i> ' + window.t('scanner.stats.nfo_idle');
            }
            return '<i class="bi bi-check-lg"></i> ' + window.t('scanner.stats.btn_done');
        },

        get nfoUpdateButtonDisabled() {
            // generating/nfoUpdating 時鎖定；idle/done/error 時看 nfoNeedUpdateCount
            return this.isGenerating || this.nfoNeedUpdateCount === 0;
        },

        get jellyfinImageButtonText() {
            if (this.state === 'jellyfinUpdating') {
                return '<span class="loading loading-spinner loading-sm"></span> ' + window.t('scanner.stats.jellyfin_loading');
            }
            if (this.jellyfinImageCount > 0) {
                return '<i class="bi bi-images"></i> ' + window.t('scanner.stats.jellyfin_idle');
            }
            return '<i class="bi bi-check-lg"></i> ' + window.t('scanner.stats.btn_done');
        },

        // TASK-155b-T4: numberDrilldown items／payload（NFO 欄位不全／jellyfin）
        get nfoUpdateDrilldownItems() {
            return this.nfoUpdateItems.map(i => ({
                    number: i.number,
                    path: i.path,
                    note: window.t('scanner.stats.nfo_field_note_prefix') + i.missing.map(f => window.t('scanner.stats.nfo_field_' + f)).join('、'),
                }));
        },
        get nfoUpdateDrilldownPayload() {
            return { title: window.t('scanner.stats.nfo_prefix'), items: this.nfoUpdateDrilldownItems, footnote: '' };
        },
        get jellyfinDrilldownItems() {
            return this.jellyfinItems.map(i => ({ number: i.number, path: i.path }));
        },
        get jellyfinDrilldownPayload() {
            return { title: window.t('scanner.stats.jellyfin_prefix'), items: this.jellyfinDrilldownItems, footnote: '' };
        },

        // ===== Lifecycle =====
        async init() {
            // 168e-T5: 殼模式由 SSR data-shell-mode 提供；init() 內 $el 才是根節點（點擊 handler 內是按鈕）
            this.shellMode = this.$el?.dataset?.shellMode || '';
            // 覆蓋全域函數為 Alpine 版本
            const self = this;

            // 暴露 PyWebView 回調
            window.addScannerFolder = (path) => self.addFolderPath(path);

            // T5.1: 接入統一 page lifecycle
            // 提前到所有 await 之前註冊：closure 讀的都是 this.* runtime state，
            // 提前註冊不改變行為；但避免 loadConfig fetch 卡住時離頁 dirty-guard /
            // beforeunload / cleanup hook 永遠不註冊（SCAN HIGH #1）。
            if (window.__registerPage) {
                window.__registerPage({
                    beforeLeave: (href) => {
                        const guard = this.shouldWarnBeforeLeave();
                        if (guard.shouldWarn) {
                            if (guard.useModal) {
                                this.pendingNavigationUrl = href;
                                this.dirtyCheckModalOpen = true;
                                return false;
                            } else {
                                // eslint-disable-next-line no-alert -- dirty-check page-leave confirm, backlog migration to fluent-modal, reviewed 2026-05-03
                                const ok = confirm(window.t('scanner.leave_warning.confirm', { message: guard.message }));
                                if (ok) {
                                    // T2(40c): 離頁確認後 abort jellyfin check
                                    if (this._jellyfinCheckController) {
                                        this._jellyfinCheckController.abort();
                                        this._jellyfinCheckController = null;
                                    }
                                    this.jellyfinCheckState = 'idle';
                                }
                                return ok;
                            }
                        }
                        return true;
                    },
                    onBeforeUnload: () => {
                        const guard = this.shouldWarnBeforeLeave();
                        if (guard.shouldWarn) return guard.message;
                        return null;
                    },
                    cleanup: () => {
                        if (this.eventSource) { this.eventSource.close(); this.eventSource = null; }
                        window.Alpine?.store?.('toast')?.hide?.();   // 131b-T3：cleanup 不得拋錯（拋了會跳過後面所有 teardown）
                        clearTimeout(this.logTimer);
                        this._stopTaskTimer();
                        // T2(40c): abort jellyfin check fetch
                        if (this._jellyfinCheckController) {
                            this._jellyfinCheckController.abort();
                            this._jellyfinCheckController = null;
                        }
                        this.jellyfinCheckState = 'idle';
                        // T10: save pending enrich items on leave
                        if (this.state === 'enriching' && this.missingItems.length > this.missingEnrichOffset) {
                            localStorage.setItem('avlist_enrich_pending', JSON.stringify(this.missingItems.slice(this.missingEnrichOffset)));
                        }
                        if (this._enrichAbortController) {
                            this._enrichAbortController.abort();
                            this._enrichAbortController = null;
                        }
                        // TASK-94 Codex P1：離頁時清最後一片 flush dwell timer，避免 timer 事後
                        // 觸發 finalize（checkMissing fetch / state 變更）clobber 已離頁狀態。
                        if (this._flushTimer) {
                            clearTimeout(this._flushTimer);
                            this._flushTimer = null;
                        }
                    }
                });
            }

            // 初始載入
            await this.loadConfig();
            this.loadStats();
            this.checkNfoUpdates();

            // T7b: 恢復日誌（logOutput 為 scanner.html 靜態 x-ref 元素，
            // init 時早已 mount，直接同步還原、無需等 $nextTick）
            this.restoreLogs();

            // T10: 觸發 missing check（loadStats 後）
            this.checkMissing();

            // T10: restore pending enrich
            const pending = localStorage.getItem('avlist_enrich_pending');
            if (pending) {
                try {
                    const items = JSON.parse(pending);
                    if (Array.isArray(items) && items.length > 0) {
                        this.missingItems = items;
                        this.resumePillVisible = true;
                    }
                } catch { localStorage.removeItem('avlist_enrich_pending'); }
            }
        },

        // ===== Leave Guard =====
        shouldWarnBeforeLeave() {
            // T7b: 改為讀取 Alpine state，而非全域變數
            if (this.isGenerating) {
                return {
                    shouldWarn: true,
                    message: window.t('scanner.leave_warning.generating'),
                    useModal: false
                };
            }
            // T2(40c): Jellyfin check 進行中觸發離頁確認
            if (this.jellyfinCheckState === 'checking') {
                return {
                    shouldWarn: true,
                    message: window.t('scanner.leave_warning.image_check'),
                    useModal: false
                };
            }
            if (this.isFolderDirty) {
                return {
                    shouldWarn: true,
                    message: window.t('scanner.leave_warning.folder_dirty'),
                    useModal: true
                };
            }
            return { shouldWarn: false };
        },

        // ===== Config Methods =====
        async loadConfig() {
            this.folderSnapshot = null;

            try {
                const resp = await fetch('/api/config');
                const result = await resp.json();
                if (result.success) {
                    this.config = result.data;
                    this.directories = this.config.gallery?.directories || [];
                    const availableSources = this.tagSourceOptions;
                    if (!availableSources.some((source) => source.id === this.tagSourceUpdateSource)) {
                        this.tagSourceUpdateSource = availableSources[0]?.id || 'auto';
                    }
                    if (!availableSources.some((source) => source.id === this.renameSource)) {
                        this.renameSource = availableSources[0]?.id || 'auto';
                    }
                    // response-only：後端解析出的實際輸出路徑，供「輸出到」顯示
                    this.resolvedGalleryOutputPath = result.resolved?.gallery_output_path || '';

                    // T7b: 不再需要同步全域變數（core.js 已刪除）

                    // 建立快照
                    this.folderSnapshot = JSON.stringify(this.directories);
                }
            } catch (e) {
                console.error('載入設定失敗:', e);
            }
        },

        async saveConfig() {
            try {
                this.config.gallery = this.config.gallery || {};
                this.config.gallery.directories = this.directories;

                const resp = await fetch('/api/config', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.config)
                });
                const result = await resp.json();
                if (result.success) {
                    this.configDirty = false;
                    this.folderSnapshot = JSON.stringify(this.directories);
                    this.showToast(window.t('scanner.toast.config_saved'), 'success');
                    return true;
                } else {
                    this.showToast(window.t('scanner.toast.save_failed', { error: result.error || window.t('common.unknown_error') }), 'error');
                    return false;
                }
            } catch (e) {
                console.error('儲存失敗:', e);
                this.showToast(window.t('scanner.toast.save_failed', { error: e.message }), 'error');
                return false;
            }
        },

        // ===== Stats Methods =====
        async loadStats() {
            try {
                const resp = await fetch('/api/gallery/stats');
                const result = await resp.json();
                if (result.success && result.data) {
                    const stats = result.data;
                    if (stats.total > 0) {
                        this.statsVisible = true;
                        this.statTotal = stats.total;

                        if (stats.last_run) {
                            const lastRun = new Date(stats.last_run);
                            const timeStr = lastRun.toLocaleString('zh-TW', {
                                month: 'numeric',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit'
                            });
                            let runInfo = window.t('scanner.stats.last_run_prefix') + timeStr;
                            if (stats.last_added !== null && stats.last_added !== undefined) {
                                runInfo += ' ' + window.t('scanner.stats.last_added', { count: stats.last_added });
                            }
                            this.statLastRun = runInfo;
                        }
                    }
                }
            } catch (e) {
                console.error('載入統計失敗:', e);
            }
        },

        async checkNfoUpdates() {
            try {
                const resp = await fetch('/api/gallery/update-check');
                const result = await resp.json();
                if (!result.success || !result.data) return;
                const count = result.data.need_update || 0;
                this.nfoNeedUpdateCount = count;
                this.nfoUpdatePaths = Array.isArray(result.data.paths) ? result.data.paths : [];
                this.nfoUpdateItems = Array.isArray(result.data.items) ? result.data.items : [];
                this.nfoUpdateVisible = count > 0;
                this.nfoPreviewPage = 1;
                if (count === 0) {
                    this.nfoSelectedPaths = [];
                }
            } catch (e) {
                console.error('檢查 NFO 待補欄位失敗:', e);
            }
        },

        async clearCache() {
            this.clearCacheLoading = true;
            try {
                const resp = await fetch('/api/gallery/cache', { method: 'DELETE' });
                const result = await resp.json();
                if (result.success) {
                    this.showToast(window.t('scanner.toast.cache_cleared', { count: result.deleted }), 'success');
                    this.statTotal = 0;
                    this.statsVisible = false;
                    this.nfoUpdateVisible = false;
                    this.nfoNeedUpdateCount = 0;
                    this.nfoUpdatePaths = [];
                    this.nfoUpdateItems = [];
                    this.nfoSelectedPaths = [];
                    this.jellyfinImageVisible = false;
                    this.jellyfinCheckState = 'idle';
                    this.clearCacheModalOpen = false;
                    // T10: reset missing pill state
                    this.missingPillVisible = false;
                    this.resumePillVisible = false;
                    this.missingItems = [];
                    localStorage.removeItem('avlist_enrich_pending');
                } else {
                    this.showToast(window.t('scanner.toast.clear_failed', { error: result.error || window.t('common.unknown_error') }), 'error');
                }
            } catch (e) {
                this.showToast(window.t('scanner.toast.clear_failed', { error: e.message }), 'error');
            } finally {
                this.clearCacheLoading = false;
            }
        },

        // ===== T6d: Jellyfin Image Check =====
        async checkJellyfinImages() {
            // 正向白名單（fail-closed）：config 未載入 / 載入失敗 / 缺 external_manager 時
            // 一律不補圖（對應後端 STEM_IMAGE_MODES）。勿改回 === 'off'（undefined 會 fail-open）。
            if (!['jellyfin', 'emby', 'kodi'].includes(this.config?.scraper?.external_manager)) return;

            // T2(40c): 取消上一次未完成的請求（防重複點擊）
            if (this._jellyfinCheckController) {
                this._jellyfinCheckController.abort();
            }
            const controller = new AbortController();
            this._jellyfinCheckController = controller;
            this.jellyfinCheckState = 'checking';

            try {
                const resp = await fetch('/api/gallery/jellyfin-check', {
                    signal: controller.signal
                });
                const data = await resp.json();
                if (!data.success) {
                    console.error('Jellyfin check API error:', data.error);
                    this.jellyfinCheckState = 'idle';
                    return;
                }
                if (data.data.need_update > 0) {
                    this.jellyfinImageCount = data.data.need_update;
                    this.jellyfinItems = data.data.items ?? [];
                    this.jellyfinImageVisible = true;
                } else {
                    this.jellyfinImageCount = 0;
                    this.jellyfinItems = [];
                    this.jellyfinImageVisible = false;
                }
                this.jellyfinCheckState = 'done';
            } catch (e) {
                if (e.name === 'AbortError') {
                    this.jellyfinCheckState = 'idle';
                    return;
                }
                console.error('Jellyfin check failed:', e);
                this.jellyfinCheckState = 'idle';
            } finally {
                if (this._jellyfinCheckController === controller) {
                    this._jellyfinCheckController = null;
                }
            }
        },

        // ===== Folder Management =====
        async selectFolder() {
            if (this.shellMode === 'client' || typeof window.pywebview === 'undefined' || !window.pywebview.api) {
                this.openBrowseDir('scanner', (path) => { this.addFolderPath(path); });
                return;
            }

            try {
                const result = await window.pywebview.api.select_folder();

                if (result && result.folder) {
                    this.addFolderPath(result.folder);
                } else if (Array.isArray(result) && result.length > 0) {
                    const firstFile = result[0];
                    const lastSep = Math.max(firstFile.lastIndexOf('\\'), firstFile.lastIndexOf('/'));
                    const folderPath = lastSep > 0 ? firstFile.substring(0, lastSep) : null;
                    if (folderPath) {
                        this.addFolderPath(folderPath);
                    }
                }
            } catch (e) {
                console.error('[AVList] 選取資料夾失敗:', e);
            }
        },

        addFolderPath(folderPath) {
            if (!this.directories.some(d => dirPath(d) === folderPath)) {
                this.directories.push({ path: folderPath, readonly: false, output_path: '' });
                this.configDirty = true;
            } else {
                this.showToast(window.t('scanner.toast.folder_already_added'), 'warning');
            }
        },

        toggleManualInput() {
            this.manualInputVisible = !this.manualInputVisible;
            if (this.manualInputVisible) {
                this.$nextTick(() => {
                    this.$refs.manualPathInput.focus();
                });
            }
        },

        addManualPath() {
            const path = this.manualPath.trim();
            if (!path) return;

            if (this.directories.some(d => dirPath(d) === path)) {
                this.showToast(window.t('scanner.toast.folder_already_added'), 'warning');
                return;
            }

            this.directories.push({ path: path, readonly: false, output_path: '' });
            this.configDirty = true;
            this.manualPath = '';
        },

        removeDirectory(idx) {
            this.directories.splice(idx, 1);
            this.configDirty = true;
        },

        // ===== Drag-drop Methods =====
        handleDragOver(e) {
            e.preventDefault();
            if (!e.dataTransfer.types.includes('Files')) return;
            if (!this.showDragOverlay) this.showDragOverlay = true;  // CD-A4
            clearTimeout(_dragTimeoutHandle);
            _dragTimeoutHandle = setTimeout(() => this.handleDragTimeout(), DRAG_OVERLAY_TIMEOUT_MS);
        },

        // CD-A6：逾時 callback 也是「有邏輯的程式」，必須具名、能被 node:test 直接呼叫——
        // 不得沿用匿名 setTimeout(() => {...})，這一段正是「按 Esc 後覆蓋層會不會消失」的判定點本身。
        handleDragTimeout() {
            if (this.showDragOverlay) this.showDragOverlay = false;  // CD-A4
            _dragTimeoutHandle = null;
        },

        handleDrop(e) {
            e.preventDefault();
            clearTimeout(_dragTimeoutHandle);
            _dragTimeoutHandle = null;
            if (this.showDragOverlay) this.showDragOverlay = false;
            // 桌面版由 pywebview 端的 window.handleFolderDrop 接手（見 main.js），這裡不插手
            if (typeof window.pywebview !== 'undefined' && window.pywebview.api) return;
            this.showToast(window.t('scanner.toast.browse_dir_fallback'), 'info');
            this.openBrowseDir('scanner', (path) => { this.addFolderPath(path); });
        },

        // ===== TASK-90b-T1: Readonly Confirm Modal Actions =====
        onReadonlyToggleClick(idx) {
            const dir = this.directories[idx];
            if (!dir) return;
            if (dir.readonly) {
                // 勾→未勾：不攔截，直接生效（Non-Goal 明定不加確認）
                dir.readonly = false;
                this.configDirty = true;
            } else {
                // 未勾→勾：不立即改 dir.readonly，開 modal
                this.readonlyConfirmTargetIdx = idx;
                this.readonlyConfirmModalOpen = true;
            }
        },

        readonlyConfirmAccept() {
            if (this.readonlyConfirmTargetIdx == null || !this.directories[this.readonlyConfirmTargetIdx]) {
                this.readonlyConfirmModalOpen = false;
                return;
            }
            this.directories[this.readonlyConfirmTargetIdx].readonly = true;
            this.configDirty = true;
            this.readonlyConfirmModalOpen = false;
            this.readonlyConfirmTargetIdx = null;
        },

        readonlyConfirmCancel() {
            this.readonlyConfirmModalOpen = false;
            this.readonlyConfirmTargetIdx = null;
        },

        // ===== Dirty Check Modal Actions =====
        dirtyCheckCancel() {
            this.dirtyCheckModalOpen = false;
            this.pendingNavigationUrl = '';
        },

        async dirtyCheckDiscard() {
            await this.loadConfig();
            this.dirtyCheckModalOpen = false;
            if (this.pendingNavigationUrl) {
                const url = this.pendingNavigationUrl;
                // dirty state cleared by loadConfig(); beforeLeave will now return true
                // → __leavePage triggers _doCleanup (closes eventSource + clears timers)
                if (window.__leavePage) {
                    window.__leavePage(url);
                }
                window.location.href = url;
            }
        },

        async dirtyCheckSave() {
            const saved = await this.saveConfig();
            if (saved) {
                this.dirtyCheckModalOpen = false;
                if (this.pendingNavigationUrl) {
                    const url = this.pendingNavigationUrl;
                    // dirty state cleared by saveConfig(); beforeLeave will now return true
                    // → __leavePage triggers _doCleanup (closes eventSource + clears timers)
                    if (window.__leavePage) {
                        window.__leavePage(url);
                    }
                    window.location.href = url;
                }
            }
            // If save failed, modal stays open, user sees toast error
        },

        // ===== Utility Methods =====
        escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        },

        // ===== T7b: Log System =====
        /**
         * Log 系統效能設計說明
         *
         * 使用 insertAdjacentHTML（而非 Alpine x-for）的原因：
         * 1. Scanner 典型場景會產生 200-3000 條 log
         * 2. Alpine x-for 重渲染在大量 log 時慢 10x（100-300ms vs 20-40ms）
         * 3. 批次處理 + insertAdjacentHTML 可維持流暢體驗（< 40ms）
         *
         * 實作特性：
         * - 100ms debounce 批次插入（減少 DOM 操作）
         * - CSS-only 篩選（filter-all/error/warn class，零 JS 開銷）
         * - 雙重儲存：logEntries（結構化）+ logHtml（快速恢復）
         */
        addLog(level, message) {
            // T7d: 加入結構化陣列
            this.logEntries.push({ level, message, timestamp: Date.now() });
            if (level === 'error') {
                this.logPanelExpanded = true;
            }

            const cls = level === 'error' ? 'log-error' :
                        level === 'warn' ? 'log-warn' : 'log-info';
            const escaped = this.escapeHtml(message);
            this.logBatch.push(`<div class="${cls}" data-level="${level}">${escaped}</div>`);

            if (!this.logTimer) {
                this.logTimer = setTimeout(() => this.flushLogs(), 100);
            }
        },

        flushLogs() {
            if (this.logBatch.length === 0) {
                this.logTimer = null;
                return;
            }

            const logOutput = this.$refs.logOutput;
            logOutput.insertAdjacentHTML('beforeend', this.logBatch.join(''));
            logOutput.scrollTop = logOutput.scrollHeight;

            // 更新 Alpine state（供 restoreLogs 使用）
            this.logHtml = logOutput.innerHTML;

            // 儲存到 localStorage
            localStorage.setItem('avlist_logs', this.logHtml);

            this.logBatch = [];
            this.logTimer = null;
        },

        restoreLogs() {
            const savedLogs = localStorage.getItem('avlist_logs');
            const wasGenerating = localStorage.getItem('avlist_generating') === 'true';

            if (savedLogs) {
                const logOutput = this.$refs.logOutput;
                logOutput.innerHTML = savedLogs;
                this.logHtml = savedLogs;

                // T7d: 解析 HTML，重建 logEntries（相容舊格式無 data-level）
                this.logEntries = [];
                const logDivs = logOutput.querySelectorAll('.log-info, .log-warn, .log-error');
                logDivs.forEach(div => {
                    let level = div.getAttribute('data-level');
                    if (!level) {
                        if (div.classList.contains('log-error')) level = 'error';
                        else if (div.classList.contains('log-warn')) level = 'warn';
                        else level = 'info';
                    }
                    this.logEntries.push({ level, message: div.textContent, timestamp: Date.now() });
                });

                if (wasGenerating) {
                    this.addLog('warn', window.t('scanner.stats.log_interrupted'));
                    this.flushLogs();
                    localStorage.setItem('avlist_generating', 'false');
                }

                const lastStatus = localStorage.getItem('avlist_last_status');
                if (lastStatus) {
                    this.progressStatus = lastStatus;
                }

                // 如果有未完成的任務，顯示 progress section
                if (wasGenerating || savedLogs) {
                    this.state = 'idle';  // 重置狀態為 idle（已中斷）
                }
            }
        },

        clearLogs() {
            localStorage.removeItem('avlist_logs');
            localStorage.removeItem('avlist_generating');
            localStorage.removeItem('avlist_last_status');
            this.logHtml = '';
            this.logEntries = [];
            this.logPanelExpanded = false;
            this.$refs.logOutput.innerHTML = '';
        },

        // ===== T7d: Log Terminal 增強 =====
        toggleLogPanel() {
            this.logPanelExpanded = !this.logPanelExpanded;
        },

        setLogFilter(filter) {
            this.logFilter = filter;
            if (filter !== 'all') {
                this.logPanelExpanded = true;
            }
        },

        clearLogsDisplay() {
            this.logHtml = '';
            this.logEntries = [];
            this.$refs.logOutput.innerHTML = '';
        },

        copyLogs() {
            if (this.logEntries.length === 0) {
                this.showToast(window.t('scanner.toast.no_logs'), 'info');
                return;
            }

            const text = this.logEntries.map(entry => entry.message).join('\n');

            // T3.6 P2 fix: guard against undefined navigator.clipboard (HTTP / older WebView)
            // 若無 Clipboard API，直接走 fail modal fallback；
            // 否則 .then/.catch chain 會在 sync property access 階段就 TypeError，.catch 不會跑。
            if (!navigator.clipboard?.writeText) {
                this.openCopyFailModal(text);
                return;
            }

            navigator.clipboard.writeText(text).then(() => {
                this.showToast(window.t('scanner.toast.logs_copied', { count: this.logEntries.length }), 'success');
            }).catch(() => {
                this.openCopyFailModal(text);
            });
        },

        // T3.6: Copy Logs Fail Modal — fluent-modal <pre> dump fallback
        openCopyFailModal(text) {
            this.copyFailDump = text || '';
            this.copyFailModalOpen = true;
        },

        closeCopyFailModal() {
            this.copyFailModalOpen = false;
            this.copyFailDump = '';
        },

        confirmClearAll() {
            const hasLogs = this.logEntries.length > 0 || localStorage.getItem('avlist_logs');
            if (!hasLogs) {
                this.showToast(window.t('scanner.toast.no_logs'), 'info');
                return;
            }

            // eslint-disable-next-line no-alert -- clearLogs confirm, backlog migration to fluent-modal, reviewed 2026-05-03
            if (confirm(window.t('scanner.toast.confirm_clear_logs'))) {
                this.clearLogs();
                this.showToast(window.t('scanner.toast.logs_cleared'), 'success');
            }
        },

        // ===== r18: Task control =====
        toggleMaintenance() {
            this.maintenanceExpanded = !this.maintenanceExpanded;
        },

        _formatDuration(seconds) {
            const value = Math.max(0, Math.floor(seconds || 0));
            if (value < 60) return window.t('scanner.task.seconds', { value });
            const minutes = Math.floor(value / 60);
            const remainder = value % 60;
            return window.t('scanner.task.minutes', { minutes, seconds: remainder });
        },

        _startTask(kind, status, total = 0) {
            this._stopTaskTimer();
            this.taskKind = kind;
            this.taskStartedAt = Date.now();
            this.taskEndedAt = 0;
            this.taskClockTick = this.taskStartedAt;
            this.taskCurrentItem = '';
            this.taskSuccessCount = 0;
            this.taskFailedCount = 0;
            this.taskSkippedCount = 0;
            this.taskChangedCount = 0;
            this.taskEtaSeconds = 0;
            this.taskSummaryText = '';
            this.taskFailedItems = [];
            this.progressStatus = status;
            this.progressCurrent = 0;
            this.progressTotal = total;
            this.maintenanceExpanded = true;
            this.taskTimer = setInterval(() => {
                this.taskClockTick = Date.now();
            }, 1000);
        },

        _stopTaskTimer() {
            if (this.taskTimer) {
                clearInterval(this.taskTimer);
                this.taskTimer = null;
            }
        },

        _applyTaskMetrics(data) {
            if (data?.number || data?.num) {
                this.taskCurrentItem = data.number || data.num;
            }
            if (typeof data?.success === 'number') this.taskSuccessCount = data.success;
            if (typeof data?.failed === 'number') this.taskFailedCount = data.failed;
            if (typeof data?.skipped === 'number') this.taskSkippedCount = data.skipped;
            if (typeof data?.changed === 'number') this.taskChangedCount = data.changed;
            if (typeof data?.eta_seconds === 'number') this.taskEtaSeconds = data.eta_seconds;
        },

        _syncTaskSummary(summary) {
            if (!summary) return;
            if (typeof summary.success === 'number') this.taskSuccessCount = summary.success;
            if (typeof summary.failed === 'number') this.taskFailedCount = summary.failed;
            if (typeof summary.skipped === 'number') this.taskSkippedCount = summary.skipped;
            if (typeof summary.changed === 'number') this.taskChangedCount = summary.changed;
            if (Array.isArray(summary.failed_items)) this.taskFailedItems = summary.failed_items;
        },

        _finishTask(nextState, status, summary = null, failedItems = null) {
            this.state = nextState;
            this.taskEndedAt = Date.now();
            this._stopTaskTimer();
            this.taskCurrentItem = '';
            this.progressStatus = status || this.progressStatus;
            this.taskSummaryText = status || '';
            this._syncTaskSummary(summary);
            if (Array.isArray(failedItems)) {
                this.taskFailedItems = failedItems;
            } else if (Array.isArray(summary?.failed_items)) {
                this.taskFailedItems = summary.failed_items;
            }
            localStorage.setItem('avlist_generating', 'false');
            localStorage.setItem('avlist_last_status', this.progressStatus);
        },

        cancelCurrentTask() {
            if (!this.isGenerating) return;

            if (this.state === 'enriching' && this._enrichAbortController) {
                this._enrichAbortController.abort();
                this._enrichAbortController = null;
            }
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
            this._finishTask(
                'cancelled',
                window.t('scanner.task.cancelled'),
                {
                    success: this.taskSuccessDisplay,
                    failed: this.taskFailedDisplay,
                    skipped: this.taskSkippedCount,
                    failed_items: this.taskFailedItems,
                }
            );
            this.addLog('warn', window.t('scanner.task.cancelled_log'));
            this.flushLogs();
            this.showToast(window.t('scanner.task.cancelled'), 'info', 3000);
        },

        retryFailedItems() {
            if (!this.taskCanRetry) return;
            const numbers = [...new Set(this.taskFailedItems.map(item => item.number).filter(Boolean))];
            const paths = [...new Set(this.taskFailedItems.map(item => item.path).filter(Boolean))];

            if (this.taskKind === 'nfo-update' && paths.length > 0) {
                this.openNfoUpdateConfirm(paths);
                return;
            }
            if (['tag-preview', 'tag-update'].includes(this.taskKind) && numbers.length > 0) {
                this.startTagSourcePreview({
                    numbers,
                    applyAfter: false,
                    retryMode: true,
                });
                return;
            }
            if (this.taskKind === 'jellyfin-update') {
                this.jellyfinImageCount = Math.max(this.taskFailedItems.length, 1);
                this.jellyfinImageVisible = true;
                this.runJellyfinImageUpdate();
            }
        },

        // ===== T7b: Generate Flow =====
        async generate() {
            // 互斥鎖定：generating/nfoUpdating 時不可再次執行
            if (this.isGenerating) return;

            if (this.directories.length === 0) {
                this.showToast(window.t('scanner.toast.no_folder'), 'info');
                return;
            }

            // 自動儲存設定
            // configDirty：設定表單改動；isFolderDirty：資料夾清單改動（含 readonly 切換、
            // output_path 編輯）。後者不會設 configDirty，若不納入 gate，readonly/輸出路徑的
            // 編輯不會存檔，generate 會用舊的持久化設定 → readonly 路徑永遠不執行（PR#91 ①）。
            if (this.configDirty || this.isFolderDirty) {
                const saved = await this.saveConfig();
                if (!saved) return;
            }

            // 重置狀態
            this.state = 'generating';
            this._startTask('generate', window.t('scanner.stats.status_preparing'));
            this.outputPath = '';
            this.nfoUpdateVisible = false;
            this.clearLogs();

            // 設置 localStorage 標記
            localStorage.setItem('avlist_generating', 'true');

            try {
                this.eventSource = new EventSource('/api/gallery/generate');

                this.eventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);

                    if (data.type === 'progress') {
                        this.progressStatus = data.status;
                        this.progressCurrent = data.current;
                        this.progressTotal = data.total;
                        this._applyTaskMetrics(data);
                        localStorage.setItem('avlist_last_status', data.status);
                    } else if (data.type === 'log') {
                        this.addLog(data.level, data.message);
                    } else if (data.type === 'done') {
                        this.eventSource.close();
                        this.eventSource = null;
                        this.progressStatus = window.t('scanner.stats.status_done_count', { count: data.video_count });
                        this.progressCurrent = this.progressTotal;
                        this.outputPath = data.output_path;
                        this._finishTask(
                            'done',
                            this.progressStatus,
                            { success: data.video_count || 0, failed: 0, skipped: 0 }
                        );

                        localStorage.setItem('avlist_generating', 'false');
                        localStorage.setItem('avlist_last_status', window.t('scanner.stats.status_done'));
                        localStorage.removeItem('avlist_state');  // 清除 viewer 狀態

                        // 處理 NFO 更新提示
                        if (data.session_update && data.session_update.count > 0) {
                            this.nfoNeedUpdateCount = data.session_update.count;
                            this.nfoUpdatePaths = data.session_update.paths;
                            this.nfoUpdateItems = data.session_update.items ?? [];
                            this.nfoUpdateVisible = true;
                        } else {
                            this.nfoNeedUpdateCount = 0;
                            this.nfoUpdatePaths = [];
                            this.nfoUpdateItems = [];
                            this.nfoUpdateVisible = false;
                        }

                        // 88c-P2: 唯讀來源整源失敗（source_errors）或個別影片失敗（failed）時
                        // 完成 toast 走 warn，不可純 success（後端完成通知已同步納入兩者）。
                        // no_scrape 是「線上查無 metadata」的正常情況，不計為失敗（PR#91 ②）。
                        // 89b-T6（Codex P1）：後端完成通知 warn-gate 已納入 no_output（未設輸出夾）/
                        // unreachable（來源無法連線）/ partial（partial-scan 略過刪除偵測）三種情境
                        // （web/routers/scanner.py），但 scanner 頁自己的完成 toast 沒同步 consult，
                        // 三者原本仍顯示 success，違反 spec §89b.3.3「警告並略過，不誤報成功」。
                        // pruned 是正常成功結果（非警告），不納入此判斷。
                        const srcErrors = (data.readonly_stats && data.readonly_stats.source_errors) || 0;
                        const failedCount = (data.readonly_stats && data.readonly_stats.failed) || 0;
                        const noOutput = (data.readonly_stats && data.readonly_stats.no_output) || 0;
                        const unreachable = (data.readonly_stats && data.readonly_stats.unreachable) || 0;
                        const partial = (data.readonly_stats && data.readonly_stats.partial) || 0;
                        if (srcErrors > 0 || failedCount > 0 || noOutput > 0 || unreachable > 0 || partial > 0) {
                            const parts = [];
                            if (srcErrors > 0) parts.push(window.t('scanner.toast.readonly_failed_count', { count: srcErrors }));
                            if (failedCount > 0) parts.push(window.t('scanner.toast.failed_count', { count: failedCount }));
                            if (unreachable > 0) parts.push(window.t('scanner.toast.unreachable_count', { count: unreachable }));
                            if (partial > 0) parts.push(window.t('scanner.toast.partial_count', { count: partial }));
                            if (noOutput > 0) parts.push(window.t('scanner.toast.no_output_count', { count: noOutput }));
                            this.showToast(
                                window.t('scanner.toast.done_with_warnings', { count: data.video_count, parts: parts.join('、') }),
                                'warn'
                            );
                        } else {
                            this.showToast(window.t('scanner.toast.generate_success', { count: data.video_count }), 'success');
                        }

                        const missingNfo = Number(data.missing_nfo) || 0;
                        if (missingNfo > 0) {
                            this.showToast(
                                window.t('scanner.toast.missing_nfo_warning', { count: missingNfo }),
                                'warn',
                                8000
                            );
                        }

                        // a5: Windows 長路徑警告
                        if (data.long_paths && data.long_paths.length > 0) {
                            this.showToast(
                                window.t('scanner.toast.long_paths_warning', { count: data.long_paths.length }),
                                'warn',
                                6000
                            );
                        }

                        this.flushLogs();

                        // 刷新統計（不含 NFO 檢查）
                        this.loadStats();

                        // T10: 掃描完成後檢查缺失 NFO/封面
                        this.checkMissing();

                        // 更新資料夾快照（generate 成功視為儲存）
                        this.folderSnapshot = JSON.stringify(this.directories);
                    } else if (data.type === 'error') {
                        this.eventSource.close();
                        this.eventSource = null;
                        this.addLog('error', window.t('scanner.stats.log_error_prefix', { message: data.message }));
                        this._finishTask('error', data.message || window.t('scanner.task.failed'));
                        this.flushLogs();
                        localStorage.setItem('avlist_generating', 'false');
                    }
                };

                this.eventSource.onerror = () => {
                    if (this.state === 'done' || this.state === 'cancelled') return;
                    this.eventSource.close();
                    this.eventSource = null;
                    this.addLog('error', window.t('scanner.stats.log_disconnected'));
                    this._finishTask('error', window.t('scanner.task.failed'));
                    this.flushLogs();
                    localStorage.setItem('avlist_generating', 'false');
                };
            } catch (e) {
                this._finishTask('error', window.t('scanner.task.failed'));
                localStorage.setItem('avlist_generating', 'false');
                console.error('[Scanner] generate error:', e);
                this.showToast(window.t('scanner.toast.generate_error'), 'error', 4000);
            }
        },

        // ===== T7b: NFO Update Flow =====
        openNfoUpdateConfirm(paths = []) {
            if (this.isGenerating) return;
            const candidates = paths.length > 0
                ? paths.slice()
                : (this.nfoUpdatePaths.length > 0 ? this.nfoUpdatePaths.slice() : []);
            if (candidates.length === 0 && this.nfoNeedUpdateCount > 0) {
                this.checkNfoUpdates().then(() => {
                    if (this.nfoUpdatePaths.length > 0) this.openNfoUpdateConfirm(paths);
                    else this.showToast(window.t('scanner.toast.no_nfo_update_needed'), 'info');
                });
                return;
            }
            if (candidates.length === 0) {
                this.showToast(window.t('scanner.toast.no_nfo_update_needed'), 'info');
                return;
            }
            this.nfoSelectedPaths = candidates.slice();
            this.nfoPreviewPage = 1;
            this.nfoUpdateConfirmModalOpen = true;
        },

        cancelNfoUpdate() {
            this.nfoUpdateConfirmModalOpen = false;
            this.nfoSelectedPaths = [];
        },

        confirmNfoUpdate() {
            if (this.nfoUpdateConfirmDisabled) return;
            const paths = this.nfoSelectedPaths.slice();
            this.nfoUpdateConfirmModalOpen = false;
            this.runNfoUpdate(paths);
        },

        async runNfoUpdate(paths = []) {
            // 互斥鎖定
            if (this.isGenerating) return;

            const selectedPaths = paths.length > 0 ? paths.slice() : this.nfoSelectedPaths.slice();
            const expectedCount = selectedPaths.length;
            if (expectedCount === 0) {
                this.showToast(window.t('scanner.toast.no_nfo_update_needed'), 'info');
                return;
            }

            // 重置狀態
            this.state = 'nfoUpdating';
            this._startTask('nfo-update', window.t('scanner.stats.status_preparing'), expectedCount);
            this.clearLogs();

            localStorage.setItem('avlist_generating', 'true');

            try {
                const params = new URLSearchParams({
                    backup: this.nfoUpdateBackupEnabled ? 'true' : 'false',
                });
                for (const path of selectedPaths) params.append('path', path);
                this.eventSource = new EventSource(`/api/gallery/update?${params.toString()}`);

                this.eventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);

                    if (data.type === 'progress') {
                        this.progressStatus = data.status;
                        this.progressCurrent = data.current;
                        this.progressTotal = data.total;
                        this._applyTaskMetrics(data);
                        localStorage.setItem('avlist_last_status', data.status);
                    } else if (data.type === 'log') {
                        this.addLog(data.level, data.message);
                    } else if (data.type === 'done') {
                        this.eventSource.close();
                        this.eventSource = null;
                        this.progressCurrent = this.progressTotal;
                        this._finishTask(
                            data.summary?.cancelled ? 'cancelled' : 'done',
                            data.message || window.t('scanner.stats.status_done'),
                            data.summary || null
                        );

                        localStorage.setItem('avlist_generating', 'false');
                        localStorage.setItem('avlist_last_status', data.message || window.t('scanner.stats.status_done'));

                        const failed = data.summary?.failed || 0;
                        this.showToast(
                            failed > 0 ? window.t('scanner.task.done_with_failures', { failed }) : window.t('scanner.toast.nfo_update_done'),
                            failed > 0 ? 'warn' : 'success'
                        );
                        if (data.message) {
                            this.addLog('info', data.message);
                        }
                        this.flushLogs();

                        // 隱藏 NFO 更新按鈕（已完成）
                        this.nfoNeedUpdateCount = Math.max(
                            0,
                            this.nfoNeedUpdateCount - (data.summary?.success || 0)
                        );
                        const completed = new Set(selectedPaths);
                        this.nfoUpdatePaths = this.nfoUpdatePaths.filter((path) => !completed.has(path));
                        this.nfoUpdateItems = this.nfoUpdateItems.filter((item) => !completed.has(item.path));
                        this.nfoSelectedPaths = [];
                        this.nfoUpdateVisible = this.nfoNeedUpdateCount > 0;
                        this.checkNfoUpdates();
                    } else if (data.type === 'error') {
                        this.eventSource.close();
                        this.eventSource = null;
                        this.addLog('error', window.t('scanner.stats.log_error_prefix', { message: data.message }));
                        this._finishTask('error', data.message || window.t('scanner.task.failed'));
                        this.flushLogs();
                        localStorage.setItem('avlist_generating', 'false');
                    }
                };

                this.eventSource.onerror = () => {
                    if (this.state === 'done' || this.state === 'cancelled') return;
                    this.eventSource.close();
                    this.eventSource = null;
                    this.addLog('error', window.t('scanner.stats.log_disconnected'));
                    this._finishTask('error', window.t('scanner.task.failed'));
                    this.flushLogs();
                    localStorage.setItem('avlist_generating', 'false');
                };
            } catch (e) {
                this._finishTask('error', window.t('scanner.task.failed'));
                localStorage.setItem('avlist_generating', 'false');
                console.error('[Scanner] runNfoUpdate error:', e);
                this.showToast(window.t('scanner.toast.nfo_update_error'), 'error', 4000);
            }
        },

        setNfoPreviewPage(delta) {
            this.nfoPreviewPage = Math.min(
                this.nfoUpdatePageCount,
                Math.max(1, this.nfoPreviewPage + delta)
            );
        },

        toggleNfoSelection() {
            if (this.nfoSelectedCount === this.nfoUpdatePaths.length) {
                this.nfoSelectedPaths = [];
            } else {
                this.nfoSelectedPaths = this.nfoUpdatePaths.slice();
            }
        },

        // ===== r16: Batch tag source update =====
        openTagSourceUpdateConfirm() {
            if (this.tagSourceUpdateButtonDisabled) return;
            this.startTagSourcePreview({ applyAfter: true });
        },

        previewTagSourceUpdate() {
            if (this.tagSourceUpdateButtonDisabled) return;
            this.startTagSourcePreview({ applyAfter: false });
        },

        cancelTagSourceUpdate() {
            this.tagSourceConfirmModalOpen = false;
            this.tagSourcePreviewOnly = false;
        },

        setTagSourcePreviewPage(delta) {
            this.tagSourcePreviewPage = Math.min(
                this.tagSourcePreviewPageCount,
                Math.max(1, this.tagSourcePreviewPage + delta)
            );
        },

        toggleTagSourceSelection() {
            const changed = [...new Set(this.tagSourcePreviewChangedItems.map((item) => item.number))];
            if (this.tagSourceSelectedChangedCount === changed.length) {
                this.tagSourcePreviewNumbers = [];
            } else {
                this.tagSourcePreviewNumbers = changed;
            }
        },

        confirmTagSourceUpdate() {
            if (this.tagSourceConfirmButtonDisabled) return;
            this.tagSourceConfirmModalOpen = false;
            this.startTagSourceUpdate({
                numbers: this.tagSourcePreviewNumbers,
                backup: this.tagSourceBackupEnabled,
            });
        },

        async startTagSourcePreview({ applyAfter = false, numbers = [], retryMode = false } = {}) {
            if (this.isGenerating || !this.tagSourceUpdateSource) return;

            const sourceId = this.tagSourceUpdateSource;
            const sourceLabel = this.selectedTagSourceLabel;
            this.tagSourcePreviewSource = sourceId;
            this.tagSourcePreviewSourceLabel = sourceLabel;
            this.tagSourcePreviewOnly = !applyAfter;
            this.tagSourcePreviewNumbers = numbers.slice();
            this.state = 'tagSourcePreviewing';
            this._startTask(
                'tag-preview',
                retryMode
                    ? window.t('scanner.stats.tag_source_retry_previewing')
                    : window.t('scanner.stats.tag_source_previewing'),
                numbers.length || this.statTotal
            );
            this.clearLogs();
            localStorage.setItem('avlist_generating', 'true');

            const params = new URLSearchParams({ source: sourceId });
            if (numbers.length > 0) params.set('numbers', numbers.join(','));
            this.eventSource = new EventSource(`/api/gallery/tag-source-preview?${params.toString()}`);

            this.eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === 'progress') {
                    this.progressStatus = data.status || window.t('scanner.stats.tag_source_previewing');
                    this.progressCurrent = data.current || 0;
                    this.progressTotal = data.total || this.progressTotal;
                    this._applyTaskMetrics(data);
                    localStorage.setItem('avlist_last_status', this.progressStatus);
                } else if (data.type === 'log') {
                    this.addLog(data.level || 'info', data.message || '');
                } else if (data.type === 'done') {
                    this.eventSource.close();
                    this.eventSource = null;
                    this.progressCurrent = this.progressTotal;
                    this.tagSourcePreviewData = data.summary || null;
                    const changedNumbers = Array.isArray(data.summary?.changed_numbers)
                        ? data.summary.changed_numbers
                        : (data.summary?.items || [])
                            .filter((item) => item.status === 'changed')
                            .map((item) => item.number);
                    this.tagSourcePreviewNumbers = [...new Set(changedNumbers.filter(Boolean))];
                    this.tagSourcePreviewPage = 1;
                    this._finishTask(
                        data.summary?.cancelled ? 'cancelled' : 'done',
                        data.message || window.t('scanner.stats.tag_source_preview_done'),
                        data.summary || null
                    );
                    this.tagSourceConfirmModalOpen = true;
                    const failed = data.summary?.failed || 0;
                    this.showToast(
                        data.message || window.t('scanner.stats.tag_source_preview_done'),
                        failed > 0 ? 'warn' : 'success',
                        4000
                    );
                    if (data.message) this.addLog('info', data.message);
                    this.flushLogs();
                } else if (data.type === 'error') {
                    this.eventSource.close();
                    this.eventSource = null;
                    this.addLog(
                        'error',
                        window.t('scanner.stats.log_error_prefix', { message: data.message || '' })
                    );
                    this._finishTask('error', data.message || window.t('scanner.task.failed'));
                    this.flushLogs();
                    this.showToast(window.t('scanner.toast.tag_source_update_error'), 'error', 4000);
                }
            };

            this.eventSource.onerror = () => {
                if (this.state === 'done' || this.state === 'error' || this.state === 'cancelled') return;
                this.eventSource.close();
                this.eventSource = null;
                this.addLog('error', window.t('scanner.stats.log_disconnected'));
                this._finishTask('error', window.t('scanner.task.failed'));
                this.flushLogs();
                this.showToast(window.t('scanner.toast.tag_source_update_error'), 'error', 4000);
            };
        },

        async startTagSourceUpdate({ numbers = [], backup = true } = {}) {
            if (this.isGenerating || !this.tagSourcePreviewSource) return;

            this.state = 'tagSourceUpdating';
            this._startTask(
                'tag-update',
                window.t('scanner.stats.tag_source_preparing'),
                numbers.length || this.statTotal
            );
            this.clearLogs();
            localStorage.setItem('avlist_generating', 'true');

            const params = new URLSearchParams({
                source: this.tagSourcePreviewSource,
                backup: backup ? 'true' : 'false',
            });
            if (numbers.length > 0) params.set('numbers', numbers.join(','));
            this.eventSource = new EventSource(`/api/gallery/tag-source-update?${params.toString()}`);

            this.eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === 'progress') {
                    this.progressStatus = data.status || window.t('scanner.stats.tag_source_updating');
                    this.progressCurrent = data.current || 0;
                    this.progressTotal = data.total || this.statTotal;
                    this._applyTaskMetrics(data);
                    localStorage.setItem('avlist_last_status', this.progressStatus);
                } else if (data.type === 'log') {
                    this.addLog(data.level || 'info', data.message || '');
                } else if (data.type === 'done') {
                    this.eventSource.close();
                    this.eventSource = null;
                    this.progressCurrent = this.progressTotal;
                    this._finishTask(
                        data.summary?.cancelled ? 'cancelled' : 'done',
                        data.message || window.t('scanner.stats.tag_source_done'),
                        data.summary || null
                    );
                    this.tagSourcePreviewData = data.summary || this.tagSourcePreviewData;
                    localStorage.setItem('avlist_generating', 'false');
                    const failed = data.summary?.failed || 0;
                    this.showToast(
                        failed > 0
                            ? window.t('scanner.task.done_with_failures', { failed })
                            : window.t('scanner.toast.tag_source_update_done'),
                        failed > 0 ? 'warn' : 'success',
                        4000
                    );
                    if (data.message) this.addLog('info', data.message);
                    this.flushLogs();
                } else if (data.type === 'error') {
                    this.eventSource.close();
                    this.eventSource = null;
                    this.addLog(
                        'error',
                        window.t('scanner.stats.log_error_prefix', { message: data.message || '' })
                    );
                    this._finishTask('error', data.message || window.t('scanner.task.failed'));
                    this.flushLogs();
                    localStorage.setItem('avlist_generating', 'false');
                }
            };

            this.eventSource.onerror = () => {
                if (this.state === 'done' || this.state === 'error' || this.state === 'cancelled') return;
                this.eventSource.close();
                this.eventSource = null;
                this.addLog('error', window.t('scanner.stats.log_disconnected'));
                this._finishTask('error', window.t('scanner.task.failed'));
                this.flushLogs();
                localStorage.setItem('avlist_generating', 'false');
                this.showToast(window.t('scanner.toast.tag_source_update_error'), 'error', 4000);
            };
        },

        // ===== T6d: Jellyfin Image Update Flow =====
        async runJellyfinImageUpdate() {
            if (this.isGenerating) return;

            if (this.jellyfinImageCount === 0) {
                this.showToast(window.t('scanner.toast.no_jellyfin_update_needed'), 'info');
                return;
            }

            this.state = 'jellyfinUpdating';
            this._startTask('jellyfin-update', window.t('scanner.stats.status_preparing'), this.jellyfinImageCount);
            this.clearLogs();

            localStorage.setItem('avlist_generating', 'true');

            try {
                this.eventSource = new EventSource('/api/gallery/jellyfin-update');

                this.eventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);

                    if (data.type === 'progress') {
                        this.progressStatus = data.status;
                        this.progressCurrent = data.current;
                        this.progressTotal = data.total;
                        this._applyTaskMetrics(data);
                        localStorage.setItem('avlist_last_status', data.status);
                    } else if (data.type === 'log') {
                        this.addLog(data.level, data.message);
                    } else if (data.type === 'done') {
                        this.eventSource.close();
                        this.eventSource = null;
                        // TASK-111 P2-b 後續（codex delta review）：done 不再必然代表「全數完成」——
                        // 批次跑到一半若把 external_manager 切成 off，後端會在下一部片 break 並送
                        // done(updated=已完成筆數)。這裡若無條件補滿 progressTotal，UI 會顯示 3/3
                        // 「補齊完成」，與後端訊息「已補齊 1 部」矛盾。正常跑完時 updated === total，
                        // 兩種情形共用同一條路徑，不需要分歧的文案。
                        this.progressCurrent = (typeof data.updated === 'number')
                            ? data.updated
                            : this.progressTotal;
                        this._finishTask(
                            data.summary?.cancelled ? 'cancelled' : 'done',
                            data.message || window.t('scanner.stats.status_done'),
                            data.summary || { success: data.updated || 0 }
                        );

                        localStorage.setItem('avlist_generating', 'false');
                        localStorage.setItem('avlist_last_status', data.message || window.t('scanner.stats.status_done'));

                        // T3(40c) Codex fix: update 完成後重設 jellyfin check 狀態，讓觸發列重新出現
                        this.jellyfinImageVisible = false;
                        this.jellyfinImageCount = 0;
                        this.jellyfinItems = [];
                        this.jellyfinCheckState = 'idle';

                        const failed = data.summary?.failed || 0;
                        this.showToast(
                            failed > 0
                                ? window.t('scanner.task.done_with_failures', { failed })
                                : window.t('scanner.toast.jellyfin_update_done'),
                            failed > 0 ? 'warn' : 'success'
                        );
                        if (data.message) {
                            this.addLog('info', data.message);
                        }
                        this.flushLogs();
                    } else if (data.type === 'error') {
                        this.eventSource.close();
                        this.eventSource = null;
                        this.addLog('error', window.t('scanner.stats.log_error_prefix', { message: data.message }));
                        this._finishTask('error', data.message || window.t('scanner.task.failed'));
                        this.flushLogs();
                        localStorage.setItem('avlist_generating', 'false');
                    }
                };

                this.eventSource.onerror = () => {
                    if (this.state === 'done' || this.state === 'cancelled') return;
                    this.eventSource.close();
                    this.eventSource = null;
                    this.addLog('error', window.t('scanner.stats.log_disconnected'));
                    this._finishTask('error', window.t('scanner.task.failed'));
                    this.flushLogs();
                    localStorage.setItem('avlist_generating', 'false');
                };
            } catch (e) {
                this._finishTask('error', window.t('scanner.task.failed'));
                localStorage.setItem('avlist_generating', 'false');
                console.error('[Scanner] runJellyfinImageUpdate error:', e);
                this.showToast(window.t('scanner.toast.jellyfin_update_error'), 'error', 4000);
            }
        },

        // ===== T7b: Utility =====
        copyDisplayedPath() {
            const path = this.outputPathDisplay;
            if (!path) return;

            copyText(path).then((ok) => {
                this.showToast(
                    ok
                        ? window.t('scanner.toast.path_copied', { path })
                        : window.t('scanner.toast.copy_path_failed').replace('{path}', path),
                    ok ? 'success' : 'error',
                    4000
                );
            });
        },

        copyOutputPath() {
            if (!this.outputPath) return;

            const showFailToast = () => {
                this.showToast(
                    window.t('scanner.toast.copy_path_failed').replace('{path}', this.outputPath),
                    'error',
                    4000
                );
            };

            copyText(this.outputPath).then((ok) => {
                if (ok) {
                    this.showToast(window.t('scanner.toast.path_copied', { path: this.outputPath }), 'success');
                } else {
                    showFailToast();
                }
            });
        },

    };
}
