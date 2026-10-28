/**
 * open-local.js — 共用「開啟資料夾」純函式（shared ESM，T4）
 *
 * openLocal：從檔案路徑萃取所在資料夾。PyWebView 桌面模式呼叫 open_folder
 * 開啟資料夾，僅在 bridge 回報成功時才複製 bridge 回的 local_path 所在資料夾
 * （這台電腦的路徑；失敗一律不動剪貼簿）；純瀏覽器模式複製顯示用路徑。
 * 各結果分支對應不同 toast 文案（key 沿用，不新增）。
 *
 * 必須用一般 function 宣告（非 arrow）：函式體內以 this.showToast(...)
 * 存取呼叫端 Alpine component 的方法，this 綁定由呼叫時機決定，arrow
 * function 會把 this 詞法綁死在模組頂層（undefined），導致 runtime
 * TypeError。
 *
 * 被 search/state/result-card.js 與 showcase/state-videos.js 兩頁
 * import，各自以 shorthand property 掛回其 Alpine state 物件。
 * 行為由 showcase/__tests__/bridge-open-wiring.test.mjs 守；字面由
 * scripts/static_guard_lint.mjs 的 162c TestOpenLocalGuard 區塊守。
 */

import { pathToDisplay } from '@/components/path-utils.js';
import { bridgeReasonMessage } from '@/shared/bridge-notify.js';
import { copyText } from '@/shared/clipboard.js';

/** 取檔案路徑所在資料夾（Windows 反斜線與 POSIX 斜線都認）。 */
function folderOf(p) {
  const lastSlash = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
  return lastSlash >= 0 ? p.substring(0, lastSlash) : p;
}

/**
 * 開啟本地資料夾。bridge 模式：開成功才複製這台電腦的資料夾路徑；
 * 純瀏覽器模式：複製顯示用路徑。
 * this 綁定於呼叫端的 Alpine component（需要 this.showToast）。
 *
 * @param {string} path 檔案路徑
 */
export function openLocal(path) {
  if (!path) return;

  const folder = folderOf(path);
  const displayPath = pathToDisplay(folder);

  if (window.pywebview?.api?.open_folder) {
    window.pywebview.api.open_folder(path)
      .then(async (result) => {
        // 168a-T4：bridge 回 dict；具名原因（not_found／not_video／uncovered）贏過其他分支
        const named = result && result.ok === true ? null : bridgeReasonMessage(result);
        if (named !== null) {
          this.showToast(named, 'error');
        } else if (result && result.ok === true && !(typeof result.local_path === 'string' && result.local_path)) {
          this.showToast(window.t('common.open_local.folder_opened'), 'success');
        } else if (result && result.ok === true) {
          const copied = await copyText(folderOf(result.local_path));
          this.showToast(copied ? window.t('common.open_local.folder_opened_copied') : window.t('common.open_local.folder_opened'), 'success');
        } else {
          this.showToast(window.t('common.open_local.folder_open_failed'), 'error');
        }
      })
      .catch(() => {
        this.showToast(window.t('common.open_local.folder_open_failed'), 'error');
      });
  } else {
    copyText(displayPath).then(ok => {
      this.showToast(ok ? window.t('common.open_local.path_copied', { path: displayPath }) : window.t('common.open_local.copy_failed'), ok ? 'success' : 'error');
    });
  }
}
