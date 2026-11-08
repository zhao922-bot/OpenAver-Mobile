# OpenAver Mobile r46 计划

> **基线**：r45（`v0.17.18-android-r45`，versionCode 17061，2026-11-07T12:26Z 已发布）
> **撰写日期**：2026-11-08
> **性质**：r45 验收后的收尾补丁。**不含新功能**，只补 r45 留下的洞。
> **上游**：OpenAver v0.17.18（本次不跟随上游任何变更）

---

## 0. 摘要

r45 把五个长期欠账一次清完，功能层是完整的。这份计划只处理验收时发现的六个收尾项，其中**只有第 1 项属于必须在下一个版本前修掉的问题**，其余是质量债。

| # | 项目 | 优先级 | 风险 | 改动量 | 新增文案 |
|---|---|---|---|---|---|
| 1 | `Retry-After` 无上限，单请求可挂 2 小时 | **P0** | 高 | ~10 行 | 无 |
| 2 | `_restore_snapshot` 回滚分支零覆盖 | P1 | 中 | ~90 行测试 | 无 |
| 3 | 导入前无磁盘空间预检 | P2 | 中 | ~25 行 | 4 语言 × 1 条 |
| 4 | `importorskip` 仍会静默跳过 | P2 | 低 | ~6 行 | 无 |
| 5 | 通知里的 `EXTRA_LABEL` 是死参数 | P3 | 无 | ~8 行 | 无 |
| 6 | web menu 对话框仍用平台主题 | P3 | 无 | 1 行 + 目视 | 无 |

**建议**：1 + 2 + 4 一个批次出 r46；3 + 5 + 6 一起出 r47。理由见第 9 节。

---

## 1. 范围与边界

### 1.1 本计划包含

- 传输层重试的 `Retry-After` 上限
- 数据库恢复失败路径的测试覆盖
- 数据库导入的磁盘空间预检
- 本地化测试的静默跳过问题
- 前台服务通知的死参数
- 最后一个未统一的对话框主题

### 1.2 本计划**不**包含

- 任何新功能（不做"记住选择"、不做导入进度条、不做备份管理 UI）
- `targetSdk` 升级（仍为 29，见 11 节 R6）
- `patches/` 层瘦身（`007` 已 871 KB，是独立课题）
- 上游 OpenAver 的同步
- `pydantic` / `urllib3` 以外的依赖升级

### 1.3 硬约束

1. **不得重写**：所有改动都是在 r45 代码上做增量，不重构模块。
2. **不得删除或覆盖已发布产物**：r42–r45 的 tag / release / APK 一律不动。
3. **禁止**：`git reset --hard`、`git checkout --`、force-push、`git add -A`。
4. 根目录下的诊断文件（`.nfo` / `.xml` / `.txt` / 截图 / 日志）**不提交、不删除**。
5. 改完 `app/src/main/python` 后**必须**重新生成 patches（`tools/generate_patches.py`）。
6. 不打印 GitHub token、keystore、密码。
7. **未经明确指示不 commit、不打 tag、不 push。**
8. 只碰模拟器 `emulator-5554`，不碰真机 `901LGaff7f7de`。

---

## 2. 基线（本次实测，非引用）

| 项目 | 实测值 | 命令 |
|---|---|---|
| 测试 | **207 passed, 0 skipped** | `pytest tests -q` |
| Python 层同步 | 451 files match | `tools/verify_python_sync.py` |
| r45 APK | 30,028,748 B | GitHub release asset |
| APK 内 urllib3 | **2.8.0** | `unzip -l assets/chaquopy/requirements-common.imy` |
| APK 内 python-multipart | 0.0.32 | 同上 |
| patch 层合计 | 1.42 MB（`007` 单文件 871 KB） | `ls -la patches/` |
| `targetSdk` / `minSdk` | 29 / 29 | `app/build.gradle:32-33` |

r44 → r45 的测试增量是 193 → 207（+14：+2 解除跳过的 opencc 测试，+12 新增）。APK 只涨 17,852 B，说明 r45 几乎没有引入新依赖——这一点是好的。

---

## 3. 任务一：给 `Retry-After` 加上限（P0）

### 3.1 现状

`app/src/main/python/core/proxy_policy.py:125-135`：

```python
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
```

`respect_retry_after_header=True` 是**对的**——尊重服务端的退避指令比盲目指数退避更礼貌。问题在于它没有配套的上限。

