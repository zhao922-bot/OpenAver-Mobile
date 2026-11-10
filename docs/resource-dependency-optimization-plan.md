# OpenAver Mobile 资源与依赖优化指导方案

> 基线：`v0.17.18-android-r55`（versionCode `17073`）
> 当前 APK：约 28.74 MiB（30,136,752 bytes）
> 性质：分阶段优化指导，不改变 Python/WebView 总体架构
> 状态：A0–D4 已完成；r56 发布
> 编写日期：2026-11-10

## 0. 目标与原则

本方案只解决两类问题：

1. 减少 APK 中不必要的静态资源和重复资源。
2. 在不破坏刮削、翻译、文件管理和多语言功能的前提下，评估可移除的 Python 依赖。

执行原则：

1. **先测量，再修改**。每一阶段都必须记录修改前后的 APK 大小、冷启动、内存和关键页面表现。
2. **低风险优先**。先处理图片、字体和前端图表，最后才评估 Python 依赖。
3. **一次只改一类**。资源转换、ECharts 裁剪和 Python 依赖替换必须分开提交，避免无法定位回归。
4. **不凭引用搜索删除功能**。删除文件前必须同时检查模板、JavaScript、Python、测试和运行时动态路径。
5. **不以体积为由改架构**。本方案不包含 Kotlin 重写、Flutter 迁移或 Python 运行时替换。
6. **不自动发布**。每个阶段完成并通过验收后，再由维护者决定版本号和发布方式。

## 1. 范围

### 1.1 本方案包含

- 静态图片压缩和格式转换。
- 重复字体资源清理。
- ECharts 按需构建。
- 可选的发布构建 JS/CSS 压缩。
- `lxml` 单依赖替换实验。
- release 构建和真实设备回归验证。
- APK、启动、内存和片库滚动性能对比。

### 1.2 本方案不包含

- 不换 Kotlin、Flutter、React Native 或 Go/Rust。
- 不删除 `Pydantic`、`Pillow`、`FastAPI`、`Starlette`、`Uvicorn`、`Jinja2`。
- 不强行合并 `requests` 和 `httpx`。
- 不裁剪 Python 标准库中的模块。
- 不改变数据库结构、NFO 格式、剧照格式或多分段视频规则。
- 不修改用户配置文件、缓存目录和扫描目录布局。
- 不清理工作区中的历史诊断文件。

## 2. r55 基线

以下数据用于阶段验收，不应在没有重新测量的情况下直接当作当前版本数据。

| 项目 | r55 实测 |
| --- | ---: |
| Release APK | 28.74 MiB / 30,136,752 bytes |
| APK 内 `assets` | 24.00 MiB compressed |
| APK 内原生库 | 4.54 MiB compressed / 12.61 MiB uncompressed |
| DEX | 0.14 MiB |
| Android resources | 0.01 MiB |
| `requirements-common.imy` | 9.15 MiB compressed |
| `app.imy` | 8.02 MiB compressed |
| `stdlib-common.imy` | 4.13 MiB compressed |
| `stdlib-arm64-v8a.imy` | 1.37 MiB compressed |
| 静态 JPEG | 30 张，约 3.44 MiB |
| ECharts 完整包 | 约 1.07 MiB |
| Bootstrap Icons | WOFF 172 KiB + WOFF2 127.5 KiB |

主要 Python 依赖的解压体积：

| 依赖 | 解压体积 | 当前结论 |
| --- | ---: | --- |
| `pydantic_core` | 4.57 MiB | 暂不替换 |
| `lxml` | 4.15 MiB | 唯一优先评估项 |
| ChaquoPy 支持包 | 3.93 MiB | 架构依赖，暂不处理 |
| `Pillow` | 1.80 MiB | 核心图片能力，保留 |
| `pydantic` | 1.78 MiB | 使用面广，暂不替换 |

## 3. 阶段总览

