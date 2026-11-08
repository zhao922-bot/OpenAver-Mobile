# OpenAver Mobile r47 之后：建议清单

> **基线**：r47（`v0.17.18-android-r47`，versionCode 17063，2026-11-08 已发布）
> **撰写**：2026-11-08
> **性质**：**建议**，不是计划。每条给证据、成本、不做的后果；第 7 节专门写"不建议做的事"。
> 文中所有数字均为本次实测，不是估算。

---

## 0. 一页结论

| # | 建议 | 优先级 | 成本 | 我的判断 |
|---|---|---|---|---|
| 1 | 补三个 release 的说明正文 | **高**（性价比） | 10 分钟 | **立刻做** |
| 2 | 把 4 处 pydantic v1 写法改成 v2 写法 | 中 | 1 小时 | **现在做**（不需要升级 pydantic） |
| 3 | 放弃"升级 pydantic"的念头，先接受 2.12.5 是天花板 | — | 0 | **这是结论，不是任务** |
| 4 | patch 层瘦身 | 低 | 数天 | **先别动**，先测量 |
| 5 | 升 `targetSdk` | 低 | 数天 | **不要为升而升** |

一句话：**这个项目现在的状态比它看起来健康。** r45→r47 把能修的都修完了，剩下的是"结构性选择"，不是"待办缺陷"。唯一立刻值得做的是第 1 条，唯一现在值得动代码的是第 2 条。

---

## 1. 判断依据（r47 实测）

| 项目 | 值 | 说明 |
|---|---|---|
| 测试 | 212 passed, 0 skipped | r44 是 193/2 |
| Python 同步 | 451 files match | `verify_python_sync.py` |
| APK | 30,030,256 B | r45→r46→r47 各 +880 / +628 B |
| patch 层 | 1,437,753 B / 8 个文件 | `007` 单个 871,904 B |
| 原生库 | **21/21 个 `.so` 的 LOAD 段 `p_align = 0x4000`** | 见第 5.3 节，这条推翻了一个旧说法 |
| APK 内 urllib3 | 2.8.0（已钉） | r46 起显式声明 |
| 弃用警告 | 4 条 | 3 个 `class Config` + 1 个 `@validator` |

---

## 2. 建议一：把 release 说明补上

### 2.1 现状

三个 release 的 body 完全一样，除了版本号：

```
## OpenAver Mobile v0.17.18-android-r47

- versionName: 0.17.18-r47
- versionCode: 17063
- ABI: arm64-v8a

**Full Changelog**: https://github.com/.../compare/r46...r47
```

`Full Changelog` 链接指向 GitHub 的 commit diff —— 对下载 APK 的普通用户没有任何意义。

### 2.2 为什么值得

README 里的版本说明写得**很好**：

> r46：网络重试尊重服务端 `Retry-After`，但最长只等待 15 秒，避免刮削或批量任务因单个异常响应长时间卡住
> r47：数据库导入前检查可用存储空间，空间不足时明确提示所需容量

问题是：**下载 APK 的人看的是 release 页，不是 README。** release 页是唯一一个"用户在下载前一定会看"的界面，而它现在是空的。写好的文案放错了地方。

### 2.3 建议动作

把 README 里对应的那两行直接搬到 release body。建议格式：

```markdown
## 本版变更

- 网络重试尊重服务端 `Retry-After`，但最长只等待 15 秒，避免单个异常响应让
  刮削或批量任务长时间卡住
- 数据库导入回滚路径补充测试覆盖
- 本地化依赖缺失时改为硬失败，不再静默跳过

## 安装

下载 `openaver-v0.17.18-android-r46-arm64-v8a.apk` 直接安装。
升级会保留数据库与配置；如需回滚，先导出数据库备份。

- 版本：`0.17.18-r46`（versionCode `17062`）
- 架构：`arm64-v8a`，Android 10+
- SHA-256：见 `SHA256SUMS.txt`
```

r45 / r46 / r47 三个都补。

### 2.4 不做的后果

没有功能性后果。但这是全项目**唯一一个投入产出比超过 100 倍**的改动——10 分钟换一个用户能看懂的变更说明。

---

## 3. 建议二与三：pydantic 的真实处境

