/**
 * aggregate.js — 片庫分析聚合純函式（TASK-156b-T1 / T2 / T4）
 *
 * 純函式，零 window / Alpine / DOM。
 * T1：setRecords / getRecords / buildMakerColorSlots / buildMainMakerYearMap
 * T2：periodRecords / scopeRecords / aggregateYears + UNKNOWN_KEY
 * T4：buildMakerDonutData / classifyRecordAgainstMainMaker + REST_KEY
 * T5：buildActressBoard
 * T6：aggregateTags
 * T156c-T1：aggregateAge
 * T156c-T3：buildGanttRows / ganttYearAxis / buildGanttYearCells /
 *           ganttAgeEligibility / ganttAgeAxis / buildGanttAgeCells
 * T156c-T4：buildSoloRows
 */

import { computeActressAgeForVideo } from '../../shared/actress-release-age.js';
import { canonicalMakerLabels } from '../../shared/maker-merge.js';
import { periodContainsYear, scopeRecords } from './selection.js';

/** 年份「未知」分類與片商「未知」桶的內部鍵；畫面顯示文字由 charts.js（T3）做 i18n 映射。 */
export const UNKNOWN_KEY = '__unknown__';

/** 具名片商排名太後面被歸併的內部鍵（與 UNKNOWN_KEY 語意不同，不可混用）。 */
export const REST_KEY = '__rest__';

/** 女優榜列出的前 N 名（TASK-161b-T2 / CD-161b-5）。 */
export const ACTRESS_TOP_N = 25;

var PODIUM5_SINGLE_MIN = 560;
var PODIUM5_SINGLE_MAX = 1024;
var PODIUM5_DUAL_MIN = 1160;

/**
 * 視窗寬度 → 頒獎台人數（TASK-161b-T2 / CD-161b-3）。
 * 560..1024（單欄）或 >=1160（雙欄）回 5；其餘（含非數字/NaN/undefined）回 3。
 */
export function podiumSizeForViewport(innerWidth) {
    if (typeof innerWidth !== 'number' || Number.isNaN(innerWidth)) return 3;
    if (innerWidth >= PODIUM5_SINGLE_MIN && innerWidth <= PODIUM5_SINGLE_MAX) return 5;
    if (innerWidth >= PODIUM5_DUAL_MIN) return 5;
    return 3;
}


export var _records = [];

export function setRecords(records) {
    _records.length = 0;
    for (const item of (records || [])) _records.push(item);
    canonicalizeMakers(_records);
}

export function getRecords() {
    return _records;
}

/**
 * 片商大小寫／全半形／空白合併（TASK-161a-T2a）。
 * 就地改寫 records[].maker 為該組最常見的原始寫法，平手取字串遞增最小者。
 */
export function canonicalizeMakers(records) {
    if (!records || records.length === 0) return;
    var spellingCounts = new Map();
    records.forEach(function (r) {
        var mk = r && r.maker;
        if (mk == null || mk === '') return;
        spellingCounts.set(mk, (spellingCounts.get(mk) || 0) + 1);
    });

    var canonical = canonicalMakerLabels(spellingCounts);

    records.forEach(function (r) {
        var mk = r && r.maker;
        if (!mk) return;
        var target = canonical.get(mk);
        if (target !== undefined) {
            r.maker = target;
        }
    });
}

/**
 * 全庫片商 Top8 色票槽位。回傳 { [makerName]: slotIndex }（0-based，0..7）。
 * 只統計 maker 為非 null／非空字串的紀錄；計數遞減、同計數時名稱字串遞增。
 */
export function buildMakerColorSlots(records) {
    var counts = new Map();
    (records || []).forEach(function (r) {
        var mk = r && r.maker;
        if (mk == null || mk === '') return;
        counts.set(mk, (counts.get(mk) || 0) + 1);
    });
    var named = Array.from(counts.entries());
    named.sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); });
    var top = named.slice(0, 8);
    var slots = {};
    top.forEach(function (e, i) { slots[e[0]] = i; });
    return slots;
}

/**
 * 主要片商年判定。回傳 { [`${actress}|${year}`]: makerName }。
 * 門檻：該女優該年至少 4 部，且最高具名片商佔比 >= 80%。
 * maker 為 null 的片計入分母，但不能被選為主要片商本身。
 */
