# 云端图片向量与人脸适配实施计划

> **For agentic workers:** Use superpowers:executing-plans task-by-task. 用户已批准设计并要求实施及模拟器验证，在当前会话连续执行。

**Goal:** Qwen 图片向量及 Qwen、DeepSeek、B.AI 的 OpenAI 兼容人脸视觉模式可实际调用。
**Architecture:** 保留旧 endpoint 模式，新增服务类型分派、严格响应转换；连接身份隔离向量索引。前端保存和测试与后台任务使用相同配置。
**Tech Stack:** Python/httpx/Pydantic/FastAPI、Alpine.js、Android WebView。
**Spec:** `docs/superpowers/specs/2026-11-14-cloud-vision-adapters-design.md`。

## Global Constraints

- 不升级版本、不发布；保留旧配置与现有功能；只操作专用 `emulator-5554`。
- 不增加大型依赖；不读取其他 App 的凭据；没有真实厂商凭据时只报告协议验证。
- 五语言文案；不恢复演示照片；新模式不能把拒绝、空响应或非法坐标判为成功。

## Review Focus

- 同名/同维模型来自不同地址的向量不可混用，重启也不能绕过；Task 2。
- 旧配置无 provider 时完全保留 endpoint 行为、密钥、模型；Task 1/2。
- 基础地址、完整端点和中转前缀不重复拼路径；Task 1。
- 拒绝、截断、越界框与合法空人脸列表须区分；Task 1。
- 用户测试图不能触发自动全库重算，字段切换不串密钥；Task 2/3。

### Task 1: 传输与响应适配

**Files:** 新增 `core/ai_services/cloud_protocols.py`；修改 `embeddings.py`、`faces.py`、`core/config.py`；测试 `tests/test_cloud_vision_adapters.py`。
**Interfaces:** provider 默认 `endpoint`；图片增加 `qwen`，人脸增加 `openai`；`embedding_connection_id(cfg)->str`、`endpoint_url(base,suffix)->str`；`embed/detect` 保持原签名和内部结果类型。

- [x] 编写 MockTransport 实物请求测试，覆盖 Qwen 原生 Data URI、三家人脸地址、独立认证、坐标、错误和路径前缀；运行确认 RED。
- [x] 实现类型、URL、Qwen 原生请求转换、人脸 JSON 提示词/严格转换与适当超时，保留旧模式。
- [x] 新测试与旧 AI 测试全部 GREEN，再显式提交本任务文件。

### Task 2: 后台、索引与接口

**Files:** `similar_index.py`、`similar_state.py`、`faces_detect.py`、`faces_recompute.py`、`samples.py`、`core/database/embeddings.py`、`web/routers/{ai_services,config}.py`；同测试文件及新 `tests/test_cloud_vision_integration.py`。
**Interfaces:** 所有配置解析携带 provider；测试请求携带 provider，人脸可选 `image_data_uri`，返回框及检测验证状态；新索引持久化连接签名，旧索引在旧连接下兼容。

- [x] 写失败测试：生产/测试配置一致、保存服务切换后的索引失效、重启保护、真实测试图/无图测试、保存云人脸不自动全库任务。
- [x] 实现持久化连接隔离与 gate，切换服务后要求建立新索引；更新全部后台调用链。云人脸测试不要求合成图案必须检出脸。
- [x] 增加当前人脸连接的模型查询，沿用密钥遮罩和错误分类；实现自选测试图及框返回。
- [x] 聚焦与完整 Python 回归 GREEN，再显式提交。

### Task 3: 设置界面与模拟器验收

**Files:** `settings.html`、`state-config.js`、`ai-{similar,faces}-panel.js`、两逻辑文件、五语言 JSON；`tools/generate_patches.py` 与生成补丁。
**Interfaces:** `aiSimilarProvider`、`aiFacesProvider`；人脸厂商预设只填地址/模型，密钥保持独立；测试图只在内存，不保存进配置。

- [x] 写 JS 行为回归确认 RED，覆盖 provider 保存刷新、请求体、草稿隔离、关闭不请求。
- [x] 实现服务选择、地址/模型示例、模型查询和测试图框预览；补齐五语言。
- [x] 两套 Python 全量、所有 JS 语法、补丁回放、JVM/x86_64 Debug 构建。
- [x] 专用模拟器配合本地 HTTP 协议服务，实测服务选择、保存刷新、模型查询、向量测试/索引及人脸图像/框；记录假服务验证的限制。
- [ ] 一次独立全分支代码审阅；修复实质问题并回归，记录结果后交付 Debug APK，不发布。

## Ledger

- 基线 `ff9646d0`：410 passed；原仓库历史诊断保留。使用原仓库测试解释器运行新 worktree 源码。
- 用户已批准推荐范围并明确要求实施；不再追加执行方式确认。
- Ruling：原有服务保存会自动重算人脸，新云模式按批准设计改为显式发起；旧模式兼容。
- Pre-flight：Task 2/3 消费 Task 1 的 provider 和 URL 解析；前端测试及后台必须同时传递，不允许只修设置页。

- Task 1 complete: 6674aa4a; protocol tests RED→GREEN, complete suite 425 passed.
- Task 2 complete: 95b142fd; integration tests RED→GREEN, complete suite 431 passed.
- Task 3 progress: cloud panel behavior and five-language strings; focused suite 39 passed.
- Task 3 regression: invalid legacy URL can be repaired without binding its index to the new connection.

## 验证记录

- Python TUR/Cleanup 各 435 passed；129 个 JS 语法检查通过；456 files 补丁回放一致。
- JVM 测试及 x86_64 Debug 构建通过（2m13s）。
- 专用模拟器：两部影片向量建库完成；切换连接后重启仍要求重建；重建完成后恢复使用。
- 三家人脸预设使用官方协议的本地测试服务验证认证/模型查询；选图后展示检测框；空人脸/拒绝/越界框分别处理；手动重建完成 1/1 部符合筛选规则的影片。
- 限制：无厂商真实凭据，未进行云平台在线计费调用或真实检测准确率验收。