### 3.2 为什么这是 P0

urllib3 2.8.0（r45 APK 里就是这个版本，已核实）的 `Retry.__init__` 签名：

```
retry_after_max: int = 21600
```

21600 秒 = **6 小时**。而 `Retry.sleep_for_retry()` 是**无条件下 `time.sleep(retry_after)`**，不做任何额外截断。

于是这个场景成立：

| 步骤 | 结果 |
|---|---|
| 某源返回 `429` + `Retry-After: 3600` | urllib3 睡 3600 秒 |
| 醒来重试，再收 `429` + `Retry-After: 3600` | 再睡 3600 秒 |
| `total=2` 用尽 | 返回 429 |

**单个请求耗时 2 小时。** 而批量刮削的并发是 4（`scanner.py:2197 _TITLE_BACKFILL_CONCURRENCY = 4`），200 条的批次里只要有 4 条命中这种源，整个批次就会像死机一样停在那里——UI 的进度条不动、取消按钮要等当前请求返回才生效。

对比一下 r45 之前的基线：同样是这个请求，以前是**立刻**计入失败项，用户 3 秒后就知道"这批没刮到"。现在变成 2 小时后才知道。**这是 r45 引入的、唯一一处"可能比改之前更糟"的行为。**

必须说清楚：这不是理论推演。DMM 的 429 通常不带 `Retry-After`（走 `backoff_factor`，0.5s / 1.0s，无害），JavDB 走 CF 403（不在 `status_forcelist` 里，无害）。**日常路径是安全的。** 风险来自自定义来源（`core/custom_source/fetch.py:76` 也走 `new_session()`）和任何一家突然开始发长 `Retry-After` 的站点。P0 的理由不是"现在就在坏"，而是"坏起来没有任何止损机制，且用户无法分辨是卡死还是慢"。

### 3.3 方案

```python
_RETRY_AFTER_MAX = 15  # 秒

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
    retry_after_max=_RETRY_AFTER_MAX,
)
```

### 3.4 为什么是 15 秒

- `core/scrapers/utils.py:144` 的 `rate_limit(delay)` 默认 0.3 秒，`ScraperConfig.delay` 上限 5 秒。15 秒是**正常节奏的 50 倍**，足够容纳任何"短时抖动"级别的真实退避。
- 超过 15 秒的 `Retry-After` 意味着对方在说"你现在别来"。这种情况下**快速失败、计入失败项、让用户稍后重跑**，比让 App 挂着好。扫描失败项本来就有记录（`scanner.py:1644`），用户能看到具体是哪几条。
- 15 秒 × 2 次重试 = 单请求最坏 30 秒。4 并发下，一个 200 条批次最坏多花 30 秒而不是几小时。这个量级用户可以接受，也分辨得出"慢"和"死"。

不要设成 0 或 `respect_retry_after_header=False`：那等于丢掉服务端最有价值的信息，会让重试变成"硬闯"。

### 3.5 依赖风险：`urllib3` 没有钉版本

`retry_after_max` 参数**只在 urllib3 ≥ 2.5 存在**。而 `app/build.gradle` 的 pip 块里没有 `urllib3`，它是 `requests==2.33.1` 的传递依赖，由 Chaquopy 在构建时解析。

今天解析到 2.8.0（已核实 APK 内容），所以直接加参数没问题。但如果哪天解析到 2.4.x，`Retry(..., retry_after_max=15)` 会在**模块导入时**抛 `TypeError`，`proxy_policy` 整个模块挂掉，所有刮削、所有自定义来源、整个设置页的代理配置一起死。这是一个"改一行、炸全站"的失败模式。

**因此本任务必须同时加一条钉版本**：

```gradle
install("requests==2.33.1")
install("urllib3==2.8.0")   # 新增：retry_after_max 需要 >= 2.5
```

2.8.0 就是 APK 里现有的版本，钉住**不产生任何行为变化**，只是把"隐式解析"变成"显式声明"。

如果不想钉版本，替代方案是运行时探测（不推荐，代码丑且掩盖问题）：

```python
_kwargs = {...}
if "retry_after_max" in inspect.signature(Retry.__init__).parameters:
    _kwargs["retry_after_max"] = _RETRY_AFTER_MAX
_RETRY = Retry(**_kwargs)
```

### 3.6 改动清单

