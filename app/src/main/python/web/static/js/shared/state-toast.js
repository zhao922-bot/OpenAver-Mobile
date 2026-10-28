export function toastState() {
    return {
        showToast(...args) {
            Alpine.store('toast').show(...args);
        },
    };
}
