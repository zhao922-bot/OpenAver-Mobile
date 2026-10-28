export function emptySel() {
    return {
        period: { type: 'all' },
        actress: null,
        maker: null,
    };
}

export function normalizePeriod(p) {
    if (!p || typeof p !== 'object') return { type: 'all' };
    if (p.type === 'year') {
        return p.year != null ? { type: 'year', year: p.year } : { type: 'all' };
    }
    if (p.type !== 'range' || p.from == null || p.to == null) {
        return { type: 'all' };
    }
    let { from, to } = p;
    if (from > to) {
        const tmp = from;
        from = to;
        to = tmp;
    }
    if (from === to) return { type: 'year', year: from };
    return { type: 'range', from, to };
}

export function periodContainsYear(period, year) {
    period = normalizePeriod(period);
    if (!period || period.type === 'all') return true;
    if (period.type === 'year') return year != null && year === period.year;
    return year != null && year >= period.from && year <= period.to;
}

export function toggleYear(sel, year) {
    const base = sel || emptySel();
    sel = {
        ...base,
        period: normalizePeriod(base.period),
    };
    if (sel.period.type === 'year' && sel.period.year === year) return { ...sel, period: { type: 'all' } };
    return { ...sel, period: { type: 'year', year } };
}

export function toggleActress(sel, name) {
    const base = sel || emptySel();
    return {
        ...base,
        period: normalizePeriod(base.period),
        actress: base.actress === name ? null : name,
    };
}

export function toggleMaker(sel, name) {
    sel = sel || emptySel();
    return {
        ...sel,
        period: normalizePeriod(sel.period),
        maker: sel.maker === name ? null : name,
    };
}

export function scopeRecords(records, sel, skipDim) {
    sel = sel || emptySel();
    const period = normalizePeriod(sel.period);
    return (records || []).filter((r) => {
        if (skipDim !== 'period' && !periodContainsYear(period, r.year)) return false;
        if (skipDim !== 'actress' && sel.actress != null && !(r.actresses || []).includes(sel.actress)) return false;
        if (skipDim !== 'maker' && sel.maker != null && r.maker !== sel.maker) return false;
        return true;
    });
}

export function emptyKey(sel, skipDim, count) {
    if (count > 0) return null;
    sel = sel || emptySel();
    const period = normalizePeriod(sel.period);
    const hasPeriodFilter = skipDim !== 'period' && period.type !== 'all';
    const hasActressFilter = skipDim !== 'actress' && sel.actress != null;
    const hasMakerFilter = skipDim !== 'maker' && sel.maker != null;
    if (hasPeriodFilter || hasActressFilter || hasMakerFilter) {
        return 'insights.period_empty';
    }
    return 'insights.no_data';
}

export function periodLabel(period, allLabel) {
    period = normalizePeriod(period);
    if (period.type === 'year') {
        return String(period.year);
    }
    if (period.type === 'range') {
        return String(period.from) + '–' + String(period.to);
    }
    return allLabel;
}

export function suffixLabel(sel, suffixDims, allLabel) {
    sel = sel || emptySel();
    const hasAny = Array.isArray(suffixDims) && suffixDims.some((d) => sel[d] != null);
    if (!hasAny) return '';
    return ' · ' + periodLabel(sel.period, allLabel);
}

export function toggleGanttCell(sel, name, year) {
    const base = sel || emptySel();
    const period = normalizePeriod(base.period);
    if (year == null) return { ...base, period, actress: name };
    if (base.actress === name && period.type === 'year' && period.year === year) return { ...base, period: { type: 'all' }, actress: name };
    return { ...base, period: { type: 'year', year }, actress: name };
}

export function isHoverPointer(ev) {
    if (!ev) return true;
    return ev.pointerType !== 'touch';
}

