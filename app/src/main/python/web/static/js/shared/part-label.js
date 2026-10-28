/**
 * part-label.js — 分集標記顯示字串（TASK-122-T3，CD-122-5）
 *
 * 只消費後端已定案的 `part_tokens` 陣列做格式化，不得在此重新判斷分組、
 * 不得剝 token、不得自己算 part number（spec §4.1／CD-122-5）。
 */

export function formatPartLabel(tokens) {
    if (!tokens || tokens.length < 2) return '';
    const prefixes = tokens.map(t => t.replace(/[0-9]+$/, ''));
    const samePrefix = prefixes.every(p => p === prefixes[0]);
    if (!samePrefix) return window.t('showcase.video.part_count_fallback', { n: tokens.length });
    if (tokens.length === 2) return tokens.join('/');
    return `${tokens[0]}–${tokens[tokens.length - 1]}`;  // en dash
}
