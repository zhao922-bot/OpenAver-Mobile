import subprocess
from pathlib import Path


def test_plot_search_prompts_only_after_saving_and_translation_is_separate():
    script = r'''
const fs=require('node:fs');const assert=require('node:assert/strict');
const stored=new Map();global.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
global.window={t:k=>k};
const text=fs.readFileSync('app/src/main/python/web/static/js/pages/scanner/state-batch.js','utf8').replace(/^import .*;$/mg,'').replace(/export /g,'');
const make=new Function(text+';return stateBatch;')();
const vm=make();vm.config={translate:{enabled:false}};vm.isBusy=false;vm.missingPlotCount=2;vm.plotBackfillSource='javbus';vm.showToast=()=>{};
const calls=[];vm._runBackfillStream=async options=>{calls.push(options);return {type:'done',summary:{success:2,failed:0,translation_batch:'a'.repeat(32),translation_count:2}}};
(async()=>{
assert.equal(vm.plotBackfillDisabled,false);
await vm.runPlotBackfill();
assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/gallery/backfill-plots');
assert.equal(vm.plotTranslationConfirmOpen,true);assert.equal(vm.pendingPlotTranslation.count,2);
vm.keepOriginalPlots();assert.equal(vm.plotTranslationConfirmOpen,false);assert.equal(calls.length,1);
const restored=make();assert.equal(restored.pendingPlotTranslation.batch_id,'a'.repeat(32));
vm.config.translate.enabled=true;await vm.runPlotTranslation();
assert.equal(calls.length,2);assert.equal(calls[1].url,'/api/gallery/translate-backfilled-plots');
assert.equal(calls[1].body.batch_id,'a'.repeat(32));assert.equal(calls[1].source,undefined);
assert.equal(vm.pendingPlotTranslation,null);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout+result.stderr
