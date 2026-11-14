from __future__ import annotations

import asyncio
import copy
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from core import config as config_module
from core.ai_services.tagging import resolve_vision_conn
from core.ai_services.vision_chat import VisionConn, vision_chat
from core.secret_fields import render_config_secrets, resolve_secret
from core.translate_service import create_translate_service


def test_legacy_tags_connection_is_copied_only_once():
    cfg = {
        "translate": {"openai": {"base_url": "https://translate.test/v1", "api_key": "old-key"}},
        "ai_services": {"tags": {"provider": "openai", "model": "vision-model"}},
    }
    config_module._migrate_additive_config(cfg)
    tags = cfg["ai_services"]["tags"]
    assert tags.get("base_url") == "https://translate.test/v1"
    assert tags.get("api_key") == "old-key"
    tags["api_key"] = ""
    cfg["translate"]["openai"] = {"base_url": "https://changed.test/v1", "api_key": "new-key"}
    config_module._migrate_additive_config(cfg)
    assert tags["base_url"] == "https://translate.test/v1"
    assert tags["api_key"] == ""
    assert tags["model"] == "vision-model"


@pytest.mark.parametrize("provider,url", [
    ("gemini", "https://generativelanguage.googleapis.com/v1beta"),
    ("claude", "https://api.anthropic.com"),
    ("openai_official", "https://api.openai.com/v1"),
    ("ollama", "http://localhost:11434"),
])
def test_legacy_tags_migration_preserves_default_service(provider, url):
    cfg = {"translate": {provider: {"api_key": "legacy-key"}},
           "ai_services": {"tags": {"provider": provider, "model": "my-model"}}}
    config_module._migrate_additive_config(cfg)
    assert cfg["ai_services"]["tags"].get("base_url") == url


def test_config_roundtrip_keeps_independent_addresses_and_secrets():
    raw = {"translate": {
        "ollama": {"url": "https://ollama.test", "api_key": "ollama-secret"},
        "gemini": {"base_url": "https://gemini.test/v1beta"},
        "claude": {"base_url": "https://claude.test"},
        "openai_official": {"base_url": "https://openai.test/v1"},
    }, "ai_services": {"tags": {
        "base_url": "https://tags.test/v1", "api_key": "tags-secret", "model": "vision-model",
    }}}
    saved = config_module.AppConfig(**raw).model_dump()
    assert saved["translate"]["ollama"].get("api_key") == "ollama-secret"
    for p in ("gemini", "claude", "openai_official"):
        assert saved["translate"][p].get("base_url") == raw["translate"][p]["base_url"]
    assert saved["ai_services"]["tags"].get("base_url") == "https://tags.test/v1"
    masked = render_config_secrets(saved)
    for section, stored in ((masked["translate"]["ollama"], "ollama-secret"),
                            (masked["ai_services"]["tags"], "tags-secret")):
        assert section["api_key"] != stored
        assert resolve_secret(section["api_key"], stored) == stored


def test_tags_does_not_read_translate_credentials_after_migration():
    cfg = {"translate": {"openai": {"base_url": "https://wrong.test", "api_key": "wrong"}},
           "ai_services": {"tags": {"provider": "openai", "model": "vision-model",
                                     "base_url": "https://tags.test/v1", "api_key": "tags-key",
                                     "connection_version": 1}}}
    conn = resolve_vision_conn(cfg)
    assert (conn.base_url, conn.api_key, conn.model) == ("https://tags.test/v1", "tags-key", "vision-model")
    cfg["ai_services"]["tags"]["api_key"] = ""
    assert resolve_vision_conn(cfg).api_key == ""


def test_tags_test_overrides_and_mask_resolve_only_against_tags(monkeypatch):
    from web.routers import ai_tags
    cfg = {"translate": {"openai": {"api_key": "wrong-translate-key"}},
           "ai_services": {"tags": {"provider": "openai", "model": "saved-model",
               "base_url": "https://saved.test/v1", "api_key": "saved-tags-key", "connection_version": 1}}}
    monkeypatch.setattr(ai_tags, "load_config", lambda: copy.deepcopy(cfg))
    monkeypatch.setattr(ai_tags, "_tags_sample_uri", lambda: "data:image/jpeg;base64,YQ==")
    masked_key = render_config_secrets(cfg)["ai_services"]["tags"]["api_key"]
    conn, *_ = ai_tags._prepare_tags_test(ai_tags.TagsTestRequest(
        base_url="https://unsaved.test/v1", api_key=masked_key, model="unsaved-model"))
    assert (conn.base_url, conn.api_key, conn.model) == ("https://unsaved.test/v1", "saved-tags-key", "unsaved-model")
    assert cfg["ai_services"]["tags"]["model"] == "saved-model"


