const ANDROID_SHELL_UA = /(?:^|\s)OpenAverMobile\/\S+/;
let active = false;

function notify(schemeUrl) {
    if (!ANDROID_SHELL_UA.test(navigator.userAgent)) return;
    window.location.href = schemeUrl;
}

window.__openaverTaskKeepAlive = {
    start(label) {
        if (active) return;
        active = true;
        notify('openaver-task://start?label=' + encodeURIComponent(label || ''));
    },

    stop() {
        if (!active) return;
        active = false;
        notify('openaver-task://stop');
    },
};

window.addEventListener('pagehide', () => {
    if (active) notify('openaver-task://stop');
});
