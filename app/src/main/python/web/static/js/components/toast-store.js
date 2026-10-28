export function createToastStore() {
    return {
        message: '',
        type: 'success',
        visible: false,
        action: null, // UI 暫態 {label, onClick}；每次 show() 覆寫，hide()／到期清 null
        _timer: null,
        // 逐字保留今日五份實作的共同語意：後到的覆蓋先到的（先取消舊計時器再排新的）
        show(msg, type = 'success', duration = 2500, action = null) {
            this.message = msg;
            this.type = type;
            this.visible = true;
            this.action = action;
            if (this._timer) clearTimeout(this._timer);
            this._timer = setTimeout(() => { this.visible = false; this.action = null; this._timer = null; }, duration);
        },
        hide() {
            if (this._timer) clearTimeout(this._timer);
            this._timer = null;
            this.visible = false;
            this.action = null;
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.store('toast', createToastStore());
});
