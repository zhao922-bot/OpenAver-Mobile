from pathlib import Path
import shutil
import subprocess

import pytest


def test_source_choice_starts_update_and_retry_keeps_original_source():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is not installed')
    script = r'''
const fs=require('node:fs'), assert=require('node:assert/strict');
global.window={t:key=>key};
global.dirPath='';
global.localStorage={getItem:()=>null,setItem:()=>{}};
const connections=[];
global.EventSource=class {constructor(url){this.url=new URL(url,'http://localhost');connections.push(this);}close(){}};
function load(file,name){return new Function(fs.readFileSync(file,'utf8').replace(/^import .*;$/mg,'').replace(/export /g,'')+`;return ${name};`)()();}
const root='app/src/main/python/web/static/js/pages/scanner/';
const vm=load(root+'state-scan.js','stateScan');
Object.defineProperties(vm,Object.getOwnPropertyDescriptors(load(root+'state-batch.js','stateBatch')));
vm.config={sources:[]}; vm.statTotal=2;
for(const name of ['clearLogs','flushLogs','addLog','showToast'])vm[name]=()=>{};
vm._startTask=kind=>{vm.taskKind=kind;};
vm._finishTask=(state,status,summary)=>{vm.state=state;vm.taskFailedItems=summary?.failed_items||[];};
(async()=>{
    vm.maintenanceSourceAction='tag-update';vm.maintenanceSourceModalOpen=true;
    await vm.chooseMaintenanceSource('jable');
    assert.equal(connections.length,1);
    assert.equal(connections[0].url.pathname,'/api/gallery/tag-source-update');
    assert.equal(connections[0].url.searchParams.get('source'),'jable');
    assert.equal(connections[0].url.searchParams.has('backup'),false);
    assert.equal(vm.maintenanceSourceModalOpen,false);
    await vm.startTagSourceUpdate();assert.equal(connections.length,1,'busy task must not start twice');
    connections[0].onmessage({data:JSON.stringify({type:'done',summary:{success:1,failed:1,failed_items:[{number:'ABC-123',path:'/ABC-123.mp4'}]}})});
    vm.tagSourceUpdateSource='javlibrary';
    vm.retryFailedItems();
    assert.equal(connections.length,2);
    assert.equal(connections[1].url.pathname,'/api/gallery/tag-source-update');
    assert.equal(connections[1].url.searchParams.get('source'),'jable');
    assert.equal(connections[1].url.searchParams.get('numbers'),'ABC-123');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
