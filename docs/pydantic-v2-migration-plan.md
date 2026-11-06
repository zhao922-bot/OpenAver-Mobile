# OpenAver Mobile 迁移 pydantic v2 方案（草案）

| 项目 | 值 |
| --- | --- |
| 状态 | **草案；Phase 0 已预跑，Phase 1 未开始** |
| 关联 | `docs/r41-audit.md` §7.1（依赖版本线落后于上游安全基线） |
| 目标版本 | pydantic `2.13.3` + pydantic-core `2.46.3` |
| 代码基线 | r41（`1b2f681`）+ 工作区在途改动（见 §2.5） |
| 撰写日期 | 2026-11-06 |

## 0. 摘要

用外部预编译 wheel 把 pydantic 从 v1 升到 v2，解开 FastAPI / Starlette 的版本锁。

**预跑结果推翻了初稿的两个判断，先给结论：**

1. **代码基本已经兼容 v2。** 在桌面 venv（pydantic 2.13.3 + fastapi 0.125.0 +
   starlette 0.50.0）下跑完整测试：r41 基线 **175 passed**，当前工作区 **179 passed**，
   都只有 4 条弃用警告。不需要大改代码，也不需要"原子迁移"。
2. **只有一个真问题**：`SourceConfig.model_dump()` 会绕过 `dict()` 覆写，
   静默丢掉 `is_censored` 字段。这条现有测试**完全覆盖不到**，必须新增断言。

所以整件事的重心不在代码，而在 **Phase 1 的 wheel 能否在 Chaquopy 里加载**。
代码侧的工作量已经从"一次完整迭代"降到"一个方法 + 一个测试"。

## 1. 为什么做

当前依赖链是被 pydantic v1 卡住的，不是主动选择：

```
Android 无 pydantic-core wheel
  → pydantic 只能 1.10.24
    → FastAPI 只能 0.125.0（0.136.1 要求 pydantic>=2.9.0）
      → Starlette 只能 0.50.0（上游 1.6.0）
        → 上游为清 CVE 而锁的版本全部拿不到
```

上游 `requirements.txt` 的注释写明 starlette 1.6.0 是为清 `CVE-2026-48818`（StaticFiles
UNC/SMB）和 `CVE-2026-54283`（multipart form DoS）而锁的；pillow 12.3.0 那批列了 13 条 CVE。
移动端目前一条都吃不到。

升级 pydantic 是解开这条链的唯一入口。

## 2. 事实基线

### 2.1 版本对照

| 包 | 上游 | 移动端现状 | 迁移后 | 说明 |
| --- | --- | --- | --- | --- |
| pydantic | 2.13.4 | 1.10.24 | **2.13.3** | 只能用 2.13.3，见 §2.3 |
| pydantic-core | 2.46.4 | —（不存在） | **2.46.3** | 外部 wheel |
| fastapi | 0.136.1 | 0.125.0 | 0.125.0 | Phase 3 再升 |
| starlette | 1.6.0 | 0.50.0 | 0.50.0 | Phase 3 再升 |
| pillow | 12.3.0 | 11.0.0 | 不变 | Chaquopy 仓库只有 11.0.0 |
| lxml | 6.1.0 | 5.3.0 | 不变 | Chaquopy 仓库只有 5.3.0 |

pillow / lxml 无法通过本方案改善：Chaquopy 官方仓库对 cp313 + arm64 只提供
`pillow-11.0.0-0` 和 `lxml-5.3.0-0`（已逐条核实索引页，无更新版本）。

### 2.2 wheel 事实（已下载并解包核实）

| 项目 | 值 |
| --- | --- |
| 来源 | `Eutalix/android-pydantic-core` Release `v2.46.3`（2026-05-01） |
| 原始文件名 | `pydantic_core-2.46.3-cp313-cp313-linux_aarch64.whl` |
| 内部 WHEEL 标签 | `cp313-cp313-android_24_arm64_v8a` |
| 大小 | 1.9 MB（wheel）/ 4,547,784 B（`.so` 解压后） |
| SHA-256 | `323f219228e6a73f36e6c904dba0d8de01934abc889ce491c392c25a32385fed` |
| NEEDED | `libpython3.13.so`、`libdl.so`、`libc.so` |
| RUNPATH | `/data/data/com.termux/files/usr/lib`（**不含 `$ORIGIN`**） |
| LOAD 对齐 | `0x1000`（4 KB，**不是 16 KB**） |
| 许可证 | MIT |
| 项目状态 | **已归档**（2026-10-30 弃用公告） |