| 文件 | 位置 | 改动 |
|---|---|---|
| `app/src/main/python/core/proxy_policy.py` | `:125-135` | 加 `_RETRY_AFTER_MAX = 15`，`Retry(...)` 加 `retry_after_max=` |
| `app/build.gradle` | pip 块 | 加 `install("urllib3==2.8.0")` |
| `patches/004-network-and-scraper-fallbacks.patch` | — | 重新生成 |

### 3.7 验证

新增到 `tests/test_r45_retry_policy.py`（沿用现有本地 HTTP server 脚手架）：

```python
def test_retry_policy_caps_retry_after():
    """Retry-After: 3600 必须被截到上限，不能真的睡一小时。"""
    import time
    started = time.monotonic()
    status, requests = _get_with_retry_after([429, 200], retry_after="3600")
    elapsed = time.monotonic() - started

    assert status == 200
    assert requests == 2
    assert elapsed < 40, f"retry_after_max 未生效，耗时 {elapsed:.1f}s"
```

需要在 `_serve()` 的 handler 里把 `Retry-After` 从硬编码 `"0"` 改成参数。

同时保留现有三条：`does_not_retry_404`（1 次）、`stops_after_two_status_retries`（3 次）、`honors_retry_after_and_recovers`（2 次）。

手工验证（模拟器 `emulator-5554`）：

1. 装 r46，扫描 50 条，观察是否与 r45 耗时相当（不应变慢）。
2. 用自定义来源指向一个返回 `429 + Retry-After: 3600` 的地址，确认该条在 ~30 秒内计入失败项，而不是挂着。

### 3.8 风险

| 编号 | 风险 | 概率 | 缓解 |
|---|---|---|---|
| R1a | `retry_after_max=15` 太紧，把真实短退避也截断 | 低 | 15 秒 > `delay` 上限 3 倍；截断只影响睡眠时长，不影响是否重试 |
| R1b | 未钉 urllib3 导致 `TypeError` | 中（若不加钉） | 必须加 `install("urllib3==2.8.0")` |
| R1c | 重试仍无法救 403 | 确定 | 设计如此，见 `_BLOCKED_STATUS` 不含 403；403 是"被挡"，重试只会加重 |

---

## 4. 任务二：回滚分支的测试（P1）

### 4.1 现状

`app/src/main/python/web/routers/database_backup.py:211-242` 的 `_restore_snapshot()` 是全项目最危险的函数：它要替换用户的整个数据库。现有 5 条测试（`tests/test_r45_database_restore.py`）覆盖了正常导入、哈希不符、非 ZIP、路径穿越、任务占用。

**但 `except` 分支（`:228-239`）一行都没被测过。**

```python
    except Exception:
        logger.exception("database restore failed")
        if replacement_started:
            _clear_db_init_cache()
            _delete_sqlite_sidecars(db_path)
            if backup_path is not None and backup_path.exists():
                try:
                    os.replace(backup_path, db_path)
                    init_db(force=True)
                except Exception:
                    logger.exception("database rollback failed")
        raise
```

### 4.2 三个未覆盖路径

| 路径 | 触发条件 | 当前后果（未测） |
|---|---|---|
| A | `os.replace(new_db, db_path)` 成功，`init_db(force=True)` 抛异常 | 应回滚到 `.bak`；若回滚也失败，用户数据库处于半毁状态 |
| B | 回滚的 `os.replace` 本身失败 | 只剩 `.bak` 文件，`db_path` 不存在 → App 下次启动会当成全新库 |
| C | 首次运行（`db_path` 不存在），`backup_path is None` | 回滚分支直接跳过，`raise` 后留下空目录 |

路径 A 是唯一"用户数据可能丢"的路径，也是唯一能用测试模拟的（B 需要文件系统故障注入，代价过高，列为已知风险）。

### 4.3 方案

在 `tests/test_r45_database_restore.py` 追加三条：

