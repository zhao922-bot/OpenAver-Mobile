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
    const page={displayOpen:true,infoVisible:true};
    const ui={toolbarOpen:true};
    const root={};
    const body={classList:{contains:name=>name==='page-showcase'}};
    const window={Alpine:{$data:el=>el===root?page:{},store:()=>ui}};
    const document={body,documentElement:{},querySelector:()=>root,querySelectorAll:()=>[]};
    const source=await readFile(new URL('../../app/src/main/python/web/static/js/components/mobile-back.js',import.meta.url),'utf8');
    runInNewContext(source,{window,document,console});
    assert.equal(window.OpenAverMobileBack(),true);
    assert.equal(page.displayOpen,false);
    assert.equal(page.infoVisible,true);
    assert.equal(ui.toolbarOpen,true);
});

test('saved live preferences override stale legacy layout and retain 120 films', async () => {
    const { resolveDisplayPreferences } = await import(path);
    assert.deepEqual(resolveDisplayPreferences({presentation:'cover',columns:5,items_per_page:120},
        {mode:'list',cardShape:'poster'}, {items_per_page:30}),
    {presentation:'cover',columns:5,items_per_page:120});
});

test('legacy custom page sizes and explicit cover choice survive migration', async () => {
    const { resolveDisplayPreferences } = await import(path);
    assert.deepEqual(resolveDisplayPreferences(null,{mode:'list'},{items_per_page:30}),
        {presentation:'list',columns:2,items_per_page:30});
    for (const mode of ['grid', 'list', 'table']) {
        assert.equal(resolveDisplayPreferences(null,{mode}, {items_per_page:75}).items_per_page,75);
    }
    assert.equal(resolveDisplayPreferences(null,{}, {items_per_page:0}).items_per_page,45);
    assert.deepEqual(resolveDisplayPreferences({presentation:'bad',columns:4,items_per_page:Infinity}),
        {presentation:'poster',columns:2,items_per_page:45});
});

test('legacy explicit cover choice survives migration', async () => {
    const { resolveDisplayPreferences } = await import(path);
    assert.equal(resolveDisplayPreferences(null,{mode:'grid',cardShape:'cover'},{}).presentation,'cover');
});

test('page-size changes supersede the initial fetch and retain full-list mode', async () => {
    const { register } = await import('node:module');
    const root = new URL('../../app/src/main/python/web/static/js/', import.meta.url).href;
    register(`data:text/javascript,${encodeURIComponent(`
        export async function resolve(s,c,next) {
            if(s.startsWith('@/showcase/'))s=${JSON.stringify(root)}+'pages/showcase/'+s.slice(11);
            if(s.startsWith('@/shared/'))s=${JSON.stringify(root)}+'shared/'+s.slice(9);
            if(s.startsWith('@/components/'))s=${JSON.stringify(root)}+'components/'+s.slice(13);
            return next(s,c);
        }`)}`, import.meta.url);
    const oldWindow=globalThis.window, oldFetch=globalThis.fetch, oldStorage=globalThis.localStorage, oldAlpine=globalThis.Alpine;
    globalThis.window={t:key=>key,addEventListener(){}};
    globalThis.Alpine={store:()=>({})};
    globalThis.localStorage={getItem:()=>null};
    try {
        const { stateVideos } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-videos.js');
        const { stateDisplay } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-display.js');
        const { stateBase } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-base.js');
        const { stateLightbox } = await import('../../app/src/main/python/web/static/js/pages/showcase/state-lightbox.js');
        for (const all of [false, true]) {
            let release;
            const calls=[];
            globalThis.fetch=async url=>{
                if(!url.startsWith('/api/showcase/videos'))return {ok:true,json:async()=>({groups:[],badges:[]})};
                const params=new URL(url,'http://localhost').searchParams;
                calls.push(params);
                if(calls.length===1)await new Promise(r=>release=r);
                const full=params.get('paged')==='false';
                const count=full?157:Number(params.get('per_page'));
                return {ok:true,json:async()=>({success:true,paged:!full,total:157,page:Number(params.get('page')||1),
                    videos:Array.from({length:count},(_,i)=>({path:`test-${i}`,number:`TEST-${i}`}))})};
            };
            const state=Object.assign(stateBase.call({$persist:v=>({as:()=>v})}),stateVideos(),stateDisplay(async v=>v),{
                page:3,perPage:45,mode:'grid',cardShape:'poster',sort:all?'random':'number',order:'asc',
                _serverPaged:false,_fullVideosLoaded:false,_serverTotal:0,_videoFetchGeneration:0,
                _serverActressFilter:'',pills:[],search:'',saveState(){},
                restoreState(){},refreshSourceStatus(){},showFavoriteActresses:true,
                loadActresses(){},applyFilterAndSort(){},$watch(){},$nextTick(){},
            });
            const initial=all?state.init():state.fetchVideos({page:3,all});
            await state.setDisplayPageSize(120);
            release();await initial;
            assert.equal(calls.length,2,'the initial request must be superseded');
            assert.equal(calls[1].get('paged'),all?'false':'true');
            assert.equal(state.perPage,120);
            assert.equal(state.paginatedVideos.length,120);
            assert.equal(state.page,1);
            assert.equal(state.totalPages,2);
        }
        const actions=[];
        const modal=Object.assign(stateLightbox(),{
            displayOpen:true,mode:'grid',page:2,totalPages:3,
            prevPage(){actions.push('prev');},nextPage(){actions.push('next');},
            toggleInfo(){actions.push('info');},_presentationOrder:()=>['poster','cover'],
            _currentPresentation:()=> 'poster',setDisplayPresentation(){actions.push('presentation');},
        });
        const target={tagName:'SELECT',closest:()=>null};
        for(const key of ['ArrowLeft','ArrowRight','s','a'])modal.handleKeydown({key,target,preventDefault(){}});
        modal.handleWheel({deltaX:250,deltaY:0,target,preventDefault(){}});
        assert.deepEqual(actions,[],'display dialog must own navigation while open');
        modal.handleKeydown({key:'Escape',target,preventDefault(){}});
        assert.equal(modal.displayOpen,false);
    } finally {
        globalThis.window=oldWindow;globalThis.fetch=oldFetch;globalThis.localStorage=oldStorage;globalThis.Alpine=oldAlpine;
    }
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
