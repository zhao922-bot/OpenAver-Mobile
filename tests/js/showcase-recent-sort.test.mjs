import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.window.t = (key) => key;

const IMPORTMAP = {
    '@/shared/': 'shared/',
    '@/showcase/': 'pages/showcase/',
};
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve('app/src/main/python/web/static/js') + path.sep,
).href;
const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateActress } = await import(
    '../../app/src/main/python/web/static/js/pages/showcase/state-actress.js'
);
const { _setActresses } = await import(
    '../../app/src/main/python/web/static/js/pages/showcase/state-base.js'
);

test('recent actress sort uses score then video count and is deterministic', () => {
    _setActresses([
        { name: 'low', recent_score: 2, video_count: 100 },
        { name: 'tie-small', recent_score: 5, video_count: 3 },
        { name: 'tie-large', recent_score: 5, video_count: 9 },
        { name: 'zero', recent_score: 0, video_count: 200 },
        { name: 'missing', video_count: 1 },
    ]);
    const component = Object.assign({}, stateActress(), {
        actressSort: 'recent',
        actressOrder: 'desc',
        actressSearch: '',
        actressPills: [],
    });
    component.applyActressFilterAndSort();
    assert.deepEqual(
        component.paginatedActresses.map((actress) => actress.name),
        ['tie-large', 'tie-small', 'low', 'zero', 'missing'],
    );
});