export function buildMainMakerYearMap(records) {
    var byActressYear = new Map();
    (records || []).forEach(function (r) {
        if (!r || r.year == null) return;
        var actresses = r.actresses || [];
        var seen = new Set();
        actresses.forEach(function (name) {
            if (seen.has(name)) return;
            seen.add(name);
            if (!byActressYear.has(name)) byActressYear.set(name, new Map());
            var ymap = byActressYear.get(name);
            if (!ymap.has(r.year)) ymap.set(r.year, new Map());
            var mkmap = ymap.get(r.year);
            var mk = r.maker || null;
            mkmap.set(mk, (mkmap.get(mk) || 0) + 1);
        });
    });
    var result = {};
    byActressYear.forEach(function (ymap, name) {
        ymap.forEach(function (mkmap, year) {
            var total = 0;
            mkmap.forEach(function (c) { total += c; });
            var bestMk = null;
            var bestCount = 0;
            mkmap.forEach(function (c, mk) {
                if (mk === null) return;
                if (c > bestCount) {
                    bestCount = c;
                    bestMk = mk;
                }
            });
            if (bestMk && total >= 4 && bestCount / total >= 0.8) {
                result[name + '|' + year] = bestMk;
            }
        });
    });
    return result;
}

/**
 * 依 period 篩選紀錄。
 * {type:'all'} 保留 year===null；{type:'year',year:N} 只留 year===N；
 * {type:'range',from,to} 只留範圍內（含兩端），排除 year 為 null。
 */
export function periodRecords(records, period) {
    if (period === undefined) period = { type: 'all' };
    var list = records || [];
    if (!period || period.type === 'all') return list.slice();
    if (period.type === 'year') {
        return list.filter(function (r) { return r.year === period.year; });
    }
    return list.filter(function (r) { return periodContainsYear(period, r.year); });
}

function _yearRange(base) {
    var years = [];
    var hasNull = false;
    base.forEach(function (r) {
        if (r.year == null) { hasNull = true; return; }
        years.push(r.year);
    });
    if (!years.length) return { years: [], hasNull: hasNull };
    var minYear = Math.min.apply(null, years);
    var maxYear = Math.max.apply(null, years);
    var range = [];
    for (let y = minYear; y <= maxYear; y++) { range.push(y); }
    return { years: range, hasNull: hasNull };
}

function _buildDimmed(categories, period) {
    if (!period || period.type === 'all') {
        return categories.map(function () { return false; });
    }
    return categories.map(function (c) { return !periodContainsYear(period, c === UNKNOWN_KEY ? null : Number(c)); });
}

/**
 * 年份長條資料整形。基底永遠用 scopeRecords(records, sel, 'period')；
 * period 只影響 dimmed，不影響 series[].data 數值。
 */
export function aggregateYears(records, sel) {
    const period = sel.period;

    const base = scopeRecords(records, sel, 'period');

    if (sel.actress == null && sel.maker != null) {
        if (!base.length) return { categories: [], series: [], dimmed: [] };
        var makerRange = _yearRange(base);
        var makerCats = makerRange.years.map(String);
        if (makerRange.hasNull) makerCats = makerCats.concat([UNKNOWN_KEY]);
        var makerCounts = {};
        makerRange.years.forEach(function (y) { makerCounts[y] = 0; });
        var makerUnknown = 0;
        base.forEach(function (r) {
            if (r.year == null) { makerUnknown += 1; return; }
            makerCounts[r.year] = (makerCounts[r.year] || 0) + 1;
        });
        var makerData = makerRange.years.map(function (y) { return makerCounts[y] || 0; });
        if (makerRange.hasNull) makerData = makerData.concat([makerUnknown]);
        return {
            categories: makerCats,
            series: [{ name: sel.maker, data: makerData }],
            dimmed: _buildDimmed(makerCats, period),
        };
    }

    if (sel.actress != null) {
        if (!base.length) return { categories: [], series: [], dimmed: [] };
        var actRange = _yearRange(base);
        var actCats = actRange.years.map(String);
        if (actRange.hasNull) actCats = actCats.concat([UNKNOWN_KEY]);

        var byYear = {};
        actRange.years.forEach(function (y) { byYear[y] = {}; });
        var makerTotals = {};
        var unknownByMaker = {};
        base.forEach(function (r) {
            var mk = r.maker || UNKNOWN_KEY;
            makerTotals[mk] = (makerTotals[mk] || 0) + 1;
            if (r.year == null) {
                unknownByMaker[mk] = (unknownByMaker[mk] || 0) + 1;
                return;
            }
            if (!byYear[r.year]) byYear[r.year] = {};
            byYear[r.year][mk] = (byYear[r.year][mk] || 0) + 1;
        });
        var makers = Object.keys(makerTotals);
        makers.sort(function (a, b) {
            return makerTotals[b] - makerTotals[a] || (a < b ? -1 : 1);
        });
        var actSeries = makers.map(function (mk) {
            var data = actRange.years.map(function (y) {
                return (byYear[y] && byYear[y][mk]) || 0;
            });
            if (actRange.hasNull) data = data.concat([unknownByMaker[mk] || 0]);
            return { name: mk, data: data };
        });
        return {
            categories: actCats,
            series: actSeries,
            dimmed: _buildDimmed(actCats, period),
        };
    }

    // 無焦點：全庫 min..max + 尾端固定 UNKNOWN_KEY
    // P3-2：base 真的一筆都沒有時不得只剩單一 UNKNOWN_KEY 空格——比照上面 maker/actress
    // 焦點分支已有的早退寫法，讓呼叫端的「沒有資料」分支正確接手。
    if (!base.length) return { categories: [], series: [], dimmed: [] };
    var noneRange = _yearRange(base);
    var noneCats = noneRange.years.map(String).concat([UNKNOWN_KEY]);
    var noneCounts = {};
    noneRange.years.forEach(function (y) { noneCounts[y] = 0; });
    var noneUnknown = 0;
    base.forEach(function (r) {
        if (r.year == null) { noneUnknown += 1; return; }
        noneCounts[r.year] = (noneCounts[r.year] || 0) + 1;
    });
    var noneData = noneRange.years.map(function (y) { return noneCounts[y] || 0; });
    noneData = noneData.concat([noneUnknown]);
    return {
        categories: noneCats,
        series: [{ name: null, data: noneData }],
        dimmed: _buildDimmed(noneCats, period),
    };
}