### 2.3 为什么必须锁 2.13.3

pydantic 对 pydantic-core 是精确版本约束（已查 PyPI 元数据）：

| pydantic | 要求 pydantic-core | 仓库是否提供 cp313 wheel |
| --- | --- | --- |
| 2.13.0 | 2.46.0 | 否 |
| 2.13.1 | 2.46.1 | 否 |
| 2.13.2 | 2.46.2 | 否 |
| **2.13.3** | **2.46.3** | **是** |
| 2.13.4（上游） | 2.46.4 | 否 |

v2.49.0 / v2.50.0 虽然有正确的 `android_24_arm64_v8a` 标签，但只有 `cp314`，
与本项目的 Python 3.13 不匹配。

### 2.4 Chaquopy 的标签规则（已核实源码）

`chaquopy/server/pypi/build-wheel.py:124`：

```python
self.compat_tag = f"{self.python_tag}-android_{self.api_level}_{self.abi_tag}"
```

Chaquopy 仓库里的真实文件名也是这个格式，例如
`pillow-11.0.0-0-cp313-cp313-android_24_arm64_v8a.whl`。

所以 Eutalix 的 `linux_aarch64` 文件名会被 Chaquopy 的 pip 判定为不支持平台。
但它的**内部 WHEEL 元数据已经是 `android_24_arm64_v8a`**——只是构建脚本为了让 Termux
的 pip 接受而改了文件名。**把文件名改回去即可。**

`android_24` 标签在 minSdk 29 的应用上可用：现有 pillow 就是 `android_24` 标签，
项目能正常构建，这是现成的经验证据。

### 2.5 代码基线说明

方案撰写期间工作区出现了 30 个已跟踪文件的改动，以及 `database_backup.py`、
`VideoPartParser.java`、`test_r42_improvements.py` 等新增文件（均非本次方案产生）。
本方案的所有结论基于**当前工作区**，落地前需要在最终基线（r42 提交后）重新确认一次：

- 测试数量：r41 基线 175 个，当前工作区 179 个
- `core/source_config.py` 未被这些改动触及，§3 的结论仍然成立
- 若 r42 的改动涉及 `web/app.py` 的中间件或 `StreamingResponse`，会影响 Phase 3 的风险评估

## 3. 代码兼容性预跑结果

### 3.1 实验设置

独立 venv（不动 `app/build/python/env/cleanup`），Python 3.13：

```
python -m venv /tmp/pyd2check
pip install -r requirements-test.txt
pip install "pydantic==2.13.3"        # 覆盖 1.10.24
pytest tests/ -q
```

实际装出的组合：`pydantic 2.13.3 / fastapi 0.125.0 / starlette 0.50.0`。

### 3.2 结果：两个基线都全绿

| 代码基线 | 用例数 | pydantic 1.10.24 | pydantic 2.13.3 |
| --- | --- | --- | --- |
| r41（`1b2f681`，临时 worktree） | 175 | 通过 | **175 passed** |
| 当前工作区（含在途改动） | 179 | 通过 | **179 passed** |

v2 下的原始输出（r41 基线）：

```
........................................................................ [ 40%]
........................................................................ [ 80%]
...................................                                      [100%]
175 passed, 4 warnings in 8.36s
```

4 条警告全部是 `PydanticDeprecatedSince20`：

| 位置 | 警告内容 | 处理 |
| --- | --- | --- |
| `core/proxy_policy.py:30` | class-based `config` 弃用 | Phase 4 改 `model_config` |
| `core/scrapers/models.py:8` | 同上（`Actress`） | Phase 4 |
| `core/scrapers/models.py:16` | 同上（`Video`） | Phase 4 |
| `core/source_config.py:50` | v1 风格 `@validator` 弃用 | 可选，见 §3.4 |

**结论：v2 的严格类型转换没有造成任何测试失败。** 初稿担心的 `int → str` 问题在现有
测试覆盖的路径上没有出现。

### 3.3 唯一的真问题：`model_dump()` 绕过 `dict()` 覆写

`core/source_config.py:95-98`：

