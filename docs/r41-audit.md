# OpenAver Mobile r41 代码审查与改进建议

| 项目 | 值 |
| --- | --- |
| 审查对象 | `0.17.18-r41`（versionCode `17057`） |
| 提交 | `1b2f681078de98550de6d1f0474cf472fe268c4c` |
| 上游基线 | OpenAver `v0.17.18` / `af0d99741e63e71980773c9ade04c473407a60b7` |
| 审查日期 | 2026-11-06 |
| 审查方式 | 只读代码审查 + 本地测试基线验证，未修改任何文件 |

## 0. 审查范围与方法

覆盖范围：

- `app/src/main/java/dev/openaver/mobile/`（8 个文件，3,904 行，其中 `MainActivity` 1,473 行）
- `app/src/main/python/`（212 个 `.py`，62,867 行）
- `patches/001`–`008`、`tools/`、`tests/`、`.github/workflows/`
- `app/build.gradle`、`AndroidManifest.xml`、`res/`、`README.md`、`docs/`

已执行的基线验证（全部通过）：

```
pytest tests/ -q                          → 175 passed in 14.08s
tools/verify_python_sync.py               → 448 files match upstream + patches
git status --short                        → tracked worktree 干净
git diff --check                          → 无空白错误
```

## 1. 结论摘要

r41 的核心链路是可靠的：扫描、补剧照、分集分组、分段播放都有测试覆盖，
渲染进程回收、WAL、原子写、回环鉴权这些关键机制实现得比一般移植项目扎实。

剩下的问题集中在三类结构性欠账，而不是零散 bug：

1. **数据没有出口**——数据库只存在应用私有目录，`allowBackup=false`，没有任何导出/恢复入口。
2. **长任务没有生命周期保障**——无退避重试、无前台服务、取消不立即生效、失败项不可重试。
3. **分集识别覆盖面窄**——只认 `cd/dvd/part/pt/disc` + 单个数字，且没有手动合并入口。

按影响排序，最该先修的是「数据库导出/恢复」，因为它是唯一不可逆的一类。

## 2. 问题总览

| 编号 | 级别 | 类别 | 问题 | 主要证据 |
| --- | --- | --- | --- | --- |
| 1 | P0 | 数据安全 | 数据库无导出/备份，卸载即全丢 | `MainActivity.java:440`、`AndroidManifest.xml:19` |
| 2 | P2 | 安全 | 依赖版本线落后于上游 CVE 基线 | `app/build.gradle:122-132` |
| 3 | P1 | 可靠性 | 批量任务无退避重试 | `scanner.py:1833-1834`、`gemini_client.py:105` |
| 4 | P1 | 可靠性 | 无前台服务，后台任务冻结 | `MainActivity.java:1246` |
| 5 | P1 | 可靠性 | 取消不立即生效 | `scanner.py:2325` |
| 6 | P2 | 可用性 | 失败项无"只重试失败" | `state-batch.js:576-589` |
| 7 | P1 | 功能 | 分集识别只覆盖一半命名，且不可手动干预 | `core/multipart_tokens.py:19-22` |
| 8 | P2 | 一致性 | 搜索页播放丢分段信息 | `search.html:71,1088` |
| 9 | P2 | 一致性 | 无外部播放器时无兜底 | `MainActivity.java:998` |
| 10 | P3 | 存储 | 缩略图缓存无自动上限 | `core/thumbnail_cache.py` |
| 11 | P3 | 工程 | Java 层零测试、JS 未进 CI | `.github/workflows/build.yml` |
| 12 | P3 | 工程 | targetSdk 29 技术债、16KB 页未验证 | `docs/target-sdk-upgrade.md` |
| 13 | P3 | 工程 | patch 体量与 pydantic v1 shim 的升级成本 | `patches/007`（632,830 B） |
| 14 | P3 | 内存 | 无 `onTrimMemory` + `largeHeap="true"` | `AndroidManifest.xml:26` |

## 3. P0｜数据安全

