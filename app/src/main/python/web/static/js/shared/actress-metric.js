/**
 * actress-metric.js — 女優數值取值單一所有者（116a-T1）。
 *
 * 排序（state-actress.js）與篩選（actress-pill-filter.js）共用同一組 extractor，
 * 避免兩份取值邏輯漂移（CD-116a-1）。
 * 零 import、零 Alpine 依賴。
 */

export function actressAgeValue(a) {
    if (a.age == null) return null;
    var s = String(a.age).trim();
    if (s === '') return null;
    var n = Number(s);
    // Number.isFinite 而非 isNaN：isNaN(Infinity) 是 false，'1e999' 會漏成 Infinity
    // 通過，讓「fail-closed」名不符實（Codex PR review P3）。
    return Number.isFinite(n) ? n : null;
}

export function actressHeightValue(a) {
    var h = parseInt(a.height);
    return isNaN(h) ? null : h;
}

export function actressCupValue(a) {
    var c = a.cup;                                  // 保持與現行相同：a 為 null 時照樣拋（呼叫端一律傳物件）
    if (typeof c !== 'string' || c.length !== 1) return null;
    var code = c.charCodeAt(0);
    if (code < 65 || code > 90) return null;        // 'A'=65 … 'Z'=90
    return code - 64;                               // A=1 … Z=26
}

/**
 * actressMetricRange(list, extractor) — 116c-T2（CD-116c-6）。
 *
 * 參數是 extractor 函式本身，不是 dim 字串——避免在本模組再擺一張
 * { age, height, cup } 表（那張表的所有者是 actress-pill-filter.js）。
 *
 * list 空、或該維度全部取不到值 → null。純函式、零 Alpine 依賴。
 */
export function actressMetricRange(list, extractor) {
    var min = null;
    var max = null;
    for (var i = 0; i < list.length; i++) {
        var v = extractor(list[i]);
        if (v == null) continue;
        if (min == null || v < min) min = v;
        if (max == null || v > max) max = v;
    }
    return min == null ? null : { min: min, max: max };
}
