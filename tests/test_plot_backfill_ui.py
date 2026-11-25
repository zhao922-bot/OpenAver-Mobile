import subprocess
from pathlib import Path


def test_element_picker_submits_only_chosen_sources_then_offers_saved_plots_for_translation():
    script = r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const stored = new Map();
global.localStorage = {
    getItem: key => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: key => stored.delete(key),
};
global.window = {t: key => key};
const text = fs.readFileSync('app/src/main/python/web/static/js/pages/scanner/state-batch.js', 'utf8')
    .replace(/^import .*;$/mg, '').replace(/export /g, '');
const make = new Function(text + ';return stateBatch;')();
const vm = make();
const dialog = {open: false, showModal() {this.open = true}, close() {this.open = false}};
vm.$refs = {elementPicker: dialog};
vm.$nextTick = async () => {};
vm.config = {translate: {enabled: false}};
vm.isBusy = false;
vm.showToast = () => {};
const calls = [];
const ids = ['a'.repeat(32), 'b'.repeat(32)];
const catalog = {
    cover: [{id: 'cover-site', label: 'Cover site'}],
    plot: [{id: 'plot-site', label: 'Plot site'}],
    samples: [],
    tags: [{id: 'tag-site', label: 'Tag site'}],
};
global.fetch = async url => {
    assert.equal(url, '/api/gallery/backfill-elements/sources');
    return {ok: true, json: async () => ({success: true, sources: catalog})};
};
vm._runBackfillStream = async options => {
    calls.push(options);
    const batch = ids[calls.length - 1];
    return {type: 'done', summary: {success: 1, failed: 0, translation_batch: batch, translation_count: 1}};
};
(async () => {
    await vm.openElementPicker();
    assert.equal(dialog.open, true);
    assert.deepEqual(vm.elementSelection, {cover: '', plot: '', samples: '', tags: ''});
    vm.elementSelection.plot = 'cover-site';
    await vm.runElementBackfill();
    assert.equal(calls.length, 0);
    assert.equal(dialog.open, true);
    Object.assign(vm.elementSelection, {cover: 'cover-site', plot: 'plot-site'});
    await vm.runElementBackfill();
    assert.equal(dialog.open, false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/gallery/backfill-elements');
    assert.deepEqual(calls[0].body, {sources: {cover: 'cover-site', plot: 'plot-site'}});
    assert.equal(vm.plotTranslationConfirmOpen, true);
    vm.keepOriginalPlots();
    assert.equal(vm.plotTranslationConfirmOpen, false);
    assert.equal(make().pendingPlotTranslation.batch_id, ids[0]);

    catalog.cover = [];
    await vm.openElementPicker(vm.lastElementSources);
    assert.deepEqual(vm.elementSelection, {cover: '', plot: 'plot-site', samples: '', tags: ''});
    dialog.close();
    await vm.openElementPicker();
    assert.deepEqual(vm.elementSelection, {cover: '', plot: '', samples: '', tags: ''});
    vm.elementSelection.plot = 'plot-site';
    await vm.runElementBackfill();
    assert.deepEqual(make().pendingPlotTranslations.map(b => b.batch_id).sort(), ids);
    vm.config.translate.enabled = true;
    await vm.runPlotTranslation();
    assert.equal(calls.length, 3);
    assert.equal(calls[2].url, '/api/gallery/translate-backfilled-plots');
    assert.deepEqual(calls[2].body, {batch_id: ids[1]});
    assert.equal(vm.pendingPlotTranslation, null);
    assert.equal(vm.pendingPlotTranslations[0].batch_id, ids[0]);
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    result = subprocess.run(
        ['node', '-e', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