### 3.1 数据库只活在应用私有目录，且没有任何导出/备份入口

**现象**

- 数据库路径为 `getFilesDir()/openaver_data/openaver.db`，属于应用私有内部存储
  （`app/src/main/java/dev/openaver/mobile/MainActivity.java:440`）。
- `AndroidManifest.xml:19` 设置 `android:allowBackup="false"`，系统备份通道也被关闭。
- 路由层不存在 export / backup / restore 端点（已 grep 全量 `web/routers/*.py`）。
- 设置页唯一的"导出"是离线 HTML 导出，那是 Windows 桌面功能，与数据库无关。

**影响**

以下操作会导致数据不可恢复地丢失：

- 卸载重装（包括签名不一致被迫卸载、降级安装失败）
- 换机、恢复出厂、系统"清除数据"
- 用户误点系统设置里的"清除存储"

丢失的内容不只是列表，还包括**只存在于数据库、不会写进 NFO 的用户数据**：

- 手动封面裁切坐标（`auto_focal` / `crop_mode`）
- 收藏、标签、别名、愿望单
- 补图/补翻译的历史状态

重扫只能从文件名和 NFO 恢复一部分，裁切坐标必须重新一张张框。

**建议**

1. 新增 `GET /api/database/export`：用 `VACUUM INTO` 生成一致性快照
   （WAL 模式下直接拷 `.db` 可能拿到不一致副本），打包为 zip 写入用户选定的 SAF 目录。
2. 新增 `POST /api/database/restore`：校验 schema 版本后原子替换，替换前自动留一份 `.bak`。
3. 设置页加"导出数据库 / 从文件恢复"两个入口，导出成功后显示文件路径与大小。
4. 可选：启动时若检测到距上次导出超过 N 天，在维护页给一条温和提示。

**验证方式**

- 单元测试：导出后重新打开快照，`PRAGMA integrity_check` 为 `ok`，行数与源库一致。
- 手工：导出 → 清数据 → 恢复 → 检查裁切坐标、标签、收藏是否原样。
- 边界：导出过程中同时有补图任务在写库，快照仍应一致（`VACUUM INTO` 本身是事务性的）。

## 4. P1｜长任务可靠性

### 4.1 批量任务没有任何退避重试

**现象**

- `_TITLE_BACKFILL_CONCURRENCY = 4`（`scanner.py:1833`）与
  `_SAMPLE_BACKFILL_CONCURRENCY = 3`（`scanner.py:1834`）分别驱动两个批量生成器，
  两者内部都没有任何 `sleep` / backoff / retry 逻辑，全文件只有断连轮询用的两处 `asyncio.sleep`。
- `gemini_client.classify_http_error` 把 429 / 402 / `RESOURCE_EXHAUSTED`
  归类为 `rate_limited`（`core/gemini_client.py:105`），随后直接抛错。

**影响**

- 标题补全：Gemini 一旦限流，剩余每一部都会立刻失败，并且继续以 4 路并发打接口，
  既浪费配额又可能延长限流窗口。2000 部的库可能在第 300 部就全线崩掉。
- 剧照补全：3 路并发直连刮削站点，触发 Cloudflare 后同样整批失败。
- 用户侧只有一个"重跑全量"的选项，没有断点，也没有"只重试失败"。

**建议**

1. 识别 `rate_limited` / `forbidden` / 连续网络错误后，插入指数退避
   （例如 5s → 15s → 45s，最多 3 次），并在 SSE 里推一条 `log` 说明"正在等待限流恢复"。
2. 同一批次内连续 N 次（例如 5 次）限流则整体暂停，推 `done` 并标记
   `paused_reason: "rate_limited"`，让用户决定是否继续。
3. 刮削侧按域名做最小请求间隔（例如同一 host 不小于 1.5s），避免 3 路并发把同一站点打满。

**验证方式**

- 单测：mock 客户端连续返回 429，断言任务在退避后重试且最终暂停，而不是把剩余项全标 failed。
- 单测：mock 第 2 次成功，断言该项被记为 success 而非 failed。

