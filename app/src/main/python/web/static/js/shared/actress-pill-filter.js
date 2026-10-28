/**
 * actress-pill-filter.js — 女優數值 pill 比對層（116a-T2 / 116b-T1）。
 *
 * 純函式，無 Alpine 依賴。取值走 actress-metric.js（CD-116a-1），
 * 不 import pill-filter.js（CD-116a-3 結構性防誤用）。
 * 116b：四 op if/else 鏈（CD-116b-2），value 不含單位。
 */

import { actressAgeValue, actressHeightValue, actressCupValue } from './actress-metric.js';

var EXTRACTORS = { age: actressAgeValue, height: actressHeightValue, cup: actressCupValue };
var FIELD_NAME = { age: 'age', height: 'height', cup: 'cup' };

// 模組級單例：所有 fail-closed 路徑回傳同一個函式，避免每次都建新 closure
function _never() { return false; }

// 把「pill 上記下的那個標記」丟給與女優欄位同一個 extractor 求值。
// raw 為 null/undefined/空字串 → null（呼叫端據此 fail-closed）。
function _pillScalar(extractor, field, raw) {
    if (raw == null || raw === '') return null;
    var wrapper = {};
    wrapper[field] = raw;
    return extractor(wrapper);
}

export function buildActressPillPredicate(actressPills) {
    if (!actressPills || actressPills.length === 0) return function () { return true; };
    var matchers = actressPills.map(_buildOne);
    return function (actress) { return matchers.every(function (m) { return m(actress); }); };
}

function _buildOne(pill) {
    // hasOwnProperty 查表（比照 115 pill-filter.js 的 alias 查表）：裸 EXTRACTORS[dim] 會讓
    // Object.prototype 的 key 漏進來——dim='toString' 取到函式、通過 !extractor 檢查、
    // 最後 predicate 對每一位女優回 true（fail-open，正好與本模組的契約相反）。
    if (!Object.prototype.hasOwnProperty.call(EXTRACTORS, pill.dim)) return _never;
    var extractor = EXTRACTORS[pill.dim];
    var field = FIELD_NAME[pill.dim];
    var lo = _pillScalar(extractor, field, pill.value);
    if (lo == null) return _never;

    if (pill.op === '=')  return function (a) { var v = extractor(a); return v != null && v === lo; };
    if (pill.op === '<=') return function (a) { var v = extractor(a); return v != null && v <= lo; };
    if (pill.op === '>=') return function (a) { var v = extractor(a); return v != null && v >= lo; };
    if (pill.op === 'range') {
        if (pill.dim === 'cup') return _never;              // spec §4.4：罩杯沒有區間，結構層再擋一次
        var hi = _pillScalar(extractor, field, pill.value2);
        if (hi == null) return _never;
        return function (a) { var v = extractor(a); return v != null && v >= lo && v <= hi; };
    }
    return _never;                                          // fail-closed：未知 op
}
