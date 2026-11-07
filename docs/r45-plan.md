# OpenAver Mobile r45 计划

> 基线：`v0.17.18-android-r44`（commit `90c3f0f`，versionCode 17060）
> 目标：`v0.17.18-android-r45`（versionCode 17061）
> 范围：只做 5 项，不做其它
> 状态：已执行，发布中（2026-11-07）

## 执行结果（2026-11-07）

- TUR 与 Cleanup 两套全量测试均为 `207 passed`。
- 全部前端 JavaScript 通过 `node --check`。
- Python patches 已重新生成，`verify_python_sync.py` 校验 `451 files match`。
- API 36 模拟器 `emulator-5554` 已验证数据库导入、四语言原生播放器选择框、
  四语言前台服务通知、拒绝通知权限时的后台保活、退到桌面后的任务继续执行。
- r45 的 `targetSdk` 仍为 29。Android 13+ 不应由 App 主动调用
  `requestPermissions(POST_NOTIFICATIONS)`；否则系统可能立即自动关闭授权页。
  当前实现创建通知渠道后直接启动前台 Service。拒绝通知权限不会终止任务，
  授予通知权限后通知栏会显示四语言对应的任务通知。
- arm64-v8a 的 Debug 与 Release 构建均成功。本机未提供 release 签名环境变量，
  本地 Release 产物为未签名 APK；正式签名包由 GitHub Release workflow 使用仓库
  Secrets 构建并上传。

---

## 0. 摘要

r44 之后仍遗留 5 项问题，本计划只处理这 5 项，不夹带任何其它改动。

| # | 问题 | 级别 | 改动面 | 风险 | 建议批次 |
| --- | --- | --- | --- | --- | --- |
| 1 | 数据库只导出不导入 | P0 | 后端 1 文件 + 前端 1 文件 | 中 | B |
| 2 | 两条本地化测试永远 skip | P2 | 依赖 1 行 | 极低 | A |
| 3 | 对话框主题硬编码 | P3 | 资源 1 文件 + Java 2 文件 | 极低 | A |
| 4 | 无退避重试 | P1 | 后端 1 文件 | 中 | C |
| 5 | 无前台服务 | P1 | 新增 Service + Manifest + Java + JS | 高 | D |

**执行顺序建议 A → B → C → D**，理由：A 批两项零风险、十分钟可完成、能立刻兑现收益；B 是唯一的功能缺口；C 改变网络行为，需要独立验证；D 引入新组件，最需要单独一轮回归。

如果四批全部一次做完再发布，出问题时无法判断是哪一项引起的。建议 **A+B 出 r45，C+D 出 r46**；若必须一次发，至少保证 A/B/C/D 各自单独 commit，便于二分回滚。

---

## 1. 范围与边界

### 1.1 本计划包含

1. 数据库导入/恢复端点 + 设置页入口
2. `opencc` 加入测试依赖，让两条守门测试真正执行
3. 6 处 `AlertDialog` 主题统一为应用自定义主题
4. `proxy_policy.new_session()` 挂载 urllib3 重试适配器
5. 前台保活 Service + 前端任务生命周期钩子

### 1.2 本计划**不**包含

- 不改 `targetSdk`（仍为 29）
- 不加 `onTrimMemory`
- 不改缩略图缓存上限
- 不扩展分集识别词表（`core/multipart_tokens.py` 不动）
- 不改 r44 播放器选择框的"记住选择"（用户未列入范围）
- 不清理 pydantic v1 弃用警告
- 不拆分 patch 层

### 1.3 硬约束

| 约束 | 说明 |
| --- | --- |
| 版本号 | versionCode `17061`、versionName `0.17.18-r45`、tag `v0.17.18-android-r45` |
| 不动 r41–r44 | 已发布的 tag 和 release 一律不碰 |
| 不用 `git add -A` | 根目录有大量诊断文件，逐文件 `git add` |
| 不破坏性操作 | 禁止 `reset --hard`、`checkout --`、强推、amend |
| patches 同步 | 改 `app/src/main/python` 后必须跑 `tools/generate_patches.py` |
| 不自动发布 | 除非明确要求，不提交、不打 tag、不上传 |

---

## 2. 基线状态

执行前先确认这些数字，偏离就停下来查原因。

```
HEAD                      90c3f0f  Fix: offer built-in player for single videos
versionCode               17060
versionName               0.17.18-r44
pytest                    193 passed, 2 skipped
verify_python_sync        449 files match
patches/                  1.4 MB（007 占 841.5 KB）
locales                   4 × 2286 leaves，键完全对齐
APK（r44 官方）           30,010,896 B
APK 内 pydantic           2.12.5 / core 2.41.5 / fastapi 0.136.1 / starlette 1.6.0
pydantic_core.so          p_align 0x4000（16 KB）
```

复验命令：

```bash
python tools/verify_python_sync.py \
  --upstream-root ../OpenAver \
  --source-root app/src/main/python
python -m pytest -q
```

---

## 3. 任务一：数据库导入/恢复（P0）

### 3.1 现状

`app/src/main/python/web/routers/database_backup.py` 只有一个路由：

```python
85: @router.get("/export")
86: def export_database() -> FileResponse:
```

设置页 `app/src/main/python/web/templates/settings.html:1593-1607` 只有一个下载按钮，注释写明：

```html
<!-- Database backup is intentionally export-only in r42. -->
```

用户导出的 zip 里是 `openaver.db` + `manifest.json`，但 App 内没有任何入口能把它装回去。重装后只能靠 adb push 到 `/data/data/dev.openaver.mobile/files/openaver_data/`。

**结论：数据有了出口，没有入口。P0 只完成一半。**

### 3.2 技术前提（已核实）

| 前提 | 结论 | 依据 |
| --- | --- | --- |
| WebView 能选文件吗 | **能** | `MainActivity.java:1566` `onShowFileChooser` 完整实现，走 `REQUEST_FILE_CHOOSER` + `FileChooserParams.parseResult`（1432 行） |
| 数据库连接是池化的吗 | **不是** | `core/database/connection.py:28` 每次 `sqlite3.connect()` 新建，无全局池 |
| 有初始化缓存吗 | **有** | `connection.py:19` `_initialized_db_paths`，`_clear_db_init_cache()`（432 行）可清 |
| WAL 模式 | **是** | `connection.py:43` `PRAGMA journal_mode=WAL`，会产生 `-wal` / `-shm` |
| 核心表 | 9 张 | `videos`、`actresses`、`actress_aliases`、`tag_aliases`、`wishlist`、`notifications`、`organize_failures`、`maker_javbus_map`、`app_meta` |
| 有活跃任务检测吗 | **有** | `core/generate_state.py:is_generate_in_progress()` |
| 数据库路径 | `get_db_path()` | `<data_root>/openaver.db` |

### 3.3 方案

新增 `POST /api/database/import`，multipart 上传 zip，校验后原子替换。