### 4.2 没有前台服务，退到后台任务就"冻住"

**现象**

- `MainActivity.onPause()` 调用 `webView.onPause()`（`MainActivity.java:1246-1254`），
  WebView 的 JS 执行被暂停。
- Python/Uvicorn 跑在 Activity 进程的 daemon thread 里，没有 Service、没有通知栏。
- `docs/target-sdk-upgrade.md` 的结论摘要里也写明："当前 FastAPI/Uvicorn 运行在
  Activity 进程中，退到后台后没有服务生命周期保障。"

**影响**

- 补剧照/补标题跑长任务时，用户切到微信或锁屏：JS 停止读取 SSE → TCP 背压 →
  服务端生成器阻塞 → 任务实际停摆。
- Android 12+ 的 cached app freezer 会进一步冻结进程；内存紧张时进程被回收，
  整批进度直接丢失（数据库里已完成的项还在，但本次任务状态没了）。

**建议**

短期（r42 可做）：任务开始前提示"请保持应用在前台"；回到前台后自动重新拉取
`/missing-check` 刷新进度，并允许从剩余项继续。

中期（单独排期）：前台服务 + 常驻通知（进度条 + 取消按钮），把 Uvicorn 的
生命周期从 Activity 解耦。这与 targetSdk 升级是同一批工作。

### 4.3 点"取消"不会立刻停

**现象**

`scanner.py:2325`：

```python
finally:
    executor.shutdown(wait=True, cancel_futures=True)
```

`cancel_futures=True` 只取消**尚未开始**的任务；已经在跑的 3 个线程会继续执行到结束，
`wait=True` 让生成器一直阻塞到它们全部返回。而前端在 AbortController 触发时
已经显示"已取消"。

**影响**

- 用户看到"已取消"，但后台还在下载、还在写库、还在消耗流量。
- 如果某个下载卡在慢速 CDN 上，取消动作会被拖到几十秒甚至更久。
- 生成器线程被占住期间，同一请求的清理逻辑（`mark_generate_done`）也延后。

**建议**

- 改为 `shutdown(wait=False, cancel_futures=True)`，让在途任务在各自的下一次
  检查点读取 `cancel_event` 后主动退出（`fetch_one` 内部需要在下载循环里检查）。
- 若担心线程泄漏，可保留一个后台清理线程，但不要阻塞 SSE 的 `done` 事件。

**验证方式**

单测：提交一个会 sleep 3 秒的假任务，置位 `cancel_event`，断言 `done` 事件在
500ms 内产出且 `cancelled=true`。

### 4.4 失败项没有"只重试失败"

**现象**

两个批量任务的 `done` 事件都带 `summary.failed_items`（`scanner.py:2328-2352`），
但前端只在 `result-item` 时把失败原因写进日志
（`web/static/js/pages/scanner/state-batch.js:576-589`），
`failed_items` 本身没有被渲染成列表，也没有任何"重试"入口。

**影响**

- 2000 部补剧照里失败 37 部，用户看不到是哪 37 部、各自失败原因是什么。
- 只能整批重跑。虽然 `/missing-check` 会过滤掉已完成的项，重跑不会重复下载，
  但用户无法针对失败项做定向处理（例如换源、补番号后重试）。
- 失败原因不聚合，无法判断是"网络抖动"还是"番号识别失败"，也就无法决定该不该重试。

**建议**

1. `done` 后把 `failed_items` 渲染成可展开列表：番号 + 错误码 + 一句话原因。
2. 提供"只重试这 N 部"按钮，请求体带 `file_paths` 子集，生成器只处理该子集。
3. 按 `error_code` 分组统计（例如 `sample_download_failed: 21`、
   `missing_number: 16`），让用户一眼看出主因。

**验证方式**

单测：给生成器传入 3 条候选、mock 其中 1 条失败，断言 `summary.failed_items`
含且仅含该条，并带正确的 `error_code`。

## 5. P1｜分集能力

### 5.1 分集识别只覆盖一半命名，且不可手动干预