@pytest.mark.parametrize("provider,path,header", [
    ("ollama", "/prefix/api/tags", "authorization"),
    ("gemini", "/prefix/models", "x-goog-api-key"),
    ("claude", "/prefix/v1/models", "x-api-key"),
    ("openai_official", "/prefix/models", "authorization"),
])
@pytest.mark.parametrize("with_key", [True, False])
def test_model_queries_use_feature_credentials(monkeypatch, provider, path, header, with_key):
    from web.routers import ai_tags, config, gemini, claude_translate, openai_translate
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"models": [{"name": "gemini-flash-lite-latest"}],
            "data": [{"id": "claude-haiku-5-5"}, {"id": "gpt-4o-mini"}], "has_more": False})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handle)))
    for module in (ai_tags, config, gemini, claude_translate, openai_translate):
        monkeypatch.setattr(module, "load_config", lambda: {})
    result = asyncio.run(ai_tags.tags_models(ai_tags.TagsTestRequest(
        provider=provider, base_url="https://tags.test/prefix", api_key="tags-key" if with_key else "")))
    assert result["success"] is True
    assert result["models"]
    if provider == "ollama":
        result = asyncio.run(config.post_ollama_models(config.OllamaModelsRequest(
            url="https://translate.test/prefix", api_key="translate-key" if with_key else "")))
    elif provider == "gemini":
        result = asyncio.run(gemini.test_gemini_connection(gemini.TestRequest(
            base_url="https://translate.test/prefix", api_key="translate-key" if with_key else "")))
    elif provider == "claude":
        result = asyncio.run(claude_translate.fetch_claude_models(claude_translate.ModelsRequest(
            base_url="https://translate.test/prefix", api_key="translate-key" if with_key else "")))
    else:
        result = asyncio.run(openai_translate.fetch_openai_official_models(openai_translate.OfficialModelsRequest(
            base_url="https://translate.test/prefix", api_key="translate-key" if with_key else "")))
    assert (result["success"] if isinstance(result, dict) else result.success) is True
    assert [str(c.url).split("?")[0] for c in calls] == ["https://tags.test"+path, "https://translate.test"+path]
    assert [c.headers.get(header) for c in calls] == ((["Bearer tags-key", "Bearer translate-key"] if header == "authorization" else ["tags-key", "translate-key"]) if with_key else [None, None])


@pytest.mark.parametrize("provider,path,auth_header", [
    ("ollama", "/custom/api/chat", "authorization"),
    ("gemini", "/custom/models/my-model:generateContent", "x-goog-api-key"),
    ("claude", "/custom/v1/messages", "x-api-key"),
    ("openai_official", "/custom/chat/completions", "authorization"),
])
@pytest.mark.parametrize("with_key", [True, False])
def test_translation_and_vision_use_own_custom_connection(monkeypatch, provider, path, auth_header, with_key):
    calls = []

    def handle(request):
        calls.append((str(request.url), request.headers, json.loads(request.content)))
        if provider == "gemini":
            data = {"candidates": [{"content": {"parts": [{"text": "Translated title"}]}, "finishReason": "STOP"}]}
        elif provider == "claude":
            data = {"content": [{"type": "text", "text": "Translated title"}], "stop_reason": "end_turn"}
        elif provider == "ollama":
            data = {"message": {"content": "Translated title"}, "done": True}
        else:
            data = {"choices": [{"message": {"content": "Translated title"}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=data)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handle)))
    settings = {"url" if provider == "ollama" else "base_url": "https://translate.test/custom/",
                "api_key": "translate-key" if with_key else "", "model": "my-model"}
    service = create_translate_service({"provider": provider, provider: settings}, "en")
    assert asyncio.run(service.translate_or_raise("テスト作品")) == "Translated title"
    asyncio.run(vision_chat(VisionConn(provider=provider, model="my-model", api_key="vision-key" if with_key else "",
                                     base_url="https://vision.test/custom/"), "system", "tag", "data:image/jpeg;base64,YQ=="))
    assert [c[0] for c in calls] == ["https://translate.test" + path, "https://vision.test" + path]
    for call, key in zip(calls, ("translate-key", "vision-key")):
        assert call[1].get(auth_header) == (("Bearer " + key if auth_header == "authorization" else key) if with_key else None)
        if provider != "gemini":
            assert call[2]["model"] == "my-model"


