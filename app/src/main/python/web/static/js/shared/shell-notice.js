/**
 * shell-notice.js — 桌面殼 → 頁面的提醒 hook（168c-T5）
 * window.handleShellNotice(payload)：回 boolean，true 代表「提醒真的顯示了」（殼靠它記帳）。
 * 形狀照 bridge-notify.js；模組頂層不碰 document / Alpine（node 可 import）。
 */
// 各頁 toast 容器沒有共通 id，只有三種穩定 class；都沒有的頁面（連線頁等）顯示不出來。
const TOAST_CONTAINER_SELECTOR = '.toast, .fluent-toast-container, .search-toast-container';
const DOT_SELECTOR = '[data-shell-update]';
const VERSION_PATTERN = /^\d+(\.\d+)*$/;

function hasToastContainer() {
  return document.querySelector(TOAST_CONTAINER_SELECTOR) !== null;
}

// 常駐小圓點：純 DOM，不依賴 Alpine／toast 容器（連線頁等沒有提醒容器的頁也要看得到）
function showUpdateMarker(version) {
  const dots = document.querySelectorAll(DOT_SELECTOR);
  if (!dots || dots.length === 0) return false;
  const title = window.t('common.shell.update_marker_title', { version });
  for (const el of dots) {
    el.title = title;
    el.hidden = false;
  }
  return true;
}

export function handleShellNotice(payload) {
  if (!payload || typeof payload !== 'object') return false;
  const { kind, version } = payload;
  if (kind !== 'update_available' && kind !== 'update_marker') return false;
  if (typeof version !== 'string' || !VERSION_PATTERN.test(version)) return false;
  if (kind === 'update_marker') return showUpdateMarker(version);
  if (typeof Alpine === 'undefined' || !Alpine || typeof Alpine.store !== 'function') return false;
  const store = Alpine.store('toast');
  if (!store || typeof store.show !== 'function') return false;
  if (!hasToastContainer()) return false;
  store.show(window.t('common.shell.update_available', { version }), 'info', 10000);
  return true;
}

if (typeof window !== 'undefined') {
  window.handleShellNotice = handleShellNotice;
}
