/**
 * bridge-notify.js — PyWebView bridge 回傳 dict 的使用者通知（168a-T4）
 *
 * bridge（open_file / open_folder）回 {ok, reason, local_path, server_path}。
 * 本模組把 reason 轉成 toast 文案；路徑一律取 Python 給的欄位，JS 不剝 URI、不換算。
 * 刻意不 import `@/…` 別名，node:test 零 loader 可測。
 *
 * 也提供 Python→JS 全域 hook：window.handleBridgeUncovered(paths, kind)
 * （形狀照 scanner/main.js 的 window.handleFolderDrop）。
 *
 * 每個 key 必須寫成字面 window.t('…')（i18n_lint 靠字面找消費點）；
 * 不用 t(k) || fallback（FE-JS-06：查無 key 回 '[key]' 是 truthy）。
 */

/**
 * 具名原因（not_found / not_video / uncovered）的文案；其餘（failed／untrusted／
 * 缺 reason／非物件／所需路徑欄位缺值）回 null，由呼叫端走 fallback。
 *
 * @param {*} result bridge 回傳
 * @returns {string|null}
 */
export function bridgeReasonMessage(result) {
  if (!result || typeof result !== 'object') return null;
  switch (result.reason) {
    case 'not_found':
      if (!result.local_path) return null;
      return window.t('common.bridge.file_not_found', { path: result.local_path });
    case 'not_video':
      if (!result.local_path) return null;
      return window.t('common.bridge.not_video', { path: result.local_path });
    case 'uncovered':
      if (!result.server_path) return null;
      return window.t('common.bridge.path_uncovered_local', { path: result.server_path });
    default:
      return null;
  }
}

/**
 * 失敗時顯示 error toast；回傳 result.ok 是否為 true。
 *
 * @param {(msg: string, type: string) => void} showToast
 * @param {*} result bridge 回傳
 * @param {'file'|'folder'} kind 決定 fallback 文案
 * @returns {boolean}
 */
export function notifyOpenResult(showToast, result, kind) {
  if (result && typeof result === 'object' && result.ok === true) return true;
  let msg = bridgeReasonMessage(result);
  if (msg === null) {
    msg = kind === 'folder'
      ? window.t('common.open_local.folder_open_failed')
      : window.t('showcase.video.play_failed');
  }
  showToast(msg, 'error');
  return false;
}

/**
 * Python 側呼叫：本機選到／拖入伺服器看不到的路徑。多筆合併成一則 toast。
 *
 * @param {string[]} paths 本機輸入原樣（不經 pathToDisplay）
 * @param {'file'|'folder'|'any'} [kind] 被擋的對象種類（Python 決定）；缺值／未知值走 any
 */
export function handleBridgeUncovered(paths, kind) {
  if (!Array.isArray(paths) || paths.length === 0) return;
  if (typeof Alpine === 'undefined' || !Alpine || typeof Alpine.store !== 'function') {
    console.warn('handleBridgeUncovered: Alpine not ready');
    return;
  }
  const path = paths.join('、');
  const message = (() => {
    switch (kind) {
      case 'file':
        return window.t('common.bridge.path_uncovered_server_file', { path });
      case 'folder':
        return window.t('common.bridge.path_uncovered_server_folder', { path });
      default:
        return window.t('common.bridge.path_uncovered_server_any', { path });
    }
  })();
  Alpine.store('toast').show(message, 'error');
}

if (typeof window !== 'undefined') {
  window.handleBridgeUncovered = handleBridgeUncovered;
}
