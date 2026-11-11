import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve('app/src/main/python/web/static/js') + path.sep,
).href;

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateVideos } = await import(
    '../../app/src/main/python/web/static/js/pages/showcase/state-videos.js'
);
const { stateLightbox } = await import(
    '../../app/src/main/python/web/static/js/pages/showcase/state-lightbox.js'
);
const { stateActress } = await import(
    '../../app/src/main/python/web/static/js/pages/showcase/state-actress.js'
);
const { stateBase, _setActresses } = await import(
    '../../app/src/main/python/web/static/js/pages/showcase/state-base.js'
);

_setActresses([{ name: 'Yui Hatano', is_favorite: false }]);
globalThis.window.location = { pathname: '/showcase', search: '' };
globalThis.window.history = { replaceState() {} };
globalThis.document = {
    querySelector: () => null,
    body: { classList: { add() {}, remove() {} } },
};

function makeComponent() {
    const base = stateBase.call({ $persist: (obj) => ({ as: () => obj }) });
    const c = Object.assign({}, base, stateVideos(), stateLightbox(), stateActress(), {
        pills: [],
        search: '',
        mode: 'table',
        sort: 'date',
        order: 'desc',
        page: 1,
        animLog: [],
        heroCalls: 0,
    });
    c.$nextTick = (fn) => fn();
    c._animateFilter = function () {
        c.animLog.push({ search: c.search, pills: c.pills.length });
    };
    c._reconcileHeroCard = function () {
        c.heroCalls++;
    };
    return c;
}

function click(c, value, dim) {
    c.searchFromMetadata(value, dim);
    if (c.lightboxCloseTimer) {
        clearTimeout(c.lightboxCloseTimer);
        c.lightboxCloseTimer = null;
    }
}

test('digits-only search clears for six metadata dimensions and release', () => {
    const inputs = ['199', '001', '1991', '１９９', ' 199 ', '2024'];
    const dims = [
        ['三上悠亞', 'actress'],
        ['S1', 'maker'],
        ['Madonna', 'series'],
        ['某導演', 'director'],
        ['Premium', 'label'],
        ['NTR', 'tag'],
        ['2023-05-12', 'release'],
    ];
    for (const search of inputs) {
        for (const [value, dim] of dims) {
            const c = makeComponent();
            c.search = search;
            click(c, value, dim);
            assert.equal(c.search, '', JSON.stringify({ search, value, dim }));
            assert.equal(c.pills.length, 1);
            assert.equal(c.animLog.length, 1);
            assert.equal(c.animLog[0].search, '');
            assert.equal(c.heroCalls, 1);
        }
    }
});

test('non-numeric search remains and duplicate actions do not clear text', () => {
    for (const search of ['三上', 'SSIS-001', '199 三上']) {
        const c = makeComponent();
        c.search = search;
        click(c, 'NTR', 'tag');
        assert.equal(c.search, search);
        assert.equal(c.pills.length, 1);
    }

    const c = makeComponent();
    c.search = '199';
    click(c, '三上悠亞', 'actress');
    c.search = '199';
    click(c, '三上悠亞', 'actress');
    assert.equal(c.search, '199');
    assert.equal(c.pills.length, 1);

    const pick = makeComponent();
    pick.search = '199';
    pick.togglePickPill();
    assert.equal(pick.search, '199');
    assert.equal(pick.pills[0].dim, 'pick');
});
