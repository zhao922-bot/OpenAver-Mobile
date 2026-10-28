// 168b-T6a: connect page pure logic. No DOM, Alpine, window or i18n; returns codes, not copy.

const CONNECTABLE = ['ok', 'patch_diff'];
const KNOWN_KINDS = ['synology', 'linux', 'windows', 'mac'];
const REASON_CODES = ['unreachable', 'timeout', 'tls', 'lan_forbidden', 'not_openaver'];
const BLOCKED_CODES = ['server_old', 'client_old', 'unparseable', 'not_openaver'];

function isConnectableStatus(compat) {
    return !!compat && CONNECTABLE.includes(compat.status);
}

/** The single source of truth for which buttons and fields are enabled (I-U). */
export function connectActions(s) {
    const probe = s.probe || null;
    const fresh = !!probe && typeof s.probedText === 'string' && s.probedText === String(s.urlText || '').trim();
    const live = fresh ? probe : null;
    const ready = s.bridge === 'ready' && !s.busy && !s.restarting;
    const connectable = fresh && probe.ok === true && isConnectableStatus(probe.compat);

    let passwordField = 'hidden';
    if (live && !(live.ok === false && live.reason)) {
        if (!connectable) passwordField = 'disabled';
        else passwordField = live.auth_required === true ? 'input' : 'none';
    }

    const authOk = connectable && (probe.auth_required !== true || probe.authed === true || s.phase === 'authed');
    const canLogin = ready && passwordField === 'input' && typeof s.pin === 'string' && s.pin !== '';
    const changed = String(s.urlText || '').trim() !== String(s.savedUrl || '');
    const canApply = ready && authOk
        && (s.mode === 'local' || (s.mode === 'client' && (changed || s.phase === 'authed')));
    const canSwitchLocal = s.mode === 'client' && ready;
    const probeUrl = probe ? probe.url : undefined;
    const tableOk = s.sourcesState === 'ok' && s.sourcesFor === probeUrl;
    const sameServer = probeUrl === s.savedUrl;
    const dirty = tableOk && Array.isArray(s.rows) && isRowsDirty(s.rows, s.rowsSnapshot);
    const canSaveRows = s.mode === 'client' && ready && tableOk && sameServer && dirty;
    const canReloadSources = authOk && s.sourcesState === 'error' && !s.busy;
    const canProbe = s.bridge === 'ready' && !s.busy && !s.restarting && String(s.urlText || '').trim() !== '';

    const showRetryCf = s.bridge === 'ready' && cfView(s.cf, s.shellKind).state === 'not_ready';
    const canRetryCf = showRetryCf && ready && !s.cfBusy;

    return {
        probeFresh: fresh,
        connectable,
        authOk,
        canProbe,
        passwordField,
        canLogin,
        canApply,
        applyKind: s.mode === 'local' ? 'switch' : 'apply',
        canSwitchLocal,
        tableVisible: authOk,
        canSaveRows,
        canReloadSources,
        showRetryCf,
        canRetryCf,
    };
}

/** connect_probe reply -> code. */
export function probeCode(probe) {
    if (!probe) return 'unreachable';
    const status = probe.compat && probe.compat.status;
    if (probe.ok === false && probe.reason) return REASON_CODES.includes(probe.reason) ? probe.reason : 'unreachable';
    if (status === 'patch_diff' || status === 'server_old' || status === 'client_old' || status === 'unparseable') return status;
    return probe.ok === true ? 'ok' : 'unreachable';
}

/** code -> ok | blocked | unreachable (status dot). */
export function dotState(code) {
    if (code === 'ok' || code === 'patch_diff') return 'ok';
    if (BLOCKED_CODES.includes(code)) return 'blocked';
    return 'unreachable';
}

export function kindCode(kind) {
    return KNOWN_KINDS.includes(kind) ? kind : null;
}

const FORGOT_MAP = {
    synology: 'synology',
    linux: 'linux',
    windows: 'desktop',
    mac: 'desktop',
};

export function forgotCode(kind) {
    return Object.hasOwn(FORGOT_MAP, kind) ? FORGOT_MAP[kind] : null;
}

// ---------- path-map table (T6b) ----------

