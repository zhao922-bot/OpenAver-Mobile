// 168c-T4: 桌面殼 bridge 的共用小工具（設定頁與說明頁共用）。ES module，無頂層 window 存取。

// 殼說「頁面種類已判定」才可呼叫 bridge（BE-WEBVIEW-06）。window 在呼叫時才解析。
export function whenBridgeReady(timeoutMs = 3000) {
    const w = globalThis.window;
    if (!w) return Promise.resolve(false);
    if (w.__oaBridgeKind) return Promise.resolve(true);
    return new Promise((resolve) => {
        let done = false;
        const finish = (ok) => {
            if (done) return;
            done = true;
            clearTimeout(timer);
            w.removeEventListener('oabridgeready', onReady);
            resolve(ok);
        };
        const onReady = () => finish(true);
        const timer = setTimeout(() => finish(false), timeoutMs);
        w.addEventListener('oabridgeready', onReady);
    });
}

async function callOnce(name, args) {
    const api = globalThis.window && globalThis.window.pywebview && globalThis.window.pywebview.api;
    if (!api || typeof api[name] !== 'function') return { ok: false, reason: 'no_bridge' };
    try {
        const reply = await api[name](...args);
        return reply && typeof reply === 'object' ? reply : { ok: false, reason: 'error' };
    } catch (e) {
        return { ok: false, reason: 'error' };
    }
}

// 永不外丟。reason:'untrusted' 時照連線頁行為重試一次：清旗標、再等一次就緒。
export async function callBridge(name, ...args) {
    let reply = await callOnce(name, args);
    if (reply && reply.reason === 'untrusted') {
        if (globalThis.window) globalThis.window.__oaBridgeKind = undefined;
        await whenBridgeReady();
        reply = await callOnce(name, args);
    }
    return reply;
}

// 'bridge'：client 模式、bridge 存在、requiredMethods 每個都是 function；否則 'server'。
export function clientRouting(shellMode, bridge, requiredMethods) {
    if (shellMode !== 'client' || !bridge) return 'server';
    return requiredMethods.every((m) => typeof bridge[m] === 'function') ? 'bridge' : 'server';
}