```
1. 体积闸门      Content-Length > 256 MB → 413
                 （chunked 上传没有 Content-Length，改在落盘时累计计数，超限即中断）
2. 落临时目录     tempfile.mkdtemp()，写入 upload.zip
3. 解压白名单     只取 manifest.json + openaver.db，拒绝 ../ 和绝对路径
4. 格式校验      manifest.format == "openaver-mobile-database-backup"
                 manifest.format_version <= _BACKUP_FORMAT_VERSION
5. 哈希校验      sha256(openaver.db) == manifest.database_sha256 → 否则 422
6. 库校验        PRAGMA integrity_check == "ok"
                 9 张核心表全部存在 → 否则 422
7. 活跃任务闸门   is_generate_in_progress() → 409
8. 备份现状      openaver.db → openaver.db.bak-<timestamp>（保留最近 3 份）
9. 清 WAL        删除 openaver.db-wal / openaver.db-shm
10. 原子替换     os.replace(新 db, openaver.db)
11. 重载缓存     _clear_db_init_cache(); init_db(force=True)
12. 返回         {ok: true, restored_from: <created_at>, backup: <bak 文件名>}
```

第 1–6 步全部是只读校验，不碰现有库，所以任何一步拒绝都不会留下副作用。第 2 步的临时目录必须在 `finally` 里 `shutil.rmtree(ignore_errors=True)`，否则导入失败会累积垃圾——这一点容易漏，因为成功路径上临时目录被 `os.replace` 搬走了，看起来"不需要清理"。

**为什么第 9 步必须做**：WAL 文件里存的是旧库未 checkpoint 的页。如果只换主库文件、留下旧 `-wal`，SQLite 打开新库时会尝试重放旧 WAL，导致数据错乱甚至 `database disk image is malformed`。必须把 `-wal` / `-shm` 一起删掉。

**为什么第 10 步用 `os.replace` 而不是 `shutil.copy`**：`os.replace` 在同一文件系统内是原子的，中途断电不会留下半个数据库。`copy` 会。

**为什么第 7 步要闸门**：扫描任务会持续 `_upsert_db`。替换文件时若有写入，旧连接持有旧 inode 继续写，新连接读新库，结果是"扫描结果写进了被丢弃的库"。必须拒绝，而不是"尽力而为"。

### 3.4 改动清单

**A. `app/src/main/python/web/routers/database_backup.py`**

在文件顶部常量区加：

```python
_BACKUP_MAX_BYTES = 256 * 1024 * 1024
_REQUIRED_TABLES = {
    "videos", "actresses", "actress_aliases", "tag_aliases",
    "wishlist", "notifications", "organize_failures",
    "maker_javbus_map", "app_meta",
}
_KEEP_BACKUPS = 3
```

新增三个函数：

| 函数 | 职责 |
| --- | --- |
| `_extract_backup(zip_path, dest_dir) -> tuple[Path, dict]` | 解压白名单 + 路径穿越防护，返回 (db 路径, manifest) |
| `_validate_snapshot(db_path, manifest) -> None` | 哈希 + integrity_check + 表存在性 |
| `_restore_snapshot(db_path, new_db) -> Path` | 备份现有库、清 WAL、`os.replace`、重载缓存，返回备份文件名 |

新增路由（约 90 行）：

```python
@router.post("/import")
async def import_database(file: UploadFile = File(...)) -> dict:
    ...
```

依赖：`from fastapi import UploadFile, File`（现有 import 只有 `APIRouter, HTTPException`，需要补）。

**B. `app/src/main/python/web/templates/settings.html`**

在现有导出块之后插入：具体位置是 `settings.html:1606` 的 `</div>` 之后、`1607` 的 `<hr class="my-3">` 之前（仍在 `{% if is_android %}` 块内）。

```html
<div class="settings-form-row">
    <label class="row-label">
        {{ t('settings.system.database_restore_label') }}
        <small class="settings-hint">{{ t('settings.system.database_restore_hint') }}</small>
    </label>
    <input type="file" accept=".zip,application/zip" class="hidden"
           x-ref="dbRestoreInput" @change="restoreDatabase($event)">
    <button type="button" class="btn btn-sm btn-outline btn-neutral"
            @click="$refs.dbRestoreInput.click()">
        <i class="bi bi-database-up"></i>
        {{ t('settings.system.database_restore_action') }}
    </button>
</div>
```

**C. 前端逻辑**

设置页的 Alpine 组件由 `web/static/js/pages/settings/main.js:11` 的 `mergeState(...)` 拼装：

```js
Alpine.data('settings', () => mergeState(
    stateConfig(), stateProviders(), stateUI(),
    stateSourceProbe(), browseDirState(), toastState(),
));
```

`showToast` 来自 `toastState()`（`shared/state-toast.js`），可以直接用。

**新建** `web/static/js/pages/settings/state-database.js`，不要塞进 `state-ui.js`——那是脏检查/目录选择的地盘，数据库恢复是独立职责：

```js
export function stateDatabase() {
    return {
        restoringDatabase: false,

        async restoreDatabase(event) {
            const input = event.target;
            const file = input.files?.[0];
            input.value = '';
            if (!file) return;

            if (!window.confirm(window.t('settings.system.database_restore_confirm'))) {
                return;
            }

            const form = new FormData();
            form.append('file', file);
            this.restoringDatabase = true;
            try {
                const resp = await fetch('/api/database/import', {
                    method: 'POST',
                    body: form,
                });
                if (!resp.ok) {
                    const detail = await resp.json().catch(() => ({}));
                    throw new Error(detail.detail || `HTTP ${resp.status}`);
                }
                this.showToast(window.t('settings.system.database_restore_done'), 'success');
                await new Promise(r => setTimeout(r, 800));
                window.location.reload();
            } catch (err) {
                this.showToast(
                    window.t('settings.system.database_restore_failed') + ': ' + err.message,
                    'error', 6000
                );
            } finally {
                this.restoringDatabase = false;
            }
        },
    };
}
```

然后在 `main.js` 加两行：

```js
import { stateDatabase }     from '@/settings/state-database.js';
// ...
Alpine.data('settings', () => mergeState(
    stateConfig(), stateProviders(), stateUI(),
    stateSourceProbe(), browseDirState(), toastState(),
    stateDatabase(),
));
```

用原生 `window.confirm` 而不是自定义弹窗，因为恢复数据库是不可逆操作，系统级确认框的阻断感更合适。如果项目里已有统一的 `confirmDialog`，执行时换成它——但要确认它在 `mergeState` 的某个 state 里确实存在。

**D. 四语言 i18n**

`app/src/main/python/locales/{en,ja,zh_CN,zh_TW}.json`，在 `settings.system` 下、`database_backup_action`（zh_CN:760）之后追加 6 个键：

| 键 | zh_CN |
| --- | --- |
| `database_restore_label` | 恢复数据库 |
| `database_restore_hint` | 导入此前导出的备份文件，将覆盖当前收藏、标签、别名、评分数据 |
| `database_restore_action` | 导入备份 |
| `database_restore_confirm` | 导入会覆盖当前数据库，且无法撤销。确定继续？ |
| `database_restore_done` | 数据库已恢复，页面即将刷新 |
| `database_restore_failed` | 恢复失败 |