function toRow(server, kind, readonly, sample, local, stale) {
    return {
        server, kind, readonly, sample, local, local_path: '', state: null, testing: false, testGen: 0, removed: false, stale,
    };
}

/** One row per server source; local is prefilled from a saved rule whose server string is identical. */
export function mergeRows(sources, savedRules) {
    const saved = Array.isArray(savedRules) ? savedRules : [];
    return (Array.isArray(sources) ? sources : []).map((src) => {
        const hit = saved.find((r) => r.server === src.path);
        return toRow(src.path, src.kind, src.readonly === true, src.sample === undefined ? null : src.sample,
            hit ? String(hit.local) : '', false);
    });
}

/** Saved rules whose server is no longer offered: kept (and flagged) so they are not silently lost. */
export function staleRows(sources, savedRules) {
    const paths = new Set((Array.isArray(sources) ? sources : []).map((src) => src.path));
    const saved = Array.isArray(savedRules) ? savedRules : [];
    const toStaleRow = (r) => toRow(r.server, 'saved_only', false, null, String(r.local), true);
    return saved.filter((r) => !paths.has(r.server)).map(toStaleRow);
}

/** Same rule as core.path_translate.strip_wrapping_quotes: trim, then drop one wrapping pair of double quotes. */
export function stripWrappingQuotes(value) {
    const s = String(value).trim();
    if (s.length >= 2 && s[0] === '"' && s[s.length - 1] === '"') return s.slice(1, -1).trim();
    return s;
}

/** Rules to persist: skip removed rows and rows with an empty side. */
export function rulesForSave(rows) {
    const out = [];
    for (const row of rows) {
        if (row.removed === true) continue;
        const server = String(row.server).trim();
        const local = stripWrappingQuotes(row.local);
        if (server === '' || local === '') continue;
        out.push({ server: row.server, local });
    }
    return out;
}

export function isRowsDirty(rows, snapshot) {
    return JSON.stringify(rulesForSave(rows)) !== snapshot;
}

const ROW_RESULT_MAP = {
    ok: 'ok',
    not_found: 'fail',
    uncovered: 'fail',
    timeout: 'slow',
    no_sample: 'note',
};

/** Row test state code -> ok | fail | slow | note | none. */
export function rowResultView(state) {
    return typeof state === 'string' && Object.hasOwn(ROW_RESULT_MAP, state) ? ROW_RESULT_MAP[state] : 'none';
}

/** Rules sent with apply; null means "leave the stored map alone" (sources not loaded for this server). */
export function pathMapForApply(s) {
    if (s.sourcesState !== 'ok' || s.sourcesFor !== (s.probe && s.probe.url)) return null;
    return rulesForSave(s.rows);
}

// ---------- CF line (168d-T6) ----------

const CF_STATES = ['ready', 'not_ready', 'unsupported'];
const CF_REASONS = ['starting', 'no_windows', 'proxy_unusable', 'server_old', 'unreachable', 'unauthorized', 'offline_boot', 'webview2_failed', 'shell_old'];
const CF_PROXY = ['applied', 'server_local_direct'];

function proxyCode(note) {
    return CF_PROXY.includes(note) ? note : null;
}

/** connect_get_state `cf` -> { state, reason, proxy } codes. Bad shape (old shell) degrades to not_ready/shell_old. */
export function cfView(cf, shellKind) {
    if (!cf || typeof cf !== 'object') return { state: 'not_ready', reason: 'shell_old', proxy: null };
    if (!CF_STATES.includes(cf.state)) return { state: 'not_ready', reason: 'shell_old', proxy: null };
    if (cf.state === 'unsupported') return { state: 'unsupported', reason: null, proxy: null };
    const proxy = shellKind === 'mac' ? null : proxyCode(cf.proxy_note);
    if (cf.state === 'ready') return { state: 'ready', reason: null, proxy };
    const reason = CF_REASONS.includes(cf.reason) ? cf.reason : 'shell_old';
    return { state: 'not_ready', reason, proxy };
}

/** cf_retry reply -> busy | unavailable | failed (only called for a reply that is not a usable ok+cf). */
export function cfRetryErrorCode(reply) {
    const reason = reply && reply.reason;
    if (reason === 'busy') return 'busy';
    if (reason === 'unavailable' || reason === 'no_bridge') return 'unavailable';
    return 'failed';
}