```python
def dict(self, *args, **kwargs):
    data = super().dict(*args, **kwargs)
    data['is_censored'] = self.is_censored
    return data
```

现在能工作，是因为 shim 把 `model_dump` 映射成了 `self.dict()`：

```python
# pydantic_v1_compat.py:19-21
def model_dump(self, *args, **kwargs):
    return self.dict(*args, **kwargs)
```

**实测（pydantic 2.13.3）**：

```python
class B(BaseModel):
    id: str = "x"
    def dict(self, *a, **k):
        d = super().dict(*a, **k); d["extra_flag"] = True; return d

b.dict()        -> {'id': 'x', 'extra_flag': True}
b.model_dump()  -> {'id': 'x'}          # ← extra_flag 没了
```

`core/config.py:560`、`:608`、`:627` 都在用 `source.model_dump()`：

```python
return [source.model_dump() for source in get_builtin_sources()]
```

后果：`config.json` 的 `sources[*]` 丢掉 `is_censored`，而
`web/routers/capabilities.py:1622` 把这个字段写进了对外 API 契约
（`{id, display_name, type, enabled, order, is_censored}`）。**静默回归，不报错。**

**更麻烦的是：现有测试完全覆盖不到。** `grep -rn "is_censored" tests/` 零命中。
也就是说 §3.2 的 179 passed **不能证明**这个问题不存在——它只是没被测到。

**修法（两选一）**

方案 A（推荐，v2 惯用法）：

```python
@computed_field
@property
def is_censored(self) -> bool:
    ...
```

配合删掉 `dict()` 覆写。缺点是 `computed_field` 在 v1 里不存在，只能在换 wheel 之后改。

方案 B（版本无关，可分两步走）：

```python
def model_dump(self, *args, **kwargs):
    data = super().model_dump(*args, **kwargs)   # v2 走真实实现
    data['is_censored'] = self.is_censored       # v1 下 super() 是 shim，走 dict()
    return data
```

优点：在 v1 和 v2 下都能用，可以先落地、后换 wheel，风险最小。
缺点：`dict()` 覆写留着，v2 下每次调用都会触发弃用警告。

**已实测**：同一段代码在 `pydantic 2.13.3` 与 `pydantic 1.10.24 + shim` 两个环境下，
`dict()` 和 `model_dump()` 都返回 `{'id': 'x', 'extra_flag': True}`，无递归。

**无论选哪个，都必须补一条测试**：

```python
def test_source_config_model_dump_includes_is_censored():
    sc = SourceConfig(id="dmm", type="builtin", display_name_key="dmm")
    assert sc.model_dump()["is_censored"] is True
```

### 3.4 弃用但可用：`@validator`

初稿判断"`values.get()` 在 v2 下会抛 `AttributeError`"，**实测是错的**。
pydantic 2.13.3 的 v1 兼容层传的是**普通 dict**：

```
value = False
values type = dict
repr = {'id': 'dmm', 'type': 'builtin'}
```

`always=True` 的语义也保留了：缺 `requires_proxy` 键时仍然重算，得到 `True`。

**结论：`core/source_config.py:50` 不改也能跑。** 迁移到 `@model_validator(mode='after')`
只是消除弃用警告、为 pydantic v3 做准备，属于 Phase 4 的清理项，不是迁移前置条件。

### 3.5 其它已确认的小项

| 位置 | 现状 | v2 下的行为 | 处理 |
| --- | --- | --- | --- |
| `core/proxy_policy.py:31`、`core/scrapers/models.py:10,18` | `class Config: frozen = True` | 仍支持，仅警告 | Phase 4 改 `model_config` |
| `core/source_config.py:12` | `from pydantic import validator` | 可用（弃用别名） | Phase 4 可选 |
| `pydantic_v1_compat.py` 全文 | 手写 shim | `install()` 首行 `major >= 2` 直接 return，**自动失效** | Phase 4 删除 |
| `Field(...)` 的 v1 专有参数 | 无 | — | 已 grep 确认：`regex=`/`const=`/`min_items`/`orm_mode` 等全为 0 |

`pydantic_v1_compat.install()` 自带版本判断，所以切换依赖后即使忘了删调用点也不会报错。
这是现有实现里做得好的地方，迁移时可以借力。

## 4. 方案总览