### 3.1 先纠正一个我自己说过的说法

我在 r47 评价里说"pydantic 3 一出就全断，这是目前唯一一个确定会爆的雷"。

**这个说法不准确。** 实测：

- PyPI 上 pydantic 最新是 **2.14.3**
- **3.x 系列尚未发布**（`releases` 里没有任何 3.x 版本）

所以不是"v3 要来了"，而是"v1 写法在 2.x 上被标记为 `removed in V3.0`，时间未定"。

### 3.2 真正的问题：项目被钉死在 2.12.5，而且动不了

`app/build.gradle` 里 `install("pydantic==2.12.5")`，配 `app/wheels/pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl`。

pydantic 和 pydantic-core 是**精确 `==` 绑定**的：

| pydantic | 需要的 pydantic-core | cp313 android wheel |
|---|---|---|
| 2.12.5 | 2.41.5 | ✅ 已有（vendored） |
| 2.13.5 | 2.46.5 | ❌ 不存在 |
| 2.14.3（最新） | 2.50.4 | ❌ 不存在 |

TUR 索引里 cp313 的 `pydantic_core` 只有两个版本：

```
pydantic_core-2.35.2-cp313-cp313-android_24_arm64_v8a.whl
pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl
```

而 cp314 一直排到 `2.50.4`。

**结论：在 Python 3.13 上，pydantic 2.12.5 就是天花板。** 不是"我们选择不升级"，是"没有可用的 core wheel 可升"。这一点 `app/wheels/README.md` 里其实已经写清楚了（"Upgrading pydantic requires a matching core wheel"），只是没人把它当成一个战略约束来看。

### 3.3 三条出路，都不该现在走

**出路 A：留在 2.12.5。**

代价：拿不到 2.13/2.14 的任何修复。收益：什么都不用做，且 2.12.5 是 pydantic v2 成熟版本，没有已知的严重问题。

**这是当前推荐。** 一个纯本地、单用户、不做公网 API 的 App，pydantic 的小版本差异几乎不可感知。

**出路 B：把 Chaquopy 切到 Python 3.14。**

有个反直觉的好消息：**项目用的 Chaquopy 17.2.0 已经支持 Python 3.14.8**（甚至 3.15）。不需要升级插件，只要把 `chaquopy.defaultConfig.version` 从 `"3.13"` 改成 `"3.14"`。

坏消息是那只是第一步。切 3.14 意味着**每一个带原生扩展的依赖**都要有 cp314 的 android wheel：

| 依赖 | 现状 | cp314 风险 |
|---|---|---|
| `pydantic-core` | 2.41.5 cp313 | ✅ TUR 有 2.50.4 cp314 |
| `lxml` | 5.3.0 | ⚠️ TUR 只有 `lxml-6.1.1-cp314`，要跨大版本 |
| `pillow` | 11.0.0 | ❓ TUR 索引里**查不到**任何 arm64 android wheel |
| `PyYAML` / `httptools` 等 | — | ❓ 未核对 |

注：`lxml` / `pillow` 实际来自 Chaquopy 自带的包索引（不是 TUR），要判断 3.14 可行性必须**逐个核对 Chaquopy 索引**，这一步本次没做。所以"3.14 可行"目前是**未知**，不是"可行"。

**结论：3.14 迁移是一个独立项目，不是一次版本号修改。** 不建议在 r48/r49 顺手做。

**出路 C：自己编 pydantic-core 的 cp313 android wheel。**

需要 android NDK + maturin + 交叉编译，且要保证 16 KB 对齐（TUR 的 2.41.5 恰好是 0x4000）。技术可行，维护成本高，收益只是"能升一个小版本"。**不值得。**

### 3.4 无论走哪条，现在就该做的事：改掉 4 处 v1 写法

这一条**不依赖任何版本升级**，在 2.12.5 上就能做，且能立刻消掉全部 4 条弃用警告。

**低成本、零风险的三处**（`frozen = True`，语义完全等价）：

| 文件 | 行 | 改法 |
|---|---|---|
| `core/proxy_policy.py` | `:33` | `class Config: frozen = True` → `model_config = ConfigDict(frozen=True)` |
| `core/scrapers/models.py` | `:10` | 同上（`Actress`） |
| `core/scrapers/models.py` | `:18` | 同上（`Video`） |