```python
def test_database_import_rolls_back_when_init_fails(tmp_path, monkeypatch):
    """init_db 在替换后失败时，必须把 .bak 换回来。"""
    source_db = tmp_path / "source.db"
    live_db = tmp_path / "openaver.db"
    backup_zip = tmp_path / "backup.zip"
    _initialize_database(source_db, "file:///library/source.mp4")
    _initialize_database(live_db, "file:///library/live.mp4")
    _make_backup(source_db, backup_zip)
    _patch_live_database(monkeypatch, live_db)

    real_init_db = database_backup.init_db
    calls = {"n": 0}

    def flaky_init_db(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated init failure")
        return real_init_db(*args, **kwargs)

    monkeypatch.setattr(database_backup, "init_db", flaky_init_db)

    with pytest.raises(HTTPException) as error:
        database_backup.import_database(_upload(backup_zip))

    assert error.value.status_code == 500
    assert calls["n"] == 2, "回滚后必须重新 init 一次"
    assert VideoRepository(live_db).get_by_path("file:///library/live.mp4") is not None
    assert VideoRepository(live_db).get_by_path("file:///library/source.mp4") is None


def test_database_import_prunes_old_backups(tmp_path, monkeypatch):
    """最多保留 3 份 .bak。"""
    live_db = tmp_path / "openaver.db"
    _initialize_database(live_db, "file:///library/live.mp4")
    for index in range(4):
        (tmp_path / f"openaver.db.bak-2026010{index}-000000-{index}").write_bytes(b"old")

    source_db = tmp_path / "source.db"
    backup_zip = tmp_path / "backup.zip"
    _initialize_database(source_db, "file:///library/source.mp4")
    _make_backup(source_db, backup_zip)
    _patch_live_database(monkeypatch, live_db)

    database_backup.import_database(_upload(backup_zip))

    assert len(list(tmp_path.glob("openaver.db.bak-*"))) == 3


def test_database_import_creates_missing_live_database(tmp_path, monkeypatch):
    """首次运行没有现存库时，backup 字段应为 None 且导入成功。"""
    source_db = tmp_path / "source.db"
    live_db = tmp_path / "openaver.db"
    backup_zip = tmp_path / "backup.zip"
    _initialize_database(source_db, "file:///library/source.mp4")
    _make_backup(source_db, backup_zip)
    _patch_live_database(monkeypatch, live_db)

    result = database_backup.import_database(_upload(backup_zip))

    assert result["ok"] is True
    assert result["backup"] is None
    assert VideoRepository(live_db).get_by_path("file:///library/source.mp4") is not None
```

注意：`init_db` 在 `database_backup` 里是 `from core.database import init_db` 直接导入的，所以必须 patch `database_backup.init_db`，不能 patch `core.database.init_db`。

### 4.4 改动清单

| 文件 | 改动 |
|---|---|
| `tests/test_r45_database_restore.py` | 追加 3 个测试函数（约 90 行） |

生产代码**不改**。这一项纯粹是补证据。

### 4.5 验证

```bash
pytest tests/test_r45_database_restore.py -v   # 期望 8 passed
pytest tests -q                                # 期望 211 passed, 0 skipped
```

### 4.6 风险

| 编号 | 风险 | 概率 | 缓解 |
|---|---|---|---|
| R2a | 测试本身写错，给假信心 | 中 | 故意把 `_restore_snapshot` 的回滚行注释掉，确认 A 测试变红 |
| R2b | 路径 B（回滚也失败）仍无覆盖 | 确定 | 记录为已知缺口，不做故障注入 |

---

## 5. 任务三：导入前磁盘空间预检（P2）

### 5.1 现状

`database_backup.py` 全文没有 `disk_usage` / `ENOSPC` 处理。上传上限是 `_BACKUP_MAX_BYTES = 256 MB`（`:31`）。

### 5.2 算一下占用

一次导入在 `db_path.parent`（App 私有目录，同一分区）里同时存在：

| 对象 | 大小 |
|---|---|
| `upload.zip`（已落盘） | ≈ 0.6–0.9 × 库体积（deflate） |
| 解压出的 `openaver.db` | 1.0 × 库体积 |
| `.bak` 快照（`VACUUM INTO`） | 1.0 × 库体积 |

**瞬时峰值约 3 倍库体积。** 一个 80 MB 的库，导入时需要 ~240 MB 空闲。中端手机 `/data` 分区剩几百 MB 是常态，ENOSPC 不是假想。

现在的行为：写到一半 `OSError` → `except (OSError, ...)` → 返回 422 "ZIP 格式无效"。**用户会以为是备份文件坏了**，实际上只是空间不够——这是一个错误归因，比失败本身更糟。

### 5.3 方案

在 `_extract_backup()` 里，`declared_total` 已经算出来了（`:101` 附近），写入前插入检查：

