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
- [直接下载 arm64-v8a APK](https://github.com/zhao922-bot/OpenAver-Mobile/releases/latest/download/openaver-v0.17.18-android-r27-arm64-v8a.apk)

当前发布包：

- 文件名：`openaver-v0.17.18-android-r27-arm64-v8a.apk`
- 包名：`dev.openaver.mobile`
- 版本：`0.17.18-r27`（versionCode `17043`）
- 架构：仅 `arm64-v8a`
- 最低系统：Android 10（API 29）
- 目标系统：Android 10（API 29）；外置 SD 卡写入使用系统目录授权桥接
- SHA-256：`签名构建后更新`

## 安装

1. 在 64 位 ARM Android 10+ 手机上打开 APK，并允许安装未知应用。
2. Android 11+：授予“所有文件访问权限”。
3. Android 10：授予读取和写入手机存储权限。
4. 如果视频在 SD 卡，打开右侧菜单 → “授权可写目录”，在系统目录选择器中选中
   与扫描目录相同的 SD 卡文件夹。Android 10 的传统存储权限可读取外置 SD 卡，
   但任意文件写入仍需要这一步目录授权。
5. 进入“列表生成”，点击文件夹按钮。
6. 从 `/storage/emulated/0` 或 SD 卡选择视频目录并生成列表。
7. 如果来源确实不应修改，可开启“只读”；OpenAver 会把生成内容写入应用私有媒体库。

如果系统没有直接显示权限页，请手动进入：

`设置 → 应用 → OpenAver 移动版 → 权限`

## 已实现

- 完全本地运行的 Python/FastAPI 服务，仅监听 `127.0.0.1` 的本机端口（优先 8765，占用时自动切换）
- 内嵌 API 使用进程内随机 token；WebView 使用 HttpOnly/SameSite Cookie，Java 代理使用 Bearer Header
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
- Android 10 外置 SD 卡目录授权桥接，支持完整 NFO、封面、poster、fanart、
  标题翻译和补抓剧照写回
  （真机 LG G8X Android 10 验证）
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
- r14：补抓剧照逐图返回下载诊断，重复 URL 去重，损坏的既有剧照会删除重抓
- r14：标题写回与剧照下载在 SD 卡直写被拒后自动转交 SAF；写入后校验字节，
  失败时恢复旧 NFO
- r14：Android 进程内脸部检测现在传递硬超时，并区分 `timeout`、`no_face`
  与运行失败，不再无限占用后台线程
- r14：构建工作流升级到使用当前 Node 运行时的 Actions 主版本
- r15：`generate_nfo` 的文本原子写入接入 SAF，普通刮削和重新刮削可直接生成
  SD 卡 NFO
- r15：`crop_to_poster` 改为内存生成 JPEG 后统一落地，poster 可直接写入 SD 卡
- r15：`generate_jellyfin_images` 与 readonly 侧车复制接入同一套 SAF 文件桥接，
  fanart 和 curator 原图可逐字节复制到 SD 卡
- r15：下载图片、衍生图片和 NFO 统一使用字节校验与原子替换路径，写入失败时
  保留旧文件
- r16：批量补全 NFO 改用统一 SAF 写入路径，修复外置 SD 卡上的
  `PermissionError`，并兼容 Windows 拷入的 `.NFO` 大写扩展名
- r16：新增“批量更换标签来源”，可按一个已启用来源重新获取普通标签并同步
  NFO 与数据库；保留标题、封面、简介和用户标签，字幕侧车文件仍会保留
  “中文字幕”属性
- r16：批量标签任务离开页面或连接断开后会主动停止；Cloudflare 手动来源和
  自定义来源不会出现在批量来源列表中
- r17：仅进行移动端 UI 优化。扫描页新增片库概览/批量维护层级，标签来源控件
  改为响应式操作行，输出路径支持一键复制
- r17：运行状态卡支持折叠日志、错误自动展开和当前进度比例；移动端顶部导航
  显示当前页面名称，硬件返回键会正确关闭批量标签确认弹窗
- r18：批量维护区默认折叠；标签来源改为“仅预览”和“预览并更换”两阶段流程，
  执行前显示新增/移除标签差异、处理数量和失败项
- r18：批量标签和 NFO 补全可在写入前生成同目录 `.openaver-backup`，备份失败的
  影片会被跳过；失败项可在任务结束后单独重试
- r18：扫描、NFO、标签、Jellyfin 图片和补完任务统一显示当前影片、成功/失败/
  跳过数量、计时与预计剩余时间，并支持取消
- r18：设置页增加固定保存栏，明确显示“有未保存更改”“正在保存”和“已保存”状态
- r19：统一移动端错误卡为“发生了什么、影响范围、处理建议、详细日志”四段，
  错误与警告 toast 也支持一键复制诊断信息
- r19：补齐加载骨架、空状态、离线横幅、来源超时/无权限/不可达状态、部分成功
  提示，以及扫描任务的当前影片、成功/失败/跳过摘要
- r19：硬件返回键按“弹窗/灯箱/详情/页面”层级消费，搜索详情返回结果墙，
  不再直接跳回上一个菜单；灯箱、剧照廊和编辑层保持同一套关闭顺序
- r19：右侧悬浮按钮改为拖动后吸附屏幕边缘，空闲时半透明收起，并避让状态栏、
  导航栏和屏幕安全区；主要触控目标统一到至少 48dp
- r19：统一移动端主操作、次操作和危险操作的颜色/尺寸层级，收紧卡片圆角、
  阴影和间距，并统一卡片、详情页、播放器标题的行数限制
- r19：搜索空状态与错误卡恢复完整宽度；搜索栏左右操作区按实际按钮数量动态
  收放，修复图标遮挡占位文字和小屏输入区域过窄
- r20：片库分析页移除无实际信息的 OpenAver 品牌横幅，将影片数、年份、女优和
  片商压缩为一条四列筛选栏，年份与主要图表在手机首屏即可看到
- r21：重做片库分析“深入：女优与片商”区；环形图说明明确内圈/外圈、深浅色和
  灰色含义，并标出“主力片商”的 4 部／80% 判定规则
- r21：女优片商年表改用两位年份、横向滑动和高对比 16 色片商色盘；普通年份圆点
  按该女优当年实际片商着色，不再全部显示灰色
- r21：女优片商分布改为手机单列两行布局，名称、片数、片商家数和分段条不再
  互相挤压；年表无数据时隐藏无意义的图例和滑动提示
- r22：BAZOOKA 移出橙黄色系，避免与 Moodyz 混淆；片商圆点、图例和年表增加
    圆形、方形、菱形、环形、条形编码，不再只依赖颜色区分
- r22：手机端“说明”页改为专用本地操作指南，移除 Telegram、桌面更新检查、
    AI 终端、服务器模式、快捷键等桌面内容；保留原作者致谢和 GitHub 链接
- r22：停用桌面版新手引导，不再自动弹出或在说明页显示入口
- r23：修复番号后直接接中文标题时无法识别番号、导致“缺件 0”的问题
- r23：新增“统一文件名格式”预览与执行：支持 `ABC123`、`ABC_123`、
    `ABC-123标题` → `ABC-123 标题`，同步处理 NFO、封面、poster、fanart 和字幕，
    不动文件夹、`extrafanart` 和其他辅助文件；冲突不执行，失败自动回滚并保存清单
- r24：修复外置存储亚微秒 mtime 波动导致预览被误判为过期、执行时只显示
    `plan_changed` 的问题；计划变化时会自动刷新预览并再次要求确认
- r24：新增“统一文件夹格式”，只规范扫描目录下一层的影片文件夹，并同步数据库中的
    视频、封面和剧照路径；文件夹内文件保持原名，支持冲突阻断和失败回滚
- r24：扫描页的“复制路径 / 设置 / 生成网页”改为统一高度、圆角和视觉层级的操作组；
    文件名规范化说明不再展示无关的密钥文件示例
- r25：修复部分 SD 卡目录提供器在重命名后短暂返回旧目录列表、导致已经成功的
    重命名被判为 `rename_verify_failed` 并触发整批回滚的问题；改为校验系统返回的
    新文档 URI 和实际显示名称
- r25：回滚失败提示现在会附带具体错误原因，便于在不读取应用私有目录时定位问题
- r26：SD 卡重命名改为以 Android `renameDocument()` 返回非空新 URI 作为成功依据，
    不再依赖可能短暂滞后的目录列表或显示名；整批完成后再统一扫描验证
- r26：若重命名仍失败，错误信息会附带具体旧文件名和新文件名
- r27：识别 MTP/FUSE 复制到 SD 卡时因超过 255 字节而被截断的超长文件名；
    可在数据库记录仍完整时按番号找回唯一视频，并修复到安全长度
- r27：视频、封面、NFO、poster 和 fanart 共用同一条截断后的文件名主干，
    超长标题以 `...` 结尾，避免侧车名称不一致或再次超过 Android 文件系统限制

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
- Android 11+ 使用 `MANAGE_EXTERNAL_STORAGE`；Android 10 的普通存储权限不足以
  任意写入外置 SD 卡，必须额外完成一次“授权可写目录”。APK 面向手动侧载，
  不适合直接上架 Google Play。
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

### 上游同步

`app/src/main/python/` 不是独立维护的第二份上游源码，而是固定的
OpenAver `v0.17.18`（提交
`af0d99741e63e71980773c9ade04c473407a60b7`）加 `patches/` 下八个有编号的
补丁。`patches/manifest.json` 记录上游提交和每个补丁负责的文件。

CI 在构建前执行：

```bash
python tools/verify_python_sync.py \
  --upstream-root upstream \
  --source-root app/src/main/python
```

该检查会确认上游提交匹配，然后在临时目录中重放全部补丁，并逐文件比较哈希。
修改任何 Android Python 文件时，必须同时更新对应 patch；完整维护流程见
[patches/README.md](patches/README.md)。

## 许可证

上游 OpenAver 和本项目修改均采用 MIT License，详见 [LICENSE](LICENSE)。