四个语言文件必须键完全对齐——`tests/test_r43_localization.py::test_locale_files_have_identical_keys_and_placeholders` 会校验。

### 3.5 验证

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 导出 → 立即导入 | 200，数据不变，`openaver.db.bak-*` 出现 |
| 2 | 导入 r44 导出的旧备份 | 200，schema 迁移正常 |
| 3 | 篡改 zip 内 db 一个字节 | 422，`sha256 mismatch`，原库不受影响 |
| 4 | 上传非 zip 文件 | 422，格式错误，原库不受影响 |
| 5 | zip 内含 `../../evil.db` | 422，拒绝路径穿越 |
| 6 | 扫描任务运行时导入 | 409，提示先停止任务 |
| 7 | 导入后立即搜索 | 新数据可见，无 `database is locked` |
| 8 | 导入后杀掉 app 重启 | 数据仍在，无 malformed |

新增 `tests/test_r45_database_restore.py`，至少覆盖 3、4、5 三个拒绝路径 + 1 个成功路径（用 `tmp_path` 造库）。

### 3.6 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 替换瞬间有并发写 | 数据不一致 | `is_generate_in_progress()` 闸门 + 前端二次确认 |
| 备份文件占空间 | 每份 ≈ 库大小 | 只保留最近 3 份，`_KEEP_BACKUPS` 控制 |
| 上传大文件 OOM | app 崩溃 | 256 MB 上限 + `UploadFile` 走临时文件（Starlette 默认 spool） |
| 导入后前端状态陈旧 | 界面显示旧数据 | 成功后强制 `location.reload()` |

---

## 4. 任务二：让本地化守门测试真正执行（P2）

### 4.1 现状

```python
# tests/test_r43_localization.py:82
opencc = pytest.importorskip("opencc")
# tests/test_r43_localization.py:94
opencc = pytest.importorskip("opencc")
```

`requirements-test.txt`（11 行）里没有 `opencc`，CI 只执行 `pip install -r requirements-test.txt`，所以这两条测试**必然 skip**：

```
SKIPPED [1] tests\test_r43_localization.py:82: could not import 'opencc'
SKIPPED [1] tests\test_r43_localization.py:94: could not import 'opencc'
```

r43 的主题就是四语言本地化，而验证"简体不含繁体字形""繁体不含简体字形"的两道防线从未执行过。

### 4.2 方案

在 `requirements-test.txt` 追加一行：

```
opencc==1.4.2
```

**为什么是 1.4.2 而不是别的版本**：`opencc` 是编译扩展，只有 1.4.2 提供 cp313 的 manylinux / win_amd64 / macos wheel。1.1.x 没有 cp313 wheel，pip 会退回源码编译，需要 CMake + C++ 工具链，CI 会失败。

已实测（Windows / Python 3.13 / `--only-binary=:all:`）：安装成功，`OpenCC('s2t')` 与 `OpenCC('t2s')` 均可用。

**为什么不选 `opencc-python-reimplemented`**：它是纯 Python（`py2.py3-none-any`），装得上，但转换表是重实现版本，与 r43 作者调试时用的官方绑定可能有细微差异，会让"避坑白名单"（`test_traditional_chinese_avoids_known_opencc_overconversions`）的判断基准漂移。用官方绑定更接近原始验证环境。

### 4.3 改动清单

`requirements-test.txt` 追加一行（建议放末尾，保持字母序无所谓，但要有注释说明用途）：

```
opencc==1.4.2
```

`app/build.gradle` **不动**——`opencc` 只用于测试，不进 APK。这一点要确认：执行时 `grep -rn "opencc" app/src/main/python/` 应为空（当前为空）。

### 4.4 验证

```bash
python -m pytest tests/test_r43_localization.py -v
```

期望 **10 passed, 0 skipped**。

已在本机实测过这个结果：

```
test_locale_files_have_identical_keys_and_placeholders PASSED
test_locale_fallback_is_simplified_chinese PASSED
test_simplified_chinese_contains_no_traditional_characters PASSED
test_traditional_chinese_contains_no_simplified_characters PASSED
test_traditional_chinese_avoids_known_opencc_overconversions PASSED
test_android_native_strings_cover_all_ui_locales PASSED
test_gallery_html_uses_the_selected_locale PASSED
test_frontend_does_not_hardcode_traditional_locale_for_dates PASSED
test_enrichment_errors_follow_the_selected_locale PASSED
test_scanner_failure_log_does_not_leak_producer_chinese PASSED
→ 10 passed
```

也就是说 r43 的本地化质量本身没问题，**只是没人验证过**。加这一行之后，`pytest` 总数从 `193 passed, 2 skipped` 变成 `195 passed`。

### 4.5 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| CI 的 ubuntu 装不上 | 构建失败 | 已确认 1.4.2 有 `manylinux2014_x86_64` cp313 wheel；CI 用 `ubuntu-latest` + Python 3.13，命中 |
| 未来 opencc 升级破坏测试 | 误报 | 锁死 `==1.4.2` |

---

## 5. 任务三：对话框主题统一（P3）

### 5.1 现状

6 处 `AlertDialog` 全部硬编码系统主题：

| 文件 | 行号 | 用途 |
| --- | --- | --- |
| `ExternalPlayer.java` | 51 | 多分段选择 |
| `ExternalPlayer.java` | 92 | 播放器选择（r44 新增） |
| `ExternalPlayer.java` | 131 | 内置播放器兜底确认 |
| `MainActivity.java` | 881 | 离开页面确认 |
| `MainActivity.java` | 1084 | 通用确认框 |
| `MainActivity.java` | 1543 | `onJsConfirm` 桥接 |

```java
new AlertDialog.Builder(activity, android.R.style.Theme_Material_Dialog_Alert)
```

### 5.2 这不是"深浅色错配"

需要先纠正一个常见误判。查过资源：

```
values/colors.xml     bg = #090D13（深）, accent = #74A0FF（蓝）
values/themes.xml     parent = @android:style/Theme.Material.NoActionBar（深色）
values-night/         不存在
```

`Theme.Material` 本身就是深色主题，`Theme_Material_Dialog_Alert` 也是深色，所以对话框和 app **不是**一亮一暗。

真正的问题是**视觉语言不一致**：

| 属性 | App 主题 | 系统对话框 |
| --- | --- | --- |
| accent（按钮/选中色） | `#74A0FF` 蓝 | 系统默认 teal |
| 背景 | `#141B25` surface | 系统 `#424242` 灰 |
| 圆角/间距 | 自定义 drawable | 系统默认 |

结果：弹窗看起来"不像这个 app"。而且 `values-night` 不存在，说明 app 本来就不做深浅切换，所以也不需要 DayNight 主题——**只需要一个和 App 配色对齐的对话框主题**。

### 5.3 方案

在 `app/src/main/res/values/themes.xml` 新增：

