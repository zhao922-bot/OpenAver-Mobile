import {test} from 'node:test';
import assert from 'node:assert/strict';
import {register} from 'node:module';
import {stateLightboxElements} from '../../app/src/main/python/web/static/js/pages/showcase/state-lightbox-elements.js';

const root = new URL('../../app/src/main/python/web/static/js/', import.meta.url).href;
register(`data:text/javascript,${encodeURIComponent(`
    export function resolve(specifier, context, next) {
        if (specifier.startsWith('@/showcase/')) specifier = ${JSON.stringify(root)} + 'pages/showcase/' + specifier.slice(11);
        else if (specifier.startsWith('@/')) specifier = ${JSON.stringify(root)} + specifier.slice(2);
        return next(specifier, context);
    }
`)}`, import.meta.url);
Object.defineProperty(globalThis, 'localStorage', {value: {getItem: () => null}, configurable: true});
const {stateLightbox} = await import(root + 'pages/showcase/state-lightbox.js');
const {_setVideos, _setFilteredVideos} = await import(root + 'pages/showcase/state-base.js');
const uri = 'file:///Library/A%20%26%20B/part%201.mp4';
const otherUri = 'file:///Library/other/part.mp4';
const catalog = {cover: [{id: 'one'}], plot: [{id: 'two'}], tags: [{id: 'three'}], samples: []};
const json = data => Response.json(data);
const eventLine = data => 'data: ' + JSON.stringify(data) + '\r\n\r\n';
const enc = new TextEncoder();
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup() {
    global.window = {t: (s, args) => args ? s + ' ' + JSON.stringify(args) : s};
    const vm = stateLightbox();
    Object.defineProperties(vm, Object.getOwnPropertyDescriptors(stateLightboxElements()));
    vm.lightboxOpen = true;
    vm.currentLightboxVideo = {path: uri, number: 'same'};
    const card = {...vm.currentLightboxVideo};
    const other = {path: otherUri, number: 'same', tags: 'keep'};
    _setVideos([card, other]);
    _setFilteredVideos([card, other]);
    vm.paginatedVideos = [card, other];
    vm.$refs = {videoElementsDialog: {showModal() {this.open = true}, close() {this.open = false}}};
    vm.$nextTick = fn => fn();
    let plotLoads = 0;
    vm.lbPlotOpen = true;
    vm._lbPlotLoad = () => plotLoads++;
    return {vm, card, other, plotLoads: () => plotLoads};
}

function network(handlePost, handleRefresh) {
    const calls = [];
    global.fetch = async (url, options) => {
        if (url === '/api/gallery/backfill-elements/sources') return json({success: true, sources: catalog});
        if (url === '/api/gallery/rescrape-elements') {
            calls.push(JSON.parse(options.body));
            return handlePost(options);
        }
        assert.equal(url, '/api/showcase/video?path=' + encodeURIComponent(uri));
        if (handleRefresh) return handleRefresh();
        return json({success: true, video: {path: uri, number: 'same', tags: 'updated',
            cover_url: '/api/gallery/thumb?path=a', cover_full_url: '/api/gallery/image?path=b',
            sample_images: ['/api/gallery/image?path=c']}});
    };
    return calls;
}

test('partial results refresh the exact detail and card, including images at stable URLs', async () => {
    const {vm, card, other, plotLoads} = setup();
    const events = [{type: 'progress', message: 'loading'}, {type: 'result-item', element: 'cover', success: true, message: '✓'},
        {type: 'result-item', element: 'plot', success: false, error: 'missing'},
        {type: 'done', summary: {success: 1, failed: 1, skipped: 0}}];
    const bytes = enc.encode(events.map(eventLine).join('').trimEnd());
    const calls = network(() => new Response(new ReadableStream({start(ctl) {
        for (let i = 0; i < bytes.length; i += 3) ctl.enqueue(bytes.slice(i, i + 3));
        ctl.close();
    }})));
    await vm.openVideoElements();
    assert.deepEqual(vm.elementSelection, {cover:'', plot:'', samples:'', tags:''});
    vm.elementSelection.plot = 'one';
    await vm.runVideoElements();
    assert.deepEqual(calls, []);
    Object.assign(vm.elementSelection, {cover:'one', plot:'two', samples:'one'});
    await Promise.all([vm.runVideoElements(), vm.runVideoElements()]);
    assert.deepEqual(calls, [{file_path: uri, sources: {cover:'one', plot:'two'}}]);
    assert.deepEqual(vm.videoElementResults, [{field:'cover', message:'showcase.elements.updated'}, {field:'plot', message:'missing'}]);
    assert.match(vm.videoElementsStatus, /"failed":1/);
    for (const row of [card, vm.currentLightboxVideo]) {
        assert.match(row.cover_url, /&t=\d+/);
        assert.match(row.cover_full_url, /&t=\d+/);
        assert.match(row.sample_images[0], /&t=\d+/);
        assert.equal(row._coverRequested, true);
        assert.equal(row._imgLoaded, false);
    }
    assert.equal(plotLoads(), 1);
    assert.equal(other.tags, 'keep');
});