| 阶段 | 内容 | 预计收益 | 风险 | 建议顺序 |
| --- | --- | ---: | --- | --- |
| A | 图片、字体、ECharts、前端资源 | 3–5 MiB | 低到中低 | 立即执行 |
| B | 评估并移除 `lxml` | 1–2 MiB | 中 | A 验收后执行 |
| C | release 构建、R8、ABI 和运行时检查 | 0–1 MiB | 低到中 | 与 A/B 分开验证 |
| D | 全功能回归和性能验收 | 不直接减包 | 低 | 每个发布批次执行 |

预计收益是优化目标，不是承诺值；必须以实际构建结果为准。

### 3.1 执行看板

- [x] A0：记录 r55 的 APK、启动、内存和片库性能基线。
- [x] A1：移除仅用于演示的页面、脚本和静态图片。
- [x] A2：删除重复的 Bootstrap Icons WOFF 字体。
- [x] A3：将 ECharts 改为按需构建。
- [x] A4：评估 release 构建的 JS/CSS 压缩。
- [x] A5：完成阶段 A 的体积、页面和功能验收。
- [x] B1：为各 `lxml` 解析入口准备固定 HTML 样本。
- [x] B2：逐个来源替换并验证 `lxml`。
- [x] B3：确认运行时不再引用 `lxml` 后删除依赖。
- [x] B4：完成自定义来源和全部刮削器回归。
- [x] C1：评估 release 的 R8 和资源压缩。
- [x] C2：确认 ABI、语言资源和 Python 归档没有重复。
- [x] C3：记录 APK、安装占用、冷启动、内存和滚动数据。
- [x] D1：通过 TUR、Cleanup 和 JavaScript 检查。
- [x] D2：完成四语言、扫描、播放、翻译、NFO、剧集和后台任务回归。
- [x] D3：完成模拟器与真实设备验证。
- [x] D4：确认是否达到发布条件，并由维护者决定版本号。

## 4. 阶段 A：低风险资源优化

### A0. 建立基线

先保存以下数据：

- APK 文件大小和 SHA-256。
- APK 内 `assets`、`lib`、DEX、resources 的分类体积。
- Insights 页面首次打开时间。
- 片库首屏加载时间。
- 5000 部以上影片的滚动流畅度。
- App 冷启动和前台进程内存。

建议将每次结果追加到本文件末尾的“执行记录”表。

### A1. 移除演示子系统与静态图片

这些资源只服务于开发期的 `/motion-lab` 和 `/design-system` 演示页，普通用户入口不会使用：

- `app/src/main/python/web/static/img/showcase/`
- `app/src/main/python/web/static/img/picker-demo/`
- `app/src/main/python/web/static/img/demo/`
- `web/templates/motion_lab.html`
- `web/templates/design-system.html`
- `web/templates/design_system/`
- `web/static/css/pages/design-system.css`
- `web/static/js/pages/motion-lab*.js`
- `web/static/js/pages/motion-lab/`
- `web/routers/motion_lab.py`

当前约 30 张 JPEG，总计约 3.44 MiB。

执行要求：

1. 删除 `/motion-lab` 和 `/design-system` 的页面、路由、专属 CSS/JS 与图片。
2. 保留仍被片库、搜索、扫描和 Insights 使用的共享动画组件，不能按文件名误删。
3. 清理 `base.html` 中只为演示页加载的重型 GSAP 插件和组件开关。
4. 新增测试，防止演示路由、模板、脚本和图片目录重新进入安装包。
5. 在模拟器逐一打开扫描、片库、搜索、Insights 和设置页，确认生产功能正常。

验收：

- `/motion-lab` 和 `/design-system` 返回 404。
- 生产页面无资源 404、白屏或 JavaScript 异常。
- 三个演示图片目录中的静态 JPEG 数量为 0。
- 静态图片总体积从约 3.44 MiB 降至 0。
- 预计 APK 减少约 2–3 MiB。

### A2. 清理重复字体格式

相关文件：

- `app/src/main/python/web/static/vendor/bootstrap-icons/bootstrap-icons.css`
- `app/src/main/python/web/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff`
- `app/src/main/python/web/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2`

执行要求：

1. 确认目标 WebView 最低版本支持 WOFF2。
2. 删除 CSS 中的 WOFF 回退，只保留 WOFF2。
3. 删除未使用的 WOFF 文件。
4. 更新 vendor manifest 或校验记录，避免下次同步时重新引入。

