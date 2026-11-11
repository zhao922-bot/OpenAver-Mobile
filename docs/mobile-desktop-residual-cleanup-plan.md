# OpenAver Mobile 桌面残留清理计划

> 基线：`v0.17.18-android-r55`（commit `f7be117`，versionCode `17073`）
> 目标：清理 Android 包内只服务桌面壳、桌面更新器或开发占位页的功能
> 范围：移动端运行时、路由、页面资源、设置页和共享 JavaScript
> 性质：分阶段执行计划，不在本阶段修改源码
> 状态：已完成（r57）
> 编写日期：2026-11-10

## 0. 摘要

当前手机版没有明显暴露“连接桌面端”“桌面更新器”等菜单入口，但仍有一批桌面端代码存在于 Android 安装包和运行时中。它们主要带来三类成本：

1. App 启动时可能初始化没有意义的桌面更新任务。
2. 手机端无入口的页面、模板、JavaScript、CSS 和 API 仍被打包。
3. 设置页和共享脚本仍解析桌面壳、PyWebView、`local-machine` 分支，增加维护面。

本计划按风险从低到高分为四个阶段：

| 阶段 | 内容 | 主要收益 | 风险 |
| --- | --- | --- | --- |
| A | Android 运行时隔离 | 减少启动后台任务和无意义网络逻辑 | 低 |
| B | 死路由、页面和桌面资源删除 | 减少包体和路由暴露面 | 低到中 |
| C | 设置页和共享 JS 拆分 | 降低前端解析、维护和回归成本 | 中 |
| D | 全量回归、构建和发布验收 | 确认移动端功能无回归 | 低 |

预计 APK 体积收益只有几十 KiB，不是本轮的主要目标。主要收益是减少 Android 运行时无效逻辑、缩小维护范围，并避免未来修改桌面功能时误伤移动端。

## 1. 目标与边界

### 1.1 本计划包含

- Android 启动时不再创建桌面自动更新检查任务。
- 移除手机端没有调用方的桌面更新 API。
- 删除无入口的 `/updater`、`/scraper` 和桌面专用 `/connect` 页面链路。
- 删除桌面帮助页、连接页、更新器占位页及其专属 JS/CSS。
- 删除 `client`、`cf_shell` 等桌面壳路由，保留移动端仍在使用的通用 CF 逻辑。
- 手机端不再加载 `shell-notice`、`shell-reload`、`conn-state` 等桌面壳脚本。
- 拆分或删除设置页的 `local-machine`、`shell-client` 依赖。
- 清理搜索、扫描、片库、设置中的 PyWebView 桌面分支。
- 增加静态守门测试，防止桌面残留重新进入 Android 包。
- 完成模拟器、真实设备和 arm64 构建验收。

### 1.2 本计划不包含

- 不更换 Python、WebView、FastAPI 或 ChaquoPy 架构。
- 不修改数据库结构、NFO 格式、封面和剧照格式。
- 不修改分段视频按逻辑影片计数的规则。
- 不修改翻译、刮削、播放器选择、后台任务保活等移动端核心功能。
- 不删除 `cf.py`、`cf_handoff.py`、`cf_transport.py` 等仍被刮削流程引用的通用 CF 基础设施。
- 不删除 `clipboard.js` 的浏览器剪贴板降级；只清理其 PyWebView 分支。
- 不删除移动端仍需要的 `open-local.js` 浏览器路径复制降级；只清理桌面打开文件夹分支。
- 不清理历史诊断截图、数据库、XML、日志和用户下载文件。
- 不删除多语言 key，除非已有测试证明该 key 在移动端完全不再被引用。

### 1.3 执行约束