**现象**

`core/multipart_tokens.py:19-22`：

```python
MULTIPART_TOKENS = frozenset({"cd", "dvd", "part", "pt", "disc"})
MULTIPART_RE = re.compile(
    r"(?<![A-Za-z0-9])(cd|dvd|part|pt|disc)([1-9])(?![0-9])"
    r"(?=[-_.\s\[\]()]|$)",
    re.IGNORECASE,
)
```

已确认不支持：

| 命名 | 示例 | 是否识别 |
| --- | --- | --- |
| `cd1` / `cd2` | `ABC-123-cd1.mp4` | 支持 |
| `part1` / `pt2` / `disc1` / `dvd2` | `ABC-123-part2.mp4` | 支持 |
| `cd10` 及以上 | `ABC-123-cd10.mp4` | **不支持**（正则只允许 `[1-9]` 单字符） |
| 前編 / 後編 | `ABC-123-前編.mp4` | **不支持**（全项目 grep 无匹配） |
| 上巻 / 下巻 | `ABC-123-上巻.mp4` | **不支持** |
| `-1` / `-2` 后缀 | `ABC-123-1.mp4` | **不支持**（会与番号本身混淆） |
| `A` / `B` 后缀 | `ABC-123A.mp4` | **不支持** |

同时，前端没有任何"手动合并/拆分分集"的入口（已 grep `showcase/*.js`）。

**影响**

- 日系片源里 前編/後編、上巻/下巻 很常见，这类片子会一直显示为两张独立卡片。
- 独立卡片意味着：不能分段续播、不能共用剧照、补剧照时会被
  `multi_video_folder` 直接拒绝（因为同文件夹里有两部"无关"影片）。
- 用户没有任何自救手段——分组是纯自动的，识别不到就只能手动改文件名。

**建议**

1. 扩展 token 表：`zenpen`/`kouhen`、`前編`/`後編`、`上巻`/`下巻`、`vol`/`volume`。
   注意「前/後」不是数字，需要在 `VideoGroup` 里允许非数字段号（用固定顺序映射 1/2）。
2. 把 `([1-9])` 放宽到 `([1-9][0-9]?)`，覆盖 cd10 以上的长合集。
3. `-1`/`-2` 这类后缀风险高（容易和番号尾部数字冲突），建议只在
   "同文件夹 + 剥后缀后 stem 完全相同 + 成员数 ≥ 2" 三重条件下才启用。
4. 补一个手动覆盖：数据库加 `multipart_override` 表（group_key → 成员列表），
   列表页右键/长按提供"合并为分集"与"拆分为独立影片"。

**验证方式**

- 每条新规则一组参数化测试：文件名 → 期望的分组结果。
- 回归：现有 8 个多分段测试（`tests/test_multipart_backfill_and_player.py`）必须全绿。
- 必须同步更新 `patches/`，否则 CI 的 `verify_python_sync.py` 会失败。

## 6. P2｜体验一致性

### 6.1 从搜索页播放丢分段信息

**现象**

`web/templates/search.html:71` 与 `:1088` 的播放按钮只传一个路径字符串：

```js
window.openVideoPlayer(currentLightboxVideo()?._localStatus?.paths?.[0] || '')
```

没有传 `part_paths`。而片库页 `state-videos.js:1088-1115` 已经改成传
`{ parts, labels }`。

**影响**

安卓端 `openVideoPlayer` 走 `openaver-player://` scheme，`ExternalPlayer.open`
只有在 `parts.length > 1` 时才弹分段选择框。从搜索页播放 cd1/cd2 影片时
**永远不会弹框**，直接播第 1 段，且没有切换入口。

**建议**

让搜索页复用同一套数据：把 `_localStatus` 里的多路径映射成
`{ parts: paths, labels: part_tokens }` 再调用。若搜索结果的 `_localStatus`
不携带 `part_tokens`，需要后端在搜索结果序列化时补上（或前端按路径再查一次）。

**验证方式**

