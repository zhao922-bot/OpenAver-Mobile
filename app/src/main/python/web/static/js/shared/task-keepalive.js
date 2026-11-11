const ANDROID_SHELL_UA = /(?:^|\s)OpenAverMobile\/\S+/;
let active = false;
const owners = new Set();

function notify(schemeUrl) {
    if (!ANDROID_SHELL_UA.test(navigator.userAgent)) return;
    window.location.href = schemeUrl;
}

function sync() {
    const shouldRun = owners.size > 0;
    if (shouldRun === active) return;
    active = shouldRun;
    notify(shouldRun ? 'openaver-task://start' : 'openaver-task://stop');
}

window.__openaverTaskKeepAlive = {
    start(owner = 'default') {
        owners.add(String(owner));
        sync();
    },

    stop(owner = 'default') {
        owners.delete(String(owner));
        sync();
    },
};