| 约束 | 要求 |
| --- | --- |
| 移动端唯一目标 | 本仓库发布的是 Android APK，不再以桌面壳为运行目标 |
| 删除方式 | 先证明无调用方，再删除；不能只按文件名判断 |
| 共享文件 | 必须按函数或条件分支拆分，不能整文件删除 |
| 版本 | 清理完成后再决定 versionCode、versionName 和 tag |
| Git | 禁止 `git add -A`；工作区有大量历史未跟踪文件，只能逐文件暂存 |
| 破坏性命令 | 禁止 `reset --hard`、`checkout --`、强推和 amend |
| Python 补丁 | 修改 `app/src/main/python` 后必须重新生成并校验 patches |
| 发布 | 计划完成和验收通过前不提交发布 tag，不自动上传 GitHub |

## 2. 当前残留清单

### 2.1 运行时和路由

| 区域 | 当前情况 | 处理决定 | 优先级 |
| --- | --- | --- | --- |
| 自动更新任务 | `web/app.py` 在 lifespan 中创建启动检查和周期检查任务 | Android 不创建；桌面更新逻辑不进入移动端运行时 | P0 |
| 手动更新 API | `/api/check-update`、`/api/install-context`、`/api/trigger-update` | 移入桌面专用模块或从 Android 路由中移除 | P0 |
| 更新配置 | `auto_check_update` 和 `last_notified_update_version` | 保留旧配置字段兼容，但 Android 不再读取和写入更新通知状态 | P1 |
| 桌面客户端 API | `web/routers/client.py` | 手机端无调用方，删除路由和文件 | P1 |
| 桌面壳 CF API | `web/routers/cf_shell.py` | 删除；`cf.py` 和 core CF 逻辑保留 | P1 |
| `/connect` | 手机端当前返回 404，但模板、JS、CSS 仍在包内 | 删除路由、模板和专属资源 | P1 |
| `/updater` | 无入口占位页 | 删除路由和模板 | P1 |
| `/scraper` | 无入口占位页 | 删除路由和模板 | P1 |

### 2.2 页面和前端资源

| 区域 | 当前情况 | 处理决定 | 优先级 |
| --- | --- | --- | --- |
| `help.html` | 手机端使用 `help_mobile.html`，桌面帮助页无入口 | 删除 `help.html` 和 `help.js`，只保留移动帮助页 | P1 |
| `connect.html` | 仅桌面壳使用 | 删除模板、连接页 JS 目录和 CSS | P1 |
| `updater.html` | 无入口占位页 | 删除 | P1 |
| `scraper.html` | 无入口占位页 | 删除 | P1 |
| `base.html` 桌面壳脚本 | 所有页面加载 `shell-notice.js`、`shell-reload.js`、`conn-state.js` | 手机端删除加载；对应文件无其他调用后删除 | P1 |
| `base.html` 连接图标 CSS | `.nav-link--conn` 等桌面连接状态样式仍存在 | 与连接页一起删除 | P2 |
| `base.html` import map | `@/connect/` 仍映射到连接页目录 | 删除映射 | P2 |

### 2.3 设置页和共享 JavaScript

