/**
 * charts.js — 片庫分析 ECharts 組裝（TASK-156b-T3 / T4）
 *
 * ECharts 實例與 option 一律存模組級 Map，不進 Alpine reactive scope（CD-156-4）。
 * §3.10 spike 產物：divideShape='split'；setOption 不全域套用 notMerge（維持預設 merge
 * 以便 universalTransition 一對多分裂）。
 */

import {
    UNKNOWN_KEY,
    REST_KEY,
    getRecords,
    aggregateYears,
    aggregateTags,
    aggregateAge,
    aggregateFieldTop8,
    buildMakerColorSlots,
    buildMakerDonutData,
} from './aggregate.js';
import { emptyKey, emptySel, periodContainsYear, scopeRecords } from './selection.js';

/** @type {'split'|'clone'} spike 選定值——見 TASK-156b-T3 執行紀錄 */
export const YEARS_DIVIDE_SHAPE = 'split';

/** @type {Map<string, object>} */
const _charts = new Map();
/** @type {Map<string, ResizeObserver>} */
const _observers = new Map();
/** @type {string[]} */
let _lastYearCats = [];
/** @type {{startIdx:number,curIdx:number,byTouch:boolean,onDocUp:Function,lastSpanKey:string}|null} 年份拖曳手勢狀態（不進 Alpine／sel） */
let _yearsDrag = null;
/** @type {Record<string, number>} */
let _makerSlots = {};
/** @type {Record<string, string>} 全庫主要片商年 map（init 算一次，重繪複用） */
let _mainMakerYearMap = {};
/** @type {{w:number,h:number}} */
let _donutLastGoodSize = { w: 280, h: 220 };
/** @type {{ getSel: Function, setPeriod: Function }|null} */
let _yearsCallbacks = null;
/** @type {{ getSel: Function, toggleMaker: Function }|null} */
let _donutCallbacks = null;
/** @type {{ getSel: Function }|null} */
let _tagsCallbacks = null;
/** @type {{ getSel: Function, getFavorites: Function }|null} */
let _ageCallbacks = null;
/** @type {Map<string, { getSel: Function }>} */
const _fieldCallbacks = new Map();

// ── 純函式（node:test 可測）──────────────────────────────────────────

export function resolveYearBarColorMode(sel) {
    return sel && sel.actress != null ? 'byMaker' : 'neutral';
}

export function shouldAnimate(prefersReducedMotion) {
    return !prefersReducedMotion;
}

/**
 * 計算圓餅 startAngle，使目標具名片商扇形中點落在正上方（ECharts 預設 90°）。
 * name===null／不在 inner／total===0 → 回傳 90（原位）。
 */
export function computeDonutStartAngle(inner, name) {
    const list = inner || [];
    let total = 0;
    for (let i = 0; i < list.length; i++) {
        total += list[i].value || 0;
    }
    if (!name || total === 0) return 90;
    let sumBefore = 0;
    let found = null;
    for (let i = 0; i < list.length; i++) {
        if (list[i].name === name) {
            found = list[i];
            break;
        }
        sumBefore += list[i].value || 0;
    }
    if (!found) return 90;
    const midFrac = (sumBefore + (found.value || 0) / 2) / total;
    let angle = 90 + 360 * midFrac;
    angle = ((angle % 360) + 360) % 360;
    return angle;
}


/**
 * getImageData 四分量 → CSS 色字串。a===255 回 rgb()，否則 rgba(..., a/255)。
 * 純函式，供 node:test 守 alpha 不被丟掉。
 */
export function formatRgbaChannels(r, g, b, a) {
    if (a === 255) {
        return 'rgb(' + r + ', ' + g + ', ' + b + ')';
    }
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + (a / 255) + ')';
}

// ── 色票／CSS 讀取 ───────────────────────────────────────────────────

let _colorProbe = null;

function _ensureProbe() {
    if (_colorProbe || typeof document === 'undefined') return;
    _colorProbe = document.createElement('span');
    _colorProbe.style.cssText =
        'position:absolute;left:-9999px;top:-9999px;width:0;height:0;overflow:hidden;pointer-events:none;';
    document.body.appendChild(_colorProbe);
}

function cssColorToRgb(cssColor) {
    // FE-CSS-25：getComputedStyle 可能讀回 oklch(...)；zrender 只認 hex/rgb/hsl，
    // 用 1×1 canvas fillStyle→getImageData 轉成 sRGB（保留 alpha）。
    if (typeof document === 'undefined') return cssColor || '#888888';
    const c = document.createElement('canvas');
    c.width = 1;
    c.height = 1;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    if (!ctx) return cssColor || '#888888';
    ctx.fillStyle = '#000000';
    ctx.fillStyle = cssColor;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    return formatRgbaChannels(r, g, b, a);
}

function resolveColor(expr) {
    _ensureProbe();
    if (!_colorProbe) return '#888888';
    _colorProbe.style.color = '';
    _colorProbe.style.color = expr;
    const css = getComputedStyle(_colorProbe).color || '#888888';
    return cssColorToRgb(css);
}

function cssVar(name) {
    return resolveColor('var(' + name + ')');
}

function readPrefersReducedMotion() {
    return (
        typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
    );
}

function tKey(key, params) {
    if (typeof window !== 'undefined' && typeof window.t === 'function') {
        return window.t(key, params);
    }
    return key;
}

/**
 * 年份拖曳手勢的判定（CD-161a-4）。cats 與 _lastYearCats 同形（未知欄 UNKNOWN_KEY 在尾端）。
 * 回傳 null（無動作）｜{kind:'point', year}｜{kind:'range', from, to}（from<to）。
 * 起點不是真實年份欄 → null；終點夾在 [0, 最後一個真實年份欄]，非有限數視為沒移動；
 * 夾限後兩端同欄 → 單點。
 */
export function resolveDragResult(startIdx, endIdx, cats) {
    const list = Array.isArray(cats) ? cats : [];
    const isReal = (i) =>
        Number.isInteger(i) &&
        i >= 0 &&
        i < list.length &&
        list[i] !== UNKNOWN_KEY &&
        Number.isFinite(parseInt(list[i], 10));
    let lastReal = -1;
    for (let i = 0; i < list.length; i++) {
        if (isReal(i)) lastReal = i;
    }
    if (!isReal(startIdx)) return null;
    let end = Number.isFinite(endIdx) ? Math.round(endIdx) : startIdx;
    end = Math.max(0, Math.min(end, lastReal));
    if (!isReal(end)) return null;
    const a = parseInt(list[startIdx], 10);
    const b = parseInt(list[end], 10);
    if (a === b) return { kind: 'point', year: a };
    return { kind: 'range', from: Math.min(a, b), to: Math.max(a, b) };
}