```python
def _require_free_space(directory: Path, required: int) -> None:
    """Fail early with an accurate message instead of a mid-write ENOSPC."""
    try:
        free = shutil.disk_usage(str(directory)).free
    except OSError:
        return  # 查不到就不拦，交给真正的写入错误
    if free < required:
        raise _import_error(507, "runtime.database.import_no_space")
```

调用点（`:107-108` 白名单校验之后、`:110` 写入循环之前）：

```python
            if set(selected) != _ALLOWED_BACKUP_FILES:
                raise _import_error(422, "runtime.database.import_invalid_zip")

            # 解压 1 份 + 备份快照 1 份
            _require_free_space(dest_dir, declared_total * 2)

            written_total = 0
```

`declared_total` 来自 ZIP 中央目录的 `file_size`，在 r45 里已经做了 `> _BACKUP_MAX_BYTES` 的封顶，所以不会被伪造的超大值骗到。

### 5.4 新增文案（4 语言）

必须同时加进四个文件，否则 `test_locale_files_have_identical_keys_and_placeholders` 会红。

`locales/zh_CN.json`（`runtime.database` 块，`import_task_running` 之后）：

```json
"import_no_space": "存储空间不足，导入需要约 {size} MB 空闲空间",
```

`locales/zh_TW.json`：

```json
"import_no_space": "儲存空間不足，匯入需要約 {size} MB 可用空間",
```

`locales/en.json`：

```json
"import_no_space": "Not enough storage space; importing needs about {size} MB free",
```

`locales/ja.json`：

```json
"import_no_space": "空き容量が不足しています。インポートには約 {size} MB の空きが必要です",
```

占位符 `{size}` 要真的传进去，否则文案里会出现裸的 `{size}`。改 `_import_error` 让它接受格式化参数：

```python
def _import_error(status_code: int, message_key: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=i18n_t(message_key, locale=get_config_locale(), **params),
    )
```

调用处传 `size=max(1, required // (1024 * 1024))`。

注意 `test_locale_files_have_identical_keys_and_placeholders` 会检查四个语言的占位符集合一致——四个都写 `{size}` 即可通过。

### 5.5 改动清单

| 文件 | 位置 | 改动 |
|---|---|---|
| `web/routers/database_backup.py` | `:63-66` | `_import_error` 加 `**params` |
| 同上 | `:70` 后 | 新增 `_require_free_space()` |
| 同上 | `:109` 后 | 插入调用 |
| `locales/zh_CN.json` / `zh_TW.json` / `en.json` / `ja.json` | `runtime.database` | 各加 1 条 `import_no_space` |
| `patches/006-mobile-web-routers.patch` | — | 重新生成 |

### 5.6 验证

```python
def test_database_import_rejects_when_disk_is_full(tmp_path, monkeypatch):
    source_db = tmp_path / "source.db"
    live_db = tmp_path / "openaver.db"
    backup_zip = tmp_path / "backup.zip"
    _initialize_database(source_db, "file:///library/source.mp4")
    _initialize_database(live_db, "file:///library/live.mp4")
    _make_backup(source_db, backup_zip)
    _patch_live_database(monkeypatch, live_db)
    monkeypatch.setattr(
        database_backup.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1, used=1, free=1024),
    )

    with pytest.raises(HTTPException) as error:
        database_backup.import_database(_upload(backup_zip))

    assert error.value.status_code == 507
    assert VideoRepository(live_db).get_by_path("file:///library/live.mp4") is not None
```

### 5.7 风险

| 编号 | 风险 | 概率 | 缓解 |
|---|---|---|---|
| R3a | Android 上 `shutil.disk_usage` 返回的分区与实际写入分区不一致 | 低 | 目录在同一分区；`OSError` 时放行不拦 |
| R3b | 507 状态码前端没处理 | 中 | `state-database.js` 的 `resp.ok` 判断已兜底，会走 `throw` 分支显示 `detail` |
| R3c | 文案占位符格式错误导致 KeyError | 低 | 现有测试会抓占位符漂移 |

---

## 6. 任务四：让 opencc 测试硬失败（P2）

### 6.1 现状

`tests/test_r43_localization.py:82` 和 `:94`：

```python
def test_simplified_chinese_contains_no_traditional_characters():
    opencc = pytest.importorskip("opencc")
```

r45 已经把 `opencc==1.4.2` 加进 `requirements-test.txt`，CI 两处（`build.yml:67`、`release.yml:73`）都会装。**病根拔了，但机制还在。**

