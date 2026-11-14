/** Live browsing preferences. Offline HTML export has independent defaults. */
export const DISPLAY_PRESENTATIONS = ['poster', 'cover', 'list', 'table'];
export const DISPLAY_COLUMNS = [2, 3, 5];
export const DISPLAY_PAGE_SIZES = [30, 45, 60, 90, 120];

export function resolveDisplayPreferences(display, legacyState = {}, gallery = {}) {
    const explicit = display && typeof display === 'object';
    let presentation = explicit ? display.presentation : (
        ['list', 'table'].includes(legacyState?.mode) ? legacyState.mode : 'poster');
    if (!DISPLAY_PRESENTATIONS.includes(presentation)) presentation = 'poster';
    const columns = explicit && DISPLAY_COLUMNS.includes(display.columns) ? display.columns : 2;
    const raw = explicit ? display.items_per_page : Number(gallery?.items_per_page);
    let count = Number.isInteger(raw) && raw >= 1 && raw <= 500 ? raw : 45;
    if (!explicit) count = Math.min(count, 45); // Preserve the old effective mobile size once.
    return { presentation, columns, items_per_page: count };
}

/** Only one write in flight. Queued changes coalesce to the latest snapshot. */
export function createDisplaySaver(write) {
    let running = false;
    let pending = null;
    async function drain() {
        running = true;
        while (pending) {
            const current = pending;
            pending = null;
            try {
                const result = await write(current.value);
                current.waiters.forEach(w => w.resolve(result));
            } catch (error) {
                current.waiters.forEach(w => w.reject(error));
            }
        }
        running = false;
    }
    return value => new Promise((resolve, reject) => {
        const waiters = pending ? pending.waiters : [];
        waiters.push({ resolve, reject });
        pending = { value: { ...value }, waiters };
        if (!running) void drain();
    });
}

export async function writeDisplayPreferences(value) {
    const response = await fetch('/api/config/showcase-display', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value), keepalive: true,
    });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (!data.success) throw new Error(data.error || 'Display settings could not be saved');
    return data.data;
}