/** 年份拖曳預覽蓋板的固定 id（只切 invisible，不 remove；FE-JS-05）。 */
export const YEARS_DRAG_PREVIEW_ID = 'years-drag-hl';

/** 預覽蓋板填色（與 selectedColor 同為 token＋color-mix，一層平塗）。 */
const YEARS_DRAG_PREVIEW_FILL_EXPR = 'color-mix(in oklch, var(--color-primary) 18%, transparent)';

/** zr 事件是否來自觸控（zrByTouch 標記，或 event.type 以 touch 開頭作備案）。 */
export function isTouchZrEvent(ev) {
    if (!ev) return false;
    if (ev.zrByTouch === true) return true;
    const type = ev.event && ev.event.type;
    return typeof type === 'string' && type.startsWith('touch');
}

/** 手勢提交結果：觸控拖過多欄（range）→ 無動作；同欄 tap 仍是 point。 */
export function resolveGestureResult(startIdx, endIdx, cats, byTouch) {
    const r = resolveDragResult(startIdx, endIdx, cats);
    if (byTouch && r && r.kind === 'range') return null;
    return r;
}

/** 預覽跨度：只有這次拖曳放開會成為 range 才有值，否則 null。夾限與 resolveDragResult 同源。 */
export function resolveDragPreviewSpan(startIdx, endIdx, cats) {
    const r = resolveDragResult(startIdx, endIdx, cats);
    if (!r || r.kind !== 'range') return null;
    const list = Array.isArray(cats) ? cats : [];
    const fromIdx = list.indexOf(String(r.from));
    const toIdx = list.indexOf(String(r.to));
    if (fromIdx < 0 || toIdx < 0) return null;
    return { fromIdx, toIdx };
}

/** 預覽矩形：吸附欄界、涵蓋 from 到 to 兩端整欄、高度＝整個圖高。 */
export function dragPreviewRect(span, centerX0, band, height) {
    if (!span || !(band > 0)) return null;
    const x = centerX0 + span.fromIdx * band - band / 2;
    return { x, width: (span.toIdx - span.fromIdx + 1) * band, height };
}

/** 預覽 graphic 元素：id 固定、invisible 每次明寫、不帶 action 欄位、不吃事件。 */
export function buildDragPreviewGraphic(rect, fill) {
    return {
        id: YEARS_DRAG_PREVIEW_ID,
        type: 'rect',
        silent: true, // 預覽不吃事件
        invisible: rect == null,
        shape: {
            x: rect ? rect.x : 0,
            y: 0,
            width: rect ? rect.width : 0,
            height: rect ? rect.height : 0,
        },
        style: { fill },
    };
}

/** 收掉進行中的年份拖曳（唯一的 document mouseup 移除點；可重複呼叫）。 */
export function cancelYearsDrag() {
    const drag = _yearsDrag;
    if (!drag) return;
    document.removeEventListener('mouseup', drag.onDocUp);
    _yearsDrag = null;
}

/** 開始年份拖曳：先收掉舊手勢，再掛 document 層 mouseup。 */
export function beginYearsDrag(startIdx, byTouch, onDocUp) {
    cancelYearsDrag();
    _yearsDrag = { startIdx, curIdx: startIdx, byTouch: byTouch === true, onDocUp, lastSpanKey: '' };
    document.addEventListener('mouseup', onDocUp);
}

/** 手勢狀態拷貝（不含 onDocUp）；無手勢回 null。 */
export function getYearsDragState() {
    if (!_yearsDrag) return null;
    return {
        startIdx: _yearsDrag.startIdx,
        curIdx: _yearsDrag.curIdx,
        byTouch: _yearsDrag.byTouch,
    };
}

/** 設定預覽（span＝null 收起）；merge 模式、不帶第二參數、不傳 series。 */
function _setYearsPreview(c, span) {
    if (!c || c.isDisposed()) return;
    const fill = resolveColor(YEARS_DRAG_PREVIEW_FILL_EXPR);
    let rect = null;
    if (span) {
        const centerX0 = c.convertToPixel({ seriesIndex: 0 }, [0, 0])[0];
        const band =
            _lastYearCats.length > 1
                ? Math.abs(c.convertToPixel({ seriesIndex: 0 }, [1, 0])[0] - centerX0)
                : c.getWidth();
        rect = dragPreviewRect(span, centerX0, band, c.getHeight());
    }
    c.setOption({ graphic: [buildDragPreviewGraphic(rect, fill)] });
}

/**
 * 空狀態 key 的唯一入口（CD-161a-2）：count＝該卡範圍內的片數
 * （scopeRecords(records, sel, skipDim).length），不是聚合後的筆數。
 * skipDim：年份長條 'period'、圓餅 'maker'、其餘 null。
 */
export function emptyKeyForCard(records, sel, skipDim) {
    return emptyKey(sel, skipDim, scopeRecords(records, sel, skipDim).length) || 'insights.no_data';
}

// period_empty 照原樣顯示；其餘落回該卡自己的「沒有資料」文字。
function _emptyText(key, fallbackKey) {
    return key === 'insights.period_empty' ? tKey(key) : tKey(fallbackKey);
}

/**
 * ECharts tooltip 走 renderMode:'html'，自訂 formatter 回傳的字串會被當 innerHTML
 * 插入（P3-1）；tag／片商名等來自本機資料，不可信任，插進 tooltip 前一律先過這支。
 * 刻意的 `<br/>` 是呼叫端字面接的，不經過這支，不受影響。
 */