在 API 36 模拟器上：搜索 → 打开 cd1/cd2 影片 → 点播放 → 应弹出"选择要播放的分段"。

### 6.2 没有外部播放器时无兜底

**现象**

`MainActivity.java:998-1003`：

```java
if ("openaver-player".equals(scheme)) {
    ExternalPlayer.open(
            this,
            uri.getQueryParameter("path"),
            uri.getQueryParameter("parts")
    );
    return true;
}
```

`ExternalPlayer.open()` 的布尔返回值被忽略，无论成功、失败还是用户取消，都 `return true`。
`openSelected()` 内部失败时只弹一句 `video_player_missing` 的 toast。

**影响**

- 设备上没有任何能处理 `video/*` 的应用时（精简 ROM、视频应用被禁用/卸载），
  点播放只看到一句提示，没有第二次机会。
- 安卓端 UI 实际上**从不使用内置网页播放器**：`window.openVideoPlayer` 恒有定义，
  在 Android UA 下必定跳 scheme。用户没有"用内置播放器打开"的选择。

**建议**

1. 接收 `ExternalPlayer.open()` 的返回值，失败时回退到
   `openLocalPath("/api/gallery/player?path=" + encodeURIComponent(path))`。
2. 分段选择框里加一项"用内置播放器播放"，给 MP4/H.264 用户一个确定可用的路径。
3. 顺手修正 README：`## 限制` 里"播放能力取决于手机系统 WebView 编解码器"这句
   只对内置播放器成立，App 内默认走外部播放器，MKV/AVI 是否可播取决于所选外部应用。

**验证方式**

模拟器上临时禁用/卸载所有视频应用，点播放应落到内置播放器而不是只弹 toast。

## 7. 依赖与工程债

### 7.1 依赖版本线落后于上游安全基线（P2）

| 包 | 上游 `requirements.txt` | 移动端 `app/build.gradle` | 差异 |
| --- | --- | --- | --- |
| pydantic | 2.13.4 | **1.10.24** | 大版本回退 |
| pillow | 12.3.0 | **11.0.0** | 落后一个大版本 |
| starlette | 1.6.0 | **0.50.0** | 落后一个主版本线 |
| fastapi | 0.136.1 | **0.125.0** | 落后 |
| lxml | 6.1.0 | **5.3.0** | 落后 |

**根因**：Android 没有 `pydantic-core`（Rust 扩展）的 arm64 wheel，只能退到纯 Python
的 pydantic v1；FastAPI/Starlette 随之降级；`patches/001-pydantic-v1-compat.patch`
提供了 `model_dump` / `model_validate` / `model_copy` 等少量 v2 API 的 shim。

**风险**

- 上游 `requirements.txt` 的注释明确写了这些 pin 是为清 CVE 而锁的，
  pillow 那批包含 crop/paste/alpha_composite 的堆越界写。移动端解码的正是
  从刮削站点抓回的图片，攻击面真实存在。
- starlette 的两条（StaticFiles UNC/SMB、multipart form DoS）需要逐条判断
  在 Android 上是否可达——UNC 那条在 Android 上基本不成立，form DoS 需要确认。
- shim 是手写白名单，上游一旦使用新的 v2 API（例如 `model_dump_json`、
  `TypeAdapter`），运行期才会炸，且报错信息不直观。

**建议**

1. 先确认 Chaquopy 的 wheel 仓库里 pillow 能升到哪个版本，能升就升（这条收益最大、
   改动最小）。
2. lxml 同理，确认有 aarch64 wheel 后升级。
3. pydantic v1 短期绕不过，建议在 `patches/README.md` 里记录为已知债务，
   并给 shim 补一组"上游实际调用点"的契约测试，让上游升级时能立刻发现缺口。
4. 长期方案是自建 `pydantic-core` 的 Android wheel（需要 Rust + NDK 交叉编译），
   成本高，不建议短期投入。

### 7.2 Java 层零测试、JS 未进 CI（P3）