```xml
<style name="Theme.OpenAverMobile.Dialog"
       parent="@android:style/Theme.Material.Dialog.Alert">
    <item name="android:colorAccent">@color/accent</item>
    <item name="android:colorBackground">@color/surface</item>
    <item name="android:textColorPrimary">@color/text_primary</item>
    <item name="android:textColorSecondary">@color/text_secondary</item>
    <item name="android:fontFamily">sans</item>
</style>
```

6 处调用点全部替换：

```java
new AlertDialog.Builder(activity, R.style.Theme_OpenAverMobile_Dialog)
```

注意 Java 里资源名转换规则：`Theme.OpenAverMobile.Dialog` → `R.style.Theme_OpenAverMobile_Dialog`（点变下划线）。

### 5.4 改动清单

| 文件 | 改动 |
| --- | --- |
| `app/src/main/res/values/themes.xml` | 新增 1 个 style（7 行） |
| `app/src/main/java/dev/openaver/mobile/ExternalPlayer.java` | 3 处替换（51/92/131） |
| `app/src/main/java/dev/openaver/mobile/MainActivity.java` | 3 处替换（881/1084/1543） |

**不需要**新建 `values-night/themes.xml`——app 没有夜间模式。

### 5.5 验证

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 多分段视频点播放 | 选择框按钮为蓝色（`#74A0FF`），背景 `#141B25` |
| 2 | 单集视频点播放（r44 行为） | 同上 |
| 3 | 浏览器 `confirm()` 桥接 | 同上 |
| 4 | 离开页面确认 | 同上 |
| 5 | 深色系统设置下 | 与 1–4 一致（app 不跟随系统） |
| 6 | 浅色系统设置下 | 与 1–4 一致（同上） |

第 5、6 项要专门测，因为 `Theme.Material` 不跟随系统，这正是我们要的确定性。

### 5.6 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 系统 Material 对话框的某些属性在自定义 style 下丢失 | 按钮变透明等 | 只覆盖 4 个属性，其余继承 `Theme.Material.Dialog.Alert` |
| `colorBackground` 与 `windowBackground` 不同名 | 背景不生效 | 两个都设，实测确认 |

---

## 6. 任务四：传输层退避重试（P1）

### 6.1 现状

全项目无任何重试机制：

```bash
grep -rn "max_retries\|backoff\|tenacity" app/src/main/python/
# 无命中
```

刮削器遇到 429 / 503 / 连接重置时，一次失败即计入 `failed_items`，用户只能手动点"重试失败项"（r42 已实现 `retryFailedItems()`）。

### 6.2 注入点选择

`core/proxy_policy.py:123-129` 是**全站唯一的 Session 创建点**：

```python
123: def new_session(source_id, *, settings=None) -> requests.Session:
126:     kwargs = proxy_kwargs('source_query', source_id=source_id, settings=settings)
127:     if not kwargs:
128:         return requests.Session()
129:     return _ProxiedSession(kwargs['proxies'])
```

调用方只有两处：

- `core/scrapers/base.py:31` → `BaseScraper._new_session()`（所有刮削器）
- `core/custom_source/fetch.py:76`（自定义源抓取）

**影响面精确**：只影响刮削和自定义源，不碰 AI 调用（走 httpx）、不碰本地 API。

### 6.3 方案

用 urllib3 的 `Retry` 挂 `HTTPAdapter`，不引入 `tenacity`。

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_RETRY = Retry(
    total=2,
    connect=2,
    read=1,
    status=2,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "HEAD"}),
    raise_on_status=False,
    respect_retry_after_header=True,
)

def _mount_retry(session: requests.Session) -> requests.Session:
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def new_session(source_id, *, settings=None) -> requests.Session:
    kwargs = proxy_kwargs('source_query', source_id=source_id, settings=settings)
    if not kwargs:
        return _mount_retry(requests.Session())
    return _mount_retry(_ProxiedSession(kwargs['proxies']))
```

### 6.4 每个参数的理由

| 参数 | 值 | 理由 |
| --- | --- | --- |
| `total` | 2 | 最多 2 次重试（3 次尝试）。再多会让单次刮削从 10 秒变 60 秒 |
| `connect` | 2 | 连接失败重试成本低（未发出请求），可以多试 |
| `read` | 1 | 读超时重试成本高（已等满 timeout），只给 1 次 |
| `status` | 2 | 状态码重试立即返回，成本低 |
| `backoff_factor` | 0.5 | 退避 0.5s → 1.0s，总等待 ≤ 1.5s |
| `status_forcelist` | 429/500/502/503/504 | 限流 + 服务端临时故障。**不含 4xx 其余码**——401/403/404 重试没意义 |
| `allowed_methods` | GET/HEAD | POST 不重试，避免重复提交 |
| `raise_on_status` | False | **关键**。保持现有调用方"自己看 status_code"的契约，不改变错误处理路径 |
| `respect_retry_after_header` | True | 429 带 `Retry-After` 时按服务端要求等待，比自己猜更礼貌 |

### 6.5 代价（必须承认）

单次刮削的最坏耗时：

```
timeout=10s 的场景
  连接超时 10s → 退避 0.5s → 连接超时 10s → 退避 1.0s → 连接超时 10s = 31.5s
```

r44 是 10s。**最坏情况慢 3 倍。**

但这只发生在"目标站完全不可达"时。正常站点的 429/503 会在几百毫秒内返回，重试总开销 < 2s。而"目标站不可达"本来就是要失败的情况，多等 20 秒换一次成功机会，是值得的。

如果实测发现太慢，把 `connect` 降到 1、`total` 降到 1，最坏 20.5s（10 + 0.5 + 10）。

### 6.6 不可取消性

urllib3 的退避 sleep 是阻塞的，不响应 `cancel_event`。用户点取消后，最多要等当前请求结束 + 1.5s 退避。

这在可接受范围内（r41 审查里 `executor.shutdown(wait=True)` 的问题已经改成 `wait=False`，取消语义不会再被无限拖长）。**不要**为此改成手写 `retry_call` 循环——那要改 20 个调用点，收益远小于成本。

### 6.7 改动清单

| 文件 | 改动 |
| --- | --- |
| `app/src/main/python/core/proxy_policy.py` | 加 2 个 import、1 个常量、1 个 `_mount_retry()`、改 `new_session()` 3 行 |

只改这一个文件。`base.py` 和 10 个 scraper 一行不动。

### 6.8 验证

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 正常刮削 | 无行为变化，日志无重试记录 |
| 2 | 目标返回 503 两次后成功 | 成功，日志有 2 条重试 |
| 3 | 目标返回 429 + `Retry-After: 2` | 等待 2s 后重试 |
| 4 | 目标返回 404 | **不重试**，直接失败 |
| 5 | 目标完全不可达 | 31.5s 内失败（不是无限） |
| 6 | 取消任务 | 最多等当前请求 + 1.5s |
| 7 | 自定义源抓取 | 同 2–5 |
| 8 | 全部单元测试 | `195 passed` |

第 2、3 项需要一个可控的本地 HTTP 服务，测试里用 `http.server` 起一个返回指定状态码的桩。

新增 `tests/test_r45_retry_policy.py`，覆盖 4（不重试 404）和 5（次数上限）这两条最容易写错的。

### 6.9 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 重试放大限流 | 被封 IP | `status_forcelist` 含 429 但 `total=2`，最多 3 次；`Retry-After` 优先 |
| 拖慢批量刮削 | 用户感知变慢 | 只在失败路径触发，成功路径零开销 |
| `_ProxiedSession` 的 `request()` 覆写与 adapter 冲突 | 代理失效 | `request()` 只改 `kwargs['proxies']`，adapter 在 `send()` 层，不冲突；需实测代理场景 |
| urllib3 版本差异 | 参数不支持 | 已确认 APK 内 urllib3 2.8.0，`Retry` 参数全支持 |

---

## 7. 任务五：前台保活服务（P1）

### 7.1 现状

```
AndroidManifest.xml   <service> 数量：0
权限                   INTERNET / ACCESS_NETWORK_STATE /
                      READ_EXTERNAL_STORAGE(maxSdk 29) /
                      WRITE_EXTERNAL_STORAGE(maxSdk 29) /
                      MANAGE_EXTERNAL_STORAGE