export function escapeHtml(str) {
    return String(str == null ? '' : str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function labelForCategory(cat) {
    return cat === UNKNOWN_KEY ? tKey('insights.unknown') : cat;
}

function neutralOther() {
    return resolveColor(
        'color-mix(in oklch, var(--color-base-content) 22%, transparent)',
    );
}

function colorForMaker(name) {
    if (name && Object.prototype.hasOwnProperty.call(_makerSlots, name)) {
        const slot = _makerSlots[name]; // 0..7
        return cssVar('--insights-maker-' + (slot + 1));
    }
    return neutralOther();
}

function neutralUnknown() {
    return resolveColor(
        'color-mix(in oklch, var(--color-base-content) 12%, transparent)',
    );
}

/** 外圈「其他作品」：主色淡化（poc tint 35%）。 */
function tintMakerColor(rgbStr) {
    return resolveColor(
        'color-mix(in srgb, ' + rgbStr + ' 35%, var(--surface-1))',
    );
}

function surfaceBorder() {
    return cssVar('--surface-1');
}

function labelForDonutKey(key) {
    if (key === REST_KEY) return tKey('insights.donut.other');
    if (key === UNKNOWN_KEY) return tKey('insights.donut.unknown');
    return key;
}

export function setMakerColorSlots(slots) {
    _makerSlots = slots || {};
}

export function refreshMakerColorSlots() {
    _makerSlots = buildMakerColorSlots(getRecords());
}

export function setMainMakerYearMap(map) {
    _mainMakerYearMap = map || {};
}

export function colorForMakerName(name) {
    return colorForMaker(name);
}

// ── 生命週期 ─────────────────────────────────────────────────────────

export function areChartsAlive() {
    if (_charts.size === 0) return false;
    for (const chart of _charts.values()) {
        if (!chart || chart.isDisposed()) return false;
    }
    return true;
}

export function disposeAll() {
    for (const ro of _observers.values()) {
        try {
            ro.disconnect();
        } catch {
            /* ignore */
        }
    }
    _observers.clear();
    for (const chart of _charts.values()) {
        try {
            if (chart && !chart.isDisposed()) chart.dispose();
        } catch {
            /* ignore */
        }
    }
    cancelYearsDrag(); // disposeAll：清掉年份拖曳的 document 監聽
    _charts.clear();
    // 保留 _yearsCallbacks：bfcache 還原後 reinit 還要用同一組 getter/setter
}

export function resizeAll() {
    for (const chart of _charts.values()) {
        if (chart && !chart.isDisposed()) chart.resize();
    }
}

/**
 * bfcache 還原且圖表已被 dispose 時：對既有 DOM 重新 init + setOption。
 */
export function reinitYearsAfterDispose() {
    const el = document.getElementById('yearsChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_yearsCallbacks) return;
    initYearsChart(el, _yearsCallbacks);
    updateYearsChart({
        sel: _yearsCallbacks.getSel(),
    });
}

/**
 * bfcache 還原：圓餅與年份同一套 callbacks 生命週期。
 */
export function reinitDonutAfterDispose() {
    const el = document.getElementById('donutChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_donutCallbacks) return;
    initDonutChart(el, _donutCallbacks);
    updateDonutChart({
        sel: _donutCallbacks.getSel(),
    });
}

/**
 * bfcache 還原：標籤樹圖與 years/donut 同一套 callbacks 生命週期。
 */
export function reinitTagsAfterDispose() {
    const el = document.getElementById('tagsChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_tagsCallbacks) return;
    initTagsChart(el, _tagsCallbacks);
    updateTagsChart({
        sel: _tagsCallbacks.getSel(),
    });
}

/**
 * bfcache 還原：年齡長條與 tags 同一套 callbacks 生命週期。
 */
export function reinitAgeAfterDispose() {
    const el = document.getElementById('ageChart');
    if (!el || typeof window.echarts === 'undefined') return;
    if (!_ageCallbacks) return;
    initAgeChart(el, _ageCallbacks);
    updateAgeChart({
        sel: _ageCallbacks.getSel(),
        favorites: _ageCallbacks.getFavorites(),
    });
}

/**
 * bfcache 還原：導演／系列長條圖生命週期。
 * @param {string} field
 */
export function reinitFieldBarAfterDispose(field) {
    const el = document.getElementById(field + 'Chart');
    if (!el || typeof window.echarts === 'undefined') return;
    const callbacks = _fieldCallbacks.get(field);
    if (!callbacks) return;
    initFieldBarChart(el, field, callbacks);
    updateFieldBarChart(
        {
            sel: callbacks.getSel(),
        },
        field,
    );
}

/**
 * @param {HTMLElement} containerEl
 * @param {{ getSel: Function, setPeriod: Function }} callbacks
 */
export function initYearsChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _yearsCallbacks = callbacks;
    cancelYearsDrag(); // initYearsChart：重建實例前收掉進行中的手勢

    let chart = _charts.get('years');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('years', chart);

    const prevRo = _observers.get('years');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('years');
        if (c && !c.isDisposed()) c.resize();
    });
    ro.observe(containerEl);
    _observers.set('years', ro);

    // 每次 init 都掛在新實例上（dispose 後舊 listener 隨實例消失）
    // 整支長條「柱身以外空白」也要能點到——用 getZr 原始像素，不是 series click。
    // 單點與範圍由同一個手勢辨識器（mousedown→mousemove→mouseup）提交，不用 click。

    // 像素 → 欄索引（可能 NaN／null）；不擋 grid 外，交給 resolveDragResult 夾限
    const pixelToIdx = (c, ev) => {
        const oe = ev && ev.event ? ev.event : ev;
        const ox = oe && oe.offsetX != null ? oe.offsetX : ev.offsetX;
        const oy = oe && oe.offsetY != null ? oe.offsetY : ev.offsetY;
        if (ox == null || oy == null) return { pixel: null, idx: NaN };
        const pixel = [ox, oy];
        const pointInGrid = c.convertFromPixel({ seriesIndex: 0 }, pixel);
        let idx = Array.isArray(pointInGrid) ? pointInGrid[0] : pointInGrid;
        idx = typeof idx === 'number' ? Math.round(idx) : NaN;
        return { pixel, idx };
    };

    const finishDrag = () => {
        const drag = _yearsDrag;
        if (!drag) return; // 冪等：zr mouseup 與 document mouseup 只收尾一次
        // 無條件先收預覽（單點／同範圍重選不會重繪，否則預覽會卡在畫面上）
        _setYearsPreview(_charts.get('years'), null);
        cancelYearsDrag();
        if (!_yearsCallbacks) return;
        const result = resolveGestureResult(
            drag.startIdx,
            drag.curIdx,
            _lastYearCats,
            drag.byTouch,
        );
        if (!result) return;
        if (result.kind === 'range') {
            _yearsCallbacks.setPeriod({ type: 'range', from: result.from, to: result.to });
            return;
        }
        const sel = _yearsCallbacks.getSel();
        const cur = sel && sel.period;
        if (cur && cur.type === 'year' && cur.year === result.year) {
            _yearsCallbacks.setPeriod({ type: 'all' });
        } else {
            _yearsCallbacks.setPeriod({ type: 'year', year: result.year });
        }
    };

    chart.getZr().on('mousedown', (ev) => {
        const c = _charts.get('years');
        if (!c || c.isDisposed() || !_yearsCallbacks) return;
        const oe = ev && ev.event ? ev.event : ev;
        if (oe && oe.button != null && oe.button !== 0) return;
        const { pixel, idx } = pixelToIdx(c, ev);
        if (!pixel || !c.containPixel('grid', pixel)) return;
        if (resolveDragResult(idx, idx, _lastYearCats) === null) return;
        const onDocUp = () => finishDrag();
        beginYearsDrag(idx, isTouchZrEvent(ev), onDocUp);
    });

    chart.getZr().on('mousemove', (ev) => {
        if (!_yearsDrag) return;
        const c = _charts.get('years');
        if (!c || c.isDisposed()) return;
        const { idx } = pixelToIdx(c, ev);
        if (Number.isFinite(idx)) _yearsDrag.curIdx = idx;
        if (_yearsDrag.byTouch) return; // 觸控不做預覽
        const span = resolveDragPreviewSpan(_yearsDrag.startIdx, _yearsDrag.curIdx, _lastYearCats);
        const key = span ? span.fromIdx + '-' + span.toIdx : '';
        if (key === _yearsDrag.lastSpanKey) return;
        _yearsDrag.lastSpanKey = key;
        _setYearsPreview(c, span);
    });

    chart.getZr().on('mouseup', (ev) => {
        if (!_yearsDrag) return;
        const c = _charts.get('years');
        if (c && !c.isDisposed()) {
            const { idx } = pixelToIdx(c, ev);
            if (Number.isFinite(idx)) _yearsDrag.curIdx = idx;
        }
        finishDrag();
    });
}

export function getYearsChart() {
    return _charts.get('years') || null;
}

// ── 年份長條 setOption ───────────────────────────────────────────────

function _buildAxisLabels(categories) {
    return categories.map(labelForCategory);
}

/** 從即將／當下的 maker series 名單取 seriesKey（不含全庫色票）。 */
function _makerKeysFromAggSeries(aggSeries) {
    return (aggSeries || []).map(function (s) {
        return s.name == null ? UNKNOWN_KEY : s.name;
    });
}

/**
 * 從已渲染的 ECharts series 讀出單一字面 seriesKey
 * （清除方向：舊的 N 個 maker series）。
 */
function _makerKeysFromRenderedSeries(seriesArr) {
    const keys = [];
    for (let i = 0; i < (seriesArr || []).length; i++) {
        const s = seriesArr[i];
        if (!s) continue;
        const sk = s.universalTransition && s.universalTransition.seriesKey;
        if (typeof sk === 'string' && sk) {
            keys.push(sk);
            continue;
        }
        const id = s.id;
        if (typeof id === 'string' && id.indexOf('years-maker-') === 0) {
            keys.push(id.slice('years-maker-'.length));
        }
    }
    return keys;
}

function _opacityForIndex(dimmed, i) {
    return dimmed && dimmed[i] ? 0.35 : 1;
}

/**
 * @param {{ sel: object }} state
 */
export function updateYearsChart(state) {
    const chart = _charts.get('years');
    if (!chart || chart.isDisposed()) return;

    const sel = state.sel || emptySel();
    const period = sel.period || { type: 'all' };
    const records = getRecords();
    const agg = aggregateYears(records, sel);
    const categories = agg.categories || [];
    const dimmed = agg.dimmed || [];
    _lastYearCats = categories.slice();

    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);
    const colorMode = resolveYearBarColorMode(sel);

    const normalColor = cssVar('--color-primary');
    const selectedColor = resolveColor(
        'color-mix(in oklch, var(--color-primary) 55%, white 45%)',
    );

    if (!categories.length) {
        chart.clear();
        chart.setOption({
            animation: animate,
            graphic: [
                {
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    style: {
                        text: tKey('insights.no_data'),
                        fontSize: 11,
                        fill: cssVar('--text-muted'),
                    },
                },
            ],
        });
        return;
    }

    const axisData = _buildAxisLabels(categories);
    const prevOpt = chart.getOption();
    const prevSeries = (prevOpt && prevOpt.series) || [];

    /** @type {object[]} */
    let series;

    if (colorMode === 'byMaker') {
        // 進入方向：seriesKey = 即將 setOption 的新 maker 名單；
        // 先把舊 total 的 seriesKey 對齊，再 replaceMerge 成 N 段。
        const newKeys = _makerKeysFromAggSeries(agg.series);
        if (prevSeries.length === 1) {
            try {
                chart.setOption({
                    series: [
                        {
                            id: prevSeries[0].id || 'years-total',
                            universalTransition: {
                                enabled: true,
                                seriesKey: newKeys,
                                divideShape: YEARS_DIVIDE_SHAPE,
                            },
                        },
                    ],
                });
            } catch {
                /* ignore */
            }
        }

        series = (agg.series || []).map((s) => {
            const mk = s.name;
            const color =
                mk === UNKNOWN_KEY || mk === null
                    ? neutralUnknown()
                    : colorForMaker(mk);
            const data = (s.data || []).map((v, i) => ({
                value: v,
                itemStyle: { opacity: _opacityForIndex(dimmed, i) },
            }));
            const key = mk == null ? UNKNOWN_KEY : mk;
            return {
                id: 'years-maker-' + key,
                name: labelForCategory(key),
                type: 'bar',
                stack: 'total',
                barMaxWidth: 26,
                data,
                itemStyle: {
                    color,
                    borderColor: surfaceBorder(),
                    borderWidth: 2,
                },
                emphasis: { focus: 'series' },
                universalTransition: {
                    enabled: true,
                    seriesKey: key,
                    divideShape: YEARS_DIVIDE_SHAPE,
                },
            };
        });
    } else {
        // 清除方向：seriesKey = 當下已渲染的舊 maker series；否則退回 agg 名單
        const keysFromPrev = _makerKeysFromRenderedSeries(prevSeries);
        const transitionKeys =
            keysFromPrev.length > 0
                ? keysFromPrev
                : _makerKeysFromAggSeries(agg.series);

        const src = (agg.series && agg.series[0] && agg.series[0].data) || [];
        const anySelected = period.type !== 'all';
        const data = src.map((v, i) => {
            const cat = categories[i];
            const selected =
                anySelected && cat !== UNKNOWN_KEY && periodContainsYear(period, Number(cat));
            const opacity = _opacityForIndex(dimmed, i);
            const isUnknown = cat === UNKNOWN_KEY;
            return {
                value: v,
                itemStyle: {
                    color: isUnknown
                        ? neutralUnknown()
                        : selected
                          ? selectedColor
                          : normalColor,
                    opacity,
                },
            };
        });
        series = [
            {
                id: 'years-total',
                name:
                    sel.maker != null
                        ? sel.maker
                        : tKey('insights.row.years'),
                type: 'bar',
                barMaxWidth: 26,
                data,
                universalTransition: {
                    enabled: true,
                    seriesKey: transitionKeys,
                    divideShape: YEARS_DIVIDE_SHAPE,
                },
            },
        ];
    }

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    // 兩個方向都保留 universalTransition + replaceMerge；不全域 notMerge。
    chart.setOption(
        {
            animation: animate,
            animationDuration: 250,
            animationDurationUpdate: 400,
            graphic: [buildDragPreviewGraphic(null, resolveColor('color-mix(in oklch, var(--color-primary) 18%, transparent)'))],
            grid: { left: 4, right: 8, top: 8, bottom: 20, containLabel: true },
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                textStyle: { fontSize: 11 },
            },
            xAxis: {
                type: 'category',
                data: axisData,
                axisLine: { lineStyle: { color: cssVar('--stroke-default') } },
                axisLabel: { fontSize: 11, color: cssVar('--text-muted') },
                axisTick: { show: false },
            },
            yAxis: {
                type: 'value',
                splitLine: { lineStyle: { color: cssVar('--stroke-subtle') } },
                axisLabel: { fontSize: 11, color: cssVar('--text-muted') },
            },
            series,
        },
        { replaceMerge: ['series'] },
    );
}

