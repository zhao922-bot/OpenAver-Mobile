/**
 * Shared mobile UI state and diagnostics helpers.
 *
 * This module is intentionally presentation-only: it classifies errors,
 * formats diagnostics for copying, and exposes stable state names for the
 * templates. It never performs scraping, database, or file-system work.
 */

export const UI_STATES = Object.freeze({
    loading: 'loading',
    empty: 'empty',
    offline: 'offline',
    timeout: 'timeout',
    permissionRequired: 'permission_required',
    partialSuccess: 'partial_success',
    unreachable: 'unreachable',
    error: 'error',
});

function tr(key, fallback, params) {
    if (typeof window.t !== 'function') return fallback;
    const value = window.t(key, params || {});
    return value === '[' + key + ']' ? fallback : value;
}

function stringifyDetail(value) {
    if (value === null || typeof value === 'undefined') return '';
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) {
        return value.map((item) => {
            if (item && typeof item === 'object') {
                const level = item.level ? '[' + String(item.level).toUpperCase() + '] ' : '';
                const message = item.message || item.text || JSON.stringify(item);
                return level + message;
            }
            return String(item);
        }).filter(Boolean).join('\n');
    }
    if (typeof value === 'object') {
        try {
            return JSON.stringify(value, null, 2);
        } catch (_) {
            return String(value);
        }
    }
    return String(value);
}

export function classifyError(errorOrMessage) {
    const message = String(
        typeof errorOrMessage === 'object' && errorOrMessage !== null
            ? (errorOrMessage.message || errorOrMessage.error || errorOrMessage.reason || '')
            : (errorOrMessage || '')
    ).toLowerCase();

    if (!navigator.onLine || /offline|network|failed to fetch|connection|连不上|連不上|网络|網路/.test(message)) {
        return UI_STATES.offline;
    }
    if (/timeout|timed out|超时|逾時/.test(message)) return UI_STATES.timeout;
    if (/permission|forbidden|unauthorized|403|权限|權限/.test(message)) {
        return UI_STATES.permissionRequired;
    }
    if (/partial|部分/.test(message)) return UI_STATES.partialSuccess;
    if (/empty|no data|not found|没有|沒有|暂无|暫無/.test(message)) return UI_STATES.empty;
    return UI_STATES.error;
}

export function errorSuggestion(kindOrError) {
    if (kindOrError === 'success') {
        return tr('ui_state.suggestion.success', '任务已完成，无需处理；如需留档可复制日志。');
    }
    const kind = Object.values(UI_STATES).includes(kindOrError)
        ? kindOrError
        : classifyError(kindOrError);

    if (kind === UI_STATES.offline) {
        return tr(
            'ui_state.suggestion.offline',
            '检查网络或本地服务状态后重试；离线时仍可使用已经保存在手机上的数据。'
        );
    }
    if (kind === UI_STATES.timeout) {
        return tr(
            'ui_state.suggestion.timeout',
            '稍后重试，或切换到其他来源；若多个来源同时超时，请检查网络与本地服务日志。'
        );
    }
    if (kind === UI_STATES.permissionRequired) {
        return tr(
            'ui_state.suggestion.permission',
            '检查存储权限、来源访问权限和当前目录是否可写，然后重试。'
        );
    }
    if (kind === UI_STATES.partialSuccess) {
        return tr(
            'ui_state.suggestion.partial',
            '成功项目已经保留；展开日志查看失败或跳过原因，并只重试失败项目。'
        );
    }
    return tr(
        'ui_state.suggestion.retry',
        '重试当前操作；若问题持续，复制日志用于定位问题。'
    );
}

export function sourceReasonLabel(reason) {
    const labels = {
        no_permission: ['ui_state.state.no_permission', '无权限'],
        timeout: ['ui_state.state.timeout_short', '超时'],
        unreachable: ['ui_state.state.unreachable', '不可达'],
        disabled: ['ui_state.state.disabled', '未启用'],
        available: ['ui_state.state.available', '可用'],
    };
    const item = labels[reason] || ['ui_state.state.unknown', '未知状态'];
    return tr(item[0], item[1]);
}

export function sourceReasonIcon(reason) {
    if (reason === 'no_permission') return 'bi-shield-lock';
    if (reason === 'timeout') return 'bi-stopwatch';
    if (reason === 'unreachable') return 'bi-plug';
    if (reason === 'disabled') return 'bi-toggle-off';
    if (reason === 'available') return 'bi-check2-circle';
    return 'bi-question-circle';
}

export function diagnostics(context) {
    const data = context && typeof context === 'object' ? context : { message: context };
    const lines = [
        tr('ui_state.diagnostics_title', 'OpenAver 移动端诊断信息'),
        'time: ' + new Date().toISOString(),
        'page: ' + (data.page || window.location.pathname),
        'online: ' + (navigator.onLine ? 'true' : 'false'),
        'locale: ' + (window.__locale || document.documentElement.lang || 'unknown'),
    ];

    if (data.title) lines.push('title: ' + stringifyDetail(data.title));
    if (data.scope) lines.push('scope: ' + stringifyDetail(data.scope));
    if (data.suggestion) lines.push('suggestion: ' + stringifyDetail(data.suggestion));
    if (data.error) lines.push('error: ' + stringifyDetail(data.error));
    if (data.task) lines.push('task: ' + stringifyDetail(data.task));
    if (data.video) lines.push('video: ' + stringifyDetail(data.video));

    const details = stringifyDetail(data.details);
    if (details) lines.push('details:\n' + details);
    return lines.join('\n');
}

async function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (_) {
            // Fall through to the textarea fallback for older WebViews.
        }
    }

    try {
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', 'readonly');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        const copied = document.execCommand('copy');
        document.body.removeChild(area);
        return copied;
    } catch (_) {
        return false;
    }
}

export async function copyError(payload) {
    const data = payload && typeof payload === 'object' ? payload : { error: payload };
    const text = data.text || diagnostics(data);
    const copied = await copyText(text);
    const toast = window.Alpine && typeof window.Alpine.store === 'function'
        ? window.Alpine.store('toast')
        : null;
    if (toast && typeof toast.show === 'function') {
        toast.show(
            copied
                ? tr('ui_state.copied', '日志已复制')
                : tr('ui_state.copy_failed', '复制失败，请手动选择日志'),
            copied ? 'success' : 'warning',
            2200
        );
    }
    return copied;
}

function updateNetworkState() {
    const online = navigator.onLine !== false;
    document.body.dataset.networkState = online ? 'online' : 'offline';
    const banner = document.getElementById('uiOfflineBanner');
    if (banner) banner.hidden = online;
}

window.OpenAverUIState = Object.freeze({
    states: UI_STATES,
    classifyError,
    errorSuggestion,
    sourceReasonLabel,
    sourceReasonIcon,
    diagnostics,
    copyError,
    copyText,
});

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updateNetworkState, { once: true });
} else {
    updateNetworkState();
}
window.addEventListener('online', updateNetworkState);
window.addEventListener('offline', updateNetworkState);

