// 168b-T6a: connect page (single standalone Alpine component). All remote I/O goes through the shell bridge.
import { PROBE_ICON_MAP } from '../settings/source-probe-logic.js';
import {
    connectActions, cfRetryErrorCode, probeCode, dotState, kindCode, forgotCode, cfView,
    mergeRows, staleRows, rulesForSave, stripWrappingQuotes, rowResultView, pathMapForApply as buildPathMap,
} from './connect-logic.js';

export function connectPage() {
    return {
        // --- contract state (read by connect-logic.js) ---
        bridge: 'pending',
        mode: 'local',
        busy: null,
        restarting: false,
        urlText: '',
        savedUrl: '',
        probedText: '',
        probe: null,
        phase: 'idle',
        pin: '',
        sourcesState: 'idle',
        sourcesFor: '',
        rows: [],
        rowsSnapshot: '',
        savedRules: [],
        // --- free state ---
        localVersion: '',
        savedHost: '',
        savedReach: 'unknown',
        savedVersion: '',
        savedKind: '',
        lastOk: '',
        shellKind: 'windows',
        cf: null,
        cfBusy: false, // read by connect-logic.js (canRetryCf)
        cfRetryError: '',
        actionError: '',
        pinError: '',
        _started: false,
        _kindSeen: false,
        _retried: false,

        init() {
            const ds = (this.$el && this.$el.dataset) || {};
            this.mode = ds.mode === 'client' ? 'client' : 'local';
            this.shellKind = ds.shellKind === 'mac' ? 'mac' : 'windows';
            window.addEventListener('oabridgeready', () => { this._kindSeen = true; this._tryStart(); });
            window.addEventListener('pywebviewready', () => this._tryStart());
            setTimeout(() => {
                if (this.bridge === 'pending' && !window.pywebview) this.bridge = 'unavailable';
            }, 8000);
            this._tryStart();
        },

        // 168b-T9a: first bridge call waits for the shell's "page kind decided" signal (never earlier)
        _tryStart() {
            const api = window.pywebview && window.pywebview.api;
            if (!this._kindSeen && !window.__oaBridgeKind) return;
            if (api && typeof api.connect_get_state === 'function') this.start();
        },

        async start() {
            if (this._started) return;
            this._started = true;
            const state = await this.call('connect_get_state');
            if (state && state.reason === 'untrusted' && !this._retried) {
                this._retried = true;
                this._started = false;
                this._kindSeen = false;
                window.__oaBridgeKind = undefined;
                return;
            }
            if (!state || typeof state.mode !== 'string') {
                this.bridge = 'unavailable';
                return;
            }
            this.mode = state.mode === 'client' ? 'client' : 'local';
            this.localVersion = String(state.version || '');
            this.lastOk = typeof state.last_ok === 'string' ? state.last_ok : '';
            this.savedUrl = this.mode === 'client' ? String(state.url || '') : '';
            this.savedHost = this.mode === 'client' ? String(state.host || '') : '';
            this.savedRules = Array.isArray(state.path_map) ? state.path_map : [];
            this.urlText = this.savedUrl;
            this.cf = state.cf ?? null;
            this.bridge = 'ready';
            if (this.mode === 'client' && this.savedUrl) await this.testConnection();
            await this._syncSources();
        },

        async call(name, ...args) {
            const api = window.pywebview && window.pywebview.api;
            if (!api || typeof api[name] !== 'function') return { ok: false, reason: 'no_bridge' };
            let reply;
            try {
                reply = await api[name](...args);
            } catch {
                return { ok: false, reason: 'error' };
            }
            if (reply && reply.reason === 'untrusted' && (name !== 'connect_get_state' || this._retried)) this.bridge = 'unavailable';
            return reply;
        },

        actions() {
            return connectActions(this);
        },

        async testConnection() {
            if (!this.actions().canProbe) return;
            const asked = this.urlText.trim();
            this.busy = 'probe';
            this.phase = 'probing';
            this.actionError = '';
            const reply = await this.call('connect_probe', asked);
            this.busy = null;
            if (this.bridge === 'unavailable') return;
            if (!reply || typeof reply.ok !== 'boolean') {
                this.probe = null;
                this.phase = 'idle';
                this.actionError = 'failed';
                return;
            }
            this.probe = reply;
            this.probedText = asked;
            this.phase = 'probed';
            this.pinError = '';
            if (this.mode === 'client' && asked === this.savedUrl) {
                this.savedReach = dotState(probeCode(reply)) === 'ok' ? 'ok' : 'down';
                this.savedVersion = String(reply.version || '');
                this.savedKind = String(reply.kind || '');
            }
            await this._syncSources();
        },

        async login() {
            if (!this.actions().canLogin) return;
            const pin = this.pin;
            const url = this.probe.url;
            this.busy = 'login';
            this.phase = 'logging_in';
            this.actionError = '';
            const reply = await this.call('connect_login', url, pin);
            this.pin = '';
            this.busy = null;
            this.phase = 'probed';
            if (reply && reply.ok === true) this.phase = 'authed';
            this.pinError = reply && reply.ok === true ? '' : (reply && reply.reason) || 'failed';
            await this._syncSources();
        },

        // null means the Python side keeps the stored path map.
        pathMapForApply() {
            return buildPathMap(this);
        },

        // --- path-map table ---
        async _syncSources() {
            if (!this.actions().tableVisible) return;
            if (this.sourcesState === 'loading' || this.rowsReady()) return;
            await this.loadSources();
        },

        async loadSources() {
            if (!this.probe || this.busy) return;
            const url = this.probe.url;
            this.sourcesState = 'loading';
            const reply = await this.call('connect_sources', url);
            if (this.bridge === 'unavailable') return;
            if (!this.probe || this.probe.url !== url) {
                this.sourcesState = 'idle';
                await this._syncSources();
                return;
            }
            if (!reply || reply.ok !== true || !Array.isArray(reply.sources)) {
                this.sourcesFor = '';
                this.sourcesState = 'error';
                return;
            }
            const rows = [...mergeRows(reply.sources, this.savedRules), ...staleRows(reply.sources, this.savedRules)];
            this.rows = rows;
            this.rowsSnapshot = JSON.stringify(rulesForSave(rows));
            this.sourcesFor = url;
            this.sourcesState = 'ok';
        },

        rowsReady() {
            return this.sourcesState === 'ok' && !!this.probe && this.sourcesFor === this.probe.url;
        },

        rowsLoading() {
            return !this.rowsReady() && this.sourcesState !== 'error';
        },

        canTestRow(row) {
            return this.bridge === 'ready' && !this.restarting && !row.testing && row.local.trim() !== '';
        },

        async testRow(row) {
            if (!this.canTestRow(row)) return;
            const gen = ++row.testGen;
            row.testing = true;
            const reply = await this.call('connect_test_row', row.server, row.local.trim(), row.sample);
            if (row.testGen !== gen) return;
            row.testing = false;
            if (this.bridge === 'unavailable') return;
            row.state = reply && typeof reply.state === 'string' ? reply.state : 'timeout';
            row.local_path = reply && typeof reply.local_path === 'string' ? reply.local_path : '';
        },

        onLocalInput(row) {
            row.state = null;
            row.local_path = '';
            row.testing = false;
            row.testGen++;
        },

        removeStale(row) {
            row.removed = true;
        },

        async saveRows() {
            if (!this.actions().canSaveRows) return;
            const rules = rulesForSave(this.rows);
            this.busy = 'save';
            const reply = await this.call('connect_save_path_map', rules);
            this.busy = null;
            if (this.bridge === 'unavailable') return;
            if (reply && reply.ok === true) {
                this.savedRules = rules;
                for (const row of this.rows) row.local = stripWrappingQuotes(row.local);   // CD-9 ③：顯示值與存的一致
                this.rowsSnapshot = JSON.stringify(rules);
                Alpine.store('toast').show(window.t('connect.rows.saved'), 'success');
                return;
            }
            Alpine.store('toast').show(window.t('connect.rows.save_failed'), 'error');
        },

        // --- table copy ---
        placeholderText() {
            return this.shellKind === 'mac'
                ? window.t('connect.rows.placeholder_mac')
                : window.t('connect.rows.placeholder_windows');
        },

        rowTag(row) {
            if (row.readonly) return window.t('connect.rows.readonly');
            if (row.kind === 'favorite') return window.t('connect.rows.favorite');
            return '';
        },

        rowFailText(row) {
            if (row.local_path) return window.t('connect.rows.not_found_path', { path: row.local_path });
            return window.t('connect.rows.not_found');
        },

        rowResult(row) {
            return row.testing ? 'none' : rowResultView(row.state);
        },

        okIcon() {
            return PROBE_ICON_MAP.ok;
        },

        failIcon() {
            return PROBE_ICON_MAP.unreachable;
        },

        async applyRestart() {
            if (!this.actions().canApply) return;
            this.busy = 'apply';
            this.actionError = '';
            const reply = await this.call('connect_apply_restart', this.probe.url, this.pathMapForApply());
            this.finishRestart(reply);
        },

        async switchLocal() {
            if (!this.actions().canSwitchLocal) return;
            this.busy = 'switch';
            this.actionError = '';
            const reply = await this.call('connect_switch_local_restart');
            this.finishRestart(reply);
        },

        finishRestart(reply) {
            this.busy = null;
            if (reply && reply.ok === true) {
                this.restarting = true;
                return;
            }
            this.actionError = (reply && reply.reason) || 'failed';
        },

        async retryCf() {
            if (!this.actions().canRetryCf) return;
            this.cfBusy = true;
            this.cfRetryError = '';
            const reply = await this.call('cf_retry');
            this.cfBusy = false;
            if (this.bridge === 'unavailable') return;
            if (reply && reply.ok === true && reply.cf && typeof reply.cf === 'object') {
                this.cf = reply.cf;
                return;
            }
            this.cfRetryError = cfRetryErrorCode(reply);
        },

        // --- copy ---
        kindLabel(kind) {
            switch (kindCode(kind)) {
                case 'synology': return window.t('connect.kind_synology');
                case 'linux': return window.t('connect.kind_linux');
                case 'windows': return window.t('connect.kind_windows');
                case 'mac': return window.t('connect.kind_mac');
                default: return '';
            }
        },

        versionLine(version, kind) {
            const label = this.kindLabel(kind);
            if (!label) return window.t('connect.version_only', { version });
            return window.t('connect.version_line', { version, kind: label });
        },

        statusLine() {
            if (this.mode === 'local') return window.t('connect.status_local');
            if (this.savedReach === 'down') return window.t('connect.status_down', { host: this.savedHost });
            return window.t('connect.status_connected', { host: this.savedHost });
        },

        statusVersionLine() {
            if (this.mode === 'local') return this.localVersion ? this.versionLine(this.localVersion, '') : '';
            return this.savedVersion ? this.versionLine(this.savedVersion, this.savedKind) : '';
        },

        lastOkText() {
            if (this.mode !== 'client' || !this.lastOk) return '';
            const when = new Date(this.lastOk);
            if (Number.isNaN(when.getTime())) return '';
            return window.t('connect.last_ok', { time: when.toLocaleString() });
        },

        dotName() {
            return this.actions().probeFresh ? dotState(probeCode(this.probe)) : 'unreachable';
        },

        dotIcon() {
            return PROBE_ICON_MAP[this.dotName()];
        },

        resultText() {
            const p = this.probe;
            switch (probeCode(p)) {
                case 'ok': return this.versionLine(p.version, p.kind);
                case 'patch_diff':
                    return window.t('connect.result_patch_diff', { server: p.version, local: this.localVersion });
                case 'server_old': return window.t('connect.result_server_old');
                case 'client_old': return window.t('connect.result_client_old');
                case 'unparseable': return window.t('connect.result_unparseable');
                case 'timeout': return window.t('connect.result_timeout');
                case 'tls': return window.t('connect.result_tls');
                case 'lan_forbidden': return window.t('connect.result_lan_forbidden');
                case 'not_openaver': return window.t('connect.result_not_openaver');
                default: return window.t('connect.result_unreachable');
            }
        },

        resultVersionText() {
            const p = this.probe;
            if (!p || p.ok !== true || probeCode(p) === 'ok') return '';
            return this.versionLine(p.version, p.kind);
        },

        forgotText() {
            switch (forgotCode(this.probe && this.probe.kind)) {
                case 'synology': return window.t('connect.forgot_synology');
                case 'linux': return window.t('connect.forgot_linux');
                case 'desktop': return window.t('connect.forgot_desktop');
                default: return '';
            }
        },

        pinErrorText() {
            if (!this.pinError) return '';
            if (this.pinError === 'bad_pin') return window.t('connect.pin_bad');
            return window.t('connect.pin_failed');
        },

        actionErrorText() {
            return this.actionError ? window.t('connect.error_generic') : '';
        },

        applyLabel() {
            return this.actions().applyKind === 'switch'
                ? window.t('connect.apply_switch')
                : window.t('connect.apply_apply');
        },

        applyHint() {
            return this.mode === 'local'
                ? window.t('connect.apply_hint_local')
                : window.t('connect.apply_hint_client');
        },

        cfText() {
            const v = cfView(this.cf, this.shellKind);
            if (v.state === 'ready') return window.t('connect.cf_ready');
            if (v.state === 'unsupported') return window.t('connect.cf_mac');
            return window.t('connect.cf_not_ready', { reason: this.cfReasonText(v.reason) });
        },

        cfReasonText(reason) {
            switch (reason) {
                case 'starting': return window.t('connect.cf_reason_starting');
                case 'no_windows': return window.t('connect.cf_reason_no_windows');
                case 'proxy_unusable': return window.t('connect.cf_reason_proxy_unusable');
                case 'server_old': return window.t('connect.cf_reason_server_old');
                case 'unreachable': return window.t('connect.cf_reason_unreachable');
                case 'unauthorized': return window.t('connect.cf_reason_unauthorized');
                case 'offline_boot': return window.t('connect.cf_reason_offline_boot');
                case 'webview2_failed': return window.t('connect.cf_reason_webview2_failed');
                default: return window.t('connect.cf_reason_shell_old');
            }
        },

        cfRetryErrorText() {
            switch (this.cfRetryError) {
                case 'busy': return window.t('connect.cf_retry_busy');
                case 'unavailable': return window.t('connect.cf_retry_unavailable');
                case 'failed': return window.t('connect.error_generic');
                default: return '';
            }
        },

        cfNoteText() {
            switch (cfView(this.cf, this.shellKind).proxy) {
                case 'applied': return window.t('connect.cf_proxy_applied');
                case 'server_local_direct': return window.t('connect.cf_proxy_local_direct');
                default: return '';
            }
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('connectPage', connectPage);
});
