# OpenAver Mobile targetSdk 升级评估

本文评估 OpenAver Mobile 从 `targetSdk 29` 升级到 Android 30 及以上版本时涉及的
存储、权限、前台服务、WebView 和 native 库兼容性。本文只定义迁移方案和验证门槛，
不直接改变当前发布配置。

## 结论摘要

- 当前 `targetSdk 29` 是侧载版本为兼容 Android 10 外置 SD 卡传统文件路径而保留的
  技术债，不适合作为长期方案，也不能满足 Google Play 的 target API 要求。
- 先升级到 `targetSdk 30` 并验证 `MANAGE_EXTERNAL_STORAGE` 是成本最低的下一步。
  但 Android 10 仍只能使用传统存储权限，升级后直接路径写 SD 卡是否继续可用必须用
  真机验证，不能仅凭文档推断。
- 如果 `targetSdk 30+` 在 Android 10 上确实破坏外置 SD 卡写入，同一个 APK 可能
  无法同时满足“Android 10 原地读写”和“现代 targetSdk”两个目标。此时应做一个
  明确的发布决策：保留 Android 10 兼容包，或为现代系统改用 SAF 文件访问桥接。
- `MANAGE_EXTERNAL_STORAGE` 能让侧载版本继续按普通文件路径工作，但它是特殊全盘
  访问授权，不是普通运行时权限，也受 Google Play 限制。它仍不能访问其他应用的
  `Android/data`、`Android/obb` 等私有目录。
- Android 14 及更新系统仍允许安装 `targetSdk 29` 的 APK，当前问题不是“无法安装”，
  而是旧 targetSdk 带来的行为兼容、商店合规和未来系统限制风险。
- 在 targetSdk 升级的同时，建议把“后台长期运行”明确设计为可选前台服务。当前
  FastAPI/Uvicorn 运行在 Activity 进程中，退到后台后没有服务生命周期保障。
- 升级到 Android 35/36 前，必须检查 APK 内所有 native `.so` 的 16 KB 页大小
  对齐，包括自建 `libopenaver_mobile.so`、Chaquopy/CPython 和 pip 扩展模块。

## 当前基线

| 项目 | 当前值 |
| --- | --- |
| `compileSdk` | 36 |
| `minSdk` | 29 |
| `targetSdk` | 29 |
| versionCode / versionName | `17028` / `0.17.18-r12` |
| ABI | `arm64-v8a` |
| NDK | `28.2.13676358` |
| Chaquopy | `17.2.0` |
| 存储声明 | `READ/WRITE_EXTERNAL_STORAGE`（maxSdk 29）、`MANAGE_EXTERNAL_STORAGE` |
| 传统存储开关 | `requestLegacyExternalStorage=true` |
| 后台运行模型 | `Activity` 内单线程启动 Python/Uvicorn，daemon thread |
| 本地 HTTP | `127.0.0.1:8765` 起，端口占用时向后回退 |

对应代码位置：

- `app/build.gradle`
- `app/src/main/AndroidManifest.xml`
- `app/src/main/java/dev/openaver/mobile/MainActivity.java`
- `app/src/main/java/dev/openaver/mobile/CfShellAgent.java`
- `app/src/main/java/dev/openaver/mobile/AndroidCfTransport.java`
- `app/src/main/python/openaver_boot.py`

## 版本行为与风险

### Android 10（API 29）

- 当前 targetSdk 29 配合 `requestLegacyExternalStorage=true`，可以继续使用传统
  `java.io.File` 路径和 `READ/WRITE_EXTERNAL_STORAGE`。
- `MANAGE_EXTERNAL_STORAGE` 从 API 30 才存在，Android 10 无法使用该授权路径。
- 如果 targetSdk 升到 30 或更高，`requestLegacyExternalStorage` 预计会被忽略，
  Android 10 可能进入 scoped storage。外置 SD 卡的扫描、NFO/封面写入、重命名和
  标题翻译写回都可能出现 `EACCES`。
- 当前代码按系统版本选择权限路径，而不是按实际存储能力选择。升级 targetSdk 后，
  `usesLegacyStorage()` 在 Android 10 上仍会返回 true，但传统权限并不一定等于
  传统文件系统访问，因此必须调整能力检测。