onPause()             仍调 webView.onPause()（MainActivity.java:1367-1375）
```

`onPause()` 里暂停 WebView 是合理的（省电），但它不会停 Python 线程——Python 的 FastAPI 跑在 Activity 进程的 daemon thread 里。

**这里有两条独立的问题，容易只看到第一条：**

| # | 问题 | 后果 |
| --- | --- | --- |
| 1 | 进程降级为缓存进程，LMK 会杀 | 任务中途消失，回来什么都不剩 |
| 2 | `webView.onPause()` 暂停 JS 执行 | 即使进程活着，SSE 的 `reader.read()` 回调不再执行，UI 进度冻住 |

第 2 条在 r41 审查里没写，但它是真实存在的：`state-batch.js` 的流式读取是 `while` 循环 + `await reader.read()`，回调要回 JS 主线程。WebView 暂停后主线程不跑任务队列，进度就停在切走那一刻。回到前台 `onResume` 恢复时，SSE 连接多半已经被服务端判为断开（`_DISCONNECT_POLL_INTERVAL_SEC = 0.5` 的断线侦测），前端拿到的是 `cancelled`。

**所以只加前台服务是不够的**——进程保住了，UI 仍然是死的。必须同时处理第 2 条，否则用户回来看到的是"通知还在，进度不动，过一会儿变已取消"。

### 7.2 方案

引入一个**只做保活、不跑逻辑**的前台 Service，并在任务期间跳过 `webView.onPause()`：

- 任务开始时 `startForegroundService`，挂一条常驻通知
- 任务结束时 `stopService`
- 通知内容固定（"任务进行中"），不做实时进度——避免频繁 IPC
- Service 本身不持有任何业务逻辑，app 被杀时它跟着死，不尝试恢复
- **Service 运行期间，`onPause()` 不调 `webView.onPause()`**，让 JS 继续跑完 SSE

第 5 条是这套方案能真正生效的关键。`MainActivity.java:1367-1375` 现在是：

```java
@Override
protected void onPause() {
    if (cfTransport != null) {
        cfTransport.onPause();
    }
    webView.onPause();
    super.onPause();
}
```

改成：

```java
@Override
protected void onPause() {
    if (cfTransport != null) {
        cfTransport.onPause();
    }
    // 任务期间保持 WebView 活跃，否则 SSE 的 JS 回调不再执行，
    // 即使进程活着，UI 进度也会冻住。
    if (!TaskKeepAliveService.isRunning()) {
        webView.onPause();
    }
    super.onPause();
}
```

`isRunning()` 是 Service 里的一个静态 volatile 标志，在 `onStartCommand` 置 true、`onDestroy` 置 false。不用查系统服务，零成本。

### 7.3 通信设计

**问题**：主 WebView 没有 `addJavascriptInterface`。`AndroidCfTransport.java:361` 那个 `NativeBridge` 是给隐藏 WebView 用的，只有 `onFetchResult` 一个方法。

**方案**：复用已有的自定义 scheme 机制。`MainActivity.java:1114` 已经处理 `openaver-player://`：

```java
if ("openaver-player".equals(scheme)) {
    ExternalPlayer.open(...);
    return true;
}
```

前端 `web/static/js/shared/video-player.js:12` 用 `window.location.href = 'openaver-player://play?...'` 触发，Java 返回 `true` 阻止实际导航。

新增 `openaver-task://` 分支，同一套机制：

```java
if ("openaver-task".equals(scheme)) {
    String action = uri.getHost();
    if ("start".equals(action)) {
        TaskKeepAliveService.start(this, uri.getQueryParameter("label"));
    } else if ("stop".equals(action)) {
        TaskKeepAliveService.stop(this);
    }
    return true;
}
```

**为什么不用 `addJavascriptInterface`**：那需要在主 WebView 上暴露一个 Java 对象给任意页面 JS，是攻击面。scheme 拦截只处理我们自己发出的 URL，且已经过 `isLocalServer()` 过滤。

### 7.4 前端挂载点

`web/static/js/pages/scanner/state-scan.js` 有唯一的任务生命周期钩子：

- `_startTask(kind, status, total)` — 1079 行
- `_finishTask(nextState, status, summary, failedItems)` — 1129 行

所有 taskKind（generate / nfo-update / title-backfill / sample-backfill / tag-preview / tag-update / jellyfin-update / rename）都经过这两个函数。

在 `_startTask` 末尾加：

```js
if (window.__openaverTaskKeepAlive) {
    window.__openaverTaskKeepAlive.start(kind);
}
```

在 `_finishTask` 末尾加：

```js
if (window.__openaverTaskKeepAlive) {
    window.__openaverTaskKeepAlive.stop();
}
```

新增 `web/static/js/shared/task-keepalive.js`：

```js
const ANDROID_SHELL_UA = /(?:^|\s)OpenAverMobile\/\S+/;
let active = false;

function notify(schemeUrl) {
    if (!ANDROID_SHELL_UA.test(navigator.userAgent)) return;
    window.location.href = schemeUrl;
}

window.__openaverTaskKeepAlive = {
    start(label) {
        if (active) return;
        active = true;
        notify('openaver-task://start?label=' + encodeURIComponent(label || ''));
    },
    stop() {
        if (!active) return;
        active = false;
        notify('openaver-task://stop');
    },
};

// 页面刷新/关闭时兜底，避免 _finishTask 没跑到导致通知残留。
// 只发 stop 不发 start，所以不违反"导航必须由用户手势触发"的约束。
window.addEventListener('pagehide', () => {
    if (active) notify('openaver-task://stop');
});
```

`active` 标志是必要的：`_startTask` 在 `retryFailedItems()` 之类的路径上可能连续触发，重复 `startForegroundService` 会重复 `startForeground`（虽然幂等，但会反复重建通知，造成通知栏闪烁）。

在 `web/templates/base.html` 引入。现有 `video-player.js` 在 **977 行**以 `type="module"` 引入，新脚本插在它后面：

