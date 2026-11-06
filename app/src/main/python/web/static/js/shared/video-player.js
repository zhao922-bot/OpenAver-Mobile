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

window.openVideoPlayer = openVideoPlayer;
