// TASK-161a-T4: 分析頁 → 瀏覽頁的條件寫入純函式（不接線、不碰 storage／DOM）。
// sel 只讀 period/actress/maker 三個業務鍵（FE-ALPINE-14：呼叫端傳進來的是 reactive Proxy）。
import { serializePills } from './pill-filter.js';

var EXTRA_DIMS = ['tag', 'director', 'series'];

// 一次性 extra pill：dim 限 tag/director/series、value 去空白後非空；value 保留原字面。
export function normalizeExtraPill(extra) {
    if (!extra || typeof extra !== 'object') return null;
    if (EXTRA_DIMS.indexOf(extra.dim) === -1) return null;
    if (typeof extra.value !== 'string' || extra.value.trim() === '') return null;
    return { dim: extra.dim, value: extra.value };
}

export function buildHandoffPills(sel, extra) {
    var pills = [];
    var extraPill = normalizeExtraPill(extra);
    if (sel) {
        var period = sel.period;
        var actress = sel.actress;
        var maker = sel.maker;
        if (actress) pills.push({ dim: 'actress', value: String(actress) });
        if (maker) pills.push({ dim: 'maker', value: String(maker) });
        if (period && period.type === 'year') {
            pills.push({ dim: 'release', op: '=', value: String(period.year) });
        } else if (period && period.type === 'range') {
            pills.push({ dim: 'release', op: 'range', value: String(period.from), value2: String(period.to) });
        }
    }
    if (extraPill) pills.push(extraPill);
    return serializePills(pills);
}

function parseOld(rawJson) {
    if (typeof rawJson !== 'string' || rawJson === '') return {};
    try {
        var v = JSON.parse(rawJson);
        return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
    } catch (e) {
        return {};
    }
}

export function applyHandoff(rawJson, sel, extra) {
    var old = parseOld(rawJson);
    return JSON.stringify({
        ...old,
        pills: buildHandoffPills(sel, extra),
        search: '',
        page: 1,
        showFavoriteActresses: false,
    });
}