| 区域 | 当前情况 | 处理决定 | 优先级 |
| --- | --- | --- | --- |
| 服务器模式 UI | 手机模板已有 `not is_android` 条件隐藏 | 删除手机模板中的桌面分支；后端认证和 server-mode 配置保留 | P1 |
| Windows 长路径帮助 | 手机模板不显示，但文案和结构仍存在 | 删除移动模板中的桌面分支 | P2 |
| 离线 HTML 导出 | 手机端隐藏 | 删除移动模板分支；后端接口暂不因本轮删除 | P2 |
| 桌面播放器路径 | 手机端隐藏 | 删除模板字段和前端表单字段；后端配置字段保留 | P2 |
| Windows 关闭行为 | 手机端隐藏 | 删除模板字段和前端表单字段；后端配置字段保留 | P2 |
| `local-machine.js` | 只服务桌面 client 模式的“这台电脑”设置 | 从设置页依赖树删除，确认无引用后删文件 | P2 |
| `shell-client.js` | 桌面帮助页、设置页和连接页使用 | 删除上述调用方后，确认无引用再删文件 | P2 |
| `state-ui.js` 文件夹选择 | 含 `window.pywebview.api.select_folder()` 分支 | 保留手机文件选择，删除桌面分支 | P2 |
| 搜索文件选择 | `search/main.js`、`state/file-list.js` 含 PyWebView 选择器 | 保留手机文件输入和普通浏览器逻辑，删除桌面桥分支 | P2 |
| 扫描目录选择 | `scanner/state-scan.js` 含 PyWebView 选择器 | 保留 Android SAF/目录选择，删除桌面分支 | P2 |
| 片库播放 | `showcase/state-videos.js` 含 `pywebview.api.open_file()` | 保留内置播放器和 Android 外部播放器逻辑，删除桌面桥分支 | P2 |
| 搜索来源链接 | `search/state/result-card.js` 含 `pywebview.api.open_url()` | 保留 `window.open()`，删除桌面桥分支 | P2 |
| `open-local.js` | 桌面打开文件夹和浏览器复制路径共用 | 保留浏览器复制路径，删除 PyWebView 打开文件夹分支 | P2 |
| `clipboard.js` | PyWebView、Navigator Clipboard、`execCommand` 三层降级 | 保留后两层，删除 PyWebView 分支 | P2 |
| `bridge-notify.js` | PyWebView bridge 返回值和 `handleBridgeUncovered` | 在桌面打开文件/文件夹分支删除后重新检查；无调用方则删除 | P3 |

### 2.4 不应误删的内容

以下内容仍可能被手机端使用，不能在“桌面清理”中直接删除：

- `cf.py`：移动端重抓和来源可用性检查仍会调用 `/api/cf/availability`、`/api/cf/status` 和 `/api/cf/abandon`。
- `cf_handoff.py`、`cf_transport.py`：通用刮削器通过它们判断 CF transport 是否可用。
- `clipboard.js` 的浏览器剪贴板降级：扫描日志、编号下钻和搜索页仍使用。
- `open-local.js` 的普通浏览器路径复制：手机端仍可用于复制文件夹路径。
- 移动端帮助页 `help_mobile.html`。
- Android 原生文件选择、SAF 目录选择、外部播放器和内置播放器逻辑。
- 后端 `server_mode`、访问认证和 loopback 安全逻辑；只删除桌面设置入口，不删除安全实现。

## 3. 阶段总览

| 阶段 | 目标 | 建议提交粒度 | 退出条件 |
| --- | --- | --- | --- |
| A | 阻止桌面更新和桌面壳逻辑进入 Android 运行时 | 1–2 个提交 | Android 启动无桌面更新任务，页面不加载壳脚本 |
| B | 删除无入口路由、页面和桌面专属资源 | 1–2 个提交 | 路由和静态资源守门测试通过 |
| C | 清理设置页和共享 JavaScript 的桌面分支 | 按设置页、文件选择、播放链路拆分 | 手机功能逐项验证，无 PyWebView 误删 |
| D | 全量测试、构建和真机验收 | 不单独混入功能改动 | 两套 Python 测试、JS、patches、模拟器和 arm64 构建通过 |

执行顺序必须是 `A → B → C → D`。A 的风险最低，能先降低运行时行为变化；C 涉及多个共享模块，必须放在路由和资源清理之后，避免同时修改页面加载和功能分支。

## 4. 阶段 A：Android 运行时隔离

### A1. 关闭移动端桌面更新任务

当前 `web/app.py` 的 lifespan 会创建：

- `startup_check_task`
- `periodic_update_check_task`

桌面更新检查访问的是 `slive777/OpenAver` 的桌面 Release，不是本仓库的 Android APK Release。移动端没有必要执行这条链路。

执行要求：