```
Phase 0  代码兼容（已完成预跑）        [桌面，零 Android 风险]
   │     剩余：补 is_censored 测试 + 选定修法 A/B
   ▼
Phase 1  wheel 集成 spike              [唯一的高风险点]
   │     产出：模拟器上 import 成功 + 冒烟通过
   ▼
Phase 2  端到端 + 发布 r42
   │
   ▼
Phase 3  （可选）FastAPI / Starlette 升级
   │
   ▼
Phase 4  清理弃用写法、删 shim
```

与初稿最大的不同：**Phase 0 已经跑完**，且结论比预期乐观。整件事的风险集中在 Phase 1。

## 5. Phase 0：代码兼容（剩余工作）

**已完成**：在 pydantic 2.13.3 下跑通 r41 基线的 175 个测试与当前工作区的 179 个测试（§3.2）。

**剩余**：

1. 决定 §3.3 用方案 A 还是方案 B。
   - 若选 B：现在就能改，改完在 v1 和 v2 下各跑一次测试，两次都绿才提交。
   - 若选 A：等 Phase 1 通过后再改。
2. 补 `is_censored` 的序列化测试（§3.3）。
3. 补一条"老 config.json 迁移"测试：构造缺 `requires_proxy` 的条目，断言重建后
   `requires_proxy` 正确。

**门槛**

- 当前工作区 179 个测试在 **pydantic 1.10.24 和 2.13.3 两个环境下都全绿**
- 新增的 `is_censored` 测试在 v2 下能**先失败、修完再通过**（证明它真的守住了这个契约）

## 6. Phase 1：wheel 集成 spike

**目标**：回答"这个二进制在 Chaquopy 里到底能不能加载"。这是全案唯一的未知数。

### 6.1 物料准备

1. 下载 `pydantic_core-2.46.3-cp313-cp313-linux_aarch64.whl`
2. 校验 SHA-256 = `323f219228e6a73f36e6c904dba0d8de01934abc889ce491c392c25a32385fed`
3. 重命名为 `pydantic_core-2.46.3-cp313-cp313-android_24_arm64_v8a.whl`
4. 放到 `app/wheels/`，同目录加 `README.md` 记录来源、许可证、校验值、归档状态

### 6.2 构建配置

`app/build.gradle` 的 `chaquopy` 块：

```gradle
pip {
    // 让 pip 在本地目录里找候选，避免去 PyPI 找 pydantic-core
    options("--find-links", "wheels")
    install("pydantic==2.13.3")
    // ... 其余保持不变
}
```

`--find-links` 是首选：pip 解析 `pydantic==2.13.3` 时会在 `wheels/` 里找到
`pydantic-core==2.46.3`，不依赖安装顺序。

**备选**（若相对路径解析不符合预期）：显式写
`install("wheels/pydantic_core-2.46.3-cp313-cp313-android_24_arm64_v8a.whl")`，
放在 `install("pydantic==2.13.3")` **之前**，靠顺序满足依赖。

### 6.3 最小验证

先只验证"能不能加载"，不要一次改全量：

1. 构建 Debug APK
2. 装到 API 36 模拟器（`emulator-5554`）
3. 触发一次最小调用：进设置页读来源列表（走 `SourceConfig.model_dump()`）
4. 观察 `adb logcat` 是否有 `ImportError` / `dlopen failed` / `invalid p_align`

**门槛（全部满足才进 Phase 2）**

- `import pydantic_core` 成功，`pydantic_core.__version__ == "2.46.3"`
- 应用启动无 `UnsatisfiedLinkError`
- 设置页来源列表正常显示，每条带 `is_censored`
- `adb logcat` 无 `invalid p_align`、无 `library ... not found`

### 6.4 放弃条件（任一命中即回退）

- `dlopen failed: library "libpython3.13.so" not found` 且无法通过 RUNPATH 修正
- `has invalid p_align`（Android 15+ 兼容性无解，见 §11 R2）
- 加载成功但调用时 SIGSEGV / SIGILL
- `--find-links` 与显式安装两种方式下，pip 都坚持去 PyPI 拉 `pydantic-core`

## 7. Phase 2：端到端与发布

### 7.1 改动清单