```html
<script type="module" src="/static/js/shared/task-keepalive.js"></script>
```

### 7.5 改动清单

| 文件 | 改动 |
| --- | --- |
| `app/src/main/java/dev/openaver/mobile/TaskKeepAliveService.java` | **新增**，约 120 行 |
| `app/src/main/java/dev/openaver/mobile/MainActivity.java` | `handleNavigation` 加 `openaver-task` 分支（约 10 行）+ `onPause` 加 3 行判断 |
| `app/src/main/AndroidManifest.xml` | 加 `FOREGROUND_SERVICE` 权限 + `<service>` 声明 |
| `app/src/main/python/web/static/js/shared/task-keepalive.js` | **新增**，约 30 行 |
| `app/src/main/python/web/static/js/pages/scanner/state-scan.js` | `_startTask` / `_finishTask` 各加 3 行 |
| `app/src/main/python/web/templates/base.html` | 加 1 行 `<script>` |
| `app/src/main/res/values*/strings.xml` | 5 个语言文件各加 3 个字符串 |

### 7.6 Service 实现要点

**先注意一个约束**：`app/build.gradle:114-117` 的 `dependencies` 只有两条 `testImplementation`（junit、org.json），**没有任何 androidx 依赖**。所以不能用 `ContextCompat` / `NotificationCompat`，必须走原生 API。`minSdk 29` 保证了 `startForegroundService`（API 26+）、`NotificationChannel`（API 26+）、`Notification.Builder(context, channelId)`（API 26+）全部可用。

```java
public class TaskKeepAliveService extends Service {
    private static final String CHANNEL_ID = "openaver_task";
    private static final int NOTIFICATION_ID = 17061;
    private static final String EXTRA_LABEL = "label";

    // volatile：onStartCommand/onDestroy 在 Service 线程写，onPause 在主线程读。
    private static volatile boolean running = false;

    static boolean isRunning() {
        return running;
    }

    static void start(Context context, String label) {
        Intent intent = new Intent(context, TaskKeepAliveService.class);
        intent.putExtra(EXTRA_LABEL, label);
        context.startForegroundService(intent);   // 原生，非 ContextCompat
    }

    static void stop(Context context) {
        context.stopService(new Intent(context, TaskKeepAliveService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createChannel();
        startForeground(NOTIFICATION_ID, buildNotification(
                intent == null ? null : intent.getStringExtra(EXTRA_LABEL)
        ));
        running = true;
        return START_NOT_STICKY;   // 不要 STICKY
    }

    @Override
    public void onDestroy() {
        running = false;
        stopForeground(true);      // API 33+ 建议 STOP_FOREGROUND_REMOVE，targetSdk 29 下 boolean 版仍可用
        super.onDestroy();
    }
    ...
}
```

**必须是 `START_NOT_STICKY`**。用 `START_STICKY` 的话，系统杀掉进程后会把 Service 拉起来，但那时 Python 线程已经没了，通知会挂在"任务进行中"而实际什么都没跑——用户看到的是假状态。

**`running` 必须在 `onDestroy` 里清**，不能只在 `stop()` 里清。因为 `stopService` 之后 `onDestroy` 是异步调用的，如果用户紧接着按 Home，`onPause` 可能在 `onDestroy` 之前跑，读到的还是 `true`——这一次不暂停 WebView，无害。反过来，如果只在 `stop()` 里清而 `onDestroy` 没清，进程被杀再拉起时会残留 `true`，导致 WebView 永远不暂停，白耗电。

**必须 `stopSelf()` 或 `stopService()`**。任务结束不停止，通知会一直挂着，用户只能去设置里强停 app。

`targetSdk 29` 下的两个细节：

- `FOREGROUND_SERVICE` 权限是 API 28+ 必需，要加
- `POST_NOTIFICATIONS` 是 API 33+ 的运行时权限，但 `targetSdk < 33` 时系统默认授予，**不需要**加，也不需要请求
- `android:foregroundServiceType="dataSync"` 在 API 29 引入，targetSdk 34+ 才强制。写上无害，为将来升 targetSdk 铺路

### 7.7 验证

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 开始扫描 | 通知栏出现"OpenAver 任务进行中" |
| 2 | 扫描中切到桌面 5 分钟 | 回来任务仍在跑，**进度数字已经推进**（不是停在切走那一刻） |
| 3 | 扫描中切到微信回消息 | 同上 |
| 4 | 切走后 30 秒回来看日志面板 | 有新的处理记录，证明 JS 没有停 |
| 5 | 扫描完成 | 通知自动消失 |
| 6 | 扫描中手动取消 | 通知立即消失 |
| 7 | 扫描中杀 app | 通知消失（不残留假状态） |
| 8 | 桌面浏览器访问 | 无任何 scheme 报错（UA 判断拦住） |
| 9 | 非扫描任务（重命名） | 同样有通知，同样会消失 |
| 10 | 任务结束后切到桌面 | WebView 正常暂停（`isRunning()` 回到 false） |

第 2、4 项是这次改动的核心验证点，不能只看"任务还在"——那只能证明进程没被杀，不能证明 `onPause` 的修复生效。**必须对比进度数字**：切走前记下 `progressCurrent`，5 分钟后回来应该明显变大。

第 2、3、4 项必须在**真机**或低内存模拟器上测。模拟器默认内存大，LMK 不一定会触发，测不出差异。如果只能用模拟器，用 `adb shell am send-trim-memory <pid> RUNNING_CRITICAL` 主动施压。

**注意**：交接文档规定不能碰真实设备 `901LGaff7f7de`，只能用 `emulator-5554`。所以第 2、3 项在模拟器上用 `send-trim-memory` 替代验证，并在文档里记录"未做真机长时后台验证"这个限制。

### 7.8 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 通知无法关闭 | 用户投诉 | `_finishTask` 必调 `stop()`；`onDestroy` 里也 `stopForeground(true)` |
| `startForegroundService` 5 秒内未 `startForeground` | ANR 崩溃 | `onStartCommand` 第一件事就是 `startForeground` |
| scheme 被 `isLocalServer` 提前拦截 | 通知不出现 | `handleNavigation` 里 `isLocalServer` 判断在 scheme 之前，`openaver-task://` 不是 local server，不受影响 |
| 前端异常导致 `_finishTask` 没跑 | 通知残留 | `_finishTask` 的调用方已有 `finally` 语义；另加 `pagehide` 兜底 stop |
| 部分 ROM 限制后台启动 Service | 通知不出现 | 只影响保活效果，不影响功能；不做特殊适配 |

---

## 8. 执行顺序与批次

### 批次 A（零风险，先做）

| 步骤 | 内容 | 预计改动 |
| --- | --- | --- |
| A1 | `requirements-test.txt` 加 `opencc==1.4.2` | +1 行 |
| A2 | `themes.xml` 加 `Theme.OpenAverMobile.Dialog` | +7 行 |
| A3 | 6 处 `AlertDialog` 替换主题 | 6 行 |
| A4 | 跑 `pytest` 确认 195 passed | — |