验收：

- 设置页、片库、扫描页和菜单中的 Bootstrap 图标全部正常显示。
- 预计减少约 0.15–0.17 MiB。

### A3. ECharts 按需构建

当前完整包：

- `web/static/vendor/echarts/echarts.min.js`
- 约 1.07 MiB
- 仅由 `web/templates/insights.html` 引入

Insights 当前使用的图表类型至少包括：

- 柱状图：`bar`
- 饼图：`pie`
- 矩形树图：`treemap`

执行要求：

1. 使用 `echarts/core`，不要继续打包完整 `echarts.min.js`。
2. 注册实际使用的渲染器和组件，例如：

   - `CanvasRenderer`
   - `BarChart`
   - `PieChart`
   - `TreemapChart`
   - Tooltip、Grid、Legend、Graphic 等实际用到的组件

3. 检查 `web/static/js/pages/insights/charts.js` 中的 `graphic`、点击、缩放、动画和 `setOption` 行为，避免裁掉运行时需要的组件。
4. 保持 `/insights` 页面按需加载，不要放进 `base.html` 的全局脚本。
5. 记录 ECharts 上游版本和自定义构建配置，方便后续升级。

验收：

- Insights 所有图表正常渲染、动画和点击筛选正常。
- 浏览器控制台没有缺少组件或未知组件的警告。
- ECharts 资源体积至少下降 45%。当前完整保留 `UniversalTransition`、`LabelLayout`、`MarkLine` 等交互能力后，实测从 1,121,883 降至 600,580 字节，下降 46.5%；不能为了达到 50% 而删除实际使用的功能模块。
- APK 预计减少约 0.15 MiB；当前 arm64 Release 实测减少 166,624 字节。

### A4. 可选的发布版 JS/CSS 压缩

这一项放在 A1–A3 之后，不作为第一阶段必做项。

执行要求：

1. 不修改开发环境源码，只对 release 产物或发布目录做压缩。
2. 保留 source map 或原始文件用于排查问题。
3. 检查 `tailwind.css` 是否已经清除了未使用的样式。
4. 对 Alpine、GSAP、Bootstrap Icons 等 vendor 文件确认没有重复加载。

验收：

- 页面无样式错乱、脚本执行错误或缓存版本冲突。
- 预计减少约 0.3–0.8 MiB；如果收益低于 0.2 MiB，应放弃，避免增加构建复杂度。

本次执行结果（2026-11-10）：

- 新增仅 Release 生效的 `minifyReleaseWebAssets` Gradle 任务，压缩
  `app.imy` 中 146 个自研 JS/CSS；`web/static/vendor` 和仓库源码不改写。
- `app.imy` 从 4,329,692 降至约 3,852,697 bytes，减少约 0.455 MiB。
- arm64 Release APK 从 26,045,976 降至 25,570,372 bytes，再减少
  475,604 bytes；收益高于 0.2 MiB 门槛。
- 固定版本 ESBuild 由 `npm ci --prefix tools/echarts-build` 安装，并已接入
  Build/Publish 两个 GitHub Actions 工作流。

### A5. 阶段 A 退出条件

- 静态资源总计减少至少 2 MiB。
- APK 总计减少至少 3 MiB，且不出现功能回归。
- 四语言界面、Insights、片库、扫描页和设置页完成目视检查。
- A1、A2、A3 分别形成独立提交；不要与 Python 依赖修改混在一起。

本次验收结果：

- 静态图片从约 3.44 MiB 降至 0；ECharts 从 1,121,883 降至 600,580 bytes。
- arm64 Release APK 从 30,136,752 降至 25,570,372 bytes，累计减少
  4,566,380 bytes（约 4.35 MiB）。
- `zh-CN`、`zh-TW`、`ja`、`en` 的扫描页、片库、Insights 和设置页均已
  在 API 36 模拟器检查；简繁字形审计和英文中文泄漏审计均通过。
- 修复日文扫描页长“読み取り専用”标签挤压文件夹路径、路径逐字竖排以及
  生成按钮裁切的问题；Android 端路径改为独立一行并保持省略号截断。

