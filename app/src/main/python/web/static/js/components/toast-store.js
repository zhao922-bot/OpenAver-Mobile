export function createToastStore() {
    return {
        message: '',
        type: 'success',
        visible: false,
        kind: 'success',
        title: '',
        scope: '',
        suggestion: '',
        details: '',
        occurredAt: '',
        action: null, // UI 暫態 {label, onClick}；每次 show() 覆寫，hide()／到期清 null
        _timer: null,
        // 逐字保留今日五份實作的共同語意：後到的覆蓋先到的（先取消舊計時器再排新的）
        show(msgOrOptions, type = 'success', duration = 2500, action = null) {
            const options = msgOrOptions && typeof msgOrOptions === 'object'
                ? msgOrOptions
                : { message: msgOrOptions, type, duration, action };
            const message = String(options.message ?? '');
            const severity = options.type || 'success';
            this.message = message;
            this.type = severity;
            this.kind = options.kind || (
                severity === 'error' ? 'error'
                    : (severity === 'warning' || severity === 'warn') ? 'partial_success'
                        : severity === 'info' ? 'info'
                            : 'success'
            );
            this.title = options.title || (
                severity === 'error' ? window.t('ui_state.error_title')
                    : (severity === 'warning' || severity === 'warn') ? window.t('ui_state.partial_title')
                        : message
            );
            this.scope = options.scope || (
                severity === 'error' || severity === 'warning' || severity === 'warn'
                    ? window.t('ui_state.scope.current_action')
                    : ''
            );
            this.suggestion = options.suggestion || (
                severity === 'error' || severity === 'warning' || severity === 'warn'
                    ? window.OpenAverUIState?.errorSuggestion(severity === 'error' ? 'error' : 'partial')
                    : ''
            );
            this.details = options.details || (
                severity === 'error' || severity === 'warning' || severity === 'warn'
                    ? window.OpenAverUIState?.diagnostics({
                        title: this.title,
                        scope: this.scope,
                        suggestion: this.suggestion,
                        details: message,
                    }) || message
                    : ''
            );
            this.occurredAt = options.occurredAt || new Date().toISOString();
            this.visible = true;
            this.action = options.action || null;
            if (this._timer) clearTimeout(this._timer);
            const timeout = Number.isFinite(options.duration) ? options.duration : duration;
            this._timer = setTimeout(() => { this.hide(); }, timeout);
        },
        copy() {
            return window.OpenAverUIState?.copyError({
                title: this.title,
                scope: this.scope,
                suggestion: this.suggestion,
                details: this.details,
            });
        },
        hide() {
            if (this._timer) clearTimeout(this._timer);
            this._timer = null;
            this.visible = false;
            this.action = null;
            this.kind = 'success';
            this.title = '';
            this.scope = '';
            this.suggestion = '';
            this.details = '';
            this.occurredAt = '';
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.store('toast', createToastStore());
});