`importorskip` 的本质是"装不上就算了"——这正是 r43 那两条测试三年没执行的原因。下次谁在本地重装环境、或者 CI 缓存失效导致某个依赖没装上，它又会安安静静地 skip 掉，而 summary 仍然是一片绿。

### 6.2 为什么不直接 `import opencc`

在模块顶部 `import opencc` 会让**整个文件**在收集阶段 ImportError，连带 `test_locale_files_have_identical_keys_and_placeholders` 等另外 8 条与 opencc 无关的测试一起消失。用一个依赖去绑架八个测试，比 skip 更糟。

### 6.3 方案

模块级软导入 + 测试内硬断言：

```python
try:
    import opencc
except ImportError:  # pragma: no cover
    opencc = None
```

```python
def test_simplified_chinese_contains_no_traditional_characters():
    assert opencc is not None, (
        "opencc 未安装，这条守门测试无法执行。"
        "请运行 pip install -r requirements-test.txt"
    )
    converter = opencc.OpenCC("t2s")
```

效果：依赖缺失时是**红色的 fail**（带可执行的修复指令），不是绿色的 skip；其余 5 条测试照常运行。

### 6.4 改动清单

| 文件 | 位置 | 改动 |
|---|---|---|
| `tests/test_r43_localization.py` | `:1-20` | 加 `try/except ImportError` 软导入 |
| 同上 | `:82` / `:94` | `importorskip` → `assert opencc is not None, "..."` |

### 6.5 验证

```bash
pytest tests/test_r43_localization.py -q            # 期望 10 passed
pip uninstall opencc -y && pytest tests/test_r43_localization.py -q
# 期望 2 failed（带修复提示）+ 8 passed，而不是 2 skipped
pip install opencc==1.4.2
```

---

## 7. 任务五：通知里的死参数（P3）

### 7.1 现状

`TaskKeepAliveService.java:22` 定义了 `EXTRA_LABEL`，`:52` 把它塞进 Intent：

```java
private static final String EXTRA_LABEL = "label";
...
intent.putExtra(EXTRA_LABEL, label);
```

但 `onStartCommand()`（`:69-74`）**从头到尾没读过它**：

```java
@Override
public int onStartCommand(Intent intent, int flags, int startId) {
    createNotificationChannel(this);
    startForeground(NOTIFICATION_ID, buildNotification());
    running = true;
    return START_NOT_STICKY;
}
```

整条链是通的：`state-scan.js:1101` 传 `kind` → `task-keepalive.js` 编码进 URL → `MainActivity:1126` 取出 → `TaskKeepAliveService.start(this, label)` → **然后被丢掉**。通知永远是"OpenAver 正在处理任务"。

`kind` 的实际取值：`generate`、`nfo-update`、`rename-preview`、`jellyfin-update`、`tag-source-update`、`tag-source-preview`，加上 `state-batch.js` 的 `taskKind`。

### 7.2 两个选项

**选项 A（推荐）：删掉死参数。**

- `TaskKeepAliveService.java`：删 `EXTRA_LABEL` 常量、`start(Context, String)` 的 `label` 形参、`putExtra` 行
- `MainActivity.java:1126`：`TaskKeepAliveService.start(this, uri.getQueryParameter("label"))` → `TaskKeepAliveService.start(this)`
- `task-keepalive.js`：`start(label)` → `start()`，URL 去掉 query
- `state-scan.js:1101`：`start(kind)` → `start()`

代价：零。收益：少 8 行永远不生效的代码，少一个"以为传了其实没用"的陷阱。

**选项 B：真把 kind 显示出来。**

需要把 7 个内部标识符映射到用户可读文案，即 5 个 `strings.xml`（default / en / ja / zh / zh-rTW）各加 3–4 条。收益是通知从"正在处理任务"变成"正在刮削"。

**不建议 B**：`strings.xml` 已经有 5 个语言目录要同步维护，为了一条通知标题增加 15–20 条字符串不划算；而且用户看通知时关心的是"还在跑 / 跑完了"，不是"跑的是哪个子任务"。

### 7.3 改动清单（选项 A）