风险等级：**高**。这是决定是否需要拆分发布包的关键验证项。

### Android 11（API 30）

- targetSdk 30+ 可使用 `MANAGE_EXTERNAL_STORAGE`，通过
  `Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION` 引导用户授权。
- 授权后可使用文件路径访问共享存储，但不能访问其他应用专属的
  `Android/data` 和 `Android/obb`。
- `requestLegacyExternalStorage` 在现代系统上不再是通用兼容方案，不应继续作为
  主要存储设计。
- 升级安装后旧数据库和应用私有目录通常保留，但权限需要重新确认。

风险等级：**中**。侧载路径可控，主要工作是权限迁移和 Android 10 回退策略。

### Android 12（API 31/32）

- 后台启动前台服务受到限制；不能假设 Activity 退到后台后可以随时启动服务。
- 如需保持长时间扫描、抓取或下载，应在用户可见、应用仍处于前台时启动
  `foregroundServiceType` 明确的 foreground service。
- 通知渠道和前台服务通知需要可读、稳定，不能依赖被用户关闭的普通通知。

风险等级：**中低**。当前没有 Service，短期不会直接崩溃，但后台可靠性仍不足。

### Android 13（API 33）

- 通知权限变成运行时权限。若引入前台服务，需要声明并请求
  `POST_NOTIFICATIONS`。
- 媒体读取权限拆分为 `READ_MEDIA_*`。侧载版本若继续使用
  `MANAGE_EXTERNAL_STORAGE`，不应同时把媒体权限当作任意目录读写依据。

风险等级：**低到中**。与前台服务方案一起处理。

### Android 14（API 34）

- targetSdk 29 APK 仍可侧载安装，不存在“targetSdk 29 一律无法安装”的规则。
- targetSdk 34+ 的前台服务必须声明服务类型，并申请相应
  `FOREGROUND_SERVICE_*` 权限。数据同步型服务适合声明 `dataSync`，但会受新的
  后台和超时规则约束。
- 系统更积极地限制后台进程，当前 Activity 内 daemon thread 的 Uvicorn 没有
  后台存活保证。

风险等级：**中**。升级到 targetSdk 34 前应完成服务边界设计，不能只在
`AndroidManifest.xml` 里补一个类型。

### Android 15（API 35）

- 16 KB 内存页设备开始扩大覆盖。Google Play 对 targetSdk 35+ 的 native 库有
  页大小兼容要求。
- 自建 CMake 库使用 NDK 28，通常已具备 16 KB 能力，但 Chaquopy 自带的
  CPython、Pillow/lxml 等 native 扩展也必须逐项检查。
- `dataSync` 前台服务存在累计时限；长任务需要可暂停、可恢复，并能处理系统
  停止服务的情况。
- Edge-to-edge 行为继续收紧。现有代码已设置 `setDecorFitsSystemWindows(false)`
  并应用系统栏 inset，但仍需在横屏、手势导航、刘海屏和键盘弹出时回归。

风险等级：**高**。建议单独建立 16 KB 页大小验证，不把它混进普通 targetSdk
升级。

### Android 16（API 36）

- 继续收紧后台任务、通知、大屏适配和 edge-to-edge 行为。
- 预测性返回的系统行为可能与当前 `enableOnBackInvokedCallback=false` 和自定义
  返回拦截逻辑交互，需要确认不会出现“先退菜单而不是上一级”的回归。
- 若应用最终进入 Play，target API 要求会继续前移；只满足 Android 10 的 target 29
  不能作为长期发布策略。

风险等级：**高**。应以 Android 16 模拟器加至少一台现代真机完成回归。

## 存储方案比较

### 方案 A：现代 targetSdk + `MANAGE_EXTERNAL_STORAGE`（推荐先验证）

适合 GitHub 侧载版本：

- 保留 Python 现有 `pathlib`/`os` 文件处理模型。
- 继续原地扫描视频、写同名 NFO、封面、poster、fanart 和
  `extrafanart`。
- 需要用户手动授予“所有文件访问权限”，首次启动流程要解释清楚。
- 需要在 Android 10 真机上验证：targetSdk 30+ 是否仍能直接写外置 SD 卡。