test('navigation before submit blocks the request, and navigation during refresh keeps the new detail intact', async () => {
    const {vm, card, other, plotLoads} = setup();
    let release;
    const calls = network(() => new Response(eventLine({type:'done', summary:{success:1, failed:0, skipped:0}})),
        () => new Promise(resolve => {release = resolve}));
    const original = vm.currentLightboxVideo;
    await vm.openVideoElements();
    vm.elementSelection.plot = 'two';
    vm.currentLightboxVideo = other;
    await vm.runVideoElements();
    assert.deepEqual(calls, []);
    vm.currentLightboxVideo = original;
    const run = vm.runVideoElements();
    await tick();
    vm.closeVideoElements();
    vm.currentLightboxVideo = other;
    await vm.openVideoElements();
    release(json({success:true, video:{path:uri,tags:'saved'}}));
    await run;
    assert.equal(card.tags, 'saved');
    assert.equal(other.tags, 'keep');
    assert.equal(plotLoads(), 0);
    assert.equal(vm.videoElementsStatus, '');
    assert.deepEqual(vm.selectedVideoElements, {});
});

test('HTTP errors, interruption, cancellation and server-declared errors remain visible', async () => {
    for (const mode of ['http','interrupted','cancel','server','server-cancel']) {
        const {vm, card} = setup();
        network(({signal}) => {
            if (mode === 'http') return Response.json({detail:'invalid source'}, {status:422});
            if (mode === 'interrupted') return new Response(eventLine({type:'progress'}));
            if (mode === 'server') return new Response(eventLine({type:'error',message:'missing file'}));
            if (mode === 'server-cancel') return new Response(eventLine({type:'done',cancelled:true}));
            return new Response(new ReadableStream({start(ctl) {
                signal.addEventListener('abort', () => ctl.error(signal.reason), {once:true});
            }}));
        });
        await vm.openVideoElements();
        vm.elementSelection.cover = 'one';
        const run = vm.runVideoElements();
        if (mode === 'cancel') {await tick(); vm.cancelVideoElements()}
        await run;
        assert.equal(vm.videoElementsRunning, false);
        assert.equal(vm.videoElementsStatus, {http:'invalid source',interrupted:'showcase.elements.interrupted',
            cancel:'scanner.task.cancelled_log', server:'missing file','server-cancel':'scanner.task.cancelled_log'}[mode]);
        assert.equal(card.tags, mode === 'http' ? undefined : 'updated');
    }
});

test('a refresh for a different DB row cannot replace the selected path', async () => {
    const {vm, card, other} = setup();
    network(null, () => json({success:true,video:{path: otherUri, tags:'wrong'}}));
    assert.equal(await vm.refreshVideoData(card), false);
    assert.equal(card.path, uri);
    assert.equal(other.tags,'keep');
});

test('a closed catalog response cannot populate a picker reopened for another video', async () => {
    const {vm, other} = setup();
    let resolveOld;
    global.fetch = () => new Promise(resolve => {resolveOld = resolve});
    const opening = vm.openVideoElements();
    vm.closeVideoElements();
    vm.currentLightboxVideo = other;
    global.fetch = async () => json({success: true, sources: {tags:[{id:'new'}]}});
    await vm.openVideoElements();
    resolveOld(json({success: true, sources: catalog}));
    await opening;
    assert.equal(vm.videoElementsPath, otherUri);
    assert.deepEqual(vm.elementOptions.tags, [{id:'new'}]);
    assert.deepEqual(vm.selectedVideoElements, {});
    vm.closeVideoElements();
    global.fetch = async () => new Response(null, {status:500});
    await vm.openVideoElements();
    assert.equal(vm.videoElementsStatus, 'scanner.sources.load_failed');
    assert.deepEqual(vm.selectedVideoElements, {});
});