/**
 * 片級分類：主要片商作品 / 其他作品 / 無法判定。
 * 呼叫端保證 record.maker 已知且等於當前展開的具名片商。
 */
export function classifyRecordAgainstMainMaker(record, mainMakerYearMap) {
    var actresses = (record && record.actresses) || [];
    if (record.year == null || actresses.length === 0) return 'undetermined';
    var isMain = actresses.some(function (n) {
        return mainMakerYearMap[n + '|' + record.year] === record.maker;
    });
    return isMain ? 'main' : 'other';
}

/**
 * 片商雙層圓餅資料。對傳入的 records 局部排名取前 8 名具名；
 * 第 9 名以後併入 REST_KEY；maker null/空字串併入 UNKNOWN_KEY。
 * 不呼叫 getRecords()／buildMakerColorSlots()。
 */
export function buildMakerDonutData(records, mainMakerYearMap) {
    var list = records || [];
    var total = list.length;
    var counts = new Map();
    var unknownCount = 0;
    list.forEach(function (r) {
        var mk = r && r.maker;
        if (mk == null || mk === '') {
            unknownCount += 1;
            return;
        }
        counts.set(mk, (counts.get(mk) || 0) + 1);
    });
    var named = Array.from(counts.entries());
    named.sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); });
    var top = named.slice(0, 8);
    var restCount = named.slice(8).reduce(function (s, e) { return s + e[1]; }, 0);

    var inner = top.map(function (e) {
        return { name: e[0], value: e[1], kind: 'named' };
    });
    inner.push({ name: REST_KEY, value: restCount, kind: 'rest' });
    inner.push({ name: UNKNOWN_KEY, value: unknownCount, kind: 'unknown' });

    var outer = [];
    var map = mainMakerYearMap || {};
    top.forEach(function (e) {
        var mkName = e[0];
        var cnt = { main: 0, other: 0, undetermined: 0 };
        list.forEach(function (r) {
            if (!r || r.maker !== mkName) return;
            var cls = classifyRecordAgainstMainMaker(r, map);
            cnt[cls] += 1;
        });
        if (cnt.main) {
            outer.push({ maker: mkName, value: cnt.main, kind: 'main' });
        }
        if (cnt.other) {
            outer.push({ maker: mkName, value: cnt.other, kind: 'other' });
        }
        if (cnt.undetermined) {
            outer.push({ maker: mkName, value: cnt.undetermined, kind: 'undetermined' });
        }
    });
    if (restCount) {
        outer.push({ maker: REST_KEY, value: restCount, kind: 'rest' });
    }
    if (unknownCount) {
        outer.push({ maker: UNKNOWN_KEY, value: unknownCount, kind: 'unknown' });
    }

    return { total: total, inner: inner, outer: outer };
}

/**
 * 女優榜排名。對傳入的 records 展開 actresses 計數；
 * 排序：count 遞減 → monthCount 遞減 → name 遞增。
 * monthCount ＝相異非 null 的 record.month 個數。
 * 若 sel 選了女優且她的真實 rank > 25，附加她那一列。
 * 不呼叫 getRecords()。
 */
export function buildActressBoard(records, sel) {
    var herActress = sel ? sel.actress : null;
    var counts = new Map();
    (records || []).forEach(function (r) {
        var names = (r && r.actresses) || [];
        var seenInRecord = new Set();
        names.forEach(function (name) {
            if (!name || seenInRecord.has(name)) return;
            seenInRecord.add(name);
            var entry = counts.get(name);
            if (!entry) {
                entry = { name: name, count: 0, months: new Set() };
                counts.set(name, entry);
            }
            entry.count += 1;
            if (r.month != null && r.month !== '') {
                entry.months.add(r.month);
            }
        });
    });

    var all = Array.from(counts.values()).map(function (e) {
        return {
            name: e.name,
            count: e.count,
            monthCount: e.months.size,
        };
    });
    all.sort(function (a, b) {
        return b.count - a.count || b.monthCount - a.monthCount || (a.name < b.name ? -1 : 1);
    });
    all.forEach(function (row, i) {
        row.rank = i + 1;
    });

    var rows = all.slice(0, ACTRESS_TOP_N);
    var herRank = 0;
    var herRow = null;
    if (herActress) {
        for (var i = 0; i < all.length; i++) {
            if (all[i].name === herActress) {
                herRank = all[i].rank;
                herRow = all[i];
                break;
            }
        }
    }
    if (herActress && herRank > ACTRESS_TOP_N) { rows.push(herRow); }
    return { rows: rows };
}

