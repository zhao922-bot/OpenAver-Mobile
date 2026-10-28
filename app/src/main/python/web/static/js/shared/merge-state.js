/**
 * merge-state.js — 共用 descriptor-preserving state 合併純函式（shared ESM）
 *
 * mergeState：把多個 state factory 回傳的物件依序合併成單一物件，
 * 用 Object.getOwnPropertyDescriptors + Object.defineProperties（而非
 * plain spread）保留 getter/setter descriptor（例如 showcase 頁
 * stateBase 的 $persist getter，plain spread 會丟失它）。
 *
 * 被 scanner / showcase / settings / search 四頁 main.js import，
 * 在 alpine:init 時組裝各自的 Alpine.data(...) component。
 * 純函式：無 DOM、無 Alpine、無 window、無副作用。
 * 由 scripts/static_guard_lint.mjs 鎖死（合併運算式整條斷言 + 四頁 import 存在性斷言）。
 */

/**
 * 依序合併多個 state 物件，保留每個來源的 property descriptor（含 getter/setter）。
 *
 * @param {...object} parts 待合併的 state 物件（依序，後者覆蓋前者同名鍵）
 * @returns {object} 合併後的單一物件
 */
export function mergeState(...parts) {
  const target = {};
  for (const part of parts) {
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(part));
  }
  return target;
}
