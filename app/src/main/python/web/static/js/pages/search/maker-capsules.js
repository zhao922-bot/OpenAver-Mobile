// maker-capsules.js — 搜尋頁空狀態片商膠囊排名純函式（TASK-173-T11，CD-173-2／-3）
// 零 window／Alpine／DOM。合併規則與代表寫法一律走 shared/maker-merge.js（與分析頁同一套）。

import { makerKey, canonicalMakerLabels } from '../../shared/maker-merge.js';

/**
 * rows: 端點 makers:[{maker,total,recent}]；hiddenKeys: 已確認找不到的 makerKey 清單。
 * 回傳 [{key,label,spellings,count}]，count＝組內 recent 和；門檻之後才排除 hidden（空位由下一名補上）。
 */
export function rankMakerCapsules(rows, hiddenKeys, { min = 5, max = 5 } = {}) {
    const groups = new Map();
    const spellingTotals = new Map();
    for (const r of rows || []) {
        const key = makerKey(r.maker);
        if (key === '') continue;
        spellingTotals.set(r.maker, (spellingTotals.get(r.maker) || 0) + r.total);
        let g = groups.get(key);
        if (!g) {
            g = { key, recent: 0, spellings: [] };
            groups.set(key, g);
        }
        g.recent += r.recent;
        if (!g.spellings.includes(r.maker)) g.spellings.push(r.maker);
    }
    const labels = canonicalMakerLabels(spellingTotals);
    const hidden = new Set(hiddenKeys || []);
    const out = [];
    for (const g of groups.values()) {
        if (g.recent < min) continue;
        if (hidden.has(g.key)) continue;
        out.push({ key: g.key, label: labels.get(g.spellings[0]), spellings: g.spellings, count: g.recent });
    }
    out.sort((a, b) => b.count - a.count || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0));
    return out.slice(0, max);
}