/**
 * 標籤矩形樹圖資料整形。
 * >50% 涵蓋率標籤進 pulled（上方一行文字）；其餘取前 40 進 rest（樹圖面積）。
 * 標籤字面原樣計數（同片用 Set 去重）；不做別名／大小寫合併。
 * total===0 時 pulled/rest 皆空、coverage=0，不除以零。
 *
 * @param {Array<{tags?: string[]}>} records
 * @returns {{
 *   total: number,
 *   withTagCount: number,
 *   coverage: number,
 *   pulled: Array<[string, number]>,
 *   rest: Array<[string, number]>,
 * }}
 */
export function aggregateTags(records) {
    var list = records || [];
    var total = list.length;
    var map = new Map();
    list.forEach(function (r) {
        var seen = new Set();
        ((r && r.tags) || []).forEach(function (t) {
            if (seen.has(t)) return;
            seen.add(t);
            map.set(t, (map.get(t) || 0) + 1);
        });
    });
    var named = Array.from(map.entries()).sort(function (a, b) {
        return b[1] - a[1] || (a[0] < b[0] ? -1 : 1);
    });
    var pulled = named.filter(function (e) { return total && (e[1] / total) > 0.5; });
    var rest = named.filter(function (e) { return !(total && (e[1] / total) > 0.5); });
    var top = rest.slice(0, 40);
    var withTagCount = list.filter(function (r) {
        return r && r.tags && r.tags.length;
    }).length;
    var coverage = total ? withTagCount / total : 0;
    return {
        total: total,
        withTagCount: withTagCount,
        coverage: coverage,
        pulled: pulled,
        rest: top,
    };
}

/**
 * 收藏女優發行當天年齡分布。
 * 單位＝（片, 收藏女優）配對；同片多位各算一筆。女優焦點時只算她本人。
 * 年齡一律走 computeActressAgeForVideo（含 239 合輯規則與日曆合法性）。
 * 涵蓋率＝至少一配對算出年齡的片數 ÷ scope 片數；中位數＝配對中位數（偶數取平均）。
 * 直方圖 1 歲一格，範圍＝有資料的最小～最大連續。
 *
 * @param {Array<{actresses?: string[], date?: string|null, duration?: number|null}>} records
 * @param {Record<string, {birth?: string|null}>|null|undefined} favorites
 * @param {{actress?: string|null}|null|undefined} sel
 * @returns {{
 *   total: number,
 *   recordsWithAge: number,
 *   coverage: number,
 *   pairCount: number,
 *   median: number|null,
 *   histogram: Record<number, number>,
 *   categories: string[],
 *   counts: number[],
 * }}
 */
export function aggregateAge(records, favorites, sel) {
    var list = records || [];
    var total = list.length;
    var favs = favorites || {};
    var focusActress = sel ? sel.actress : null;
    var ages = [];
    var recordsWithAge = 0;

    list.forEach(function (r) {
        var recordHasAge = false;
        var names = focusActress
            ? [focusActress]
            : ((r && r.actresses) || []);
        var seen = new Set();
        names.forEach(function (name) {
            if (seen.has(name)) return;
            seen.add(name);
            if (
                focusActress &&
                (!(r && r.actresses) || r.actresses.indexOf(name) === -1)
            ) {
                return;
            }
            var fav = favs[name];
            if (!fav || !fav.birth) return;
            var age = computeActressAgeForVideo({
                birth: fav.birth,
                releaseDate: r && r.date,
                durationMinutes: r && r.duration,
            });
            if (age != null) {
                ages.push(age);
                recordHasAge = true;
            }
        });
        if (recordHasAge) recordsWithAge += 1;
    });

    var pairCount = ages.length;
    var coverage = total ? recordsWithAge / total : 0;

    var median = null;
    if (ages.length) {
        var sorted = ages.slice().sort(function (a, b) { return a - b; });
        var mid = Math.floor(sorted.length / 2);
        median = sorted.length % 2
            ? sorted[mid]
            : (sorted[mid - 1] + sorted[mid]) / 2;
    }

    var histogram = {};
    var categories = [];
    var counts = [];
    if (ages.length) {
        var minA = ages[0];
        var maxA = ages[0];
        for (var i = 1; i < ages.length; i++) {
            if (ages[i] < minA) minA = ages[i];
            if (ages[i] > maxA) maxA = ages[i];
        }
        for (var a = minA; a <= maxA; a++) {
            histogram[a] = 0;
        }
        ages.forEach(function (age) {
            histogram[age] += 1;
        });
        for (var a2 = minA; a2 <= maxA; a2++) {
            categories.push(String(a2));
            counts.push(histogram[a2]);
        }
    }

    return {
        total: total,
        recordsWithAge: recordsWithAge,
        coverage: coverage,
        pairCount: pairCount,
        median: median,
        histogram: histogram,
        categories: categories,
        counts: counts,
    };
}