| 文件 | 改动 | 影响 patches |
| --- | --- | --- |
| `app/build.gradle` | 加 `--find-links`，pydantic 改 2.13.3 | 否 |
| `app/wheels/*.whl` + `README.md` | 新增（1.9 MB 二进制） | 否 |
| `requirements-test.txt` | `pydantic==2.13.3` | 否 |
| `app/src/main/python/core/source_config.py` | §3.3 的修法 | **是** |
| `tests/` | 新增 `is_censored` 与配置迁移测试 | 否 |
| `docs/` | 记录决策与 provenance | 否 |

Phase 4 才会动 `pydantic_v1_compat.py` 与 `openaver_boot.py`（届时同样要同步 patches）。

### 7.2 patches 同步

改了 `app/src/main/python` 下任何文件都必须重新生成补丁：

```
python tools\generate_patches.py ^
  --upstream-root ..\openaver-upstream-v0.17.18 ^
  --source-root app\src\main\python ^
  --output-dir build\patch-check
```

生成后与现有 `patches/` 逐文件比较，确认只有预期文件变化。

### 7.3 验证矩阵

| 层级 | 检查项 | 命令 / 方式 |
| --- | --- | --- |
| 单元 | 测试全绿（v1 与 v2 两个环境） | `pytest tests/ -q` ×2 |
| 补丁 | 文件同步 | `verify_python_sync.py` |
| 语法 | JS 无语法错误 | `node --check`（三个文件） |
| 构建 | Debug + Release 均成功 | `gradlew assembleDebug` / `assembleRelease` |
| 运行 | 启动、扫描、补剧照、分集选择、网页播放 | API 36 模拟器 |
| 配置 | 老 `config.json` 迁移正常 | 手工造缺 `requires_proxy` 的条目 |
| 接口 | `capabilities` 返回含 `is_censored` | `curl` 或页面检查 |
| 体积 | APK 增量约 +2 MB | `ls -lh` 对比 |
| 崩溃 | logcat 无 native 崩溃 | `adb logcat` 全量过一遍 |

### 7.4 发布

按现有流程走 r42（`versionCode 17058` / `0.17.18-r42` / tag `v0.17.18-android-r42`），
不修改 r41 的任何产物。wheel 需显式 `git add app/wheels/...`，不使用 `git add -A`。

## 8. Phase 3（可选）：FastAPI / Starlette 升级

**前置条件**：Phase 2 已在设备上稳定运行，且没有 native 层问题。

| 变更 | 风险 | 说明 |
| --- | --- | --- |
| fastapi 0.125 → 0.136.1 | 中 | 跨 11 个小版本，路由/依赖注入可能有细微变化 |
| starlette 0.50 → 1.6.0 | 中高 | 跨大版本，`StaticFiles`、中间件、`StreamingResponse` 行为都可能变 |

本项目重度使用 `StreamingResponse`（SSE 补图/补翻译）和自定义 HTTP 中间件
（`mobile_auth` 的 `@app.middleware("http")`），这两块是 Starlette 跨大版本最可能出问题的地方。

**建议**：单独一轮，不与 Phase 2 混在一起。先只升 starlette 到 1.x 跑 SSE 全链路，
再升 fastapi。若中间件签名有变，改动会落在 `web/app.py` 和 `mobile_auth.py`，都在 patches 范围内。

## 9. Phase 4：清理

1. `SourceConfig` 的 `dict()` 覆写改 `@computed_field`（若 Phase 0 选了方案 B）
2. `@validator` → `@model_validator(mode='after')`
3. `class Config` → `model_config = ConfigDict(...)`（3 处）
4. 删除 `pydantic_v1_compat.py` 与 `openaver_boot.py:119-121` 的调用
5. 更新 `patches/001`、`patches/002` 与 `patches/README.md`
6. 在 `docs/r41-audit.md` §7.1 标注"已处理，见本文档"

## 10. 回滚

Phase 1 / Phase 2 失败时：

1. 回退 `app/build.gradle` 的 pip 块与 pydantic 版本
2. 删除 `app/wheels/`
3. 回退 `requirements-test.txt`
4. 若已改 `source_config.py`，回退该文件并重新生成 patches
5. 重新跑一次 v1 环境的 179 个测试，确认回到基线

因为代码改动被压缩到"一个方法 + 两个测试"，回滚面很小，不会牵连 r41。

## 11. 风险登记