// ── 片商雙層圓餅 ─────────────────────────────────────────────────────

/**
 * @param {HTMLElement} containerEl
 * @param {{ getSel: Function, toggleMaker: Function }} callbacks
 */
export function initDonutChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _donutCallbacks = callbacks;

    let chart = _charts.get('donut');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('donut', chart);

    const prevRo = _observers.get('donut');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('donut');
        if (c && !c.isDisposed()) {
            c.resize();
            // 半徑依容器像素重算——resize 後補一次 setOption
            if (_donutCallbacks) {
                updateDonutChart({
                    sel: _donutCallbacks.getSel(),
                });
            }
        }
    });
    ro.observe(containerEl);
    _observers.set('donut', ro);

    chart.on('click', (params) => {
        if (!_donutCallbacks || typeof _donutCallbacks.toggleMaker !== 'function') {
            return;
        }
        // 只接受內圈（seriesIndex 0）具名扇形；rest／unknown 無效果。
        // 不做女優條件早退（D156-6：選了女優時點片商直接切換）。
        if (params.seriesIndex !== 0) return;
        const data = params.data;
        if (!data || data.kind !== 'named' || !data.name) return;
        const name = data.name;
        // 點擊當下扇形處於 emphasis/hover；若不先 downplay，後續 startAngle
        // transition 會被跳過（角度一步到終值，只剩 select/emphasis 的位移在動）。
        try {
            chart.dispatchAction({ type: 'downplay' });
        } catch {
            /* ignore */
        }
        _donutCallbacks.toggleMaker(name);
    });
}