| 文件 | 位置 | 改动 |
|---|---|---|
| `TaskKeepAliveService.java` | `:22, :45-52` | 删 `EXTRA_LABEL`、`label` 形参、`putExtra` |
| `MainActivity.java` | `:1126` | 调用改为无参 |
| `web/static/js/shared/task-keepalive.js` | `start()` | 去掉 `label` 与 query |
| `web/static/js/pages/scanner/state-scan.js` | `:1101` | `start(kind)` → `start()` |
| `tests/test_mobile_shell_cleanup.py` | `:117` | 断言改为 `"window.__openaverTaskKeepAlive.start()"` |

注意 `test_mobile_shell_cleanup.py:117` 现在断言的是 `"window.__openaverTaskKeepAlive.start(kind)"`，改代码必须同步改这条断言，否则测试红。

---

## 8. 任务六：web menu 对话框（P3，仅目视确认）

### 8.1 现状

`MainActivity.java:1018`：

```java
Dialog dialog = new Dialog(this, android.R.style.Theme_Material_Dialog_NoActionBar);
```

这是全项目**最后一处**用平台主题的对话框（其余 6 处已在 r45 换成 `R.style.Theme_OpenAverMobile_Dialog`）。

### 8.2 为什么可能本来就是对的

它和另外 6 处不是同类：

- 它是裸 `Dialog`，不是 `AlertDialog`，内容来自 `R.layout.dialog_web_menu`
- `:1054` 显式 `window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT))`，圆角和背景由布局自己画
- 因此平台主题里唯一可能生效的只有"没有显式设色的 `TextView` 的默认文字色"

如果 `dialog_web_menu.xml` 里所有文本都设了 `android:textColor`，那这处就是**正确的**，不该动。如果没设，那菜单文字会是 Material 默认的浅色，在深色背景上可能对比不足。

### 8.3 建议动作

1. 先看 `app/src/main/res/layout/dialog_web_menu.xml` 是否每个 `TextView` 都有 `android:textColor`。
2. 若都有 → 不动，在文档里记一句"有意保留"。
3. 若有的没设 → 换成 `R.style.Theme_OpenAverMobile_Dialog`（该 style 的 `windowBackground` 会被 `setBackgroundDrawable(TRANSPARENT)` 覆盖，不会破坏现有外观），然后在 `emulator-5554` 上截图对比。

**这一项在改之前必须先目视确认，不能凭代码推断。** r44 那次"深浅色错配"的误判就是这么来的。

---

## 9. 执行顺序与批次

### 批次 A → r46（建议）

| 顺序 | 任务 | 理由 |
|---|---|---|
| 1 | 任务一（`Retry-After` 上限 + 钉 urllib3） | 唯一有真实用户影响的项 |
| 2 | 任务二（回滚测试） | 只加测试，零生产风险；和任务一同批出可以让 r46 的测试数从 207 涨到 211 |
| 3 | 任务四（`importorskip` 硬失败） | 6 行，顺手 |

三项互不冲突，可一次构建。

### 批次 B → r47

| 顺序 | 任务 | 理由 |
|---|---|---|
| 4 | 任务三（磁盘预检） | 要动 4 个 locale 文件 + `_import_error` 签名，值得单独一批好回滚 |
| 5 | 任务五（死参数） | 纯清理 |
| 6 | 任务六（对话框） | 需目视，不适合赶 |

### 版本号

```gradle
versionCode 17062
versionName "0.17.18-r46"
```

---

## 10. 测试计划

### 10.1 新增测试汇总

| 文件 | 新增 | 类型 |
|---|---|---|
| `tests/test_r45_retry_policy.py` | 1（`caps_retry_after`） | 行为 |
| `tests/test_r45_database_restore.py` | 3（rollback / prune / missing-live） | 行为 |
| `tests/test_r45_database_restore.py` | 1（`disk_full`，批次 B） | 行为 |

### 10.2 期望结果

| 阶段 | 期望 |
|---|---|
| r46 完成 | **211 passed, 0 skipped** |
| r47 完成 | **212 passed, 0 skipped** |
| `verify_python_sync.py` | 451 files（r46/r47 不改上游文件数） |

**必须是 0 skipped。** 这是 r45 好不容易达成的，任何新 skip 都要当成失败处理。

### 10.3 手工回归（`emulator-5554`）

1. 扫 50 条 → 耗时与 r45 相当，无卡顿
2. 导入一份正常备份 → 成功 + 自动刷新 + 数据正确
3. 导入一份改坏的备份 → 422 + 现有数据完好
4. 扫描进行中导入 → 409
5. 切后台跑批量刮削 → 通知出现、任务继续、完成后通知消失
6. 播放单个视频 → 对话框配色为 `#74A0FF` 主色 + `#141B25` 背景
7. web menu（长按/菜单按钮）→ 目视确认文字对比度（任务六）

