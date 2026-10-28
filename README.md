# OpenAver Mobile

OpenAver Mobile 是 [OpenAver](https://github.com/slive777/OpenAver) 的非官方
Android 移植版，基于上游最新正式版 `v0.17.18`
（提交 `af0d99741e63e71980773c9ade04c473407a60b7`）。

App 在手机内嵌 Python 3.13、FastAPI、Uvicorn 和 OpenAver Web 服务，不需要
电脑、NAS、局域网服务器或 Termux。扫描、数据库、元数据搜索、NFO/封面写入和
视频播放均由手机本地执行；视频保留在手机原目录。

## 下载

- [发布页](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest)
- [直接下载 arm64-v8a APK](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest/download/OpenAver-Mobile-v0.17.18-arm64-v8a-r2.apk)

当前发布包：

- 文件名：`OpenAver-Mobile-v0.17.18-arm64-v8a-r2.apk`
- 包名：`dev.openaver.mobile`
- 版本：`0.17.18`（versionCode `17019`）
- 架构：仅 `arm64-v8a`
- 最低系统：Android 11（API 30）
- SHA-256：
  `EA5CB9025AD55F07159E5654354B5491C6F47A4DC43EA78654D80372514F15D9`

## 安装

1. 在 64 位 ARM Android 11+ 手机上打开 APK，并允许安装未知应用。
2. 启动后点击“打开‘所有文件访问权限’设置”。
3. 在系统设置中授予“所有文件访问权限”，然后返回 App。
4. 进入“列表生成”，点击文件夹按钮。
5. 从 `/storage/emulated/0` 或 SD 卡选择视频目录并生成列表。

如果系统没有直接显示权限页，请手动进入：

`设置 → 应用 → OpenAver 移动版 → 特殊权限 → 所有文件访问权限`

## 已实现

- 完全本地运行的 Python/FastAPI 服务，仅监听 `127.0.0.1:8765`
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
- Android 16 / API 36 模拟器上的启动、扫描、NFO 写入与播放验证

## 限制

- Windows 托盘、pywebview 桌面窗口、自动更新器、打开资源管理器等桌面专属功能
  不适用于 Android。
- Android 没有 `curl_cffi` 原生轮子。JavDB 网页查询和 AVBase 女优资料使用行为
  兼容的 `requests` fallback，不保证与桌面端完全相同。
- 自定义来源 `fetch: cf` 使用普通浏览器请求兼容模式，不保证通过所有
  Cloudflare 站点。
- 自动检查更新已关闭；升级需安装新 APK。
- 播放能力取决于手机系统 WebView 编解码器。MP4/H.264/AAC 已验证；MKV、AVI、
  RMVB 等格式即使能扫描，也可能无法在 WebView 中解码。
- APK 使用 `MANAGE_EXTERNAL_STORAGE`，面向手动侧载，不适合直接上架 Google Play。
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

## 许可证

上游 OpenAver 和本项目修改均采用 MIT License，详见 [LICENSE](LICENSE)。