def test_disabled_ai_panels_do_not_test_saved_connections():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    script = r'''
const fs=require('node:fs'), assert=require('node:assert/strict');
const dir='app/src/main/python/web/static/js/pages/settings/';
const source=file=>fs.readFileSync(dir+file,'utf8').replace(/^import [\s\S]*?;\r?$/mg,'').replace(/export /g,'');
global.window={t:key=>key};
global.aiBackfillControls=()=>({bfRefresh:async()=>{}});
global.SIMILAR_ADAPTER={};global.FACES_ADAPTER={};global.TAGS_ADAPTER={};
Object.assign(global,new Function(source('ai-tags-logic.js')+';return {buildTagsTestBody,testResultLine};')());
const calls=[];
global.fetch=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({ok:false,kind:'unreachable'})};};
(async()=>{
    for(const [file,factory,enabled,url,key,model] of [
        ['ai-similar-panel.js','aiSimilarPanel','aiSimilarEnabled','aiSimilarUrl','aiSimilarApiKey','aiSimilarModel'],
        ['ai-faces-panel.js','aiFacesPanel','aiFacesEnabled','aiFacesUrl','aiFacesApiKey','aiFacesModel'],
        ['ai-tags-panel.js','aiTagsPanel','aiTagsEnabled','aiTagsBaseUrl','aiTagsApiKey','aiTagsModel'],
    ]){
        const vm=new Function(source(file)+`;return ${factory};`)()();
        vm.form={[enabled]:false,[url]:'https://saved.example/v1',[key]:'own-key',[model]:'own-model',aiTagsProvider:'openai'};
        vm.showToast=()=>{};
        calls.length=0;
        await vm.runTest();
        assert.deepEqual(calls,[],`${factory}: a disabled feature must not contact its saved service`);
        vm.form[enabled]=true;
        await vm.runTest();
        assert.equal(calls.length,1,`${factory}: enabling must allow a connection test`);
        assert.equal(calls[0].body.api_key,'own-key');
        assert.equal(calls[0].body.model,'own-model');
    }
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_settings_js_uses_independent_unsaved_connections():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    script = r'''
const fs = require('node:fs'), assert = require('node:assert/strict');
const dir = 'app/src/main/python/web/static/js/pages/settings/';
const configSource = fs.readFileSync(dir+'state-config.js','utf8').replace(/^import [\s\S]*?;\r?$/mg,'').replace(/export /g,'');
global.currentSettingsHash=()=>'';global.readStoredSettingsTab=()=>'';global.resolveSettingsTab=()=> 'ai';
global.window={t:key=>key};
const settings=new Function(configSource+';return stateConfig;')()();
assert.equal(settings.form.aiTagsApiKey,'');assert.equal(settings.form.ollamaApiKey,'');
const logic = new Function(fs.readFileSync(dir+'ai-tags-logic.js','utf8').replace(/export /g,'')+'; return {buildTagsTestBody};')();
const form = {aiTagsProvider:'openai', aiTagsBaseUrl:'https://tags.test/v1', aiTagsApiKey:'tags-key', aiTagsModel:'vision',
    openaiBaseUrl:'https://wrong.test/v1', openaiApiKey:'wrong-key', ollamaUrl:'http://ollama.test', ollamaApiKey:'ollama-key',
    geminiBaseUrl:'https://gemini.test/custom', geminiApiKey:'gemini-key', claudeBaseUrl:'https://claude.test/custom', claudeApiKey:'claude-key',
    openaiOfficialBaseUrl:'https://official.test/custom', openaiOfficialApiKey:'official-key'};