优点：改动最小，最接近桌面版行为。

缺点：无法上架 Google Play；用户可能拒绝特殊权限；OEM 文件管理器仍可能限制
某些目录；不能访问其他应用私有目录。

### 方案 B：SAF 目录授权（适合 Play 或 Android 10 兼容包）

用户通过 `ACTION_OPEN_DOCUMENT_TREE` 选择视频根目录，应用持久化 URI 授权。

- Java 端通过 `ContentResolver`/`DocumentFile` 提供目录遍历、读写、重命名和删除。
- Python 端通过 Chaquopy 调用 Java 桥接层，不能继续把 content URI 当普通路径。
- 视频 HTTP Range 服务需要能按 content URI 打开流。
- 批量扫描需要优先使用 `DocumentsContract`，避免 `DocumentFile` 逐文件查询过慢。

优点：Play 合规性最好，不需要全盘权限。

缺点：实现量大，性能和行为与桌面版差异明显；Scoped storage 下对某些目录的
命名、隐藏文件和原子替换语义并不完全等同于 POSIX 文件系统。

### 方案 C：MediaStore 发现视频，sidecar 放应用私有目录

只适合“纯媒体库”模式：

- 可读取视频媒体条目。
- NFO、封面、剧照等不能任意写回视频旁边的目录，通常只能放应用私有目录。

该方案破坏 OpenAver 原有的 sidecar 工作流，不建议作为默认路径。

### 方案 D：双构建

如果 Android 10 验证失败，并且必须同时保留新旧设备：

- `legacy` 侧载包：`targetSdk 29`，服务 Android 10 和旧版外置 SD 卡行为。
- `modern` 侧载包：`targetSdk 36`，使用 `MANAGE_EXTERNAL_STORAGE`，服务
  Android 11+。
- 两个包使用同一签名和单调递增的 versionCode，但发布页必须明确标记设备适用范围。

这是兼容性最稳的兜底，但会增加 CI、测试和用户支持成本。只有在方案 A 的
Android 10 真机验证失败后才采用。

## 代码改造点

### 1. 存储能力检测

当前：

- `usesLegacyStorage()` 只判断系统版本。
- `hasStorageAccess()` 在 Android 10 检查普通读写权限，在 Android 11+ 检查
  `Environment.isExternalStorageManager()`。

建议：

- 保留权限请求作为“前置条件”，另加一次实际写测试。
- 在用户选择的视频根目录创建临时文件并删除，作为能力探测；失败时展示可操作的
  错误，而不是继续启动后随机报错。
- 把“能否通过普通路径访问”和“能否使用 SAF”抽象成 capability，而不是散落在
  Activity 中的版本判断。

### 2. Manifest 与权限

- targetSdk 升到 30+ 后保留：
  - `READ/WRITE_EXTERNAL_STORAGE` 的 `maxSdkVersion="29"`，仅用于 Android 10。
  - `MANAGE_EXTERNAL_STORAGE`，用于 Android 11+ 侧载全盘目录访问。
- 不要同时新增无用的 `READ_MEDIA_*`，除非另有 MediaStore 路径。
- `requestLegacyExternalStorage` 可以短期保留作兼容标记，但不能把它当作
  targetSdk 30+ 的运行时保证。

### 3. 前台服务

当前 Python/Uvicorn 是 Activity 进程内 daemon thread：

- App 进入后台后，系统可能暂停或杀死进程。
- `CfShellAgent` 也是普通线程，不是 Service。
- WebView Cloudflare 验证必须依赖 Activity 可见，不应无界面后台运行。

建议：

- 首阶段保持服务在 Activity 前台生命周期内，避免无谓的 Android 12+ 后台启动
  限制。
- 如果必须后台扫描/抓取，新增独立 `dataSync` 前台服务，并提供开始、停止、
  进度和失败状态。
- targetSdk 34 时加入 `FOREGROUND_SERVICE_DATA_SYNC` 和对应服务类型。
- targetSdk 35 时处理 dataSync 时限、暂停恢复和通知可见性。

### 4. WebView 与网络

- 本地 HTTP 仍基于 `127.0.0.1`，升级 targetSdk 后网络安全性配置应继续只允许
  loopback 明文连接。