| # | 风险 | 影响 | 概率 | 缓解 |
| --- | --- | --- | --- | --- |
| R1 | wheel 的 RUNPATH 指向 Termux 路径，加载失败 | Phase 1 直接失败 | 中 | 靠 Android 默认 lib 搜索兜底；失败则用 `patchelf` 改 RUNPATH 为 `$ORIGIN` 重打包 |
| R2 | `.so` 为 4 KB 对齐，Android 15+ 16 KB 页设备拒绝加载 | 未来设备不可用 | 高（确定存在） | 记录为已知限制；长期需自建 wheel 或等 Chaquopy 提供 |
| R3 | 依赖已归档项目，cp313 不再更新 | 无法跟进上游 | 高（已发生） | 锁定 2.46.3；记录来源与弃用状态；不当作长期方案 |
| R4 | 引用 8 个 `_Py*` 私有符号 | 换 CPython 构建时可能失败 | 低 | 已核实是 PyO3 常规用法，标准 CPython 3.13 均导出；Phase 1 实测 |
| R5 | v2 严格类型转换导致运行期校验失败 | 功能回归 | **低（已预跑，179 passed）** | 残余风险仅在未测试的刮削器原始数据路径 |
| R6 | `is_censored` 静默丢失 | 接口契约破坏 | 高（若不改） | §3.3 修法 + 专门的断言测试 |
| R7 | pydantic 只能到 2.13.3，比上游低一个 patch | 行为差异 | 低 | 记录版本差；差异仅在 core 的 patch 级修复 |
| R8 | wheel 入库增加 1.9 MB | 仓库膨胀 | 确定 | 单文件可接受；记录校验值 |
| R9 | 工作区有 30 个在途改动，与迁移改动交叉 | 冲突、误提交 | 中 | 迁移必须基于 r42 提交后的干净基线；不与在途改动混在一起 |

## 12. 决策树

```
Phase 0（已预跑：179 passed）
├─ 补 is_censored 测试后是否仍全绿？
│    ├─ 否 → 说明还有隐藏的序列化差异，逐个定位后再继续
│    └─ 是 ↓
Phase 1 import 是否成功？
├─ 否（dlopen / p_align / SIGSEGV）
│    → 放弃本方案，回退 v1，把"自建 wheel"排入长期计划
└─ 是 ↓
Phase 2 设备端功能是否全部通过？
├─ 否 → 判断是 pydantic 行为差异还是 wheel 问题；前者修，后者放弃
└─ 是 → 发布 r42，Phase 3 另起一轮
```

## 13. 附录 A｜wheel 关键事实（供复核）

```
文件名（改名后） pydantic_core-2.46.3-cp313-cp313-android_24_arm64_v8a.whl
SHA-256          323f219228e6a73f36e6c904dba0d8de01934abc889ce491c392c25a32385fed
WHEEL Tag        cp313-cp313-android_24_arm64_v8a
METADATA         Name: pydantic_core / Version: 2.46.3 / Requires-Python: >=3.9
                 Requires-Dist: typing-extensions>=4.14.1
                 License-Expression: MIT
ELF              ELF64 / AArch64 / DYN
NEEDED           libpython3.13.so, libdl.so, libc.so
RUNPATH          /data/data/com.termux/files/usr/lib
LOAD p_align     0x1000
未定义符号       204 个，其中 _Py* 私有符号 8 个
```

## 14. 附录 B｜Chaquopy 标签规则的证据

- 源码：`chaquopy/server/pypi/build-wheel.py:124`
  `self.compat_tag = f"{self.python_tag}-android_{self.api_level}_{self.abi_tag}"`
- 仓库实例：`https://chaquo.com/pypi-13.1/pillow/` 下
  `pillow-11.0.0-0-cp313-cp313-android_24_arm64_v8a.whl`
- 经验证据：本项目 minSdk 29，用的正是 `android_24` 标签的 pillow，构建正常

## 15. 待确认

1. Chaquopy 的 pip 是否支持 `options("--find-links", "wheels")` 的相对路径解析
   （文档只给了 `--extra-index-url` 的例子）。
2. `--find-links` 模式下 pip 是否仍会访问 PyPI 查询 `pydantic-core`（离线构建时是否阻塞）。
3. API 36 模拟器是否为 16 KB 页配置——如果是，Phase 1 会直接撞上 R2，
   需要换 4 KB 页的模拟器验证。
4. 工作区在途改动落地后，`source_config.py` 与 `config.py` 是否被触及
   （目前未被触及，§3 结论成立）。