- `app/src/androidTest` 与 `app/src/test` 都不存在，3,904 行 Java 没有任何自动化测试，
  其中 `MainActivity` 1,473 行包含 WebView 生命周期、权限、渲染进程回收等易错逻辑。
- `.github/workflows/build.yml` 只跑 `verify_python_sync.py`、`pytest`、`code_health.py`
  和构建；`node --check` 是手工步骤，没有进 CI。
- 前端有大量 `state-*.js`，但没有任何 JS 测试。

**建议**

1. CI 加一步 `node --check` 遍历 `web/static/js/**/*.js`（成本几乎为零）。
2. 至少给 `ExternalPlayer.parseParts()`、`StorageBridge` 的路径归一化写 JVM 单测
   （纯逻辑，不需要设备）。
3. `MainActivity` 的渲染进程回收逻辑可以抽成不依赖 Android 框架的状态机再测。

### 7.3 targetSdk 29 技术债与 16KB 页（P3）

- `docs/target-sdk-upgrade.md` 已经做了完整评估，但没有执行。
- 该文档自己也指出：升级前必须检查所有 native `.so` 的 16 KB 页对齐，
  包括自建 `libopenaver_mobile.so`、Chaquopy/CPython 和 pip 扩展模块。
- 当前 `targetSdk 29` + `requestLegacyExternalStorage` + `MANAGE_EXTERNAL_STORAGE`
  的组合只适合侧载，不能上架。

**建议**：不急于在 r42 处理，但建议在 r42 发布前跑一次
`zipalign -c -P 16 -v 4` 检查现有 APK 的 16KB 对齐情况，把结果记进该文档，
避免将来 Android 15+ 设备上出现"装得上但起不来"。

### 7.4 patch 体量与升级成本（P3）

| 补丁 | 大小 |
| --- | --- |
| `005-android-file-writeback.patch` | 204,650 B |
| `006-mobile-web-routers.patch` | 143,333 B |
| `007-mobile-ui-and-localization.patch` | **632,830 B** |
| 其余 5 个 | 各 1–12 KB |

`007` 单个补丁 632 KB，意味着任何上游前端改动都可能触发大面积冲突。
这是"上游 + 补丁"模式的固有成本，短期内无解，但可以降低：

- 把纯新增文件（移动端专属的路由/模板）从 diff 补丁里拆出来，改为"整文件新增"，
  减少上下文行数。
- 在 `patches/README.md` 里维护一张"上游文件 → 负责补丁"的映射，升级时按文件定位冲突。

### 7.5 内存：无 `onTrimMemory` + `largeHeap="true"`（P3）

- `AndroidManifest.xml:26` 开启 `largeHeap`，`MainActivity` 没有覆写
  `onTrimMemory` / `onLowMemory`。
- 缩略图生成有全局并发闸门（`_MAX_CONCURRENT_GENERATES = 2`，
  `core/thumbnail_cache.py:57`），这点是好的；但缓存本身没有自动上限。

**建议**

1. 覆写 `onTrimMemory(TRIM_MEMORY_RUNNING_LOW/CRITICAL)`：清空 WebView 的
   `freeMemory()`、丢弃封面位图、必要时重建 WebView。
2. 给 `thumb/` 加容量上限（例如 300 MB）与 LRU 淘汰；现在只能靠
   "关闭封面缩略图缓存"开关整体清空（`/api/gallery/thumb/clear`，`gallery_media.py:590`）。
3. `largeHeap` 建议保留但在文档里注明"这是兜底，不是设计目标"，避免后续开发依赖它。

## 8. r42 建议范围

建议把 r42 拆成"小改动、可验证"的一批，把有设计风险的单独立项。

### 建议纳入 r42

| 项 | 改动面 | 风险 | 验证 |
| --- | --- | --- | --- |
| 3.1 数据库导出/恢复 | 新增路由 + 设置页两个按钮 | 低（新增为主） | 单测 + 手工导出/恢复 |
| 4.3 取消立即生效 | `scanner.py` 一处 + 下载循环检查点 | 低 | 新增 1 个时序测试 |
| 4.4 失败项列表 + 定向重试 | 前端一处列表 + 生成器支持子集入参 | 低 | 新增 1 个失败汇总测试 |
| 6.1 搜索页带分段 | `search.html` 两处 + 可能补后端字段 | 低 | 模拟器手工验证 |
| 6.2 播放器兜底 | `MainActivity` 一处 + 对话框加一项 | 低 | 模拟器禁用播放器验证 |

