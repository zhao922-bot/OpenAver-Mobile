# OpenAver Mobile

[![Build APK](https://github.com/zhao922-bot/OpenAver-Mobile/actions/workflows/build.yml/badge.svg)](https://github.com/zhao922-bot/OpenAver-Mobile/actions/workflows/build.yml)

OpenAver Mobile 是 [OpenAver](https://github.com/slive777/OpenAver) 的非官方
Android 移植版，基于上游最新正式版 `v0.17.18`
（提交 `af0d99741e63e71980773c9ade04c473407a60b7`）。

App 在手机内嵌 Python 3.13、FastAPI、Uvicorn 和 OpenAver Web 服务，不需要
电脑、NAS、局域网服务器或 Termux。扫描、数据库、元数据搜索、NFO/封面写入和
视频播放均由手机本地执行；视频保留在手机原目录。

## 下载

- [发布页](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest)
- [直接下载 arm64-v8a APK](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest/download/openaver-v0.17.18-arm64-r12-focal-fix.apk)

当前发布包：

- 文件名：`openaver-v0.17.18-arm64-r12-focal-fix.apk`
- 包名：`dev.openaver.mobile`
- 版本：`0.17.18-r12`（versionCode `17028`）
- 架构：仅 `arm64-v8a`
- 最低系统：Android 10（API 29）
- 目标系统：Android 10（API 29）；使用传统外部存储权限以兼容外置 SD 卡写入
- SHA-256：
  `15CBB5F2410725F51ED9B8F726D81AA262A94F5C8BEA73F0C650A9DA211572D1`

## 安装

1. 在 64 位 ARM Android 10+ 手机上打开 APK，并允许安装未知应用。
2. Android 11+：授予“所有文件访问权限”。
3. Android 10：授予读取和写入手机存储权限。
4. 将外置 SD 卡或不可写入的视频目录设为“只读”；OpenAver 会把生成的元数据
   放入应用私有媒体库。
5. 进入“列表生成”，点击文件夹按钮。
6. 从 `/storage/emulated/0` 或 SD 卡选择视频目录并生成列表。

如果系统没有直接显示权限页，请手动进入：

`设置 → 应用 → OpenAver 移动版 → 权限`

## 已实现

- 完全本地运行的 Python/FastAPI 服务，仅监听 `127.0.0.1` 的本机端口（优先 8765，占用时自动切换）
- 使用真实文件路径扫描手机内部存储和 SD 卡视频
- SQLite 片库、列表生成、扫描结果持久化
- 元数据搜索、NFO 与封面读取/写入、文件重命名
- 本机 HTTP Range 视频服务，支持播放器拖动进度
- JavLibrary Android WebView Cloudflare 验证窗口
- FC2-javten 复用 Cloudflare WebView 验证通路
- JavDB `curl_cffi` 缺失时的网页 `requests` fallback
- AVBase 女优资料 `requests` fallback 和 UTF-8 修复
- 自定义来源 `fetch: cf` 的普通浏览器请求兼容模式
- 简体中文、繁体中文、日文和英文界面；首次启动默认简体中文
- Android 10 / API 29 上的安装、首次界面、存储授权、本地服务启动和视频扫描
- Android 10 外置 SD 卡的读取、补抓剧照和标题翻译写回（真机 LG G8X Android 10 验证）
- Android 16 / API 36 模拟器上的启动、扫描、NFO 写入与播放验证
- Python 源码预编译、非关键网络探测后台化、5 分钟启动等待和启动失败重试按钮
- 启动诊断细化到数据目录、数据库、通知、权限表和后台任务阶段，并支持长按复制错误
- 端口被残留服务占用时自动切换到后续空闲端口，并同步 WebView、健康检查和 Cloudflare 代理
- 修复 `phase=ready` 后绑定端口失败导致的 `SystemExit: 1`
- 修复 Pydantic v1 兼容层缺少 `model_copy()` 导致“补抓剧照失败”的问题
- 修复 Android 返回键跨菜单后退的问题；弹窗、灯箱、抽屉和编辑层会按层级优先关闭
- 标题翻译写回兼容 Android 文件系统的大小写规则，`.NFO` 不再被误判为不存在，并改为原子写入
- 修复灯箱多行标题第一、二行间距异常过大的问题
- 右侧灰色菜单按钮支持拖动，位置会持久化，并在旋转或窗口尺寸变化后保持在屏幕内
- 补抓剧照增加来源 URL 规范化、JavDB Referer、图片内容校验、下载诊断和可重复重试
- 补抓剧照区分“来源无剧照”“全部下载失败”“数据库写入失败”，不再显示模糊错误
- Android 手动脸部对焦改由 arm64 NDK 原生级联检测执行，实测单张封面约 0.16–0.40 秒
- 原生对焦健康检查会实际加载级联并调用检测入口，不再只检查 `.so` 是否存在

## 限制

- Windows 托盘、pywebview 桌面窗口、自动更新器、打开资源管理器等桌面专属功能
  不适用于 Android。
- Android 没有 `curl_cffi` 原生轮子。JavDB 网页查询和 AVBase 女优资料使用行为
  兼容的 `requests` fallback，不保证与桌面端完全相同。
- 自定义来源 `fetch: cf` 使用普通浏览器请求兼容模式，不保证通过所有
  Cloudflare 站点。
- 自动检查更新已关闭；升级需安装新 APK。
- 自动对焦仍遵循上游规则：有码/普通厂牌默认使用标准右裁，手动“自动侦测”不受此限制。
- 播放能力取决于手机系统 WebView 编解码器。MP4/H.264/AAC 已验证；MKV、AVI、
  RMVB 等格式即使能扫描，也可能无法在 WebView 中解码。
- Android 11+ 使用 `MANAGE_EXTERNAL_STORAGE`，Android 10 使用传统存储读写权限；
  APK 面向手动侧载，不适合直接上架 Google Play。
- 这是非官方构建，与 OpenAver 上游作者没有隶属或背书关系。

## 构建

要求：

- JDK 17
- Android SDK 36
- Android NDK `28.2.13676358`
- 可选：Python 3.13

设置 SDK 后构建：

```powershell
$env:ANDROID_HOME = "C:\path\to\Android\Sdk"
$env:OPENAVER_BUILD_PYTHON = "C:\path\to\python.exe"
.\gradlew.bat assembleRelease
```

也可使用 Gradle 属性：

```powershell
.\gradlew.bat assembleRelease -PopenaverBuildPython="C:\path\to\python.exe"
```

未指定 `OPENAVER_BUILD_PYTHON` 或 `openaverBuildPython` 时，采用 Chaquopy 的
Python 构建环境。Gradle 产物默认是未签名 APK，需要自行创建密钥、使用
`zipalign` 对齐，再通过 `apksigner` 签名。仓库不会包含发布密钥或签名密码。

### GitHub Actions

仓库内的 `Build APK` workflow 会在 `main` 分支 push 和 Pull Request 上运行
Python 同步验证、pytest 冒烟测试，并构建未签名的 `arm64-v8a` Release APK。

推送 `v*` tag 时，`Publish Android Release` workflow 会构建签名 APK、
生成 `SHA256SUMS.txt` 并创建 GitHub Release。正式发布前在仓库
`Settings → Secrets and variables → Actions` 配置：

- `ANDROID_KEYSTORE_BASE64`：release keystore 的 Base64 内容
- `KEYSTORE_PASSWORD`
- `KEY_ALIAS`
- `KEY_PASSWORD`

本地构建可通过 `ANDROID_KEYSTORE_PATH`、`KEYSTORE_PASSWORD`、
`KEY_ALIAS`、`KEY_PASSWORD` 提供签名；未提供时仍会生成未签名 APK，
方便做验证构建。

本地冒烟测试：

```bash
python -m pip install -r requirements-test.txt
python -m pytest tests -q
```

## 许可证

上游 OpenAver 和本项目修改均采用 MIT License，详见 [LICENSE](LICENSE)。
