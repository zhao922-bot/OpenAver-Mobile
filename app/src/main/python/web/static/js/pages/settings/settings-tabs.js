const STORAGE_KEY = 'settings_tab';
const DEFAULT_TAB = 'sources';
export const SETTINGS_TABS = Object.freeze([
    'sources',
    'naming',
    'gallery',
    'ai',
    'system',
]);

const LEGACY_SECTIONS = Object.freeze({
    'sec-search': 'sources',
    'sec-gallery': 'gallery',
    'sec-system': 'system',
});

export function isSettingsTab(value) {
    return SETTINGS_TABS.includes(value);
}

function panelOf(id) {
    if (typeof document === 'undefined' || !id) return null;
    const element = document.getElementById(id);
    return element?.closest?.('[data-settings-panel]')
        ?.dataset?.settingsPanel ?? null;
}

export function resolveSettingsTab({ hash, stored } = {}) {
    const id = String(hash ?? '').replace(/^#/, '');
    let fromHash = null;
    if (isSettingsTab(id)) {
        fromHash = id;
    } else if (Object.hasOwn(LEGACY_SECTIONS, id)) {
        fromHash = LEGACY_SECTIONS[id];
    } else if (id && isSettingsTab(panelOf(id))) {
        fromHash = panelOf(id);
    }
    if (fromHash) return fromHash;
    return isSettingsTab(stored) ? stored : DEFAULT_TAB;
}

export function readStoredSettingsTab() {
    try {
        return localStorage.getItem(STORAGE_KEY);
    } catch {
        return null;
    }
}

export function writeStoredSettingsTab(name) {
    if (!isSettingsTab(name)) return;
    try {
        localStorage.setItem(STORAGE_KEY, name);
    } catch {
        // Storage may be unavailable in private mode; tab switching still works.
    }
}

export function currentSettingsHash() {
    return typeof location === 'undefined' ? '' : location.hash;
}

export function settingsTabOfElement(element) {
    return element?.closest?.('[data-settings-panel]')
        ?.dataset?.settingsPanel ?? null;
}