- 验证 WebView 在 Android 14/15/16 上对 loopback、multipart 上传、下载、
  媒体解码和全屏播放的行为。
- 检查 WebView Cookie、DownloadManager、HTTP Range 和外部 Cloudflare 站点
  是否仍在 targetSdk 升级后工作。
- WebView 的 Cloudflare 验证仍必须由用户可见交互完成，不能转成 Service 后台
  自动验证。

### 5. Native 库与 16 KB 页大小

需要检查：

- `libopenaver_mobile.so`
- Chaquopy 提供的 CPython 和 Android runtime native 库
- pip wheel 中的 Pillow、lxml 等 native 扩展
- 所有 `.so` 的 `LOAD` segment 对齐和 APK 内 zip 对齐

验证命令示例：

```bash
zipalign -c -P 16 -v 4 openaver.apk
llvm-readelf -l path/to/libfoo.so
```

同时用 Android 15/16 的 16 KB 页大小模拟器或设备安装、启动、扫描、封面显示、
视频播放和脸部检测。

## 分阶段迁移计划

每个阶段单独提交、单独 tag，不允许把 targetSdk、业务功能和 patch 重排混在一个
不可回滚的提交中。

### 阶段 0：基线与测试矩阵

代码点：

- 固定当前 `targetSdk 29` 发布为已知可用基线。
- 记录 APK、versionCode、签名、ABI 和 SHA-256。
- 准备好 Android 10 真机、Android 11+ 真机/模拟器、Android 14+ 模拟器和
  16 KB 页大小测试环境。

通过标准：

- 当前 APK 可在 Android 10 和至少一个 Android 14+ 环境启动。
- 能扫描内部存储和 SD 卡，并完成 NFO/封面/剧照/标题翻译写回。

回滚：

- 不需要代码回滚；基线 APK 保留。

### 阶段 1：targetSdk 30 + 全盘访问迁移

代码点：

- `targetSdk` 改为 30。
- 调整存储能力检测，保留 Android 10 普通权限分支。
- 完善 Android 11+ 的“所有文件访问”说明和拒绝授权流程。
- 对所有视频根目录做实际写探针。

重点测试：

- Android 10：从 targetSdk 29 升级安装后，SD 卡原地读写是否仍成功。
- Android 11：首次授权、拒绝授权、撤销授权、重新授权。
- 扫描、封面、NFO、剧照、重命名、标题翻译和视频播放。

通过标准：

- Android 10 没有不可恢复的 SD 卡写失败；如果失败，立即进入方案 D 评估。
- Android 11+ 所有文件访问授权后，所有原有文件工作流通过。

回滚：

- 仅回滚 `targetSdk` 和存储检测改动，保留版本号递增，避免已升级设备无法安装
  旧 versionCode。

### 阶段 2：targetSdk 33/34 + 通知与服务边界

代码点：

- 需要后台任务时引入前台服务、通知渠道和通知权限。
- 明确 `dataSync` 服务类型、启动条件和停止条件。
- 禁止从后台无提示启动 Cloudflare WebView 任务。

重点测试：

- Android 13 通知授权拒绝/允许。
- Android 14 前台服务启动、退后台、进程重启和用户停止。
- 数据同步服务超时、失败恢复和通知不可见时的行为。

回滚：

- 关闭服务改造，退回 Activity 前台运行；不要回滚已升级的数据库 schema，除非有
  明确的向下迁移脚本。

### 阶段 3：targetSdk 35/36 + 16 KB/edge-to-edge

代码点：

- 在现代设备上启用 edge-to-edge 回归。
- 检查 predictive back 与 WebView 内部历史的交互。
- 验证所有 native 库的 16 KB 页大小兼容。

重点测试：

- Android 15/16 16 KB 页大小设备首次启动。
- 横屏、分屏、刘海、手势导航、软键盘、下载通知。
- 返回键层级、菜单抽屉、灯箱、Cloudflare 覆盖层和视频全屏。

回滚：

- 先回滚 targetSdk 到上一阶段，不删除新数据库字段；用 feature flag 关闭新服务
  和 UI 适配。

## 真机与模拟器测试矩阵