---

## 11. 风险总表

| 编号 | 风险 | 影响 | 概率 | 处置 |
|---|---|---|---|---|
| R1 | 钉 `urllib3==2.8.0` 与未来 `requests` 版本冲突 | 构建失败 | 低 | 构建时暴露，不会静默 |
| R2 | `retry_after_max` 截断导致某些源频繁失败 | 刮削成功率下降 | 低 | 15 秒已远高于正常节奏 |
| R3 | 回滚路径仍无端到端验证（仅 mock） | 极端情况下数据丢失 | 低 | 已有 `.bak` 兜底，最多留 3 份 |
| R4 | 磁盘预检误判（分区不一致） | 误报 507 | 低 | `OSError` 时放行 |
| R5 | 任务五改签名漏改测试断言 | CI 红 | 中 | 已列入改动清单 `test_mobile_shell_cleanup.py:117` |
| R6 | `targetSdk` 仍为 29 | Android 15+ 16 KB 页对齐收益**未兑现** | 确定 | 独立课题，不在本计划；16 KB 强制从 targetSdk 35 起生效 |

---

## 12. 附录 A：r45 验收记录

| 项 | 结论 |
|---|---|
| 数据库导入 | 完成。ZIP 白名单、zip-slip 拒绝、SHA-256、`integrity_check`、必需表校验、`os.replace` 原子替换、失败回滚、保留 3 份 `.bak`、409 任务占用 |
| 两条僵尸测试 | 完成。`opencc==1.4.2` 进 `requirements-test.txt`，CI 两处均安装，实测 0 skipped |
| 对话框主题 | 完成 6/7。`Theme.OpenAverMobile.Dialog` 新建，`MainActivity` 3 处 + `ExternalPlayer` 3 处替换，`Theme_Material_Dialog_Alert` 零残留；剩 `MainActivity:1018` 见任务六 |
| 退避重试 | 完成，但缺 `Retry-After` 上限（任务一） |
| 前台服务 | 完成。`TaskKeepAliveService`（`dataSync`）+ `openaver-task://` scheme + `onPause` 守卫，`_startTask`/`_finishTask` 双钩子覆盖扫描/批量/重命名预览 |
| 测试 | 207 passed / 0 skipped（r44：193 / 2） |
| 发布 | tag + release 已上，APK 30,028,748 B |

**评价：8.5/10。** 五项全部落地，其中数据库导入和前台服务的实现质量超出计划要求（计划里没要求 `.bak` 轮转和回滚，实际做了）。扣分只在任务一的副作用和测试覆盖的缺口。

---

## 13. 附录 B：一处需要更正的历史说法

早期讨论中曾断言：

> "`webView.onPause()` 会冻结 JS，所以光加前台服务没用。"

**这句话是错的。**

Android 官方文档对 `WebView.onPause()` 的说明是 "Does a best-effort attempt to pause any processing that can be paused safely, such as animations and geolocation. **Note that this call does not pause JavaScript.** To pause JavaScript globally, use `pauseTimers()`."

本项目全局搜不到 `pauseTimers` / `resumeTimers`，所以 r44 时代的冻结**不是 `onPause()` 造成的**。真实原因是进程退到后台后被降级为 cached process，随后被系统的 Cached Apps Freezer 冻结、并受 Doze 限制网络。

结论修正：

- **r45 真正起作用的是前台服务本身**——它把进程优先级提到 foreground，避开 freezer
- `onPause()` 里的 `!TaskKeepAliveService.isRunning()` 守卫是保险（避免任务期间 WebView 停掉动画/播放），**不是**修复的主因

功能实现没问题，但 release notes 和后续文档不要沿用旧说法。

另有一处小副作用：任务在后台结束时 `isRunning()` 变 false，但此时 `onPause()` 已经执行过、不会再被调用，于是这一轮后台期间 `webView.onPause()` 始终没跑。后果是 WebView 在后台保持"resumed"状态，略微费电，不影响功能。若在意，可在 `TaskKeepAliveService.stop()` 后回调 Activity 补一次 `webView.onPause()`——但 `onResume()` 会正常恢复，不补也不会出错。