export function getDonutChart() {
    return _charts.get('donut') || null;
}

/**
 * §4.2 wiring：圓餅看期間∩女優（skipDim 'maker'），選了片商只高亮。
 * @param {{ sel: object }} state
 */
export function updateDonutChart(state) {
    const chart = _charts.get('donut');
    if (!chart || chart.isDisposed()) return;

    const sel = state.sel || emptySel();
    const allRecords = getRecords();

    const dataRecords = scopeRecords(allRecords, sel, 'maker');
    const highlightKey = sel.maker != null ? sel.maker : null;

    const donut = buildMakerDonutData(dataRecords, _mainMakerYearMap);
    const total = donut.total;
    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);

    if (!total) {
        chart.clear();
        chart.setOption({
            animation: animate,
            graphic: [
                {
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    style: {
                        text: tKey(emptyKeyForCard(allRecords, sel, 'maker')),
                        fontSize: 11,
                        fill: cssVar('--text-muted'),
                    },
                },
            ],
            series: [],
        });
        return;
    }

    function opacityFor(name) {
        if (!highlightKey) return 1;
        return name === highlightKey ? 1 : 0.35;
    }

    const top5Names = {};
    donut.inner
        .filter((e) => e.kind === 'named')
        .slice(0, 5)
        .forEach((e) => {
            if (total && e.value / total >= 0.04) {
                top5Names[e.name] = true;
            }
        });

    const innerData = donut.inner.map((e) => {
        let color;
        if (e.kind === 'unknown') {
            color = neutralUnknown();
        } else if (e.kind === 'rest') {
            color = neutralOther();
        } else {
            color = colorForMaker(e.name);
        }
        return {
            name: e.name,
            value: e.value,
            kind: e.kind,
            itemStyle: {
                color,
                opacity: opacityFor(e.name),
                borderColor: surfaceBorder(),
                borderWidth: 2,
            },
            label: {
                show: !!top5Names[e.name],
            },
        };
    });

    const outerData = donut.outer.map((e) => {
        let color;
        let displayName;
        if (e.kind === 'rest') {
            color = neutralOther();
            displayName = labelForDonutKey(REST_KEY);
        } else if (e.kind === 'unknown') {
            color = neutralUnknown();
            displayName = labelForDonutKey(UNKNOWN_KEY);
        } else if (e.kind === 'undetermined') {
            color = neutralUnknown();
            displayName = e.maker;
        } else if (e.kind === 'main') {
            color = colorForMaker(e.maker);
            displayName = e.maker;
        } else {
            // other：主色淡化
            color = tintMakerColor(colorForMaker(e.maker));
            displayName = e.maker;
        }
        return {
            name: displayName + '|' + e.kind,
            value: e.value,
            maker: e.maker,
            kind: e.kind,
            itemStyle: {
                color,
                opacity: opacityFor(e.maker),
                borderColor: surfaceBorder(),
                borderWidth: 1,
            },
        };
    });

    let boxW = chart.getWidth();
    let boxH = chart.getHeight();
    if (boxW < 150 || boxH < 100) {
        boxW = _donutLastGoodSize.w;
        boxH = _donutLastGoodSize.h;
    } else {
        _donutLastGoodSize.w = boxW;
        _donutLastGoodSize.h = boxH;
    }
    const vPad = 8;
    // 窄寬（如 390）時外標籤會吃掉左右各 ~90px，maxOuterR 被寬度卡住 → 外徑 < 85% 高。
    // 改為內側標籤並縮 labelMargin，讓圓餅撐滿可用高度。
    const narrow = boxW < 420;
    const labelMargin = narrow ? 8 : 90;
    const usableW = Math.max(60, boxW - labelMargin * 2);
    const usableH = Math.max(60, boxH - vPad * 2);
    const maxOuterR = Math.min(usableW, usableH) / 2;
    const rOuterOuter = Math.round(maxOuterR * 0.99);
    const rOuterInner = Math.round(maxOuterR * 0.8);
    const rInnerOuter = Math.round(maxOuterR * 0.62);
    const rInnerInner = Math.round(maxOuterR * 0.38);

    const startAngle = computeDonutStartAngle(
        donut.inner,
        highlightKey,
    );

    const centerSub = tKey('insights.unit');
    const centerText =
        (total || 0).toLocaleString('zh-Hant') + '\n{sub|' + centerSub + '}';

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    /** 點擊 hover 的 emphasis 會讓 startAngle transition 失效；圓餅關閉 emphasis。 */
    const emphasisOff = { disabled: true };

    const innerLabel = narrow
        ? {
              show: true,
              position: 'inside',
              formatter: function (p) {
                  const nm = p.data && p.data.name;
                  if (!top5Names[nm]) return '';
                  return Math.round(p.percent) + '%';
              },
              fontSize: 10,
              color: cssVar('--text-primary'),
              overflow: 'truncate',
          }
        : {
              show: true,
              formatter: function (p) {
                  const nm = p.data && p.data.name;
                  if (!top5Names[nm]) return '';
                  return (
                      labelForDonutKey(nm) +
                      ' ' +
                      Math.round(p.percent) +
                      '%'
                  );
              },
              fontSize: 11,
              color: cssVar('--text-secondary'),
              overflow: 'none',
              width: labelMargin + 20,
              alignTo: 'labelLine',
              edgeDistance: 4,
          };

    const innerLabelLine = narrow
        ? { show: false }
        : {
              show: true,
              length: 8,
              length2: 6,
              lineStyle: { color: cssVar('--stroke-default') },
          };

    chart.setOption(
        {
            animation: animate,
            animationDuration: 250,
            animationDurationUpdate: 400,
            graphic: [
                {
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    z: 10,
                    style: {
                        text: centerText,
                        textAlign: 'center',
                        fontSize: narrow ? 14 : 16,
                        fontWeight: 700,
                        fill: cssVar('--text-primary'),
                        lineHeight: 17,
                        rich: {
                            sub: {
                                fontSize: 9,
                                fontWeight: 400,
                                fill: cssVar('--text-muted'),
                                lineHeight: 12,
                            },
                        },
                    },
                },
            ],
            tooltip: {
                trigger: 'item',
                textStyle: { fontSize: 11 },
                formatter: function (p) {
                    const d = p.data || {};
                    const title =
                        p.seriesIndex === 0
                            ? labelForDonutKey(d.name)
                            : labelForDonutKey(d.maker);
                    return (
                        escapeHtml(title) +
                        '<br/>' +
                        (d.value || 0).toLocaleString('zh-Hant') +
                        '（' +
                        p.percent +
                        '%）'
                    );
                },
            },
            series: [
                {
                    id: 'donut-inner',
                    type: 'pie',
                    name: 'inner',
                    center: ['50%', '50%'],
                    radius: [rInnerInner, rInnerOuter],
                    startAngle,
                    clockwise: true,
                    animationTypeUpdate: 'transition',
                    avoidLabelOverlap: true,
                    minShowLabelAngle: 8,
                    selectedMode: highlightKey ? 'single' : false,
                    selectedOffset: 6,
                    emphasis: emphasisOff,
                    label: innerLabel,
                    labelLine: innerLabelLine,
                    data: innerData.map((d) => ({
                        ...d,
                        selected: !!(highlightKey && d.name === highlightKey),
                    })),
                },
                {
                    id: 'donut-outer',
                    type: 'pie',
                    name: 'outer',
                    center: ['50%', '50%'],
                    radius: [rOuterInner, rOuterOuter],
                    startAngle,
                    clockwise: true,
                    animationTypeUpdate: 'transition',
                    avoidLabelOverlap: false,
                    emphasis: emphasisOff,
                    label: { show: false },
                    labelLine: { show: false },
                    data: outerData,
                },
            ],
        },
        { replaceMerge: ['series'] },
    );
}

