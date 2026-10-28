/**
 * focal.js — 共用 focal 座標解析 / object-position 純函式（shared ESM）
 *
 * parseFocal：逐條鏡射 Python core/focal/detector.py::parse_focal 契約
 * （falsy→null；split(',') 恰 2 段；空段/非數/非有限→null；閉區間 [0,1]²；否則 null）。
 * focalObjectPosition：crop_mode gate（'auto'/'manual'，manual 繞 deadzone）+ parse gate
 * + deadzone gate（只對 auto 生效）→ raw x% 的 CSS object-position 字串或 null。無 aspect
 * 校正，供遮罩幾何（state-lightbox.js:880，像素空間自行換算）使用，T3 前不可斷。
 * focalCellObjectPosition（99a-T2）：多吃 imgAspect（naturalWidth/naturalHeight）+
 * r（--poster-crop-ratio），套 aspect-aware 公式，回傳小格 cover-fit 下「所見即所得」的
 * CSS object-position 字串或 null（a≤r / crop_mode gate / parse gate / deadzone 皆會擋）。
 *
 * 由 state 模組 import、經 state 屬性揭露 template或 imperative helper（focal-cell.js）呼叫；
 * null 時退 CSS baseline right center。
 * 純函式：無 DOM、無 Alpine、無 window、無副作用（比照 dir-path.js）。imperative 副作用（load-gate
 * 套用、讀 DOM/CSS var）獨立放 focal-cell.js（TASK-99a-T2 §0，比照 dom-timing.js 的分離慣例）。
 */

/**
 * 臉已落右側舒適區的 X 門檻：x ≥ 此值 → 純右裁（不設 inline object-position）。
 * named 常數（非 inline 數字），T5 owner 真機微調。
 */
export const FOCAL_X_DEADZONE = 0.62;

/**
 * 把亮窗左緣鉗制進封面邊界 [0, W - winW]（遮罩幾何唯一 clamp 語意來源）。
 *
 * 99a Gemini P2：偵測回的 raw x 可能讓「窗中心對焦點」算出的 left 落在邊界外（臉貼左/右緣，
 * 以典型封面比例約 x<0.22 或 x>0.78）。渲染側一向 clamp，但 _maskDragStart 的起手 startLeft
 * 原本用 raw x 直接算、未 clamp → 窗子視覺停在邊界、拖曳卻從界外起算，使用者要先反向拖掉
 * 差值（x=0.95 時約封面寬 17%）窗子才開始動＝拖曳死區。三處（render / dragStart / onMove）
 * 一律走本函式，避免其中一處再度漏鉗。
 *
 * 注意：clamp 只作用於「像素空間的窗左緣」，**不可**用來鉗 _maskFocalX 本身——使用者未拖曳
 * 直接按 ✓ 時要存 pigo 的 raw x（小格 focalCellObjectPosition 有自己的 aspect 數學，會用到
 * 真實落點），鉗過的值會存成較差的座標。
 *
 * @param {number} left 未鉗制的窗左緣（px）
 * @param {number} W 封面 render 寬（px）
 * @param {number} winW 亮窗寬（px）
 * @returns {number} 鉗進 [0, W - winW] 的左緣
 */
export function clampMaskWinLeft(left, W, winW) {
  return Math.max(0, Math.min(left, W - winW));
}

/**
 * 解析 canonical "x,y" 4dp 字串為 {x, y}，鏡射 Python parse_focal。
 *
 * @param {string} s focal 字串（'' / null / undefined / 畸形 → null）
 * @returns {{x: number, y: number}|null} 通過閉區間 [0,1]² 的座標，否則 null
 */