**需要单独评估的一处**（`core/source_config.py:50`）：

```python
@validator('requires_proxy', always=True)
def _derive_requires_proxy(cls, value, values) -> bool:
    if values.get('type') == 'builtin':
        return values.get('id') in PROXY_SOURCES
    return value
```

v2 的等价写法**不是**简单替换：

```python
model_config = ConfigDict(validate_default=True)   # 对应 always=True

@field_validator('requires_proxy')
@classmethod
def _derive_requires_proxy(cls, value, info: ValidationInfo) -> bool:
    if info.data.get('type') == 'builtin':
        return info.data.get('id') in PROXY_SOURCES
    return value
```

三个坑：

1. `always=True` 要靠 `validate_default=True` 补回来，否则字段没传时校验器不跑
2. `values` → `info.data`，且 `info.data` 只包含**已经校验过的前序字段**（`type` 在 `requires_proxy` 之前，OK；如果顺序变了会静默失效）
3. 同文件 `:100-105` 有个 `model_dump()` 覆盖层（把 `is_censored` 塞进输出）。它和 `@validator` 的时序无关，但两者都建立在"当前 v2 语义"上——改校验器时要把这条一起回归

**建议**：三处 `class Config` 单独一个提交（5 分钟）；`@validator` 单独一个提交 + 跑 `test_r43_localization` 与 source_config 相关测试。

### 3.5 为什么值得做

不是为了"将来好升级 pydantic"（那件事短期做不了），而是：

- 4 条警告每次跑测试都在刷，会训练人忽略警告——这是测试卫生问题
- `class Config` / `@validator` 是**已经宣布要删**的 API，删的时候不会给你兼容期
- 三处 `frozen` 的改动成本接近零，纯粹是"趁早"

---

## 4. 建议四：patch 层瘦身 —— 先测量，别动手

### 4.1 现状

```
   1577  patches/001-pydantic-v1-compat.patch
  16410  patches/002-mobile-bootstrap.patch
   9949  patches/003-android-native-focal.patch
  12337  patches/004-network-and-scraper-fallbacks.patch
 230135  patches/005-android-file-writeback.patch
 293519  patches/006-mobile-web-routers.patch
 871904  patches/007-mobile-ui-and-localization.patch
   1922  patches/008-mobile-loopback-auth.patch
-------------------------------------------
1437753  合计
```

### 4.2 `007` 的构成（这是关键）

`007` 覆盖 **61 个文件、10,512 行新增**。按新增行排序：

| 文件 | 新增行 | 占比 |
|---|---|---|
| `web/static/css/theme.css` | 1154 | 11.0% |
| `web/static/css/pages/scanner.css` | 915 | 8.7% |
| `locales/zh_TW.json` | 748 | 7.1% |
| `web/static/js/pages/scanner/state-scan.js` | 717 | 6.8% |
| `locales/zh_CN.json` | 689 | 6.6% |
| `locales/ja.json` | 688 | 6.5% |
| `locales/en.json` | 688 | 6.5% |
| `web/templates/scanner.html` | 644 | 6.1% |
| `web/static/js/pages/scanner/state-batch.js` | 535 | 5.1% |
| `web/static/css/pages/settings.css` | 436 | 4.1% |

**四个 locale JSON 文件合计 2,813 行 = `007` 的 26.8%。**

### 4.3 为什么这是问题（不是体积）

871 KB 的文本补丁对 git 毫无压力。真正的问题是**冲突面**：

- locale 文件是上游**改动最频繁**的文件（r43 一次性加了 2286 个 key × 4 语言）
- 一个 748 行的连续新增块插在 `zh_TW.json` 中间，上游只要在附近加一个 key，补丁就可能冲突
- `verify_python_sync.py` 要求补丁重放后**逐字节**匹配，冲突的代价不是"改一下"，是"重新生成整层"

CSS 同理：`theme.css` 1154 行新增，上游改主题就撞。

### 4.4 三个选项