1. 在 lifespan 创建任务前统一判断运行平台。
2. Android 或 `OPENAVER_MOBILE=1` 时不创建启动检查和周期检查任务。
3. 保留配置字段以兼容旧配置文件，但 Android 不根据 `auto_check_update` 触发网络请求。
4. 将 `/api/check-update`、`/api/install-context`、`/api/trigger-update` 从 Android 路由中移除，或移入只在桌面运行环境注册的模块。
5. 不修改移动端 GitHub Release 发布流程；本计划不把桌面更新器改造成 Android 更新器。

验收：

- Android 启动日志中没有更新检查任务。
- Android 启动后没有对 GitHub 更新 API 的请求。
- `/api/check-update`、`/api/install-context`、`/api/trigger-update` 在 Android 上不存在或返回 404。
- 旧配置文件仍能正常启动，不因缺少更新任务报错。

### A2. 移除每页桌面壳脚本

当前 `base.html` 无条件加载：

- `shell-notice.js`
- `shell-reload.js`
- `conn-state.js`

其中 `shell-reload.js` 只在存在 `window.pywebview` 时生效，Android 上没有实际作用。

执行要求：

1. 第一阶段先用 `is_desktop` 条件隔离加载，确认移动页面无依赖。
2. 若确认仓库不再提供桌面壳，再删除这三个脚本和 `base.html` 中的加载语句。
3. 删除连接图标专用 CSS、`@/connect/` import map 和桌面侧栏连接节点。
4. 不删除 `bridge-notify.js`，直到 C 阶段完成桌面打开文件/文件夹分支审计。

验收：

- Android 页面源码中不出现 `shell-notice`、`shell-reload`、`conn-state`。
- 手机侧栏不出现连接入口或连接状态样式。
- 搜索、扫描、片库、Insights、设置和帮助页无 JavaScript 异常。

### A3. 桌面 API 路由隔离

执行要求：

1. 删除 `web/routers/client.py` 的注册。
2. 删除 `web/routers/cf_shell.py` 的注册。
3. 确认 `cf.py` 的 `/api/cf/availability` 等移动端调用仍保留。
4. 检查 `shell_identity` 的其他调用方，避免删除仍被 CF 状态判断使用的函数。
5. 更新 `tools/generate_patches.py` 的文件清单和删除补丁。

验收：

- `/api/client/hello`、`/api/client/token`、`/api/client/sources` 在 Android 上不可用。
- `/api/cf/shell/poll`、`/api/cf/shell/result` 在 Android 上不可用。
- `/api/cf/availability` 仍可由手机端重抓页面调用。
- `cf_handoff` 和刮削器测试不回归。

## 5. 阶段 B：删除无入口页面和资源

### B1. 路由与模板

删除以下页面链路：

- `/updater`：`web/app.py` 路由和 `web/templates/updater.html`
- `/scraper`：`web/app.py` 路由和 `web/templates/scraper.html`
- `/connect`：`web/app.py` 路由、`connect.html`、连接页 JS 和 CSS

要求：

1. 删除路由后，用 `app.routes` 或 HTTP 请求测试确认返回 404。
2. 保留 `/help`，但手机端固定使用 `help_mobile.html`。
3. 删除 `help.html` 和 `help.js`；不删除 `help_mobile.html` 或移动帮助 CSS。
4. 删除 `base.html` 中连接页的 import map、侧栏节点和 CSS。
5. 删除 `tools/generate_patches.py` 中这些文件的旧补丁分组，新增明确的删除补丁。

### B2. 资源清单

预计删除：

