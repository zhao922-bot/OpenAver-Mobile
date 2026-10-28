/**
 * shell-reload.js — 桌面殼內 F5 / Ctrl+R / Cmd+R 重新整理（168e-T6, E36）
 * 殼的 WebView 預設關掉瀏覽器快捷鍵，所以自己接；一般瀏覽器沒有 window.pywebview，完全不攔。
 * 形狀照 shell-notice.js：模組頂層只在 document 存在時才碰 document（node 可 import）。
 */
export function onShellReloadKey(e) {
  if (typeof window === 'undefined' || !window.pywebview) return false;
  const isF5 = e.key === 'F5';
  const isCtrlR = (e.ctrlKey || e.metaKey) && typeof e.key === 'string' && e.key.toLowerCase() === 'r';
  if (!isF5 && !isCtrlR) return false;
  e.preventDefault();
  location.reload();
  return true;
}

if (typeof document !== 'undefined') document.addEventListener('keydown', onShellReloadKey);