/**
 * 欄位前 8 名統計（導演／系列）。
 * 回傳 { total, withValueCount, coverage, top: [[name, count], ...] }。
 * record[field] 為 null 或空字串不進 top 排名但計入 total。
 * @param {object[]} records
 * @param {string} field
 */
export function aggregateFieldTop8(records, field) {
    var counts = new Map();
    var total = 0;
    var withValueCount = 0;
    (records || []).forEach(function (r) {
        if (!r) return;
        total++;
        var v = r[field];
        if (v == null || v === '') return;
        withValueCount++;
        counts.set(v, (counts.get(v) || 0) + 1);
    });
    var named = Array.from(counts.entries());
    named.sort(function (a, b) {
        return b[1] - a[1] || (a[0] < b[0] ? -1 : 1);
    });
    var top = named.slice(0, 8);
    var coverage = total ? withValueCount / total : 0;
    return {
        total: total,
        withValueCount: withValueCount,
        coverage: coverage,
        top: top,
    };
}

/**
 * 主要片商年表列選取。
 * 候選＝mainMakerYearMap 裡至少一組 (y, mk) 同時符合 period／maker 焦點（交集）；
 * 女優條件不影響候選，只看期間與片商。排序＝範圍內 classify==='main' 片數遞減、name 遞增，取 25；
 * 女優焦點且她不在前 25、但 records 有她的片 → 附加末列。
 * 不呼叫 getRecords()。
 */