| 文件或目录 | 用途 | 处理 |
| --- | --- | --- |
| `web/templates/updater.html` | 无入口占位页 | 删除 |
| `web/templates/scraper.html` | 无入口占位页 | 删除 |
| `web/templates/connect.html` | 桌面连接页 | 删除 |
| `web/static/js/pages/connect/` | 桌面连接页逻辑 | 删除 |
| `web/static/css/pages/connect.css` | 桌面连接页样式 | 删除 |
| `web/templates/help.html` | 桌面帮助页 | 删除 |
| `web/static/js/pages/help.js` | 桌面帮助页逻辑 | 删除 |
| `web/static/js/shared/shell-notice.js` | 桌面壳更新提醒 | 删除 |
| `web/static/js/shared/shell-reload.js` | 桌面壳快捷键 | 删除 |
| `web/static/js/shared/conn-state.js` | 桌面侧栏连接状态 | 删除 |
| `web/routers/client.py` | 桌面 client 握手 | 删除 |
| `web/routers/cf_shell.py` | 桌面壳 CF 工作接口 | 删除 |

验收：

- 手机端不存在上述页面和静态资源。
- 页面加载不再请求这些文件。
- 手机帮助页和 `/api/cf/*` 正常。
- 删除文件均有对应 patch 记录。

## 6. 阶段 C：设置页和共享 JavaScript 清理

### C1. 设置页桌面表单

手机端模板已经使用 `is_android` 条件隐藏部分桌面设置，但前端状态和 JS 仍然存在。

删除或拆分：

- 服务器模式和访问密码的桌面 UI 分支。
- Windows 长路径帮助。
- 离线 HTML 导出设置。
- Windows 关闭行为。
- 桌面播放器路径。
- 服务器模式切换确认框。
- `local_machine_tag()` 和 `local-machine` 状态。

注意：

- 后端 `server_mode`、访问认证、`viewerPlayer` 和 `closeAction` 配置字段先保留，避免破坏旧配置和配置保存接口。
- 手机端保存配置时不能因为前端字段消失而清空这些字段。
- 四语言 key 暂不删除，先保留兼容性和上游 patch 稳定性。

### C2. 设置页 JS 依赖拆分

当前 `state-config.js` 无条件导入：

- `@/shared/shell-client.js`
- `@/settings/local-machine.js`

执行要求：

1. 删除手机端不用的 `resolveLocalMachine`、`localDiff`、`mergeLocalIntoForm` 等桌面分支。
2. 保留手机端仍在使用的 `applyServerLocalFields` 前先审计其调用方；若只服务桌面，再删除。
3. 把仍需要的通用函数移到 `state-config.js` 或移动端专用模块。
4. `shell-client.js` 和 `local-machine.js` 只有在 `rg` 确认没有其他移动端调用后才能删除。
5. 检查设置页所有 `x-data` 方法，确保删除字段后没有模板继续引用。

验收：

- 手机设置页无 `shellMode`、`localMachineState` 和桌面壳调用。
- 设置页无 PyWebView 相关网络请求或异常。
- 保存主题、语言、字体、扫描目录、翻译服务、刮削来源和数据库备份恢复正常。

### C3. 文件选择和播放分支

按文件处理，不做整目录删除：

| 文件 | 保留 | 删除 |
| --- | --- | --- |
| `search/main.js` | 浏览器文件输入、手机文件列表 | `pywebview-files` 监听和桥接选择 |
| `search/state/file-list.js` | 手机文件/文件夹选择 | `window.pywebview.api.select_files/select_folder` |
| `scanner/state-scan.js` | Android SAF/普通文件夹选择 | PyWebView 文件夹选择和桥接拖放 |
| `settings/state-ui.js` | 手机目录选择 | `pywebview.api.select_folder()` |
| `showcase/state-videos.js` | 内置播放器、Android 外部播放器、普通浏览器播放 | `pywebview.api.open_file()` |
| `search/state/result-card.js` | `window.open()` 打开来源链接 | `pywebview.api.open_url()` |
| `shared/open-local.js` | 浏览器复制路径 | `pywebview.api.open_folder()` |
| `shared/clipboard.js` | Navigator Clipboard、`execCommand` | `pywebview.api.copy_text()` |
| `shared/bridge-notify.js` | 先审计是否有手机端调用 | 无调用方时删除 |

验收：

