from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from web.routers import scanner


@pytest.mark.parametrize("source", ["javdb", "unknown"])
@pytest.mark.parametrize("generator", [scanner._sample_backfill_generator, scanner._plot_backfill_generator])
def test_backfill_rejects_unavailable_source_before_disk_or_network(monkeypatch, source, generator):
    monkeypatch.setattr(scanner, "load_config", lambda: {
        "general": {"locale": "zh-CN"},
        "sources": [{"id": source, "enabled": source != "javdb"}],
    })

    def unexpected():
        raise AssertionError("Unavailable source must stop before opening the database")

    monkeypatch.setattr(scanner, "get_db_path", unexpected)
    events = [json.loads(line.removeprefix("data: ")) for line in generator(threading.Event(), source=source)]
    assert len(events) == 1
    assert events[0]["type"] == "error"


def test_source_picker_refreshes_settings_and_dispatches_only_explicit_choices():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    script = r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
global.window = {t: key => key};
global.dirPath = '';
global.localStorage = {getItem: () => null};
let sources = [
    {id: 'javdb', enabled: false, order: 0},
    {id: 'javbus', enabled: true, order: 2},
    {id: 'dmm', enabled: true, order: 1},
    {id: 'jable', enabled: true, order: 3},
];
global.fetch = async () => ({ok: true, json: async () => ({success: true, data: {sources}})});
function load(file, name) {
    const code = fs.readFileSync(file, 'utf8').replace(/^import .*;$/mg, '').replace(/export /g, '');
    return new Function(code + `; return ${name};`)()();
}
const root = 'app/src/main/python/web/static/js/pages/scanner/';
const state = load(root + 'state-scan.js', 'stateScan');
Object.defineProperties(state, Object.getOwnPropertyDescriptors(load(root + 'state-batch.js', 'stateBatch')));
state.config = {sources: [], gallery: {directories: ['keep']}};
state.state = 'idle';
state.statTotal = 5;
let called = [];
for (const fn of ['openNfoUpdateConfirm', 'previewRenamePlan', 'previewTagSourceUpdate', 'openTagSourceUpdateConfirm', 'runMissingEnrich', 'runSampleBackfill', 'runPlotBackfill', 'resumeMissingEnrich']) {
    state[fn] = () => called.push(fn);
}
(async () => {
    await state.openMaintenanceSourcePicker('rename');
    assert.deepEqual(state.config.gallery.directories, ['keep']);
    assert.deepEqual(state.maintenanceSourceOptions.map(x => x.id), ['dmm', 'javbus', 'javlibrary', 'fc-javten', 'jable']);
    assert.deepEqual(state.maintenanceSourceOptions.filter(x => x.disabled).map(x => x.id), []);
    for (const id of ['auto', 'javdb']) await state.chooseMaintenanceSource(id);
    assert.deepEqual(called, []);
    assert.equal(state.maintenanceSourceModalOpen, true);
    await state.chooseMaintenanceSource('javbus');
    assert.equal(state.renameSource, 'javbus');
    assert.deepEqual(called, ['previewRenamePlan']);
    await state.chooseMaintenanceSource('dmm');
    assert.equal(called.length, 1);
    sources = [{id: 'javdb', enabled: true}];
    for (const action of ['nfo', 'tag-preview', 'tag-update', 'enrich', 'samples', 'plots', 'resume']) {
        await state.openMaintenanceSourcePicker(action);
        assert.deepEqual(state.tagSourceOptions.map(x => x.id), ['javdb', 'javlibrary', 'fc-javten', 'jable']);
        await state.chooseMaintenanceSource('javdb');
    }
    for (const prop of ['nfoUpdateSource', 'tagSourceUpdateSource', 'missingEnrichSource', 'sampleBackfillSource', 'plotBackfillSource']) assert.equal(state[prop], 'javdb');
    assert.deepEqual(called.slice(1), ['openNfoUpdateConfirm', 'previewTagSourceUpdate', 'openTagSourceUpdateConfirm', 'runMissingEnrich', 'runSampleBackfill', 'runPlotBackfill', 'resumeMissingEnrich']);
    sources = [];
    await state.openMaintenanceSourcePicker('plots');
    assert.equal(state.tagSourceOptions.length, 3);
    await state.chooseMaintenanceSource('jable');
    assert.equal(called.length, 9);
    called=[];
    for (const id of ['javlibrary', 'fc-javten', 'jable']) {
        await state.openMaintenanceSourcePicker('rename');
        await state.chooseMaintenanceSource(id);
        assert.equal(state.renameSource,id);
    }
    assert.deepEqual(called,['previewRenamePlan','previewRenamePlan','previewRenamePlan']);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("source", ["javlibrary", "fc-javten", "jable"])
@pytest.mark.parametrize("configured", [False, True])
def test_pinned_sources_are_selectable_without_scan_source_toggle(source, configured):
    config = {"sources": [{"id": source, "enabled": False, "manual_only": True}] if configured else []}
    assert scanner._validate_batch_source(source, config) is None
    assert scanner._validate_batch_tag_source(source, config) is None