### 建议单独立项

- **5.1 分集识别扩展 + 手动合并**：要动 `multipart_tokens`、`multipart_group`、
  数据库 schema 和前端，必须同步 patches 并补一整组参数化测试，工作量约等于
  一次完整迭代。
- **4.1 退避重试**：需要设计退避策略、暂停语义和 SSE 事件契约，还要区分
  "限流"与"真的没有资源"，建议单独一轮并配 mock 测试。
- **4.2 前台服务**：与 targetSdk 升级绑在一起做，单独排期。

### 发布前检查清单（沿用现有流程）

```
pytest tests/ -q
tools/verify_python_sync.py --upstream-root ..\openaver-upstream-v0.17.18 --source-root app\src\main\python
node --check app/src/main/python/web/static/js/pages/player.js
git diff --check
```

改了 `app/src/main/python` 下任何文件，必须同步重新生成 `patches/`。

## 9. 待验证事项

以下结论基于代码阅读，尚未在设备上实测，落地前需要确认：

1. **Chaquopy 仓库里 pillow / lxml 的可升级上限**——决定 7.1 能做到什么程度。
2. **starlette 0.50.0 是否受 CVE-2026-54283（multipart form DoS）影响**——
   需要查该 CVE 的受影响版本区间，以及移动端是否暴露 multipart 上传入口。
3. **搜索结果是否携带 `part_tokens`**——决定 6.1 是纯前端改动还是需要动后端序列化。
4. **16 KB 页对齐现状**——对现有 r41 APK 跑一次 `zipalign -c -P 16 -v 4`。
5. **取消语义在真实网络下的表现**——当前"在途任务继续跑完"的时长取决于 CDN，
   需要实测一次典型剧照下载的耗时分布。

## 附录 A｜已确认不是问题的点

审查中重点看过、结论为"实现正确、不需要改"的部分，记录在此避免重复排查：

- **SQLite 并发**：WAL + `busy_timeout=5000` + `timeout=5.0`
  （`core/database/connection.py:35,40,43`），3 路补图并发不会触发 `database is locked`。
- **回环鉴权**：`mobile_auth.LoopbackAuth` 用 `secrets.token_urlsafe(32)` +
  `compare_digest`，Cookie 带 `HttpOnly; SameSite=Strict`，健康检查单独放行。
- **端口占用**：`openaver_boot._bind_server_socket` 从首选端口向后扫 21 个端口，
  先 bind 再交给 Uvicorn，端口冲突不会 `exit(1)`。
- **渲染进程回收**：`MainActivity.recoverWebView` 会销毁死掉的 WebView、重建、
  重新注入 Cookie，并对 15 秒内的重复崩溃做熔断，避免无限重载。
- **缩略图并发生成**：全局 `BoundedSemaphore(2)`，避免一屏 120 张封面把
  Starlette 线程池占满（`core/thumbnail_cache.py:57`）。
- **日志体积**：`RotatingFileHandler` 10 MB × 5 备份，有上限
  （`core/logger.py:66-69`）。
- **原子写**：封面/NFO/缩略图都走 `core.atomic_write`，配合 per-thumb 锁，
  关闭了"enrich 覆写封面 → serve 旧缩略图"的竞态。
- **补剧照的文件夹守卫**：`fetch_samples_endpoint` 要求分组成员数等于文件夹
  DB 行数，混入无关视频时拒绝，不会串图（`scraper.py:1030-1046`）。
- **批量补图的重复调度**：`_dedupe_multipart_sample_candidates` 按组去重，
  cd1/cd2 不会并发抓两次（`scanner.py:1688-1726`）。