| 选项 | 做法 | 代价 | 收益 |
|---|---|---|---|
| A | 不动 | 0 | 0 |
| B | locale 改成独立覆盖层（`locales/mobile_overlay.json`，加载时 merge） | 改 `core/i18n.py` 加载逻辑 + 4 个测试 | `007` 少 26.8%，且 locale 永不再冲突 |
| C | 重构整个补丁体系（按目录拆、改成 overlay 挂载） | 数天，高风险 | 最大，但会动到所有已发布版本的构建可复现性 |

### 4.5 建议：**选 A，先别动**

理由：

1. **现在没有痛感。** 上一次上游同步冲突是什么时候？如果记不起来，说明这不是当前瓶颈。
2. **B 的收益被高估。** 26.8% 的行数，但 locale 是 JSON，diff 干净、重放稳定；真正的冲突源更可能是 `state-scan.js`（717 行，逻辑代码）。
3. **C 会破坏可复现性。** r42–r47 六个已发布版本都基于当前补丁体系，重构后无法验证"同一个 tag 还能构建出同样的 APK"。这个代价远大于 871 KB。

**如果一定要动**，先做一件不花钱的事：记录一次"上游同步演练"——拿最新的上游 v0.17.18 重放全部补丁，**统计实际冲突了几个文件、几个 hunk**。有这个数据再决定 B 还是 C。没有数据就重构，是在用数天换一个想象中的问题。

---

## 5. 建议五：`targetSdk` 不要为了升而升

### 5.1 现状

`app/build.gradle`：`minSdk 29` / `targetSdk 29`。Manifest 里：

```xml
<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="29" />
<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="29" />
<uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE" tools:ignore="ScopedStorage" />
```

即：API 30+ 完全依赖 `MANAGE_EXTERNAL_STORAGE`（"所有文件访问"）。

### 5.2 升到 35 会撞的四件事（逐条有据）

**① 通知会消失。** 全局搜 `requestPermissions`，只有 `MainActivity.java:339-363` 在申请存储权限，**没有任何地方申请 `POST_NOTIFICATIONS`**。

现在 `targetSdk 29 < 33`，系统在首次创建通知渠道时自动弹权限框；一旦 `targetSdk >= 33`，必须显式 `requestPermissions`，否则前台服务的通知**永远不显示**——任务还在跑，但用户看不到任何迹象，也没法从通知栏回到 App。

**② 状态栏颜色失效。** `MainActivity.java:226-227`：

```java
window.setStatusBarColor(getColor(R.color.bg));
window.setNavigationBarColor(getColor(R.color.bg));
```

`targetSdk 35` 起强制 edge-to-edge，这两个调用**变成 no-op**。深色主题的 App 会突然出现系统默认的浅色状态栏，或内容顶到状态栏下面。要么改用 `enableEdgeToEdge()` + `WindowInsets`，要么加 `windowOptOutEdgeToEdgeEnforcement`（只是过渡）。

**③ 前台服务被限时。** `targetSdk 34+` 要求声明 `FOREGROUND_SERVICE_DATA_SYNC` 权限（现在只有 `FOREGROUND_SERVICE`）；`targetSdk 35+` 的 `dataSync` 类型有 **6 小时 / 24 小时**上限。r45 刚做的保活机制会被削一刀。

**④ 16 KB 页——这条不是问题，见 5.3。**

### 5.3 关于 16 KB 页：需要更正一个说法

我之前说过"`targetSdk` 还是 29，TUR wheel 的 16 KB 对齐收益**尚未兑现**，是prospective 的"。

**这个说法错了。** 本次实测 r47 APK：

- 全部 **21 个 `.so`**（`libpython3.13.so`、`libchaquopy_java.so`、`libopenaver_mobile.so`、`libsqlite3_python.so`、`libssl_python.so`、全部 bootstrap 扩展）的 LOAD 段 `p_align` **都是 `0x4000`**
- 这些 `.so` 在 APK 内是 **DEFLATED（压缩存储）**，说明 `extractNativeLibs=true`，安装时解压到磁盘再加载 → **ELF 对齐就是唯一决定因素，zip 内对齐不参与**

结论：**16 KB 页支持已经兑现了**，和 `targetSdk` 无关。`targetSdk` 只影响 Google Play 的上架政策，而这个 App 是通过 GitHub Releases 侧载分发的。

