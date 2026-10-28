/**
 * maker-merge.js — 片商寫法合併共用核心（TASK-173-T7，CD-173-2）
 *
 * 純函式，零 window / Alpine / DOM。分析頁 canonicalizeMakers 與搜尋頁片商膠囊共用，
 * 使用者在兩頁看到同一家片商同一種合併結果。
 */

import { normalizePillValue } from './pill-filter.js';

/** 片商寫法的比對鍵（與 pill-filter 同一套正規化）。 */
export function makerKey(s) {
    return normalizePillValue(s);
}

/**
 * spellingCounts: Map<寫法, 次數> → Map<寫法, 代表寫法>。
 * 同 key 的寫法為一組，次數最多者為代表，平手取字串遞增最小者；key 為空字串的寫法不進回傳 Map。
 */
export function canonicalMakerLabels(spellingCounts) {
    var groups = new Map();
    spellingCounts.forEach(function (n, mk) {
        var key = makerKey(mk);
        if (key === '') return;
        var counts = groups.get(key);
        if (!counts) {
            counts = new Map();
            groups.set(key, counts);
        }
        counts.set(mk, n);
    });

    var canonical = new Map();
    groups.forEach(function (counts) {
        var best = null;
        var bestN = -1;
        counts.forEach(function (n, s) {
            if (n > bestN || (n === bestN && s < best)) { best = s; bestN = n; }
        });
        counts.forEach(function (_, s) {
            canonical.set(s, best);
        });
    });
    return canonical;
}
