// 168c-T4: 設定頁「這台電腦」兩格的純函式（無 DOM／Alpine／window）。
import { clientRouting } from '@/shared/shell-client.js';

const REQUIRED = ['local_settings_get', 'local_settings_save'];

// 伺服器 PUT payload 的兩欄：ready／unavailable 保留 GET 回來的原值（不刪鍵，BE-CONFIG-05），
// off／legacy 與 0.17.7 相同寫 form 值。就地修改並回傳同一物件。
export function applyServerLocalFields(config, form, localMachineState) {
    if (localMachineState === 'ready' || localMachineState === 'unavailable') return config;
    config.showcase = { ...config.showcase, player: form.viewerPlayer.trim() };
    config.general = { ...config.general, close_action: form.closeAction };
    return config;
}

export function buildLocalPatch(form) {
    return { player: form.viewerPlayer.trim(), close_action: form.closeAction };
}

// 逐欄值比較（FE-ALPINE-14）；回變動欄位名。
export function localDiff(form, saved) {
    const changed = [];
    if (form.viewerPlayer.trim() !== String(saved.viewerPlayer ?? '').trim()) changed.push('viewerPlayer');
    if (form.closeAction !== saved.closeAction) changed.push('closeAction');
    return changed;
}

// 回新 form／新 savedState（兩者對應鍵同值），不改輸入。
export function mergeLocalIntoForm(form, savedState, local) {
    const player = local.player || '';
    const closeAction = local.close_action || 'ask';
    return {
        form: { ...form, viewerPlayer: player, closeAction },
        savedState: { ...savedState, viewerPlayer: player, closeAction },
    };
}

export function combineSaveOutcome({ serverOk, localChanged, localOk }) {
    if (!localChanged) return null;
    if (serverOk && localOk) return 'settings.toast.config_saved_with_local';
    if (serverOk) return 'settings.toast.local_failed_server_saved';
    if (localOk) return 'settings.toast.local_saved_server_failed';
    return 'settings.toast.local_failed_server_failed';
}

// deps = { whenBridgeReady, callBridge, getBridge }。非 client 零 deps 呼叫。
export async function resolveLocalMachine(shellMode, deps) {
    if (shellMode !== 'client') return { state: 'off' };
    const ready = await deps.whenBridgeReady();
    const bridge = deps.getBridge();
    if (!bridge) return { state: 'legacy' };
    if (clientRouting(shellMode, bridge, REQUIRED) === 'server') return { state: 'legacy' };
    if (!ready) return { state: 'unavailable' };
    const reply = await deps.callBridge('local_settings_get');
    if (reply && reply.ok === true) return { state: 'ready', local: reply };
    return { state: 'unavailable' };
}