assert.deepEqual(logic.buildTagsTestBody(form), {provider:'openai',base_url:'https://tags.test/v1',api_key:'tags-key',model:'vision'});
const panelSource=fs.readFileSync(dir+'ai-tags-panel.js','utf8').replace(/^import [\s\S]*?;\r?$/mg,'').replace(/export /g,'');
global.TAGS_ADAPTER={};global.aiBackfillControls=()=>({bfOnInit(){}});
const panel=new Function(panelSource+';return aiTagsPanel;')()();
panel.form={aiTagsProvider:'',aiTagsModel:'',aiTagsBaseUrl:'',aiTagsApiKey:'',translateProvider:'gemini'};
panel.isDirty=true;const watchers={};panel.$watch=(key,fn)=>{watchers[key]=fn};panel.init();
watchers['form.aiTagsEnabled'](true);
assert.equal(panel.form.aiTagsProvider,'gemini');
assert.equal(panel.form.aiTagsBaseUrl,'https://generativelanguage.googleapis.com/v1beta');
assert.equal(panel.form.aiTagsApiKey,'');
panel.form.aiTagsBaseUrl='https://custom.test';panel.form.aiTagsApiKey='own-key';panel.form.aiTagsModel='own-model';
panel.rememberConnection();panel.form.aiTagsProvider='claude';panel.onProviderChange();
assert.equal(panel.form.aiTagsApiKey,'');
panel.form.aiTagsProvider='gemini';panel.onProviderChange();
assert.equal(panel.form.aiTagsBaseUrl,'https://custom.test');assert.equal(panel.form.aiTagsApiKey,'own-key');assert.equal(panel.form.aiTagsModel,'own-model');
panel.form.aiTagsApiKey='••••1234';panel.rememberConnection();
panel.form.aiTagsProvider='claude';panel.onProviderChange();panel.form.aiTagsApiKey='new-provider-key';
// A successful save changes the canonical saved key. Old masks must not survive it.
watchers['savedState']({});
panel.form.aiTagsProvider='gemini';panel.onProviderChange();
assert.equal(panel.form.aiTagsApiKey,'');
let calls=[];
global.window={t:key=>key};
global.fetch=async (url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({success:true,models:[],count:0})};};
const code=fs.readFileSync(dir+'state-providers.js','utf8').replace(/^import .*;$/mg,'').replace(/export /g,'');
const vm=new Function(code+';return stateProviders;')()(); vm.form=form;
(async()=>{
    await vm.loadOllamaModels(form.ollamaUrl, '', {keepModel:true});
    await vm.testGeminiConnection(); await vm.fetchClaudeModels(); await vm.fetchOpenAIOfficialModels();
    assert.deepEqual(calls.map(c=>c.body), [
        {url:'http://ollama.test',api_key:'ollama-key'},
        {api_key:'gemini-key',base_url:'https://gemini.test/custom'},
        {api_key:'claude-key',base_url:'https://claude.test/custom'},
        {api_key:'official-key',base_url:'https://official.test/custom'}]);
    assert.equal(form.aiTagsApiKey,'tags-key');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("method", ["translate_or_raise", "translate_plot_or_raise"])
def test_ollama_rejected_auth_does_not_expose_key(monkeypatch, caplog, method):
    from core.cloud_translate import TranslateError
    def handle(_request):
        raise httpx.LocalProtocolError("Illegal header value b'Bearer private-key'")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handle)))
    service = create_translate_service({"provider": "ollama", "ollama": {"api_key": "private-key"}}, "en")
    with pytest.raises(TranslateError) as caught:
        asyncio.run(getattr(service, method)("テスト作品"))
    assert caught.value.kind == "auth_failed"
    assert "private-key" not in str(caught.value)
    assert "private-key" not in caplog.text


def test_gemini_translation_test_uses_entered_service_url(monkeypatch):
    from web.routers import gemini
    calls = []
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "测试译文"}]}, "finishReason": "STOP"}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(gemini, "load_config", lambda: {})
    result = asyncio.run(gemini.test_gemini_translate(gemini.TestTranslateRequest(
        base_url="https://custom.test/v1beta", api_key="key", model="test-model")))
    assert result.success is True
    assert calls == ["https://custom.test/v1beta/models/test-model:generateContent"]