// ── 標籤矩形樹圖（TASK-156b-T6）─────────────────────────────────────

function _pctLabel(n, d) {
    if (!d) return '0%';
    return Math.round((n / d) * 100) + '%';
}

function _isDimTheme() {
    return (
        typeof document !== 'undefined' &&
        document.documentElement.getAttribute('data-theme') === 'dim'
    );
}

/**
 * 樹圖點擊 params → 瀏覽頁條件；非樹圖格或無名稱回 null。
 * @param {object} params
 * @returns {{dim:'tag', value:string}|null}
 */
export function extraFromTreemapClick(params) {
    if (!params || params.componentType !== 'series' || params.seriesType !== 'treemap') return null;
    const name = params.data && params.data.name;
    if (typeof name !== 'string' || !name) return null;
    return { dim: 'tag', value: name };
}

/**
 * 導演／系列長條點擊 params → 瀏覽頁條件；field 僅接受 director／series。
 * @param {string} field
 * @param {object} params
 * @returns {{dim:string, value:string}|null}
 */
export function extraFromBarClick(field, params) {
    if (field !== 'director' && field !== 'series') return null;
    if (!params || typeof params.name !== 'string' || !params.name) return null;
    return { dim: field, value: params.name };
}

/**
 * 組 #tagsPulled：前綴文字＋每個標籤一顆按鈕＋「、」分隔；只用 createElement／textContent。
 * @param {HTMLElement} el
 * @param {Array<[string, number]>} pulled
 * @param {number} total
 * @param {string} prefix
 * @param {(extra:{dim:'tag', value:string}) => void} onPick
 */
export function renderPulledChips(el, pulled, total, prefix, onPick) {
    if (!el) return;
    if (!pulled || !pulled.length || !total) {
        el.replaceChildren();
        return;
    }
    const nodes = [document.createTextNode(prefix)];
    pulled.forEach(function (e, i) {
        if (i > 0) nodes.push(document.createTextNode('、'));
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'tags-pulled-chip';
        btn.title = tKey('insights.count_open_browse');
        const pct = Math.round((e[1] / total) * 100);
        btn.textContent = e[0] + ' ' + pct + '%';
        btn.addEventListener('click', function () { onPick({ dim: 'tag', value: e[0] }); });
        nodes.push(btn);
    });
    el.replaceChildren(...nodes);
}

/**
 * 導演／系列長條 axis tooltip：名稱經 escapeHtml（renderMode html）。
 * @param {Array<{name:string, value:number}>} params
 * @returns {string}
 */
