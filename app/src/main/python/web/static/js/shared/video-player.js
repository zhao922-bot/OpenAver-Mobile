const ANDROID_SHELL_UA = /(?:^|\s)OpenAverMobile\/\S+/;

export function openVideoPlayer(path, options = {}) {
    const value = String(path || '').trim();
    if (!value) return false;

    if (ANDROID_SHELL_UA.test(navigator.userAgent)) {
        const paths = Array.isArray(options.parts)
            ? options.parts.filter(item => typeof item === 'string' && item.trim())
            : [];
        const labels = Array.isArray(options.labels) ? options.labels : [];
        let target = 'openaver-player://play?path=' + encodeURIComponent(value);
        if (paths.length > 1) {
            const parts = paths.map((partPath, index) => ({
                path: partPath,
                label: typeof labels[index] === 'string' ? labels[index] : '',
            }));
            target += '&parts=' + encodeURIComponent(JSON.stringify(parts));
        }
        window.location.href = target;
        return true;
    }

    window.open(
        '/api/gallery/player?path=' + encodeURIComponent(value),
        '_blank'
    );
    return true;
}

export function openLocalVideoStatus(status) {
    if (!status || !status.exists) return false;
    const playback = status.playback || {};
    const paths = Array.isArray(playback.paths)
        ? playback.paths.filter(item => typeof item === 'string' && item.trim())
        : [];
    const legacyPaths = Array.isArray(status.paths)
        ? status.paths.filter(item => typeof item === 'string' && item.trim())
        : [];
    const selectedPaths = paths.length ? paths : legacyPaths;
    const path = String(
        playback.path || selectedPaths[0] || ''
    ).trim();
    if (!path) return false;
    return openVideoPlayer(path, {
        parts: selectedPaths,
        labels: Array.isArray(playback.part_tokens)
            ? playback.part_tokens
            : [],
    });
}

window.openVideoPlayer = openVideoPlayer;
window.openLocalVideoStatus = openLocalVideoStatus;
