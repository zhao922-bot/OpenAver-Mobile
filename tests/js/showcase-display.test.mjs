import { test } from 'node:test';
import assert from 'node:assert/strict';

const path = '../../app/src/main/python/web/static/js/shared/showcase-display.js';

test('saved live preferences override stale legacy layout and retain 120 films', async () => {
    const { resolveDisplayPreferences } = await import(path);
    assert.deepEqual(resolveDisplayPreferences({presentation:'cover',columns:5,items_per_page:120},
        {mode:'list',cardShape:'poster'}, {items_per_page:30}),
    {presentation:'cover',columns:5,items_per_page:120});
});

test('legacy list and effective mobile page size survive migration', async () => {
    const { resolveDisplayPreferences } = await import(path);
    assert.deepEqual(resolveDisplayPreferences(null,{mode:'list'},{items_per_page:30}),
        {presentation:'list',columns:2,items_per_page:30});
    assert.equal(resolveDisplayPreferences(null,{}, {items_per_page:90}).items_per_page,45);
    assert.equal(resolveDisplayPreferences(null,{}, {items_per_page:0}).items_per_page,45);
    assert.deepEqual(resolveDisplayPreferences({presentation:'bad',columns:4,items_per_page:Infinity}),
        {presentation:'poster',columns:2,items_per_page:45});
});

test('rapid saves are serialized and coalesced; last preference wins', async () => {
    const { createDisplaySaver } = await import(path);
    const sent=[]; let finish;
    const save=createDisplaySaver(async value=>{sent.push(value);if(sent.length===1)await new Promise(r=>finish=r);return value;});
    const first=save({columns:2});
    const second=save({columns:3});
    const third=save({columns:5});
    assert.deepEqual(sent,[{columns:2}]);
    finish();
    await Promise.all([first,second,third]);
    assert.deepEqual(sent,[{columns:2},{columns:5}]);
});

test('failed save rejects its callers and allows a retry', async () => {
    const { createDisplaySaver } = await import(path);
    let attempt=0;
    const save=createDisplaySaver(async value=>{if(++attempt===1)throw new Error('offline');return value;});
    await assert.rejects(save({columns:3}),/offline/);
    assert.deepEqual(await save({columns:5}),{columns:5});
});