A 批不改 `app/src/main/python` 的任何 `.py`/`.html`，**不需要重新生成 patches**。只有 A3 改 Java，A2 改资源。

### 批次 B（核心功能）

| 步骤 | 内容 |
| --- | --- |
| B1 | `database_backup.py` 加 3 个函数 + `/import` 路由 |
| B2 | `settings.html` 加导入行 |
| B3 | 新建 `state-database.js`，`main.js` 里 merge 进去 |
| B4 | 4 个 locale 各加 6 个键 |
| B5 | 新增 `tests/test_r45_database_restore.py` |
| B6 | `python tools/generate_patches.py` |
| B7 | `python tools/verify_python_sync.py` |
| B8 | `pytest` 全绿 |

### 批次 C（网络行为）

| 步骤 | 内容 |
| --- | --- |
| C1 | `proxy_policy.py` 加 `_RETRY` + `_mount_retry()`，改 `new_session()` |
| C2 | 新增 `tests/test_r45_retry_policy.py` |
| C3 | 生成 patches + 同步校验 |
| C4 | 实测刮削一个正常番号，确认无额外延迟 |

### 批次 D（新组件）

| 步骤 | 内容 |
| --- | --- |
| D1 | 新增 `TaskKeepAliveService.java` |
| D2 | `MainActivity.handleNavigation` 加分支 |
| D3 | Manifest 加权限 + service |
| D4 | 新增 `task-keepalive.js`，`base.html` 引入 |
| D5 | `state-scan.js` 两个钩子各加 3 行 |
| D6 | 5 个 strings.xml 各加 3 条 |
| D7 | 生成 patches + 同步校验 |
| D8 | 模拟器验证 8 项 |

### 版本号

**在 A+B 完成、准备出 r45 时改**，不要在批次之间提前改：

```gradle
versionCode 17061
versionName "0.17.18-r45"
```

如果 C+D 要单独发 r46，那时再改成 `17062` / `0.17.18-r46`。

---

## 9. 测试计划

### 9.1 自动化

| 文件 | 覆盖 | 新增/修改 |
| --- | --- | --- |
| `tests/test_r43_localization.py` | 两条守门测试从 skip 变 pass | 不改，靠依赖生效 |
| `tests/test_r45_database_restore.py` | 导入成功 / 哈希错 / 非 zip / 路径穿越 | **新增** |
| `tests/test_r45_retry_policy.py` | 404 不重试 / 次数上限 / 429 尊重 Retry-After | **新增** |
| `tests/test_mobile_shell_cleanup.py` | Java 侧断言（现有风格） | 加 1 条：`TaskKeepAliveService` 存在且 `START_NOT_STICKY` |

现有 `test_mobile_shell_cleanup.py` 的做法是读 Java 源码做字符串断言（r44 就是这样加的 `test_single_video_offers_builtin_player_choice`）。沿用这个风格，成本最低。

### 9.2 期望结果

```
pytest                195 passed（193 + 2 条 opencc 测试转正）
                      新增 2 个测试文件后 ≈ 205 passed
verify_python_sync    451 files match（449 + state-database.js + task-keepalive.js）
node --check          通过
testDebugUnitTest     通过
```

### 9.3 手工回归（模拟器 `emulator-5554`）

| 类别 | 项 |
| --- | --- |
| 数据库 | 导出 → 导入 → 搜索 → 重启 → 数据仍在 |
| 数据库 | 扫描中导入 → 409 |
| 播放 | 多分段选择框配色 |
| 播放 | 单集视频选择框配色 |
| 刮削 | 正常番号刮削成功 |
| 刮削 | 断网刮削 → 报错文案正常（不是卡 30 秒） |
| 后台 | 扫描中按 Home → 5 分钟后回来 → 进度推进 |
| 后台 | 扫描中 `am send-trim-memory RUNNING_CRITICAL` → 进程存活 |
| 语言 | 切换 4 语言 → 原生对话框文案跟随 |

**禁止**：不碰真实设备 `901LGaff7f7de`。

---

## 10. 版本与发布

本计划**不包含**发布动作。执行完只到"改完、测过、等你验收"。

如果后续要求发布，流程是：

```bash
# 逐文件 add，禁止 git add -A
git add app/src/main/python/web/routers/database_backup.py
git add app/src/main/python/web/templates/settings.html
git add app/src/main/python/locales/en.json
git add app/src/main/python/locales/ja.json
git add app/src/main/python/locales/zh_CN.json
git add app/src/main/python/locales/zh_TW.json
git add app/src/main/python/core/proxy_policy.py
git add app/src/main/python/web/static/js/shared/task-keepalive.js
git add app/src/main/python/web/static/js/pages/settings/state-database.js
git add app/src/main/python/web/static/js/pages/settings/main.js
git add app/src/main/python/web/static/js/pages/scanner/state-scan.js
git add app/src/main/python/web/templates/base.html
git add app/src/main/java/dev/openaver/mobile/TaskKeepAliveService.java
git add app/src/main/java/dev/openaver/mobile/MainActivity.java
git add app/src/main/java/dev/openaver/mobile/ExternalPlayer.java
git add app/src/main/res/values/themes.xml
git add app/src/main/res/values/strings.xml
git add app/src/main/res/values-en/strings.xml
git add app/src/main/res/values-ja/strings.xml
git add app/src/main/res/values-zh/strings.xml
git add app/src/main/res/values-zh-rTW/strings.xml
git add app/src/main/AndroidManifest.xml
git add app/build.gradle
git add requirements-test.txt
git add patches/
git add tests/test_r45_database_restore.py
git add tests/test_r45_retry_policy.py
git add tests/test_mobile_shell_cleanup.py
git add docs/r45-plan.md
```

提交前自查：

```bash
git status --porcelain | grep -v "^??"   # 只应有上面这些
git diff --cached --check                # 无空白错误
```

---

## 11. 回滚

每一项都可独立回滚，因为它们不共享代码：

| 项 | 回滚方式 |
| --- | --- |
| 数据库导入 | 删 `/import` 路由 + 设置页那一行；用户已导入的数据不受影响（导入前有 `.bak`） |
| opencc | 删 `requirements-test.txt` 那一行，两条测试退回 skip |
| 对话框主题 | 6 处改回 `android.R.style.Theme_Material_Dialog_Alert` |
| 退避重试 | `new_session()` 去掉 `_mount_retry()` 包装 |
| 前台服务 | 删 Service 文件 + Manifest 声明 + JS 钩子，前端自动降级（`window.__openaverTaskKeepAlive` 不存在时跳过） |

前台服务的降级设计是刻意的：JS 侧用 `if (window.__openaverTaskKeepAlive)` 守卫，即使 Java 侧回滚了，前端也不会报错。

---

## 12. 风险登记

