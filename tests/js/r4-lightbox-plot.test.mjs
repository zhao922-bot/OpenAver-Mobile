import { test } from 'node:test';
import assert from 'node:assert/strict';

import { applyPlotLoadResult } from '../../app/src/main/python/web/static/js/pages/showcase/lb-plot-logic.js';

test('plot response updates the Alpine-reactive view proxy', () => {
    const reactiveWrites = [];
    const view = new Proxy(
        {
            path: 'file:////sdcard/Download/OpenAverR49Test/XYZ-456.mp4',
            loading: true,
            error: false,
            plot: '',
            original: '',
            hasOriginal: false,
            showing: 'plot',
        },
        {
            set(target, property, nextValue) {
                reactiveWrites.push(String(property));
                target[property] = nextValue;
                return true;
            },
        },
    );

    const applied = applyPlotLoadResult(view, true, {
        success: true,
        plot: '测试简介',
        original_plot: '',
        has_original: false,
    });

    assert.equal(applied, true);
    assert.equal(view.plot, '测试简介');
    assert.equal(view.loading, false);
    assert.ok(reactiveWrites.includes('plot'));
    assert.ok(reactiveWrites.includes('loading'));
});

test('failed plot response clears loading and marks the view as unavailable', () => {
    const view = {
        loading: true,
        error: false,
        plot: '',
        original: '',
        hasOriginal: false,
    };

    const applied = applyPlotLoadResult(view, true, {
        success: false,
        error: 'no_nfo',
    });

    assert.equal(applied, false);
    assert.equal(view.loading, false);
    assert.equal(view.error, true);
});
