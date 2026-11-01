export function showGlobalToast(...args) {
    Alpine.store('toast').show(...args);
}

export function toastState() {
    return {
        showToast(...args) {
            showGlobalToast(...args);
        },
    };
}