## 5. 阶段 B：`lxml` 单依赖实验

### B1. 为什么先选 `lxml`

`lxml` 解压后约 4.15 MiB，是当前最有收益且使用面相对集中的依赖。

当前至少涉及以下文件：

- `app/src/main/python/core/scrapers/dmm.py`
- `app/src/main/python/core/scrapers/fc2_official.py`
- `app/src/main/python/core/scrapers/fc2_javten.py`
- `app/src/main/python/core/scrapers/heyzo.py`
- `app/src/main/python/core/custom_source/extract.py`

其中 `custom_source/extract.py` 使用 `BeautifulSoup(html, "lxml")`，不能只检查 `from lxml`。

### B2. 替换顺序

一次只替换一个来源，顺序建议：

1. `fc2_official.py`
2. `fc2_javten.py`
3. `heyzo.py`
4. `dmm.py`
5. `custom_source/extract.py`

每完成一个来源：

1. 保存该来源的真实或固定 HTML 样本。
2. 对比旧解析器和新解析器得到的番号、标题、女优、标签、日期、封面和剧照。
3. 运行该来源相关测试。
4. 在模拟器或真实设备上完成一次搜索、预览和写入。
5. 通过后再处理下一个来源。

### B3. 替换要求

- 优先使用标准库 `html.parser` 或现有 `BeautifulSoup` 解析器。
- 不改变选择器和业务字段，只改变解析实现。
- 不把解析失败静默成“无结果”；必须保留可诊断错误。
- 自定义来源 YAML 的解析规则和错误码不得变化。
- 在全部来源通过前，保留 `lxml` 依赖。
- 全部通过后使用 `rg` 确认运行时不再引用 `lxml`，再删除依赖。

### B4. 阶段 B 退出条件

- 五个解析入口全部通过固定样本和线上真实请求验证。
- 自定义来源导入、搜索和预览正常。
- 四语言下错误提示和空结果提示正常。
- `requirements-common.imy` 中不再包含 `lxml`。
- 预计 APK 再减少约 1–2 MiB。

如果任一来源出现字段漂移，立即恢复该来源的 `lxml` 实现；不要为了减包牺牲刮削正确性。

## 6. 阶段 C：构建和运行时优化

### C1. R8 和资源压缩

可以在 release 构建中评估：

```groovy
minifyEnabled true
shrinkResources true
```

注意：

- 当前 DEX 只有约 0.14 MiB，R8 对总包体帮助有限。
- 先配置 keep 规则，再验证 WebView JavaScript bridge、反射和动态资源。
- 如果收益低于 0.2 MiB，优先保持构建稳定性。

### C2. ABI 和语言资源

- 当前已经只发布 `arm64-v8a`，不要增加多 ABI。
- 不建议为四种语言拆分 APK；语言 JSON 合计体积很小，拆分收益不足。
- 不删除 Android 原生语言资源，四语言切换和原生菜单仍需回归。

### C3. Python 标准库和 `pyc`

本阶段暂不裁剪 Python 标准库。

原因是：

- 标准库模块之间存在隐式依赖。
- `unittest`、`pdb`、`doctest` 等模块体积不大，错误裁剪的收益低、风险高。
- 当前 `app.imy` 已处于压缩归档中，普通 ZIP 二次压缩不会产生明显收益。

只有在 A/B 完成后仍有明确体积目标，才单独评估 ChaquoPy 的 `exclude` 或 `pyc` 配置，并做完整启动回归。

### C4. 运行时指标

每个阶段至少记录：

- APK 下载大小。
- 安装后占用空间。
- 冷启动时间。
- 首次进入片库时间。
- Insights 首次渲染时间。
- 5000 部以上影片滚动时的卡顿和内存。
- 扫描 5000 个文件时的耗时。

阶段 A 或 B 完成后，如果 APK 明显变小但启动或滚动变差，应暂停后续优化并回滚该批改动。

## 7. 阶段 D：完整回归

### D1. 自动化测试

当前环境可使用：

```powershell
app\build\tur-pydantic-venv\Scripts\python.exe -m pytest tests\ -q
app\build\python\env\cleanup\Scripts\python.exe -m pytest tests\ -q
```

