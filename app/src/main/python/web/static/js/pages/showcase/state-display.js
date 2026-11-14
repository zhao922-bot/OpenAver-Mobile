import { resolveDisplayPreferences, createDisplaySaver, writeDisplayPreferences, DISPLAY_COLUMNS, DISPLAY_PAGE_SIZES, DISPLAY_PRESENTATIONS } from '../../shared/showcase-display.js';

export function stateDisplay(write = writeDisplayPreferences) {
    const save = createDisplaySaver(write);
    let saveGeneration = 0;
    let pageGeneration = 0;
    return {
        displayOpen: false,
        displaySaving: false,
        displayError: false,
        gridColumns: 2,
        get displayPresentation() {
            return this.mode === 'grid' ? this.cardShape : this.mode;
        },
        get displayPageSizeOptions() {
            return [...new Set([...DISPLAY_PAGE_SIZES, this.perPage])].sort((a, b) => a - b);
        },
        restoreDisplayPreferences(legacy, gallery) {
            const stored = typeof window !== 'undefined' ? window.__SHOWCASE_DISPLAY__ : null;
            const preference = resolveDisplayPreferences(stored, legacy, gallery);
            this.mode = ['cover', 'poster'].includes(preference.presentation) ? 'grid' : preference.presentation;
            this.cardShape = this.mode === 'grid' ? preference.presentation : 'poster';
            this.gridColumns = preference.columns;
            this.perPage = preference.items_per_page;
            this.showTableList = true;
        },
        openDisplaySettings() {
            this.sortOpen = false;
            this.modeOpen = false;
            this.displayOpen = true;
        },
        currentDisplayPreferences() {
            return { presentation: this.displayPresentation, columns: this.gridColumns, items_per_page: this.perPage };
        },
        async persistDisplayPreferences() {
            const generation = ++saveGeneration;
            const preference = this.currentDisplayPreferences();
            this.displaySaving = true;
            this.displayError = false;
            try {
                await save(preference);
                if (generation === saveGeneration && typeof window !== 'undefined') {
                    window.__SHOWCASE_DISPLAY__ = preference;
                }
                return true;
            } catch (_) {
                if (generation === saveGeneration) this.displayError = true;
                return false;
            } finally {
                if (generation === saveGeneration) this.displaySaving = false;
            }
        },
        async setDisplayColumns(value) {
            if (!DISPLAY_COLUMNS.includes(value)) return;
            this.gridColumns = value;
            return this.persistDisplayPreferences();
        },
        async setDisplayPresentation(value) {
            if (!DISPLAY_PRESENTATIONS.includes(value)) return;
            this.selectPresentation(value);
            return this.persistDisplayPreferences();
        },
        async setDisplayPageSize(raw) {
            const value = Number(raw);
            if (!Number.isInteger(value) || value < 1 || value > 500 || value === this.perPage) return;
            const generation = ++pageGeneration;
            this.perPage = value;
            this.page = 1;
            const saved = this.persistDisplayPreferences();
            if (!this._fullVideosLoaded) {
                const options = { page: 1 };
                // Initial loading has not confirmed _serverPaged yet. Replace
                // that request too, keeping full-list search/random semantics.
                if (this.loading && this._shouldLoadAllVideosForInitialFetch()) options.all = true;
                const loaded = await this.fetchVideos(options);
                if (!loaded || generation !== pageGeneration) return saved;
            }
            if (generation !== pageGeneration) return saved;
            this.updatePagination();
            this.saveState();
            return saved;
        },
    };
}
