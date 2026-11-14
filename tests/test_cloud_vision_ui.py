import subprocess
import json
import re
from pathlib import Path


def test_cloud_panels_send_protocol_and_keep_preset_keys_separate():
    root = Path(__file__).resolve().parents[1]
    js = (root / 'app/src/main/python/web/static/js/pages/settings').as_uri()
    script = r'''
import assert from 'node:assert/strict';
import {aiSimilarPanel} from 'JS/ai-similar-panel.js';
import {aiFacesPanel} from 'JS/ai-faces-panel.js';
global.window={t:k=>k};
const calls=[];
global.fetch=async (url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({ok:true,success:true,models:['vision-model'],boxes:[]})};};
const similar=aiSimilarPanel();
similar.form={aiSimilarEnabled:true,aiSimilarProvider:'qwen',aiSimilarUrl:'https://own.test',aiSimilarApiKey:'image-key',aiSimilarModel:'image-model'};
similar.bfRefresh=async()=>{}; similar.showToast=()=>{};
await similar.runTest();
assert.equal(calls.at(-1).body.provider,'qwen');
const vm=aiFacesPanel();
vm.form={aiFacesEnabled:true,aiFacesProvider:'openai',aiFacesUrl:'https://api.b.ai/v1',aiFacesApiKey:'bai-key',aiFacesModel:'custom-vision'};
vm.bfRefresh=async()=>{};vm.showToast=()=>{};
vm.usePreset('qwen');
assert.equal(vm.form.aiFacesApiKey,'');
assert.equal(vm.form.aiFacesUrl,'https://dashscope.aliyuncs.com/compatible-mode/v1');
vm.form.aiFacesApiKey='qwen-key';
vm.usePreset('bai');
assert.equal(vm.form.aiFacesApiKey,'bai-key');
assert.equal(vm.form.aiFacesModel,'custom-vision');
vm.aiFacesTestImage='data:image/png;base64,aA==';
await vm.runTest();
assert.equal(calls.at(-1).body.provider,'openai');
assert.equal(calls.at(-1).body.api_key,'bai-key');
assert.equal(calls.at(-1).body.image_data_uri,vm.aiFacesTestImage);
await vm.loadModels();
assert.equal(calls.at(-1).url,'/api/ai/faces/models');
assert.deepEqual(vm.aiFacesModels,['vision-model']);
const n=calls.length;vm.form.aiFacesEnabled=false;
await vm.loadModels();await vm.runTest();assert.equal(calls.length,n);
'''.replace('JS/', js + '/')
    result = subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cloud_ui_strings_exist_in_every_language():
    source = Path(__file__).resolve().parents[1] / 'app/src/main/python'
    text = (source / 'web/templates/settings.html').read_text(encoding='utf-8')
    for name in ('ai-faces-panel.js', 'ai-faces-logic.js', 'ai-similar-logic.js'):
        text += (source / 'web/static/js/pages/settings' / name).read_text(encoding='utf-8')
    keys = set(re.findall(r'settings\.ai\.cloud\.[a-z_]+', text))
    assert len(keys) >= 15
    for locale in ('en', 'ja', 'ko', 'zh_CN', 'zh_TW'):
        data = json.loads((source / 'locales' / f'{locale}.json').read_text(encoding='utf-8'))
        for key in keys:
            value = data
            for segment in key.split('.'):
                value = value[segment]
            assert isinstance(value, str) and value