| ID | 风险 | 概率 | 影响 | 缓解 |
| --- | --- | --- | --- | --- |
| R1 | 导入时替换库文件导致损坏 | 中 | **高**（数据丢失） | 12 步流程 + 哈希校验 + integrity_check + 保留 3 份备份 + 活跃任务闸门 |
| R2 | 重试让批量刮削变慢 | 中 | 中 | `total=2` 上限，只 GET/HEAD，只在失败路径触发 |
| R3 | 前台服务通知残留 | 中 | 低 | `START_NOT_STICKY` + `_finishTask` 必调 stop + `pagehide` 兜底 |
| R4 | 模拟器测不出后台保活差异 | 高 | 中（验证不充分） | 用 `am send-trim-memory` 替代；文档记录"未做真机验证" |
| R5 | patches 未重新生成导致 CI 挂 | 中 | 高（构建失败） | 每次改 `app/src/main/python` 后必跑 `generate_patches.py` + `verify_python_sync.py` |
| R6 | 四个 locale 键不对齐 | 中 | 高（测试失败） | 新增 6 个键时四文件同步加，`test_locale_files_have_identical_keys_and_placeholders` 会拦 |
| R7 | 工作区有未跟踪诊断文件被误提交 | 中 | 中 | 逐文件 `git add`，禁止 `-A`；提交前 `git status` 核对 |
| R8 | 一次性发 r45 包含 5 项，出问题难定位 | 中 | 中 | 分批 commit；建议 A+B 出 r45、C+D 出 r46 |
| R9 | `isRunning()` 状态泄漏导致 WebView 永不暂停 | 中 | 中（耗电） | `onDestroy` 里必须清；`START_NOT_STICKY` 避免僵尸 Service |
| R10 | 任务期间不暂停 WebView 增加后台耗电 | 高 | 低 | 只在有任务时跳过，任务结束立即恢复暂停；单次扫描通常 2–10 分钟 |

---

## 13. 不做的事

以下问题存在，但**不在本次范围**，不要顺手改：

- `targetSdk` 从 29 升级（牵扯存储权限、16 KB 页、分区存储，是独立工程）
- `onTrimMemory` 内存回收钩子
- 缩略图缓存磁盘上限
- `core/multipart_tokens.py` 词表扩展（`cd|dvd|part|pt|disc` 之外的命名）
- r44 播放器选择框的"记住选择"
- pydantic v1 风格 `@validator` / `class Config` 的弃用清理
- patch 层 1.4 MB 的拆分
- `_ProxiedSession` 与 retry adapter 的单元测试（只做集成验证）

---

## 附录 A 验证命令

```bash
# 1. Python 源码与 patches 同步（CI 会跑这个，失败即构建失败）
python tools/verify_python_sync.py \
  --upstream-root ../OpenAver \
  --source-root app/src/main/python

# 2. 单元测试
python -m pytest -q

# 3. 本地化专项（确认不再 skip）
python -m pytest tests/test_r43_localization.py -v

# 4. JS 语法（CI 会跑）
find app/src/main/python/web/static/js -name '*.js' -exec node --check {} \;

# 5. Java 单元测试
./gradlew --no-daemon testDebugUnitTest -Pabi=arm64-v8a

# 6. 构建（需要本地 Android SDK）
./gradlew --no-daemon assembleRelease -Pabi=arm64-v8a

# 7. 验证 APK 里的 pydantic 仍是 v2（防止静默回退）
python -c "
import zipfile, io
z = zipfile.ZipFile('app/build/outputs/apk/release/app-release.apk')
inner = zipfile.ZipFile(io.BytesIO(z.read('assets/chaquopy/requirements-common.imy')))
names = [n for n in inner.namelist() if 'dist-info' in n and n.split('/')[0].endswith('dist-info')]
for d in sorted({n.split('/')[0] for n in names}):
    if any(k in d for k in ('pydantic','fastapi','starlette')):
        print(d)
"
```

第 7 项是 r42 之后每次发版都该做的检查——CI 绿不等于 APK 里装对了。

---

## 附录 B 文件改动总览

| 文件 | 类型 | 批次 |
| --- | --- | --- |
| `requirements-test.txt` | 改（+1 行） | A |
| `app/src/main/res/values/themes.xml` | 改（+7 行） | A |
| `app/src/main/java/dev/openaver/mobile/ExternalPlayer.java` | 改（3 行） | A |
| `app/src/main/java/dev/openaver/mobile/MainActivity.java` | 改（3 行 + 13 行） | A / D |
| `app/src/main/python/web/routers/database_backup.py` | 改（+约 130 行） | B |
| `app/src/main/python/web/templates/settings.html` | 改（+12 行） | B |
| `app/src/main/python/web/static/js/pages/settings/state-database.js` | **新增**（约 45 行） | B |
| `app/src/main/python/web/static/js/pages/settings/main.js` | 改（+2 行） | B |
| `app/src/main/python/locales/{en,ja,zh_CN,zh_TW}.json` | 改（各 +6 键） | B |
| `app/src/main/python/core/proxy_policy.py` | 改（+18 行） | C |
| `app/src/main/java/dev/openaver/mobile/TaskKeepAliveService.java` | **新增**（约 120 行） | D |
| `app/src/main/AndroidManifest.xml` | 改（+6 行） | D |
| `app/src/main/python/web/static/js/shared/task-keepalive.js` | **新增**（约 30 行） | D |
| `app/src/main/python/web/static/js/pages/scanner/state-scan.js` | 改（+6 行） | D |
| `app/src/main/python/web/templates/base.html` | 改（+1 行） | D |
| `app/src/main/res/values*/strings.xml` | 改（各 +3 条） | D |
| `tests/test_r45_database_restore.py` | **新增** | B |
| `tests/test_r45_retry_policy.py` | **新增** | C |
| `tests/test_mobile_shell_cleanup.py` | 改（+1 用例） | D |
| `patches/` | 重新生成 | B / C / D |
| `app/build.gradle` | 改（版本号） | 发布前 |
| `docs/r45-plan.md` | 本文件 | — |

**总计**：新增 5 个文件、改动 22 个文件、约 580 行新代码（不含 patches 重生成）。

---

## 待确认

执行前需要你确认三件事：

1. **A+B 出 r45、C+D 出 r46，还是五项一次发 r45？**
   我建议前者。五项一起发，如果后台保活出问题，回滚会把数据库导入一起带走。

2. **数据库导入是否接受"扫描任务运行时拒绝导入"这个限制？**
   替代方案是排队等任务结束，但那要加一个任务队列，超出本次范围。

3. **前台服务的通知文案，你有没有偏好措辞？**
   默认我按现有规则写：`values/` 英文（fallback）、`values-en` 英文、`values-zh` 简体、`values-zh-rTW` 繁体、`values-ja` 日文。拟用「OpenAver 正在处理任务」+「完成后通知会自动消失」。有想法就说，没有就按这个来。

另外提醒一件事：**任务五会改 `onPause()`**（第 7.2 节）。这是五个任务里唯一触碰主 Activity 生命周期的改动，也是唯一可能影响"平时使用"的改动——如果 `isRunning()` 状态泄漏，WebView 会一直不暂停，后台耗电会上升。风险表 R9 记了这一条，验收时请专门看一眼任务结束后切后台是否正常暂停。
