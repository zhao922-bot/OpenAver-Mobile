/**
 * anchors.js — Constellation Lab anchor pool
 * CD-56B-1: 12 anchor 座標常數 + SHRINK 計算
 * CD-56B-2: pickEight pure function + sampleN helper + railEndpoint
 *
 * ESM export — 不走 window 全域
 */

const CX = 480, CY = 310;
const SHRINK = 0.92;

export const ANCHORS_RAW = [
  { id: '#01', x: 255, y: 260 },
  { id: '#02', x: 700, y: 235 },
  { id: '#03', x: 570, y:  85 },
  { id: '#04', x: 395, y: 540 },
  { id: '#05', x: 595, y: 540 },
  { id: '#06', x: 340, y:  85 },
  { id: '#07', x: 185, y: 545 },
  { id: '#08', x:  75, y: 350 },
  { id: '#09', x: 845, y: 555 }, // Changed from (830,540) — 解決最小距離瓶頸
  { id: '#10', x: 100, y: 130 },
  { id: '#11', x: 900, y: 360 },
  { id: '#12', x: 865, y:  95 },
];

/**
 * ANCHORS: ANCHORS_RAW 套用 SHRINK 朝 center (480, 310) 計算後的結果
 */
export const ANCHORS = ANCHORS_RAW.map(a => ({
  id: a.id,
  x: Math.round(CX + (a.x - CX) * SHRINK),
  y: Math.round(CY + (a.y - CY) * SHRINK),
}));

/**
 * sampleN — Fisher-Yates partial shuffle，從 candidates 取 n 個不重複元素
 * @param {string[]} candidates
 * @param {number} n
 * @param {() => number} rng - 0~1 隨機函數（可注入固定種子以利測試）
 * @returns {string[]}
 */
export function sampleN(candidates, n, rng) {
  const lst = [...candidates];
  const result = [];
  const count = Math.min(n, lst.length);
  for (let i = 0; i < count; i++) {
    const j = i + Math.floor(rng() * (lst.length - i));
    [lst[i], lst[j]] = [lst[j], lst[i]];
    result.push(lst[i]);
  }
  return result;
}

/**
 * pickEight — 從 12 個 slot 中抽 8 個，排除 clicked slot，保留 4-6 個 carry-over
 * CD-56B-2 契約：pure function，注入 rng，不依賴任何全局狀態
 *
 * @param {string} excludeSlotId - 被點擊的 slot id（不放入結果）
 * @param {Set<string>} prevVisible - 上一批 visible slot ids
 * @param {() => number} rng - 隨機函數（預設 Math.random）
 * @returns {Set<string>} 8 個 slot id 的 Set
 */
// ⚠ 覆蓋缺口（2026-08-30）：此處曾有 1,122 行測試（六個 Python 檔，tests/unit/test_constellation_*.py），已刪除。
// 它們測的是這支 JS 的 Python 手抄本（re-implementation），不是本檔本身——實質覆蓋為 0
// （測試檔自述是抄本；rails.py／state.py 完全沒有讀檔／node／.js 引用；刪除前後覆蓋率都是 0）。
//
// 同一批刪除也讓隔壁兩支失去覆蓋，它們同樣 0，但沒有各自的註解：
//   rails.js 的 railRole（全庫已無任何測試提到它）、neighbors.js 的 nearestNeighbors。
// 唯一的例外是 host_T6.py：它真的讀 motion_lab.html 的 <svg class="clip-lab-dust"> 驗 100 顆
// dust 座標的幾何不變式，那道守衛刪除後全庫歸零（/motion-lab 是開發頁，已列 accepted residual）。
//
// 下次動這裡請補真覆蓋：可照 web/static/js/pages/showcase/__tests__/*pill*.test.mjs，
// 用 import map 直接載入真模組跑 node:test，不要再抄一份 Python 邏輯。
//
// ⚠ 這段註解的射程有限：它在函式簽名正上方，預設 3 行 context 的 git diff 只在改動靠近
// 簽名時才會把它帶進 hunk；改本體中後段（約 :80 之後）看不到它。真正貼著呼叫點的提醒在
// state-similar.js 的兩處呼叫行上方。
export function pickEight(excludeSlotId, prevVisible, rng = Math.random) {
  const allIds = ANCHORS.map(a => a.id);

  const carryCandidates = allIds.filter(
    id => prevVisible.has(id) && id !== excludeSlotId
  ); // 通常 7 個

  const freshCandidates = allIds.filter(
    id => !prevVisible.has(id) && id !== excludeSlotId
  ); // 通常 4 個

  const C = 4 + Math.floor(rng() * 3); // [4, 5, 6]，uniform
  const F = 8 - C;

  const actualC = Math.min(C, carryCandidates.length);
  const actualF = Math.min(F, freshCandidates.length);

  const chosen = [
    ...sampleN(carryCandidates, actualC, rng),
    ...sampleN(freshCandidates, actualF, rng),
  ];

  // top-up safety net（理論不觸發，safety net）
  if (chosen.length < 8) {
    const chosenSet = new Set(chosen);
    const remaining = allIds.filter(
      id => !chosenSet.has(id) && id !== excludeSlotId
    );
    const needed = 8 - chosen.length;
    chosen.push(...sampleN(remaining, needed, rng));
  }

  return new Set(chosen.slice(0, 8));
}

/**
 * railEndpoint — 計算 rail 終端點（從中心延伸超出 stage 邊界）
 * 公式：center + (anchor - center) × 1.4
 *
 * @param {{ id: string, x: number, y: number }} anchor
 * @returns {{ x: number, y: number }}
 */
export function railEndpoint(anchor) {
  return {
    x: Math.round(CX + (anchor.x - CX) * 1.4),
    y: Math.round(CY + (anchor.y - CY) * 1.4),
  };
}

/**
 * nearestNeighbors — 從 candidateIds 中找距 slotId 最近的 k 個
 * CD-T2FIX-6 / TASK-T2fix5 契約：pure function，不讀寫任何 state
 *
 * @param {string} slotId - 基準點 slot id
 * @param {Iterable<string>} candidateIds - 候選 slot ids（可 Set 或 Array）
 * @param {number} [k=3] - 取最近幾個
 * @returns {string[]} 按距離升序排列的 slot id 陣列（長度 ≤ k）
 */
export function nearestNeighbors(slotId, candidateIds, k = 3) {
  const self = ANCHORS.find(a => a.id === slotId);
  if (!self) return [];

  const distPairs = [];
  for (const cid of candidateIds) {
    if (cid === slotId) continue;
    const anchor = ANCHORS.find(a => a.id === cid);
    if (!anchor) continue; // filter(Boolean) equivalent — skip unknown ids
    const dx = anchor.x - self.x;
    const dy = anchor.y - self.y;
    distPairs.push([Math.hypot(dx, dy), cid]);
  }

  distPairs.sort((a, b) => a[0] - b[0]);
  return distPairs.slice(0, k).map(p => p[1]);
}