所以"为了 16 KB 去升 targetSdk"这个理由**不存在**。

### 5.4 结论

**不建议主动升 `targetSdk`。** 当前 29 对侧载分发完全够用，升上去要付：通知权限改造、edge-to-edge 改造、FGS 类型与限时、以及一轮完整的手工回归。收益是"更符合 Play 政策"，而这里不上 Play。

**什么情况下必须升**：

1. 要上 Google Play（那 16 KB 是硬要求，且 `MANAGE_EXTERNAL_STORAGE` 需要单独申请豁免——大概率过不了）
2. 某个必须支持的新 API 只在 33+ 可用
3. Android 未来版本对 `targetSdk` 过低的应用开始弹"此应用可能无法运行"的警告

第 3 条值得盯。如果哪天出现了，再按 ① → ② → ③ 的顺序分三次升（33 / 34 / 35），每次单独出包，不要一次跳。

---

## 6. 建议六：四个小项

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| 1 | `docs/r47-plan.md` | 写"7 个 `TextView` 均显式设置 `textColor`"，实际是 **8 个**（`menuTitle` / `menuServer` / `menuRefresh` / `menuScanner` / `menuStorageSettings` / `menuStorageTree` / `menuAbout` / `menuExit`） | 改成 8。结论不变，但这条是"以证据结案"的条目，数字要准 |
| 2 | `database_backup.py:_require_free_space` | 用 `declared_total * 2` 判断，而 `declared_total` 来自 ZIP 中央目录。损坏/恶意 ZIP 可以少报大小绕过预检，然后写到一半 ENOSPC，又被归因成"ZIP 格式无效" | 低优先。若要修：在写入循环里同步检查 `shutil.disk_usage().free`，或把 `written_total` 的检查从"超上限"扩展成"超可用空间" |
| 3 | `core/generate_state.py:157` | `is_generate_in_progress()` 被 `database_backup.py` 用来判断"是否有任务在跑"，但扫描任务也注册在同一个 `_active_tokens` 里。函数名和行为不符 | 重命名为 `is_task_in_progress()`，或加 docstring 说明"含扫描与生成"。纯可读性 |
| 4 | `core/source_config.py:100-105` | 注释写 "Keep the computed contract identical on both versions"，但 v1 路径早已删除，现在只有 v2 | 注释过期，改成说明"`is_censored` 是 computed property，`model_dump()` 不会自动带上" |

---

## 7. 不建议做的事

这一节和上面同等重要。

**① 不要为了 16 KB 升 `targetSdk`。** 已经对齐了，见 5.3。这是本次实测推翻的最大一个假设。

**② 不要现在迁 Python 3.14。** Chaquopy 支持不代表依赖链支持。`lxml` / `pillow` 的 cp314 可用性尚未核对，这可能是数天的工作量，收益只是"能升 pydantic 一个小版本"。

**③ 不要重写补丁体系。** 会破坏 r42–r47 六个已发布版本的可复现构建。要动先做"上游同步演练"拿冲突数据。

**④ 不要给通知加任务名文案。** r47 刚删掉这个死参数，是对的。5 个 `strings.xml` 加 15–20 条字符串换一个"正在刮削"的标题，不划算。

**⑤ 不要把 `targetSdk 29` 当成技术债来还。** 它是**当前分发的正确选择**，不是欠账。只有在分发渠道变化时才需要重新评估。

---

## 8. 我的排序

如果只做一件事：**第 2 节，补 release 说明。** 10 分钟，立刻改善唯一面向用户的交付面。

如果有一小时：**再加第 3.4 节的三处 `class Config`。** 5 分钟改完，消掉 3 条警告，零风险。

如果有一个下午：**加 `@validator` → `@field_validator` 的迁移。** 这是唯一需要认真对待的一项，因为有 `validate_default` 和 `info.data` 两个语义坑，且要回归 `model_dump()` 覆盖层。

其余四项（patch 瘦身、`targetSdk`、Python 3.14、小项清理）**建议都不做**，直到出现真实的痛感。这个项目现在的问题不是"做得不够"，是"没有新的问题"——这是好事，不该用重构去填满它。