- 搜索页可以从手机文件选择器加入视频。
- 扫描页可以选择目录并开始扫描。
- 设置页可以选择输出目录。
- 片库普通视频和分段视频均可播放，内置/外部播放器选择正常。
- 搜索来源链接可以打开。
- 复制路径、复制日志和编号下钻正常。

### C4. 共享模块收口

完成 C1–C3 后运行：

```bash
rg -n "pywebview|shell-client|local-machine|shell-notice|shell-reload|conn-state" \
  app/src/main/python/web app/src/main/java tests
```

只允许保留以下类型的结果：

- Android 原生桥接相关代码。
- 移动端仍需要的浏览器降级逻辑。
- 测试中用于防止桌面残留回归的断言。
- 与 CF 状态判断无关的通用 core 代码。

任何仍出现的 `window.pywebview` 都必须有明确的移动端保留理由，否则删除或改写为普通浏览器路径。

## 7. 阶段 D：测试、构建和验收

### D1. 自动化测试

必须执行两套 Python 测试：

```powershell
app\build\tur-pydantic-venv\Scripts\python.exe -m pytest tests\ -q
app\build\python\env\cleanup\Scripts\python.exe -m pytest tests\ -q
```

必须执行 JavaScript 语法检查：

```powershell
Get-ChildItem app\src\main\python\web\static\js -Recurse -Filter *.js |
  ForEach-Object { node --check $_.FullName }
```

修改 Python 后必须执行：

```powershell
app\build\python\env\cleanup\Scripts\python.exe tools\generate_patches.py `
  --upstream-root '..\openaver-upstream-v0.17.18' `
  --source-root 'app/src/main/python' `
  --output-dir 'patches'

app\build\python\env\cleanup\Scripts\python.exe tools\verify_python_sync.py `
  --upstream-root '..\openaver-upstream-v0.17.18' `
  --source-root 'app/src/main/python'
