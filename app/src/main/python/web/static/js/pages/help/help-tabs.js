const TABS = ['library', 'organize', 'manual'];
const DEFAULT_TAB = 'library';
const HASH_ALIASES = Object.freeze({
    start: 'library',
    storage: 'library',
    local: 'library',
    tasks: 'organize',
    organize: 'organize',
    trouble: 'manual',
    about: 'manual',
    manual: 'manual',
});

export function resolveHelpTab(hash) {
    const raw = String(hash || '').replace(/^#/, '');
    if (TABS.includes(raw)) return raw;
    if (raw.startsWith('mobile-help-')) {
        const alias = raw.slice('mobile-help-'.length);
        if (HASH_ALIASES[alias]) return HASH_ALIASES[alias];
    }
    return HASH_ALIASES[raw] || DEFAULT_TAB;
}

function initHelpTabs() {
    const buttons = Array.from(document.querySelectorAll('[data-help-tab]'));
    const panels = Array.from(document.querySelectorAll('[data-help-panel]'));
    const tablist = document.querySelector('.mobile-help-tabs');

    function activateTab(name, { updateHash = false, focus = false } = {}) {
        const target = TABS.includes(name) ? name : DEFAULT_TAB;
        for (const button of buttons) {
            const active = button.dataset.helpTab === target;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
            button.tabIndex = active ? 0 : -1;
            if (active && focus) button.focus();
        }
        for (const panel of panels) {
            panel.hidden = panel.dataset.helpPanel !== target;
        }
        if (updateHash) {
            try {
                history.replaceState(history.state, '', `#${target}`);
            } catch {
                // Embedded WebViews can expose a restricted history object.
            }
        }
    }

    for (const button of buttons) {
        button.addEventListener('click', () => {
            activateTab(button.dataset.helpTab, { updateHash: true });
        });
    }

    tablist?.addEventListener('keydown', (event) => {
        const current = buttons.indexOf(document.activeElement);
        if (current < 0) return;
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let next = current;
        if (event.key === 'ArrowLeft') next = (current - 1 + buttons.length) % buttons.length;
        if (event.key === 'ArrowRight') next = (current + 1) % buttons.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = buttons.length - 1;
        activateTab(buttons[next].dataset.helpTab, {
            updateHash: true,
            focus: true,
        });
    });

    window.addEventListener('hashchange', () => activateTab(resolveHelpTab(window.location.hash)));
    activateTab(resolveHelpTab(window.location.hash));
}

if (typeof document !== 'undefined') initHelpTabs();