export function parseFocal(s) {
  if (!s) {
    return null;
  }
  const parts = s.split(',');
  if (parts.length !== 2) {
    return null;
  }
  // JS Number('') === 0 / Number('  ') === 0 陷阱：空/純空白段須先擋，
  // 否則會偽裝成合法 0（Python float('') 拋錯 → None）。
  if (parts[0].trim() === '' || parts[1].trim() === '') {
    return null;
  }
  const x = Number(parts[0]);
  const y = Number(parts[1]);
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }
  if (!(x >= 0 && x <= 1 && y >= 0 && y <= 1)) {
    return null;
  }
  return { x, y };
}

/**
 * 由 video 的 crop_mode / auto_focal 算 CSS object-position 字串（只調 X、Y 恆 center，raw x%，
 * 無 aspect 校正）。'auto' 套 deadzone；'manual' 繞過 deadzone（99a-T2 §1.5，spec §7 缺口）。
 *
 * @param {{crop_mode: string, auto_focal: string}|null|undefined} video
 * @returns {string|null} 如 "38.20% center"；null/default 模式 / 無座標 / 畸形 / (auto) deadzone 內 → null
 */
export function focalObjectPosition(video) {
  // imperative 呼叫端（如 _getSlotItem(anchor.id)）可能回 undefined → 優雅退 baseline，不拋。
  if (!video || (video.crop_mode !== 'auto' && video.crop_mode !== 'manual')) {
    return null;
  }
  const p = parseFocal(video.auto_focal);
  if (p === null) {
    return null;
  }
  // deadzone 只對 'auto' 生效；'manual' 是使用者明確拖定的座標，無論多接近右緣都精準套用。
  if (video.crop_mode === 'auto' && p.x >= FOCAL_X_DEADZONE) {
    return null;
  }
  return `${(p.x * 100).toFixed(2)}% center`;
}

/**
 * 小格 cover-fit object-position（aspect-aware，99a-T2 §1；100c-T3b 砍 Y 軸——收斂回單一行為，
 * 與 fd48295a~1（100b-T3 之前）逐字等價）。與 focalObjectPosition 的差異：多吃 imgAspect / r
 * 兩參數，套公式把「raw focal 座標（沿整張原圖寬/高的比例）」換算成「CSS object-position
 * 百分比（沿 cover-fit 溢出區間的比例）」，讓小格顯示與遮罩預覽所見即所得。
 *
 * imgAspect > r（寬圖，水平溢出）→ 只調 X：v = r/a，輸出 "N% center"；
 * 否則（imgAspect <= r，含相等）→ null（cover-fit 下小格不需裁切，或反向公式除以零，不吃 Y 軸）。
 *
 * @param {{crop_mode: string, auto_focal: string}|null|undefined} video
 * @param {number} imgAspect naturalWidth/naturalHeight（呼叫端算好傳入，本函式不碰 DOM）
 * @param {number} r --poster-crop-ratio / --actress-crop-ratio（呼叫端讀好傳入，不裸寫字面值）
 * @returns {string|null} 如 "11.79% center"；crop_mode gate / parse 失敗 / a<=r / deadzone 內 → null
 */
export function focalCellObjectPosition(video, imgAspect, r) {
  if (!video || (video.crop_mode !== 'auto' && video.crop_mode !== 'manual')) {
    return null;
  }
  const p = parseFocal(video.auto_focal);
  if (p === null) {
    return null;
  }
  if (video.crop_mode === 'auto' && p.x >= FOCAL_X_DEADZONE) {
    return null;
  }
  if (!(Number.isFinite(imgAspect) && Number.isFinite(r) && r > 0)) {
    return null;
  }
  if (imgAspect <= r) {
    // a <= r（含相等）：cover-fit 下小格不需裁切，或反向公式在此退化/除以零
    // （Codex 當初補的除零防護，不是垃圾值；與 fd48295a~1 逐字等價）。
    return null;
  }
  // 寬圖：水平溢出，只調 X（既有公式，數值零回歸）。
  const v = r / imgAspect;
  const raw = (p.x - v / 2) / (1 - v);
  const clamped = Math.max(0, Math.min(1, raw));
  return `${(clamped * 100).toFixed(2)}% center`;
}
