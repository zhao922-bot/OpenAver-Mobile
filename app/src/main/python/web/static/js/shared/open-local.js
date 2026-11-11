/**
 * open-local.js — 共用「複製資料夾路徑」純函式（shared ESM，T4）
 *
 * Android 與一般瀏覽器都複製顯示用資料夾路徑。
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
import { copyText } from '@/shared/clipboard.js';

/** 取檔案路徑所在資料夾（Windows 反斜線與 POSIX 斜線都認）。 */
function folderOf(p) {
  const lastSlash = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
  return lastSlash >= 0 ? p.substring(0, lastSlash) : p;
}

/**
 * 複製檔案所在資料夾的顯示路徑。
 * this 綁定於呼叫端的 Alpine component（需要 this.showToast）。
 *
 * @param {string} path 檔案路徑
 */
export function openLocal(path) {
  if (!path) return;

  const folder = folderOf(path);
  const displayPath = pathToDisplay(folder);

  copyText(displayPath).then(ok => {
    this.showToast(
      ok
        ? window.t('common.open_local.path_copied', { path: displayPath })
        : window.t('common.open_local.copy_failed'),
      ok ? 'success' : 'error',
    );
  });
}
