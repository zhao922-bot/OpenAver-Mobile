# Independent AI Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 四项 AI 功能独立填写地址、API Key、模型，旧配置继续可用。

**Architecture:** 保留现有协议与翻译服务商配置；增加统一默认地址解析与一次性标签连接迁移。AI 标签独立连接，测试和正式任务共用配置解析，前端不再复用翻译表单。

**Tech Stack:** Python/FastAPI/Pydantic、httpx、Alpine.js、Android WebView。

**Spec:** `docs/superpowers/specs/2026-11-13-independent-ai-connections-design.md`（用户已批准，当前会话直接实施）。

## Global Constraints

- 保留工作区已有批量维护和设置页改动；不删除历史诊断文件，不全量暂存。
- 不新增服务商或更改向量、人脸返回协议；不升级版本或发布。
- 官方服务默认地址沿用现状；新增密钥全部纳入现有遮罩机制。

## Review Focus

- 旧标签连接首次迁移后不随翻译配置变化。
- 用户主动清空标签密钥不重新继承；遮罩保存不丢失真实密钥。
- 自定义地址、认证、模型在测试和实际任务中相同，含 Ollama。
- 标签填写未保存资料并测试时，不泄漏或串用翻译凭据。
- 服务商切换不清空翻译已有资料；标签模型允许手填；小屏无溢出。

### Task 1: 独立配置和兼容

**Files:** `core/config.py`、`core/secret_fields.py`、新增 `core/ai_services/connections.py`；测试 `tests/test_ai_connections.py`。

**Interfaces:** `provider_base_url(provider, config) -> str` 返回去尾斜杠的默认或自定义基础地址；`migrate_tags_connection(config) -> bool` 只迁移缺少独立连接字段的旧配置。

- [x] 编写旧配置迁移、二次读取不继承、独立凭据遮罩及模型序列化测试，运行确认因缺少功能而失败。
- [x] 增加配置字段和默认解析；加载时迁移旧标签地址/密钥；扩展密钥清单。
- [x] 运行新增测试与配置迁移测试，确认通过。

### Task 2: 请求、测试与模型查询

**Files:** `core/translate_service.py`、`core/gemini_client.py`、`core/anthropic_client.py`、`core/ai_services/{vision_chat,tagging}.py`、`web/routers/{gemini,claude_translate,openai_translate,ai_tags}.py` 及 Ollama 路由。

**Interfaces:** Gemini/Claude 请求增加可选 `base_url` 参数，保持旧调用兼容；Ollama 增加可选密钥；标签连接解析改读独立字段，新增标签专属模型查询。

- [x] 使用本地 httpx MockTransport 测试自定义 URL、认证和模型，以及不同功能凭据隔离；先运行观察失败。
- [x] 修改客户端及翻译工厂；统一测试/查询使用对应功能连接，不回读另一项密钥。
- [x] 运行连接、翻译、AI 标签与官方服务回归测试。

### Task 3: 设置界面

**Files:** `web/templates/settings.html`、`web/static/js/pages/settings/{state-config,state-providers,ai-tags-panel,ai-tags-logic}.js`、`locales/{en,ja,ko,zh_CN,zh_TW}.json`。

**Interfaces:** 标签独立 `aiTagsBaseUrl`、`aiTagsApiKey`、模型及自己的查询清单；翻译新增每服务商地址与 Ollama 密钥；保存完整往返独立字段。

- [x] 编写 JS 行为测试验证标签测试体、保存/恢复及独立查询，不只匹配源码文字；运行观察失败。
- [x] 为翻译/标签提供完整三字段；保留翻译按服务商保存资料；增加五语言文案。
- [x] 验证模型可手填、切换服务商不串值，运行相关测试及 JS 语法检查。

### Task 4: 全量验证、补丁与模拟器

**Files:** `tools/generate_patches.py`、对应生成的 `patches/*.patch`；本计划记录验证结果。

- [x] 两套 Python 环境运行 `-m pytest tests/ -q`，全量 JS `node --check`。
- [x] 生成补丁并核对源码同步，基线以现有 upstream 实际提交为准。
- [x] `gradlew testDebugUnitTest assembleDebug -Pabi=x86_64`；在 `emulator-5554` 验证四面板、小屏、保存刷新和独立连接测试，不操作真机或生产数据。
- [x] 一次独立代码审阅，修复实质问题并补回归；记录结果，交付未发布 APK。

## Progress / Rulings

- 2026-11-13：用户已明确批准设计并要求实施，不再追加执行方式确认。保留当前未提交改动，使用本地功能分支；本次不提交、不发布，方便与上一任务合并验收。
- 预检：Task 2/3 都消费 Task 1 的独立标签字段；标签模型查询和测试必须共用连接解析，避免前端退回翻译清单。
- Ruling：自定义服务地址允许 API Key 留空，适用于保留的各协议；默认官方地址仍保留必要的密钥检查。这样本地网关不必填假密钥；无认证的自定义地址若实际要求认证，将显示服务的认证错误。
- 用户补充纠正：批量维护中的 JavLibrary、FC2-javten、Jable 必须默认可选，独立于设置中的自动扫描来源开关；已同时修正前端按钮及后端校验，保留其他来源的启用检查。
- Task 1: complete — 独立字段、一次性迁移、主动清空和遮罩保存回归通过。
- Task 2: complete — 自定义地址、模型、认证和无密钥请求覆盖翻译/视觉的 Ollama、Gemini、Claude、OpenAI 协议；测试与模型查询使用对应功能的配置。
- Task 3: complete — 五语言文案、可手填模型、标签独立查询及草稿切换完成；实际初始化测试补足 `node --check` 文件模式漏报的问题。
- Final review：一次独立审阅发现并修复 Gemini 测试翻译遗漏地址、标签开关引用已删除方法、保存后恢复旧密钥遮罩三项问题，各项均补充 RED→GREEN 回归；无未解决的重要问题。
- Task 4: complete — TUR 全量 404 passed（2 个依赖弃用警告），Cleanup 全量 404 passed（1 个依赖弃用警告）；129 个 JS 模块语法检查通过；JVM 与 x86_64 Debug 构建成功；455 个 Python 文件与 upstream + patches 匹配，diff 检查通过。
- 模拟器 `emulator-5554`：四项使用不同地址、假密钥与模型，通过本地协议测试服务验证模型查询、连接测试、保存与刷新后的再次调用；15 次请求的密钥与各自功能完全匹配。所有面板无横向溢出；保存其他服务商后，旧密钥遮罩草稿正确失效。
- 来源选择模拟器检查：三个固定按钮均启用，逐一点选后对应来源字段正确。未执行生产片库维护或外站批量抓取。
- 模拟器原始配置已按字节恢复，临时协议测试服务已停止、ADB 临时端口映射已移除。测试截图与诊断日志位于 `app/build/`；源码仍为未提交改动。

- 发布授权：用户随后明确要求打包上传 GitHub；本次按 `v0.18.17-android-r8` / `18008` 发布，覆盖本计划及批量维护来源选择修正，取代上文实施阶段暂不发布的约束。