export function fieldBarTooltip(params) {
    const p = Array.isArray(params) ? params[0] : params;
    if (!p) return '';
    const name = p.name;
    return escapeHtml(name) + ' ' + (p.value || 0).toLocaleString('zh-Hant') +
        '<br/>' + escapeHtml(tKey('insights.count_open_browse'));
}

/**
 * @param {HTMLElement} containerEl
 * @param {{ getSel: Function }} callbacks
 */
export function initTagsChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _tagsCallbacks = callbacks;

    let chart = _charts.get('tags');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('tags', chart);

    const prevRo = _observers.get('tags');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('tags');
        if (c && !c.isDisposed()) c.resize();
    });
    ro.observe(containerEl);
    _observers.set('tags', ro);

    chart.on('click', function (params) {
        const extra = extraFromTreemapClick(params);
        if (!extra) return;
        if (typeof _tagsCallbacks.goBrowseWith !== 'function') return;
        _tagsCallbacks.goBrowseWith(extra);
    });
}

export function getTagsChart() {
    return _charts.get('tags') || null;
}

/**
 * §4.2 wiring：範圍＝期間∩女優∩片商（scopeRecords，不跳維度）。
 * 刻意不設 animationDurationUpdate（含 0）——ECharts 6.1.0 treemap 在
 * animationDurationUpdate:0 ＋版面驟縮時會把格子算成 NaN。
 * @param {{ sel: object }} state
 */
export function updateTagsChart(state) {
    const chart = _charts.get('tags');
    if (!chart || chart.isDisposed()) return;

    const sel = state.sel || emptySel();
    const allRecords = getRecords();
    const dataRecords = scopeRecords(allRecords, sel, null);

    const agg = aggregateTags(dataRecords);
    const total = agg.total;
    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);

    const hintEl = document.getElementById('tagsHint');
    if (hintEl) {
        hintEl.textContent = tKey('insights.tags.coverage', {
            pct: _pctLabel(agg.withTagCount, total),
        });
    }

    const pulledEl = document.getElementById('tagsPulled');
    if (pulledEl) {
        renderPulledChips(pulledEl, agg.pulled, total, tKey('insights.tags.almost_all'), function (extra) {
            if (_tagsCallbacks && typeof _tagsCallbacks.goBrowseWith === 'function') {
                _tagsCallbacks.goBrowseWith(extra);
            }
        });
    }

    if (!agg.rest.length) {
        chart.clear();
        chart.setOption(
            {
                animation: animate,
                animationDuration: 250,
                graphic: [
                    {
                        type: 'text',
                        left: 'center',
                        top: 'middle',
                        style: {
                            text: _emptyText(
                                emptyKeyForCard(allRecords, sel, null),
                                'insights.tags.empty',
                            ),
                            fontSize: 11,
                            fill: cssVar('--text-muted'),
                        },
                    },
                ],
                series: [],
            },
            true,
        );
        return;
    }

    const top40 = agg.rest;
    const maxV = top40[0][1];
    const minV = top40[top40.length - 1][1];
    const borderColor = surfaceBorder();
    const isDim = _isDimTheme();
    const lLo = isDim ? 70 : 90;
    const lHi = isDim ? 40 : 60;

    const data = top40.map(function (e) {
        const t =
            maxV > minV ? (e[1] - minV) / (maxV - minV) : 1;
        const lightness = Math.round(lLo + (lHi - lLo) * t);
        const color = resolveColor(
            'oklch(' + lightness + '% 0.045 250)',
        );
        const textColor = lightness >= 60 ? '#1c1c1c' : '#f2f2f2';
        return {
            name: e[0],
            value: e[1],
            _pct: _pctLabel(e[1], total),
            itemStyle: { color: color },
            label: { color: textColor },
        };
    });

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    // notMerge:true；刻意不設 animationDurationUpdate（NaN 規避）。
    chart.setOption(
        {
            animation: animate,
            animationDuration: 250,
            graphic: [],
            tooltip: {
                trigger: 'item',
                textStyle: { fontSize: 11 },
                formatter: function (p) {
                    return tKey('insights.tags.tooltip', {
                        name: escapeHtml(p.name),
                        count: (p.value || 0).toLocaleString('zh-Hant'),
                        pct: (p.data && p.data._pct) || '0%',
                    }) + '<br/>' + escapeHtml(tKey('insights.count_open_browse'));
                },
            },
            series: [
                {
                    type: 'treemap',
                    roam: false,
                    nodeClick: false,
                    breadcrumb: { show: false },
                    left: 0,
                    top: 0,
                    right: 0,
                    bottom: 0,
                    visibleMin: 30,
                    label: {
                        show: true,
                        formatter: function (p) {
                            return p.name + '\n' + p.value;
                        },
                        fontSize: 11,
                        overflow: 'truncate',
                    },
                    upperLabel: { show: false },
                    itemStyle: {
                        borderColor: borderColor,
                        borderWidth: 1,
                        gapWidth: 1,
                    },
                    emphasis: { label: { show: true } },
                    data: data,
                },
            ],
        },
        true,
    );
}

// ── 年齡分布長條（TASK-156c-T1）─────────────────────────────────────

/**
 * @param {HTMLElement} containerEl
 * @param {{ getSel: Function, getFavorites: Function }} callbacks
 */
export function initAgeChart(containerEl, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _ageCallbacks = callbacks;

    let chart = _charts.get('age');
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set('age', chart);

    const prevRo = _observers.get('age');
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get('age');
        if (c && !c.isDisposed()) c.resize();
    });
    ro.observe(containerEl);
    _observers.set('age', ro);
}

export function getAgeChart() {
    return _charts.get('age') || null;
}

/**
 * §4.2 wiring：範圍＝期間∩女優∩片商（scopeRecords，不跳維度）。
 * setOption 用預設 merge＋固定 series id 'age'，讓長條長度過渡；
 * 只有算不出任何年齡的空分支才 clear()。
 * @param {{ sel: object, favorites?: object|null }} state
 */