| 场景 | Android 10 真机 | Android 11/12 | Android 13/14 | Android 15/16 |
| --- | --- | --- | --- | --- |
| 首次安装与升级安装 | 必测 | 必测 | 必测 | 必测 |
| 传统存储权限 / 全盘授权 | 必测 | 必测 | 必测 | 必测 |
| 内部存储扫描 | 必测 | 必测 | 必测 | 必测 |
| 外置 SD 卡扫描 | 必测 | 必测 | 必测 | 必测 |
| NFO/封面/剧照原地写入 | 必测 | 必测 | 必测 | 必测 |
| 重命名和标题翻译写回 | 必测 | 必测 | 必测 | 必测 |
| 视频 Range 播放 | 必测 | 必测 | 必测 | 必测 |
| 应用退到后台再回来 | 必测 | 必测 | 必测 | 必测 |
| 通知权限与前台服务 | 不适用/观察 | 观察 | 必测 | 必测 |
| 16 KB 页大小 native 库 | 不适用 | 不适用 | 可选 | 必测 |
| 返回键、灯箱、Cloudflare 层 | 必测 | 必测 | 必测 | 必测 |

每次测试都要记录：

- 设备型号、Android 版本、ROM、存储卷类型（内部/SD/模拟器）
- targetSdk、versionCode、APK SHA-256
- 授权前后日志
- 失败文件的路径、权限和具体 errno
- 是否可在不清理应用数据的情况下回滚

## 决策门槛

### 采用方案 A 的条件

同时满足：

1. Android 10 真机能继续扫描并原地写外置 SD 卡。
2. Android 11+ 全盘授权后所有 sidecar 工作流通过。
3. Android 14+ 不出现新的前台服务或 WebView 崩溃。
4. 16 KB native 库检查通过。

### 触发方案 D 或 SAF 的条件

满足任一：

1. Android 10 在 targetSdk 30+ 下无法稳定写 SD 卡。
2. `MANAGE_EXTERNAL_STORAGE` 在某些目标 ROM 上无法获得或授权不稳定。
3. 需要上架 Google Play，且不能获得全盘访问政策豁免。
4. SAF 根目录授权可以满足用户主要 sidecar 工作流，且性能可接受。

## 待确认问题

- Android 10 上 targetSdk 30+ 是否会强制 scoped storage，导致现有外置 SD 卡
  路径写入失败？必须用 LG G8X 真机实测，不能只依赖模拟器。
- Chaquopy 17.2.0 在 targetSdk 33/34/35/36 上是否有未公开的 Python 初始化或
  JNI 限制？
- 所有 pip native 扩展是否满足 16 KB 页大小要求，尤其是 PIL 和 lxml？
- 现有 WebView File Chooser、DownloadManager 和本地 HTTP 在 targetSdk 35+
  是否有新的权限或 mixed-content 行为？
- Android 10 与现代系统是否必须拆成两个 APK，还是能由单一 APK + 运行时
  capability 分支覆盖？

## 参考文档

- [Android 11 scoped storage](https://developer.android.com/about/versions/11/privacy/storage)
- [Manage all files on a storage device](https://developer.android.com/training/data-storage/manage-all-files)
- [Storage use cases and permissions](https://developer.android.com/training/data-storage/use-cases)
- [Access media files from shared storage](https://developer.android.com/training/data-storage/shared/media)
- [Android 13 notification permission](https://developer.android.com/develop/ui/views/notifications/notification-permission)
- [Android 14 foreground service types](https://developer.android.com/about/versions/14/changes/fgs-types-required)
- [Android 15 dataSync foreground service timeout](https://developer.android.com/about/versions/15/behavior-changes-15#data-sync-timeout)
- [Support 16 KB page sizes](https://developer.android.com/guide/practices/page-sizes)
- [Android 15 edge-to-edge](https://developer.android.com/develop/ui/views/layout/edge-to-edge)
- [Android 16 behavior changes](https://developer.android.com/about/versions/16/behavior-changes-16)
- [Google Play all files access policy](https://support.google.com/googleplay/android-developer/answer/10158779)
- [Google Play target API level requirements](https://support.google.com/googleplay/android-developer/answer/11926878)
