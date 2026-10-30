const ANDROID_SHELL_UA = /(?:^|\s)OpenAverMobile\/\S+/;

export function openVideoPlayer(path) {
    const value = String(path || '').trim();
    if (!value) return false;

    if (ANDROID_SHELL_UA.test(navigator.userAgent)) {
        window.location.href =
            'openaver-player://play?path=' + encodeURIComponent(value);
        return true;
    }

    window.open(
        '/api/gallery/player?path=' + encodeURIComponent(value),
        '_blank'
    );
    return true;
}

window.openVideoPlayer = openVideoPlayer;
