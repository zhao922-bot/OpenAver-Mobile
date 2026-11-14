import { test } from 'node:test';
import assert from 'node:assert/strict';

const path = '../../app/src/main/python/web/static/js/shared/showcase-display.js';

test('settings saves display only when its controls changed, preserving edits elsewhere', async () => {
    const { saveChangedDisplayPreferences } = await import(path);
    const form={browsePresentation:'poster',browseColumns:2,browsePerPage:45,locale:'en'};
    const saved={...form,locale:'zh-CN'};
    const calls=[];
    await saveChangedDisplayPreferences(form,saved,async value=>calls.push(value));
    assert.deepEqual(calls,[]);
    form.browseColumns=5;form.browsePerPage=120;
    await saveChangedDisplayPreferences(form,saved,async value=>calls.push(value));
    assert.deepEqual(calls,[{presentation:'poster',columns:5,items_per_page:120}]);
    await assert.rejects(saveChangedDisplayPreferences(form,saved,async()=>{throw Error('offline');}),/offline/);
});

test('Android back closes display panel before navigating', async () => {
    const { readFile } = await import('node:fs/promises');
    const { runInNewContext } = await import('node:vm');
    const page={displayOpen:true};
    const root={};
    const body={classList:{contains:name=>name==='page-showcase'}};
    const window={Alpine:{$data:el=>el===root?page:{},store:()=>({})}};
    const document={body,documentElement:{},querySelector:()=>root,querySelectorAll:()=>[]};
    const source=await readFile(new URL('../../app/src/main/python/web/static/js/components/mobile-back.js',import.meta.url),'utf8');
    runInNewContext(source,{window,document,console});
    assert.equal(window.OpenAverMobileBack(),true);
    assert.equal(page.displayOpen,false);
});

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

test('page size resets page, preserves filters and waits for current server data', async () => {
    const { stateDisplay } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-display.js');
    const writes=[];
    const state=Object.assign(stateDisplay(async v=>writes.push(v)),{
        page:4,perPage:45,mode:'grid',cardShape:'poster',gridColumns:3,
        search:'keep',pills:[{field:'actress',value:'name'}],sort:'date',order:'desc',
        _serverPaged:true,_fullVideosLoaded:false,
        fetchVideos:async function(options){assert.deepEqual(options,{page:1});assert.equal(this.perPage,120);return true;},
        updatePagination(){this.updated=true;},saveState(){},
    });
    await state.setDisplayPageSize(120);
    assert.equal(state.page,1);assert.equal(state.perPage,120);assert.equal(state.gridColumns,3);
    assert.equal(state.search,'keep');assert.deepEqual(state.pills,[{field:'actress',value:'name'}]);
    assert.equal(state.updated,true);assert.equal(writes.at(-1).items_per_page,120);
});

test('stale page-size reload cannot reapply pagination after newer selection', async () => {
    const { stateDisplay } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-display.js');
    let firstResolve;let fetches=0,updates=0;
    const state=Object.assign(stateDisplay(async v=>v),{
        page:1,perPage:45,mode:'grid',cardShape:'poster',_serverPaged:true,_fullVideosLoaded:false,
        fetchVideos(){if(++fetches===1)return new Promise(r=>firstResolve=r);return Promise.resolve(true);},
        updatePagination(){updates++;},saveState(){},
    });
    const first=state.setDisplayPageSize(60);
    await state.setDisplayPageSize(120);firstResolve(true);await first;
    assert.equal(state.perPage,120);assert.equal(updates,1);
});

test('restoration uses server preference and column choice never changes page size', async () => {
    const { stateDisplay } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-display.js');
    globalThis.window={__SHOWCASE_DISPLAY__:{presentation:'cover',columns:5,items_per_page:120}};
    const state=stateDisplay(async v=>v);
    state.restoreDisplayPreferences({mode:'list'},{items_per_page:30});
    assert.equal(state.mode,'grid');assert.equal(state.cardShape,'cover');assert.equal(state.gridColumns,5);
    await state.setDisplayColumns(3);assert.equal(state.perPage,120);
    await state.setDisplayColumns(4);assert.equal(state.gridColumns,3);
    delete globalThis.window;
});
