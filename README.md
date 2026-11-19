<div align="center">

# OpenAver Mobile

**完全本地运行的 [OpenAver](https://github.com/slive777/OpenAver) Android 移植版**

原生 Flutter 界面 · 内嵌 Python 3.13 / FastAPI · 内置 MediaKit 播放器 · 无需电脑、NAS 或 Termux

[![Build APK](https://github.com/zhao922-bot/OpenAver-Mobile/actions/workflows/build.yml/badge.svg)](https://github.com/zhao922-bot/OpenAver-Mobile/actions/workflows/build.yml)
[![Latest Release](https://img.shields.io/github/v/release/zhao922-bot/OpenAver-Mobile?label=Release&color=ff8a4c)](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest)
![Android 10+](https://img.shields.io/badge/Android-10%2B%20(arm64--v8a)-3DDC84?logo=android&logoColor=white)
![Flutter 3.44](https://img.shields.io/badge/Flutter-3.44-02569B?logo=flutter&logoColor=white)
![Python 3.13](https://img.shields.io/badge/Python-3.13%20Embedded-3776AB?logo=python&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[**下载最新 APK**](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest/download/openaver-v0.18.17-android-r86-arm64-v8a.apk) ·
[**全部版本与更新日志**](https://github.com/zhao922-bot/OpenAver-Mobile/releases) ·
[**快速上手**](#-下载与安装) ·
[**本地构建**](#-本地构建与测试) ·
[**上游项目**](https://github.com/slive777/OpenAver)

</div>

---

## ✨ 为什么选择 OpenAver Mobile

将完整的 OpenAver 后端直接打包进单个 Android APK：扫描片库、SQLite 索引、元数据刮削、NFO/封面/剧照写回、AI 翻译与视觉标签以及本地视频播放全部在手机端独立完成，**视频文件始终保留在原目录中**。

| 模块 | 核心能力 |
| :--- | :--- |
| **原生 Flutter 界面** | 展示库 / 搜索 / 片库管理 / 片库分析 / 设置五大模块；支持 **影院灰 · 纯黑 · 浅色** 三套主题与 **简中 · 繁中 · 日文 · 英文 · 韩文** 五语切换；保留一键切换经典 WebView 视图排错 |
| **片库与女优墙** | 封面网格与列表浏览、服务端/客户端完整排序与多维筛选、分集视频（`cd1/cd2`）合并、女优资料与照片更换、原生 NDK 人脸检测与手动焦点裁剪 |
| **多源聚合搜索** | 流式搜索与翻页加载、片商与常收女优胶囊、批量搜番号、以图查番、愿望单书签；内置 WebView Cloudflare 验证通路（JavLibrary / FC2-javten / Jable）与 Metatube 扩展 |
| **内置与外置播放** | 内置 `MediaKit` 播放器支持倍速记忆、横屏沉浸、分集自动续播与本地 HTTP Range 拖动；支持随时调用系统外部播放器 |
| **片库维护与 AI** | 前台服务保活后台扫描；一键补齐 NFO / 简介 / 标题翻译 / 剧照；统一文件名与目录规范化；片库健康分析与异常番号修复；支持 Ollama / Gemini / Claude / OpenAI 翻译、封面相似度、远端人脸与 AI 视觉标签 |
| **安全与存储兼容** | 仅监听 `127.0.0.1` 随机端口 + 进程内随机 Token 鉴权；支持 Android SAF 外置 SD 卡目录授权写回与数据库 ZIP 一键备份/恢复 |

---

## 📦 下载与安装

> 当前发布版基于上游 OpenAver `v0.18.17` + 移动端补丁层构建，完整改动请查看 [Release Notes](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest) 或 [r86 发布说明](docs/releases/v0.18.17-android-r86.md)。

| 项目 | 说明 |
| :--- | :--- |
| **直接下载** | [`openaver-v0.18.17-android-r86-arm64-v8a.apk`](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest/download/openaver-v0.18.17-android-r86-arm64-v8a.apk) |
| **应用包名 / 版本** | `dev.openaver.mobile` · `0.18.17-r86` (`versionCode 18086`) |
| **系统与架构要求** | Android 10+ (API 29+) · 仅 `arm64-v8a` |
| **校验文件** | 见 Release 附件中的 `SHA256SUMS.txt` |

### 快速上手

1. **安装 APK**：在 64 位 Android 10+ 设备上允许“安装未知应用”并完成安装。
2. **授予存储权限**：
   - **Android 11+**：授予“所有文件访问权限”（如未自动弹出，可前往 `设置 → 应用 → OpenAver 移动版 → 权限`）。
   - **Android 10 / 外置 SD 卡写入**：在 **设置 → 片库目录与展示 → SAF 可写目录授权** 中选择与扫描目录一致的 SD 卡文件夹。
3. **添加目录并扫描**：进入 **设置** 添加视频目录（如 `/storage/emulated/0/...` 或 SD 卡目录；不想修改源目录可开启“只读来源”），随后在 **片库管理** 点击 **扫描片库** 即可开始浏览。

---

## 🧩 架构概览

```text
┌──────────────────────────────────────────────────────────┐
│  Flutter UI (Riverpod · 5 Tabs · MediaKit Player)        │
│    ↕ HTTP/SSE (127.0.0.1 + Bearer Token)                 │
│    ↕ MethodChannel (SAF · 文件选择 · 外置播放 · 保活)      │
├──────────────────────────────────────────────────────────┤
│  Android Native Layer (Java · SAF Bridge · CF WebView)   │
├──────────────────────────────────────────────────────────┤
│  Embedded Python 3.13 (Chaquopy · FastAPI · Uvicorn)     │
│    ├─ SQLite 片库 / 书签 / 别名 / AI 索引                 │
│    └─ Android NDK arm64 原生人脸焦点检测 (.so)            │
└──────────────────────────────────────────────────────────┘
```

---

## ⚠️ 已知说明与限制

- **侧载分发**：Android 11+ 使用 `MANAGE_EXTERNAL_STORAGE` 读写本地片库，仅面向手动侧载，不面向 Google Play。
- **网络回退**：Android 无 `curl_cffi` 原生轮子，JavDB / AVBase 使用行为兼容的 `requests` 回退；自定义来源 `fetch: cf` 使用标准浏览器请求模式，不保证覆盖所有 Cloudflare 站点；Jable 站方不提供剧照图集。
- **人脸对焦策略**：自动对焦遵循上游规则（有码/普通厂牌默认标准右裁，可在影片详情页随时点击“人脸 / 封面焦点”手动检测或拖拽微调）。
- **无自动更新**：内置桌面更新检查已关闭，新版本请前往 [Releases](https://github.com/zhao922-bot/OpenAver-Mobile/releases) 下载覆盖安装。
- **非官方声明**：本项目为社区非官方 Android 移植版，与 OpenAver 上游作者无隶属或背书关系。

---

## 🛠️ 本地构建与测试

### 环境要求

- **JDK 17** · **Flutter `3.44.0`** · **Python `3.13`** · **Node.js `18+`**
- **Android SDK `36`** · **Build Tools `36.0.0`** · **NDK `28.2.13676358`** · **CMake `3.22.1`**

### 构建与校验命令

```powershell
# 1. 安装前端按需构建依赖（首次 Release 构建需要）
npm ci --prefix tools/echarts-build

# 2. Flutter 静态检查与单元测试
cd flutter_ui && flutter pub get && flutter analyze && flutter test && cd ..

# 3. Python 后端回归测试
python -m pip install -r requirements-test.txt
python -m pytest tests/ -q

# 4. 构建 arm64-v8a Release APK（默认未签名）
$env:ANDROID_HOME = "C:\path\to\Android\Sdk"
$env:OPENAVER_BUILD_PYTHON = "C:\path\to\python.exe"
.\gradlew.bat assembleRelease -Pabi=arm64-v8a -Ptarget-platform=android-arm64
```

<details>
<summary><strong>展开查看：上游补丁同步、签名配置与 GitHub Actions 说明</strong></summary>

#### 上游补丁分层校验
`app/src/main/python/` 由锁定的上游 OpenAver 提交（记录于 [`patches/manifest.json`](patches/manifest.json)）叠加 `patches/*.patch` 生成。修改任何 Python 文件后必须同步更新补丁并通过校验：

```bash
python tools/verify_python_sync.py \
  --upstream-root /path/to/OpenAver \
  --source-root app/src/main/python
```

完整维护流程请参阅 [patches/README.md](patches/README.md)。

#### 签名与自动化发布
- **CI 检查**：向 `main` 推送或提交 PR 时，`Build APK` workflow 自动运行 Flutter 测试、上游补丁同步校验、pytest、JS 语法检查、Android JVM 单测并产出未签名 `arm64-v8a` APK。
- **正式发布**：推送 `v*` tag 会触发 `Publish Android Release`，需在仓库 Secrets 配置 `ANDROID_KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD`；本地构建可通过环境变量 `ANDROID_KEYSTORE_PATH` 等传入签名信息。

</details>

---

## 📄 致谢与许可证

感谢 [slive777/OpenAver](https://github.com/slive777/OpenAver) 原项目及其贡献者。
上游 OpenAver 与本仓库所有改动均基于 **MIT License** 开源，详见 [LICENSE](LICENSE)。