export function updateAgeChart(state) {
    const chart = _charts.get('age');
    if (!chart || chart.isDisposed()) return;

    const sel = state.sel || emptySel();
    const favorites = state.favorites || null;
    const allRecords = getRecords();
    const dataRecords = scopeRecords(allRecords, sel, null);

    const agg = aggregateAge(dataRecords, favorites, sel);
    const total = agg.total;
    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);

    const hintEl = document.getElementById('ageHint');
    if (hintEl) {
        hintEl.textContent = tKey('insights.tags.coverage', {
            pct: _pctLabel(agg.recordsWithAge, total),
        });
    }

    if (!agg.pairCount) {
        chart.clear();
        chart.setOption({
            animation: animate,
            animationDuration: 250,
            graphic: [
                {
                    id: 'insightsEmptyText',
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    style: {
                        text: _emptyText(
                            emptyKeyForCard(allRecords, sel, null),
                            'insights.no_data',
                        ),
                        fontSize: 11,
                        fill: cssVar('--text-muted'),
                    },
                },
            ],
        });
        return;
    }

    const categories = agg.categories;
    const counts = agg.counts;
    const median = agg.median;
    const barColor = cssVar('--color-primary');
    const medianIdx = categories.indexOf(String(Math.round(median)));

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    chart.setOption({
        animation: animate,
        animationDuration: 250,
        animationDurationUpdate: 400,
        graphic: [{ id: 'insightsEmptyText', type: 'text', style: { text: '' } }],
        grid: { left: 8, right: 8, top: 26, bottom: 20, containLabel: true },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            textStyle: { fontSize: 11 },
        },
        xAxis: {
            type: 'category',
            data: categories,
            axisLine: { lineStyle: { color: cssVar('--stroke-default') } },
            axisLabel: {
                fontSize: 10,
                color: cssVar('--text-muted'),
                interval: categories.length > 25 ? 1 : 0,
            },
            axisTick: { show: false },
        },
        yAxis: {
            type: 'value',
            splitLine: { lineStyle: { color: cssVar('--stroke-subtle') } },
            axisLabel: { fontSize: 11, color: cssVar('--text-muted') },
        },
        series: [
            {
                id: 'age',
                type: 'bar',
                data: counts,
                barMaxWidth: 18,
                itemStyle: {
                    color: barColor,
                    borderRadius: [2, 2, 0, 0],
                },
                markLine: {
                    silent: true,
                    symbol: 'none',
                    lineStyle: {
                        color: cssVar('--color-secondary'),
                        type: 'dashed',
                    },
                    label: {
                        formatter: tKey('insights.age.median', { age: median }),
                        fontSize: 10,
                        color: cssVar('--text-secondary'),
                    },
                    data: [
                        {
                            xAxis: medianIdx >= 0 ? medianIdx : 0,
                        },
                    ],
                },
            },
        ],
    });
}

// ── 導演／系列水平長條（TASK-156c-T2）───────────────────────────────

/**
 * @param {HTMLElement} containerEl
 * @param {string} field
 * @param {{ getSel: Function }} callbacks
 */
export function initFieldBarChart(containerEl, field, callbacks) {
    if (!containerEl || typeof window.echarts === 'undefined') return;
    _fieldCallbacks.set(field, callbacks);

    let chart = _charts.get(field);
    if (chart && !chart.isDisposed()) {
        chart.dispose();
    }
    chart = window.echarts.init(containerEl);
    _charts.set(field, chart);

    const prevRo = _observers.get(field);
    if (prevRo) prevRo.disconnect();
    const ro = new ResizeObserver(() => {
        const c = _charts.get(field);
        if (c && !c.isDisposed()) c.resize();
    });
    ro.observe(containerEl);
    _observers.set(field, ro);

    chart.on('click', 'series', function (params) {
        const extra = extraFromBarClick(field, params);
        if (!extra) return;
        const cbs = _fieldCallbacks.get(field);
        if (!cbs || typeof cbs.goBrowseWith !== 'function') return;
        _fieldCallbacks.get(field).goBrowseWith(extra);
    });
}

/**
 * §4.2 wiring：範圍＝期間∩女優∩片商（scopeRecords，不跳維度）。
 * setOption 用預設 merge＋固定 series id field，讓長條長度過渡；
 * 只有 0% 涵蓋的空分支才 clear()。
 * @param {{ sel: object }} state
 * @param {string} field
 */
export function updateFieldBarChart(state, field) {
    const chart = _charts.get(field);
    if (!chart || chart.isDisposed()) return;

    const sel = state.sel || emptySel();
    const allRecords = getRecords();
    const dataRecords = scopeRecords(allRecords, sel, null);

    const agg = aggregateFieldTop8(dataRecords, field);
    const total = agg.total;
    const reduceMotion = readPrefersReducedMotion();
    const animate = shouldAnimate(reduceMotion);

    const hintEl = document.getElementById(field + 'Hint');
    if (hintEl) {
        hintEl.textContent = tKey('insights.tags.coverage', {
            pct: _pctLabel(agg.withValueCount, total),
        });
    }

    if (!agg.top.length) {
        chart.clear();
        chart.setOption({
            animation: animate,
            animationDuration: 250,
            graphic: [
                {
                    id: 'insightsEmptyText',
                    type: 'text',
                    left: 'center',
                    top: 'middle',
                    style: {
                        text: _emptyText(
                            emptyKeyForCard(allRecords, sel, null),
                            'insights.no_data',
                        ),
                        fontSize: 11,
                        fill: cssVar('--text-muted'),
                    },
                },
            ],
        });
        return;
    }

    const categories = agg.top.map((e) => e[0]);
    const counts = agg.top.map((e) => e[1]);
    const barColor = cssVar('--color-primary');

    try {
        chart.dispatchAction({ type: 'hideTip' });
    } catch {
        /* ignore */
    }

    chart.setOption({
        animation: animate,
        animationDuration: 250,
        animationDurationUpdate: 400,
        graphic: [{ id: 'insightsEmptyText', type: 'text', style: { text: '' } }],
        grid: { left: 8, right: 16, top: 12, bottom: 20, containLabel: true },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            textStyle: { fontSize: 11 },
            formatter: fieldBarTooltip,
        },
        xAxis: {
            type: 'value',
            minInterval: 1,
            splitLine: { lineStyle: { color: cssVar('--stroke-subtle') } },
            axisLabel: { fontSize: 10, color: cssVar('--text-muted') },
        },
        yAxis: {
            type: 'category',
            inverse: true,
            data: categories,
            axisLine: { lineStyle: { color: cssVar('--stroke-default') } },
            axisTick: { show: false },
            axisLabel: {
                fontSize: 10,
                color: cssVar('--text-muted'),
                width: 80,
                overflow: 'truncate',
            },
        },
        series: [
            {
                id: field,
                type: 'bar',
                data: counts,
                barMaxWidth: 16,
                itemStyle: {
                    color: barColor,
                    borderRadius: [0, 2, 2, 0],
                },
            },
        ],
    });
}

export function getFieldBarChart(field) {
    return _charts.get(field) || null;
}
