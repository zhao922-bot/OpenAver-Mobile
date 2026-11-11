/** Pure helpers for the showcase lightbox plot panel. */

export function plotFaceButtons(state) {
    const { translateEnabled, hasOriginal, showing } = state;
    if (!hasOriginal) {
        return translateEnabled ? ['translate'] : [];
    }
    if (showing === 'plot') {
        return ['toggle'];
    }
    return translateEnabled ? ['toggle', 'retranslate'] : ['toggle'];
}

export function sameAfterNormalize(left, right) {
    const normalize = (value) =>
        String(value ?? '').split(/\s+/).filter(Boolean).join(' ');
    return normalize(left) === normalize(right);
}

export function applyPlotLoadResult(view, ok, data) {
    if (!ok || !data || data.success !== true) {
        view.error = true;
        view.loading = false;
        return false;
    }
    view.plot = data.plot || '';
    view.original = data.original_plot || '';
    view.hasOriginal = !!data.has_original;
    view.loading = false;
    return true;
}