```

### D2. 静态守门测试

在 `tests/test_mobile_shell_cleanup.py` 增加：

1. Android 不注册 `client` 和 `cf_shell` 路由。
2. Android 不加载 `shell-notice`、`shell-reload`、`conn-state`。
3. `/updater`、`/scraper`、`/connect` 不再出现在 Android 路由。
4. `base.html` 不再包含连接页 import map 和连接图标。
5. 手机设置页不再引用 `local-machine.js` 或 `shell-client.js`。
6. 允许的 `pywebview` 残留必须是明确白名单。
7. 删除的模板、JS、CSS 文件不得被 patch 生成器重新加入。
8. 现有演示页、演示图片和 design-system 清理测试继续通过。

### D3. 模拟器验证

仅使用 `emulator-5554`，依次检查：

- 冷启动到扫描页。
- 搜索页文件选择、搜索、来源链接打开。
- 扫描页目录选择、扫描、补标题、补剧照。
- 片库首屏、分页、筛选、普通视频播放、分段视频播放。
- 设置页主题、语言、字体、翻译服务、刮削来源、数据库导出和导入。
- 帮助页。
- Insights 图表。
- 四语言切换后的菜单、日志和提示。
- 返回键、离开确认和前台任务通知。

### D4. 真实设备验证

真实设备只做与桌面分支直接相关的冒烟测试：

- 文件选择。
- 文件夹选择。
- 普通视频内置/外部播放器选择。
- 分段视频内置/外部播放器选择。
- 复制路径。
- 设置页保存和重新进入。

未获授权时不得操作真实设备；模拟器结果不能替代文件权限、SAF 和外部存储的最终判断。

### D5. 构建

构建环境：

```powershell
Set-Item Env:JAVA_HOME 'C:\Program Files\Android\Android Studio\jbr'
Set-Item Env:OPENAVER_BUILD_PYTHON 'C:\Users\14052\AppData\Local\Programs\Python\Python313-full\tools\python.exe'
```

开发验证：

```powershell
.\gradlew.bat --no-daemon --console=plain testDebugUnitTest assembleDebug -Pabi=x86_64
```

发布验证：

```powershell
.\gradlew.bat --no-daemon --console=plain testDebugUnitTest assembleDebug assembleRelease -Pabi=arm64-v8a
```

构建后记录：

- APK 路径和 SHA-256。
- APK 总大小。
- APK 内 `assets`、`lib`、DEX 和 resources 大小。
- 冷启动时间。
- 设置页、扫描页和片库首屏的加载时间。

## 8. 风险与控制

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| 删除设置字段导致保存时清空旧配置 | 用户播放器、关闭行为或服务器设置丢失 | 后端字段保留，前端删除前检查 PUT 合并语义 |
| 误删共享 CF 代码 | Jable、JavLibrary 等来源状态判断回归 | 只删除 `cf_shell`，保留 `cf.py`、`cf_handoff`、`cf_transport` |
| 误删 PyWebView 文件中的手机分支 | 搜索、扫描或设置无法选择文件 | 逐文件拆分，先加静态测试，再删除桌面分支 |
| 删除桌面帮助页影响 `/help` | 手机帮助页打不开 | `/help` 固定使用 `help_mobile.html`，单独验证 |
| 删除更新 API 影响未来升级 | 以后需要重新设计 Android 更新器 | 本计划只移除错误复用的桌面上游更新链路，不影响 GitHub Release |
| patch 生成遗漏删除文件 | APK 仍携带旧资源 | 每个删除文件写入 patch 组并运行 `verify_python_sync.py` |
| 一次提交过多导致无法回滚 | 回归定位困难 | A、B、C 分开提交，设置页和文件选择分支再细分 |

## 9. 验收清单

- [ ] Android 启动时没有桌面更新检查任务。
- [ ] Android 没有对桌面 GitHub Release 的自动请求。
- [ ] `/api/check-update`、`/api/install-context`、`/api/trigger-update` 在 Android 上不可用。
- [ ] `client`、`cf_shell` 路由不可用。
- [ ] `/connect`、`/updater`、`/scraper` 返回 404。
- [ ] 桌面帮助页、连接页和更新器占位页资源不再打包。
- [ ] Android 页面不加载桌面壳脚本。
- [ ] 手机设置页不依赖 `shell-client.js` 或 `local-machine.js`。
- [ ] 搜索、扫描、设置、片库中的桌面 PyWebView 分支已删除或列入白名单。
- [ ] 手机文件选择、文件夹选择、内置播放器、外部播放器、复制路径正常。
- [ ] 扫描、补标题、补剧照、翻译、NFO、片库、Insights 和四语言正常。
- [ ] 两套 Python 全量测试通过。
- [ ] 所有 JavaScript 通过 `node --check`。
- [ ] patches 已重新生成并通过同步校验。
- [ ] `emulator-5554` 完成冒烟验证。
- [ ] arm64 Debug 和 Release 构建成功。
- [ ] 记录 APK 大小、启动时间和关键页面性能变化。
- [ ] 确认没有修改用户数据库、NFO 和目录结构。
- [ ] 由维护者决定版本号、tag 和 GitHub Release。

## 10. 执行记录

每个阶段完成后在此追加记录，不覆盖旧数据。

| 日期 | 阶段 | commit | 构建/测试 | 结果 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-10 | 计划建立 | `f7be117` | 未执行 | 待开始 | 基线 r55 |
| 2026-11-11 | A–C 源码清理 | r57 | TUR / Cleanup 两套全量测试通过 | 完成 | 桌面更新任务、页面、路由、壳脚本、设置分支和 PyWebView 分支已移除 |
| 2026-11-11 | D 模拟器验收 | r57 | x86_64 Debug / arm64 Release | 通过 | 六页与四语言巡检、扫描生成、普通播放器选择、CF worker、复制路径、冷启动通过 |