export function buildGanttRows(records, mainMakerYearMap, sel) {
    var map = mainMakerYearMap || {};

    var candidateSet = new Set();
    Object.keys(map).forEach(function (key) {
        var sep = key.lastIndexOf('|');
        if (sep < 0) return;
        var name = key.slice(0, sep);
        var y = Number(key.slice(sep + 1));
        var e = { year: y, maker: map[key] };
        if (!periodContainsYear(sel.period, e.year) || (sel.maker != null && e.maker !== sel.maker)) return;
        candidateSet.add(name);
    });

    var scoped = scopeRecords(records, sel, 'actress');

    function mainCountFor(name) {
        var c = 0;
        scoped.forEach(function (r) {
            if (!r || (r.actresses || []).indexOf(name) === -1) return;
            if (classifyRecordAgainstMainMaker(r, map) === 'main') c += 1;
        });
        return c;
    }

    var rows = Array.from(candidateSet).map(function (name) {
        return { name: name, mainCount: mainCountFor(name) };
    });
    rows.sort(function (a, b) {
        return b.mainCount - a.mainCount || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var top = rows.slice(0, 25);

    if (sel.actress) {
        var herName = sel.actress;
        var already = top.some(function (r) { return r.name === herName; });
        if (!already) {
            var hasFilm = (records || []).some(function (r) {
                return r && (r.actresses || []).indexOf(herName) !== -1;
            });
            if (hasFilm) {
                top.push({
                    name: herName,
                    mainCount: mainCountFor(herName),
                    appended: true,
                });
            }
        }
        var herIdx = top.findIndex(function (r) { return r.name === herName; });
        if (herIdx !== -1) {
            var herRow = top.splice(herIdx, 1)[0];
            herRow.pinned = true;
            top.unshift(herRow);
        }
    }
    return top;
}

/**
 * 年表年份橫軸：全庫有年份紀錄的 min..max 連續，忽略 null／期間／女優／片商條件。
 * 不呼叫 getRecords()。
 */
export function ganttYearAxis(records) {
    var years = [];
    (records || []).forEach(function (r) {
        if (r && r.year != null) years.push(r.year);
    });
    if (!years.length) return [];
    var minY = Math.min.apply(null, years);
    var maxY = Math.max.apply(null, years);
    var range = [];
    for (var y = minY; y <= maxY; y++) range.push(y);
    return range;
}

/**
 * 年表年份格子。empty＝無片；main＝該年是她的主要片商年；否則 dot。
 * 不呼叫 getRecords()。
 */
export function buildGanttYearCells(name, records, mainMakerYearMap, yearAxis) {
    var map = mainMakerYearMap || {};
    var byYear = new Map();
    (records || []).forEach(function (r) {
        if (!r || r.year == null) return;
        if ((r.actresses || []).indexOf(name) === -1) return;
        if (!byYear.has(r.year)) byYear.set(r.year, []);
        byYear.get(r.year).push(r);
    });
    return (yearAxis || []).map(function (year) {
        var films = byYear.get(year) || [];
        if (!films.length) {
            return { year: year, state: 'empty', maker: null, filmCount: 0, makerCount: 0 };
        }
        var mainMk = map[name + '|' + year];
        if (mainMk) {
            var makerCount = 0;
            films.forEach(function (r) {
                if (r.maker === mainMk) makerCount += 1;
            });
            return {
                year: year,
                state: 'main',
                maker: mainMk,
                filmCount: films.length,
                makerCount: makerCount,
            };
        }
        return { year: year, state: 'dot', maker: null, filmCount: films.length, makerCount: 0 };
    });
}

/**
 * 年齡模式資格：favorites[name] 不存在或無 birth → 略過；有 birth 即合格
 * （即使所有片算不出年齡也不算略過）。不呼叫 getRecords()。
 */
export function ganttAgeEligibility(names, records, favorites) {
    var favs = favorites || {};
    var eligibleNames = [];
    var skipped = 0;
    (names || []).forEach(function (name) {
        var fav = favs[name];
        if (!fav || !fav.birth) { skipped += 1; return; }
        eligibleNames.push(name);
    });
    return { eligibleNames: eligibleNames, skippedCount: skipped };
}

/**
 * 年齡模式橫軸：顯示中各列年齡的 min..max 連續。
 * 年齡一律走 computeActressAgeForVideo。不呼叫 getRecords()。
 */
export function ganttAgeAxis(eligibleNames, records, favorites) {
    var favs = favorites || {};
    var nameSet = new Set(eligibleNames || []);
    var ages = [];
    (records || []).forEach(function (r) {
        if (!r) return;
        var seen = new Set();
        (r.actresses || []).forEach(function (name) {
            if (!nameSet.has(name) || seen.has(name)) return;
            seen.add(name);
            var fav = favs[name];
            if (!fav || !fav.birth) return;
            var age = computeActressAgeForVideo({
                birth: fav.birth,
                releaseDate: r.date,
                durationMinutes: r.duration,
            });
            if (age != null) ages.push(age);
        });
    });
    if (!ages.length) return [];
    var minA = Math.min.apply(null, ages);
    var maxA = Math.max.apply(null, ages);
    var range = [];
    for (var a = minA; a <= maxA; a++) range.push(a);
    return range;
}

/**
 * 年表年齡格子。某歲有片且至少一部落在她自己的主要片商年且片商相同 → main；
 * 有片否則 → dot；無片 → empty。不呼叫 getRecords()。
 */
export function buildGanttAgeCells(name, records, favorites, mainMakerYearMap, ageAxis) {
    var map = mainMakerYearMap || {};
    var favs = favorites || {};
    var fav = favs[name];
    var byAge = new Map();
    if (fav && fav.birth) {
        (records || []).forEach(function (r) {
            if (!r || (r.actresses || []).indexOf(name) === -1) return;
            var age = computeActressAgeForVideo({
                birth: fav.birth,
                releaseDate: r.date,
                durationMinutes: r.duration,
            });
            if (age == null) return;
            if (!byAge.has(age)) byAge.set(age, []);
            byAge.get(age).push(r);
        });
    }
    return (ageAxis || []).map(function (age) {
        var films = byAge.get(age) || [];
        if (!films.length) {
            return { age: age, state: 'empty', maker: null, filmCount: 0, makerCount: 0 };
        }
        var mainMk = null;
        films.forEach(function (r) {
            if (mainMk) return;
            if (r.year == null) return;
            var mk = map[name + '|' + r.year];
            if (mk && mk === r.maker) mainMk = mk;
        });
        if (mainMk) {
            var makerCount = 0;
            films.forEach(function (r) {
                if (r.maker === mainMk) makerCount += 1;
            });
            return {
                age: age,
                state: 'main',
                maker: mainMk,
                filmCount: films.length,
                makerCount: makerCount,
            };
        }
        return { age: age, state: 'dot', maker: null, filmCount: films.length, makerCount: 0 };
    });
}

/**
 * 女優片商分布列表（TASK-156c-T4，CD-156c-1／2／5／8）。
 *
 * 候選池（誰可以上榜）：片商焦點時看 scopeRecords(該片商)，否則看 periodRecords。
 * 每位候選的 total／mainCount／segments 一律用 periodRecords 算「她期間內全部
 * 片商」——候選池可以因片商焦點縮小，但長條畫的是她的全貌（Q2(a) 裁決，見
 * TASK-156c-T4.md「設計決策」段；不採 POC renderSolo() 候選/count 同源的舊邏輯）。
 * `topMakerNames`＝全庫前 8 色票的片商名稱陣列（呼叫端傳 state.js 的
 * `this.ganttLegend`，不是 `buildMakerColorSlots()` 回傳的 slot 物件——
 * `_makerColorSlots` 模組級變數已在 T3 移除，改用 reactive `ganttLegend`）。
 * 不呼叫 getRecords()。
 */
export function buildSoloRows(records, mainMakerYearMap, sel, ganttNames, topMakerNames) {
    var all = records || [];
    var map = mainMakerYearMap || {};
    var ganttSet = new Set(ganttNames || []);
    var namedSet = new Set(topMakerNames || []);
    var periodScope = periodRecords(all, sel.period);

    /*
     * P2 效能修正（review finding，真實片庫 6521 部實測 48ms→單趟後 <10ms）：
     * 原本每位候選都對 periodScope 全掃一遍（O(候選數 × periodScope 長度)）。
     * classifyRecordAgainstMainMaker(r, map) 與 r.maker 都只看 record 本身、
     * 不依賴「現在在算哪個名字」，同一筆片對片中每位女優的結果必然相同——
     * 改成單趟掃 periodScope、對每筆片算一次 isMain／mk，再攤給片中每位
     * （去重同一片重複列名）女優累加，效果與逐名重掃完全一致。
     * 比照同檔 buildActressBoard 的單趟 Map 累加形狀。
     */
    var statsMap = new Map();
    periodScope.forEach(function (r) {
        if (!r) return;
        var names = r.actresses || [];
        var isMain = classifyRecordAgainstMainMaker(r, map) === 'main';
        var mk = (r.maker == null || r.maker === '') ? null : r.maker;
        var seenInRecord = new Set();
        names.forEach(function (name) {
            if (!name || seenInRecord.has(name)) return;
            seenInRecord.add(name);
            var entry = statsMap.get(name);
            if (!entry) {
                entry = { total: 0, mainCount: 0, makerCounts: new Map() };
                statsMap.set(name, entry);
            }
            entry.total += 1;
            if (isMain) entry.mainCount += 1;
            entry.makerCounts.set(mk, (entry.makerCounts.get(mk) || 0) + 1);
        });
    });

    function statsFor(name) {
        return statsMap.get(name) || { total: 0, mainCount: 0, makerCounts: new Map() };
    }

    function buildSegments(makerCounts) {
        var named = [];
        var otherParts = [];
        var unknownCount = 0;
        makerCounts.forEach(function (count, mk) {
            if (mk === null) {
                unknownCount += count;
            } else if (namedSet.has(mk)) {
                named.push({ kind: 'named', maker: mk, count: count });
            } else {
                otherParts.push({ maker: mk, count: count });
            }
        });
        var namedMakerCount = named.length + otherParts.length;
        var segments = named.slice();
        if (otherParts.length) {
            otherParts.sort(function (a, b) {
                return b.count - a.count || (a.maker < b.maker ? -1 : 1);
            });
            var otherSum = otherParts.reduce(function (s, e) { return s + e.count; }, 0);
            segments.push({ kind: 'other', count: otherSum, others: otherParts });
        }
        if (unknownCount > 0) {
            segments.push({ kind: 'unknown', count: unknownCount });
        }
        var kindRank = { named: 0, other: 1, unknown: 2 };
        segments.sort(function (a, b) {
            if (b.count !== a.count) return b.count - a.count;
            if (kindRank[a.kind] !== kindRank[b.kind]) return kindRank[a.kind] - kindRank[b.kind];
            if (a.kind === 'named' && b.kind === 'named') {
                return a.maker < b.maker ? -1 : a.maker > b.maker ? 1 : 0;
            }
            return 0;
        });
        return { segments: segments, namedMakerCount: namedMakerCount };
    }

    function buildRow(name, st) {
        var built = buildSegments(st.makerCounts);
        return {
            name: name,
            total: st.total,
            mainCount: st.mainCount,
            namedMakerCount: built.namedMakerCount,
            segments: built.segments,
        };
    }

    var poolRecords = scopeRecords(all, sel, 'actress');
    var poolNames = new Set();
    poolRecords.forEach(function (r) {
        (r.actresses || []).forEach(function (name) {
            if (name) poolNames.add(name);
        });
    });

    var candidates = [];
    poolNames.forEach(function (name) {
        if (ganttSet.has(name)) return;
        var st = statsFor(name);
        var ratio = st.total ? st.mainCount / st.total : 0;
        if (ratio >= 0.5) return;
        candidates.push(buildRow(name, st));
    });
    candidates.sort(function (a, b) {
        return b.total - a.total || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var top = candidates.slice(0, 25);

    if (sel.actress) {
        var herName = sel.actress;
        var already = top.some(function (r) { return r.name === herName; });
        if (!already) {
            var herStats = statsFor(herName);
            if (herStats.total > 0) {
                var herRow = buildRow(herName, herStats);
                herRow.appended = true;
                top.push(herRow);
            }
        }
        var herIdx = top.findIndex(function (r) { return r.name === herName; });
        if (herIdx !== -1) {
            var herRow = top.splice(herIdx, 1)[0];
            herRow.pinned = true;
            top.unshift(herRow);
        }
    }
    return top;
}

/**
 * TASK-156c-T5 / CD-156c-1 / 6：與她同片搭檔列表。
 *
 * 只在女優焦點時計算，範圍為 scopeRecords(records, sel, null)。
 * 每部紀錄去重女優名單後，僅採計 2～4 人片。
 * 統計非焦點女優的合作次數，依次數遞減、名字遞增排序，取前 15 名。
 */
export function buildCostarRows(records, sel) {
    if (!sel.actress) return [];
    var herName = sel.actress;
    var scoped = scopeRecords(records, sel, null);
    var counts = new Map();
    scoped.forEach(function (r) {
        var seenInRecord = new Set();
        var names = [];
        ((r && r.actresses) || []).forEach(function (name) {
            if (!name || seenInRecord.has(name)) return;
            seenInRecord.add(name);
            names.push(name);
        });
        if (names.length < 2 || names.length > 4) return;
        names.forEach(function (name) {
            if (name === herName) return;
            counts.set(name, (counts.get(name) || 0) + 1);
        });
    });
    var list = Array.from(counts.entries()).map(function (entry) {
        return { name: entry[0], count: entry[1] };
    });
    list.sort(function (a, b) {
        return b.count - a.count || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    return list.slice(0, 15);
}


/**
 * TASK-156e-T1a / CD-156e-1 v3 / TASK-161b-T2：女優榜換位分類（純函式，不碰 DOM）。
 * 六個互斥分類供後續 Flip／淡入淡出分流。
 * @param {Array} oldRows
 * @param {Array} newRows
 * @param {number} podiumSize 頒獎台人數（3 或 5），必填無預設值
 */
export function classifyBoardTransition(oldRows, newRows, podiumSize) {
    var oldByName = new Map((oldRows || []).map(function (r) { return [r.name, r]; }));
    var newByName = new Map((newRows || []).map(function (r) { return [r.name, r]; }));
    var isPodium = function (r) { return r.rank <= podiumSize; };
    var rowStayers = [], podiumReshuffle = [], crossStructureMovers = [],
        droppedOut = [], brandNewEntrants = [], podiumNewEntrants = [];
    oldByName.forEach(function (oldRow, name) {
        var newRow = newByName.get(name);
        if (!newRow) { droppedOut.push({ name: name, wasPodium: isPodium(oldRow) }); return; }
        if (isPodium(oldRow) && isPodium(newRow)) {
            if (oldRow.rank !== newRow.rank) podiumReshuffle.push({ name: name });
            return; // rank 相同 → 無動作
        }
        if (!isPodium(oldRow) && !isPodium(newRow)) { rowStayers.push({ name: name }); return; }
        crossStructureMovers.push({ name: name }); // 一個 podium 一個不是 → 跨結構
    });
    newByName.forEach(function (newRow, name) {
        if (oldByName.has(name)) return;
        if (isPodium(newRow)) { podiumNewEntrants.push({ name: name }); }
        else { brandNewEntrants.push({ name: name }); }
    });
    return { rowStayers: rowStayers, podiumReshuffle: podiumReshuffle,
             crossStructureMovers: crossStructureMovers, droppedOut: droppedOut,
             brandNewEntrants: brandNewEntrants, podiumNewEntrants: podiumNewEntrants };
}

/**
 * TASK-156e-T1a / TASK-161b-T2：頒獎台 rank → 視覺位置 class 後綴。
 * 1→center、2→left、3→right；podiumSize===5 時 4→far-left、5→far-right。
 */
export function podiumPositionClass(rank, podiumSize) {
    if (rank === 1) return 'center';
    if (rank === 2) return 'left';
    if (rank === 3) return 'right';
    if (podiumSize === 5 && rank === 4) return 'far-left';
    if (podiumSize === 5 && rank === 5) return 'far-right';
    return '';
}

/**
 * TASK-156e-T3／CD-156e-6：比對兩份女優榜，回傳片數有變動的人。
 * 只走訪 newRows；新進榜者（oldMap 沒有）天然排除；同名同 count 不進結果。
 * @param {Array<{name:string,count:number}>|null|undefined} oldRows
 * @param {Array<{name:string,count:number}>|null|undefined} newRows
 * @returns {Array<{name:string,from:number,to:number}>}
 */
export function diffBoardCounts(oldRows, newRows) {
    const oldMap = new Map((oldRows || []).map((r) => [r.name, r.count]));
    const out = [];
    (newRows || []).forEach((r) => {
        if (oldMap.has(r.name) && oldMap.get(r.name) !== r.count) {
            out.push({ name: r.name, from: oldMap.get(r.name), to: r.count });
        }
    });
    return out;
}