前端 JavaScript 检查：

```powershell
Get-ChildItem app\src\main\python\web\static\js -Recurse -Filter *.js |
  ForEach-Object { node --check $_.FullName }
```

如果修改了 `app/src/main/python`，还需要重新生成并校验 patches：

```powershell
app\build\python\env\cleanup\Scripts\python.exe tools\generate_patches.py `
  --upstream-root '../openaver-upstream-v0.17.18' `
  --source-root 'app/src/main/python' `
  --output-dir 'patches'

app\build\python\env\cleanup\Scripts\python.exe tools\verify_python_sync.py `
  --upstream-root '../openaver-upstream-v0.17.18' `
  --source-root 'app/src/main/python'
```

### D2. 功能回归

必须覆盖：

- 简体中文、繁体中文、日文、英文四种界面。
- 扫描、浏览、搜索、筛选和封面展示。
- 多分段视频按一个逻辑视频显示。
- 内置播放器和外部播放器选择。
- 标题翻译、失败提示和日志。
- 剧照补充、缺失检查和 NFO 写入。
- 统一命名、数据库标题和 NFO 同步。
- Jable 及其他来源的搜索、标签更新和 Cloudflare 验证。
- 数据库导出、导入和失败回滚。
- 后台任务通知和任务保活。
- 设置保存、重启恢复和缓存清理。

### D3. 设备验证

至少使用一个 API 36 模拟器和一个已授权真实设备：

- 模拟器用于可重复的 UI 和日志检查。
- 真实设备用于 SD 卡路径、长时间后台任务和实际播放。
- 不要在未经授权的情况下操作其他设备。

本次验收结果（2026-11-10）：

- API 36 模拟器冷启动 `4,236 ms`；扫描、浏览、搜索、Insights、设置五个页面均正常渲染，片库保持 `ABC-123`（cd1/cd2 合并且显示一个逻辑视频）和 `XYZ-456` 两部。
- 真实设备 `901LGaff7f7de`（API 29）使用 3 秒 H.264 测试视频验证普通视频播放器选择；选择“使用内置播放器”后成功播放至 `0:03 / 0:03`。
- 真实设备启动 21 项补齐字段后台任务后按 HOME；隐藏 WebView 计数从 `0` 增至 `8`（约 9 秒），随后继续增至 `49`；`TaskKeepAliveService` 保持 `isForeground=true`，通知显示“OpenAver 正在处理任务”。
- 取消后台任务后 Service 正常停止；测试用 Debug 数据库、配置和外部存储测试目录均已恢复/删除，未改动 Release 包数据。
- 最终 arm64 Release 为 `23,278,068 bytes / 22.20 MiB`，SHA-256 `6AB087D6538023259A5859BD88503AB2B377429865F1F5017AB41C4C1A63E651`，仅含 `arm64-v8a`。

### D4. 发布条件

- 自动化测试全部通过。
- JS 语法检查全部通过。
- Python patch 同步校验通过。
- 目标 APK 比 r55 至少减少 3 MiB，或明确记录未达到目标的原因。
- 关键页面无白屏、无资源 404、无新增崩溃。
- 冷启动和片库滚动没有明显退化。
- 维护者明确决定版本号和是否发布。

本次技术审计（2026-11-10）：

- TUR `278 passed`，Cleanup `278 passed`；116 个 App JavaScript 文件 `node --check` 全部通过。
- 重新生成 12 个 Python 补丁，`verify_python_sync` 输出 `412 files match upstream + patches`。
- 最终 arm64 Release 为 `23,278,068 bytes`，较 r55 基线 `30,136,752 bytes` 减少 `6,858,684 bytes`（`22.76%`），满足至少减少 3 MiB 的目标。
- API 36 五页巡检未捕获 JavaScript 异常、HTTP 4xx/5xx 或控制台错误；可见区域没有破图，Insights 图表 canvas 正常生成。
- 残余风险：5000 部片库滚动仍为 `37 帧/5.1s`、`p95 216.7ms`，不能据此宣称滚动性能已优化；本计划只记录基线，未把滚动优化纳入本次范围。
- 维护者已确认发布 `0.17.18-r56`（versionCode `17074`），发布动作由 GitHub Actions 完成。
- 发布结果：GitHub Actions run `42851967230` 成功，Release
  `v0.17.18-android-r56` 已上传签名 APK；版本 `0.17.18-r56` / versionCode
  `17074`，仅 `arm64-v8a`，v3 签名验证通过。
- 发布包：`openaver-v0.17.18-android-r56-arm64-v8a.apk`，`23,284,612 bytes`，
  SHA-256 `7456841B1C5F312CC4E03837792C382F62C61F16D57BDD5AAE93404E16CF7434`。

## 8. 推荐提交拆分

每个提交只包含一类改动：

| 提交 | 内容 | 依赖 |
| --- | --- | --- |
| A1 | 移除演示页面、脚本和静态图片 | 无 |
| A2 | 删除重复 WOFF | 无 |
| A3 | ECharts 按需构建 | 无 |
| A4 | release JS/CSS 压缩（可选） | A1–A3 |
| B1 | 单个来源移除 `lxml` | A 验收后 |
| B2 | 其余来源和依赖删除 | B1 全部通过后 |
| C1 | R8/构建配置实验 | A/B 完成后 |
| D1 | 回归脚本和结果记录 | 每个阶段 |

不要使用 `git add -A`。工作区可能存在历史诊断文件，只能显式添加本次修改的源码、测试、文档和构建配置。

## 9. 风险与回滚

| 风险 | 处理方式 |
| --- | --- |
| 误删生产页面共用的动画资源 | 仅删除演示入口专属文件；保留共享组件并跑页面回归 |
| ECharts 缺少组件 | 恢复完整 ECharts，单独修组件注册 |
| 字体图标不显示 | 恢复 WOFF 回退并重新检查 CSS |
| 刮削器字段漂移 | 该来源恢复 `lxml`，不继续删依赖 |
| 自定义来源解析失败 | 保留旧解析器作为后备 |
| APK 变小但启动变慢 | 回滚该批改动，优先性能 |
| 发布回归 | 使用上一版 APK，按提交逐批回退 |

禁止使用 `git reset --hard`、`git checkout --`、强推或 amend 来掩盖优化问题。

## 10. 执行记录

复制下面表格到每个阶段的提交说明或验收记录中：

| 检查项 | 修改前 | 修改后 | 结论 |
| --- | ---: | ---: | --- |
| APK bytes | 30,136,752 | 23,284,612 | 签名发布包减少 6,852,140 bytes（22.74%） |
| `assets` compressed | 25,161,857 | 18,311,143 | 减少 6,850,714 bytes |
| `lib` compressed | 4,764,779 | 4,764,783 | 基本不变 |
| 静态图片总量 | 3,606,239 | 0 | 演示图片已移除 |
| ECharts 体积 | 1,121,883 | 600,580 | 下降 46.5% |
| `requirements-common.imy` | 9,599,673 | 7,306,096 | 移除 `lxml` 依赖 |
| 冷启动 | 13,209 ms | 7,148 ms | API 36 最终复测 4,236 ms |
| 片库首屏 | 未记录 | 4,370 ms | 5000 行数据场景 |
| 5000 部滚动 | 未记录 | 37 帧/5.1s，p95 216.7ms | 仍有卡顿，记录为残余风险 |
| 扫描耗时 | 未记录 | 约 1 文件/秒 | 5000 文件场景未跑完 |
| 测试结果 | 266 | 278 | TUR 278 / Cleanup 278 全部通过 |
| 四语言回归 | 未记录 | 四语言五页面通过 | 简繁日英均正常 |

## 11. 最终建议

优先完成阶段 A，不要先动 Python 依赖。移除无用演示资源和优化 ECharts 的收益明确、可回滚，并且不会改变生产业务逻辑。

阶段 B 只做一个 `lxml` 实验；如果收益不足或刮削稳定性下降，保留 `lxml`，停止依赖裁剪。

阶段 C 的 R8 和标准库裁剪收益有限，不应成为主要目标。真正影响长期体验的是缓存、缩略图并发、文件扫描和 WebView 内存，这些问题应另立性能计划处理。
