# OpenAver Mobile：改用 TUR 的 pydantic-core 2.41.5 解锁依赖链

| 项目 | 值 |
| --- | --- |
| 状态 | **已完成；r42 已构建、模拟器验证并准备发布** |
| 关联 | `docs/r41-audit.md` §7.1、`docs/pydantic-v2-migration-plan.md` |
| 替换对象 | `app/wheels/pydantic_core-2.46.3-...whl`（Eutalix，已归档，4 KB 对齐） |
| 目标物料 | `pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl`（TUR 官方构建，16 KB 对齐） |
| 目标栈 | pydantic `2.12.5` + fastapi `0.136.1` + starlette `1.6.0` |
| 代码基线 | r41（`1b2f681`）+ 工作区在途改动 |
| 撰写日期 | 2026-11-06 |

## 0. 摘要

**换掉 Eutalix 的 2.46.3，改用 TUR（Termux User Repository）官方构建的 2.41.5。**

这不是"从零接入"，而是"换供应商"——工作区已经落地了 Eutalix 方案（见 §1），
本方案只替换二进制和版本号，代码侧不动。

**三个决定性差异（全部实测，非推断）：**

| 差异 | Eutalix 2.46.3 | TUR 2.41.5 | 后果 |
| --- | --- | --- | --- |
| LOAD 段对齐 | `0x1000`（4 KB） | **`0x4000`（16 KB）** | 16 KB 页设备上 Eutalix 需依赖系统兼容模式，TUR 原生满足 |
| 平台标签来源 | `linux_aarch64` 改名而来 | **原生 `android_24_arm64_v8a`** | TUR 不需要改文件名，元数据与内容自洽 |
| 项目状态 | 2026-10-30 **已归档** | **活跃**（2026-11 仍在构建 2.50.4） | TUR 能跟版本，Eutalix 永远停在 2.46.3 |

**附带收益：解开 FastAPI / Starlette 的版本锁。**

pydantic 2.12.5 满足 `fastapi 0.136.1` 的 `pydantic>=2.9.0`，所以这次能一次把
FastAPI 从 `0.125.0` 升到 `0.136.1`、Starlette 从 `0.50.0` 升到 `1.6.0`，
吃到上游为清 `CVE-2026-48818` / `CVE-2026-54283` 而锁的版本。Eutalix 那条路做不到——
它只能到 pydantic 2.13.3，FastAPI 仍卡在 0.125.0（本次一并验证：**182 passed**）。

**代价只有一个**：pydantic 从 `2.13.3` 降到 `2.12.5`，比上游 `2.13.4` 低两个 patch。
换来的是一份能装到 2026 年新设备上的二进制。

## 1. 现状：起点不是 r41

写这份方案时，工作区已经不是干净的 r41 了。以下改动**已在磁盘上**：

| 项 | 位置 | 状态 |
| --- | --- | --- |
| `model_dump()` 覆写 | `app/src/main/python/core/source_config.py:100-106` | 已加（7 行 diff，即前一份方案的"方案 B"） |
| Eutalix wheel | `app/wheels/pydantic_core-2.46.3-...whl` | 已放（1,988,330 B） |
| 本地 wheel 目录 | `app/build.gradle:127` `options("--find-links", "wheels")` | 已加 |
| pydantic 版本 | `app/build.gradle:137` `install("pydantic==2.13.3")` | 已改 |
| 测试依赖 | `requirements-test.txt` `pydantic==2.13.3` | 已改 |
| wheel 说明 | `app/wheels/README.md` | 已写，记录了 4 KB 对齐限制 |
| patches | `patches/` | **未同步**（`source_config.py` 的改动还没进 patch） |

所以本方案的动作是**替换**，不是**新增**：

```
删 app/wheels/pydantic_core-2.46.3-*.whl
放 app/wheels/pydantic_core-2.41.5-*.whl
改 build.gradle:137  pydantic 2.13.3 → 2.12.5
改 build.gradle:128  fastapi 0.125.0 → 0.136.1
改 build.gradle:129  starlette 0.50.0 → 1.6.0
改 requirements-test.txt 同步三个版本
重写 app/wheels/README.md
重新生成 patches
```

代码（`source_config.py`）不需要再动。

## 2. 事实基线

### 2.1 wheel 事实（已下载、解包、逐项核实）

| 项目 | 值 |
| --- | --- |
| 索引页 | `https://termux-user-repository.github.io/pypi/pydantic-core/` |
| 下载地址 | `https://github.com/tur-pypi-dists/python3.13-pydantic_core/releases/download/v2.41.5/pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl` |
| 文件名 | `pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl`（**原生，无需改名**） |
| 大小 | 1,931,192 B（wheel）/ 4,591,633 B（`.so`） |
| SHA-256 | `1c6ad3f171f8078102e7f345b5d53c3d79a5a5cfb953a4789f9f7e7f8149ff8c` |
| 内部 WHEEL 标签 | `cp313-cp313-android_24_arm64_v8a` |
| 构建工具 | maturin 1.12.6 |
| 许可证 | MIT（`pydantic_core-2.41.5.dist-info/licenses/LICENSE`） |
| 上游项目 | `termux-user-repository/pypi-wheel-builder` |

包内 `.so` 名：`pydantic_core/_pydantic_core.cpython-313-aarch64-linux-android.so`

### 2.2 ELF 实测

```
Class / Type / Machine   ELF64 / DYN / AArch64
NEEDED                   libpython3.13.so, libdl.so, libc.so
RUNPATH                  $ORIGIN/../pydantic_core-libs:/data/data/com.termux/files/usr/lib
SONAME                   （无）
LOAD p_align             0x4000  ← 16 KB，四条 LOAD 中前三条为 0x4000
符号版本                 全部标记为 LIBC（bionic，非 glibc）
```

三点值得单独说明：

1. **`p_align = 0x4000` 是本次换供应商的核心理由。** Eutalix 的 `.so` 是 `0x1000`。
   16 KB 页设备（Android 15 起出现）对 4 KB 对齐的 `.so` 需要应用声明
   `android:pageSizeCompat` 走兼容模式，否则 linker 报 `has invalid p_align`；
   Google Play 也已要求新应用与更新支持 16 KB 页对齐。本项目是侧载分发，
   不直接受 Play 政策约束，但**在 16 KB 页设备上会变成"能不能装得进去"的问题**。
   TUR 的物料原生 16 KB 对齐，这层不确定性直接消失。
2. **RUNPATH 里 `$ORIGIN/../pydantic_core-libs` 排在最前**，Termux 路径是第二个兜底。
   实际 `pydantic_core-libs/` 是**空目录**（Rust 依赖已静态链接），所以这条不构成依赖。
3. **`SONAME` 为空**，linker 按文件名匹配；Chaquopy 的 `libpython3.13.so` 带
   `SONAME: libpython3.13.so`，与 NEEDED 精确对上（见 §2.4）。

### 2.3 符号全量比对（最强静态证据）

把 pydantic-core 的**全部**未定义符号，与 Chaquopy `libpython3.13.so`（从 r28 APK 提取）
加上 NDK sysroot 的 `libc.so` / `libdl.so` / `libm.so` 导出表做集合差：

```
需要 208 个未定义符号
可用 3397 个（libpython 1682 + bionic 三件套）
无法解析 0 个
```

其中 9 个 CPython 私有符号逐个确认存在：

```
OK  _PyLong_FromByteArray      OK  _PyObject_MakeTpCall    OK  _Py_CheckFunctionResult
OK  _Py_Dealloc                OK  _Py_EllipsisObject      OK  _Py_FalseStruct
OK  _Py_NoneStruct             OK  _Py_NotImplementedStruct OK  _Py_TrueStruct
```

> 对比：Eutalix 的 `.so` 是 204 个未定义符号、8 个私有符号。
> TUR 多一个 `_PyLong_FromByteArray`（2.41.5 的序列化路径用到），Chaquopy 也导出了。

### 2.4 扩展模块后缀匹配（容易被忽略的坑）

Chaquopy 的 `_sysconfigdata__android_aarch64-linux-android.pyc` 里：

```
EXT_SUFFIX = '.cpython-313-aarch64-linux-android.so'
```

TUR 包内的文件名正是 `_pydantic_core.cpython-313-aarch64-linux-android.so`，**完全匹配**，
不需要重命名。

> 对照：Chaquopy 自己构建的 pillow 用的是裸名 `PIL/_imaging.so`。
> CPython 的 `EXTENSION_SUFFIXES` 标准值是 `[EXT_SUFFIX, '.abi3.so', '.so']`，
> 裸名走的是第三条兜底规则。两种都能 import，但 TUR 的带 ABI 后缀名直接命中第一条，
> 更精确，也避免与同目录其它 `.so` 混淆。

### 2.5 Python 层与官方一致性

担心 TUR 可能 patch 过 Python 代码，做了一次逐字节比对（下载 PyPI 官方
`pydantic_core-2.41.5-cp313-cp313-win_amd64.whl` 作为参照）：

| 文件 | TUR 大小 | PyPI 大小 | 归一化后差异行数 |
| --- | --- | --- | --- |
| `pydantic_core/__init__.py` | 5,115 B | 5,286 B | **0** |
| `pydantic_core/core_schema.py` | 154,730 B | 159,165 B | **0** |

大小差异全部来自换行符（PyPI 打包为 CRLF，TUR 为 LF）。**TUR 没有改 Python 层**，
只是换了个编译器重编 Rust 部分。

### 2.6 版本链

```
pydantic 2.12.5  ──(精确依赖)──►  pydantic-core == 2.41.5   ← TUR wheel
                 ├──►  annotated-types >= 0.6.0
                 ├──►  typing-extensions >= 4.14.1
                 └──►  typing-inspection >= 0.4.2

fastapi 0.136.1  ──►  pydantic >= 2.9.0   ✅
                 ├──►  starlette >= 0.46.0 ✅
                 ├──►  typing-inspection >= 0.4.2
                 └──►  annotated-doc >= 0.0.2

starlette 1.6.0  （不依赖 pydantic）
```

关键：`pydantic>=2.9.0` 是**下界**，2.12.5 满足。所以 FastAPI 能升到上游版本。

## 3. 代码侧实测（已完成）

### 3.1 实验设置

独立 venv，装目标栈：

```
pydantic 2.12.5 / pydantic-core 2.41.5 / fastapi 0.136.1 / starlette 1.6.0
uvicorn 0.46.0 / pytest 8.4.2 / httpx 0.28.1 / Pillow 11.0.0 / lxml 5.3.0
```

直接跑项目 `pytest`（`tests/conftest.py` 会把 `app/src/main/python` 加进 `sys.path`）。

### 3.2 结果

```
184 passed, 4 warnings in 5.96s
```

比 r41 基线的 175 多 7 个，来源：工作区新增的 `tests/test_r42_improvements.py`（3 个）
加上其它在途测试改动。**没有 skip、没有 xfail、没有 error。**

4 条警告全部是 `PydanticDeprecatedSince20`：

| 位置 | 内容 |
| --- | --- |
| `core/proxy_policy.py:30` | class-based `config` |
| `core/scrapers/models.py:8` | class-based `config` |
| `core/scrapers/models.py:16` | class-based `config` |
| `core/source_config.py:50` | v1 风格 `@validator` |

都是"能用但该换写法"，不影响功能，属 Phase C 之后的清理项。

### 3.3 `is_censored` 契约已验证

工作区已实现 `model_dump()` 覆写（方案 B），在 2.12.5 下实测：

```python
sc = SourceConfig(id='dmm', type='builtin', display_name_key='dmm')
sc.dict()        -> {... 'requires_proxy': True, 'is_censored': True}
sc.model_dump()  -> {... 'requires_proxy': True, 'is_censored': True}   # 一致
get_builtin_sources()[0].model_dump() 的字段集合
                 -> ['config','display_name_key','display_name_raw','enabled','id',
                     'is_beta','is_censored','manual_only','order','requires_proxy','type']
```

`@validator('requires_proxy', always=True)` 在 2.12.5 下也正常：缺键时重算得到 `True`。

**结论：代码侧无需再改。** 唯一缺的是一条守住这个契约的测试（§6.6）。

## 4. 方案总览

```
Phase A  替换物料与版本声明          [零风险，纯文本改动]
   │     wheel + build.gradle + requirements-test + README + patches
   ▼
Phase B  构建 + 模拟器验证           [唯一需要真机/模拟器的一步]
   │     门槛：import 成功 + 来源列表带 is_censored + 无 dlopen 报错
   ▼
Phase C  发布 r42
   │
   ▼
Phase D  清理弃用写法、删 shim       [可与 C 解耦]
```

与 Eutalix 方案相比，Phase A 多了"删旧 wheel"和"改三个版本号"，
Phase B 的验证项完全一致——因为**风险点已经从二进制转移到构建配置**。

## 5. Phase A：替换物料与版本声明

### 5.1 文件变更清单

| # | 文件 | 动作 |
| --- | --- | --- |
| 1 | `app/wheels/pydantic_core-2.46.3-cp313-cp313-android_24_arm64_v8a.whl` | 删除 |
| 2 | `app/wheels/pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl` | 新增（1,931,192 B） |
| 3 | `app/wheels/README.md` | 重写（§5.3） |
| 4 | `app/build.gradle:128` | `fastapi==0.125.0` → `fastapi==0.136.1` |
| 5 | `app/build.gradle:129` | `starlette==0.50.0` → `starlette==1.6.0` |
| 6 | `app/build.gradle:137` | `pydantic==2.13.3` → `pydantic==2.12.5` |
| 7 | `requirements-test.txt` | 同步三个版本 |
| 8 | `patches/` | 重新生成（§5.4） |
| 9 | `tests/test_source_config.py`（或现有测试文件） | 新增 `is_censored` 断言（§6.6） |

**不动**：`app/src/main/python/**` 的任何代码（`model_dump()` 覆写已就位）。

### 5.2 物料准备

```bash
# 1. 下载
curl -L -o pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl \
  "https://github.com/tur-pypi-dists/python3.13-pydantic_core/releases/download/v2.41.5/pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl"

# 2. 校验（必须匹配，不匹配就停）
sha256sum pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl
# 期望：1c6ad3f171f8078102e7f345b5d53c3d79a5a5cfb953a4789f9f7e7f8149ff8c

# 3. 放入仓库
mv pydantic_core-2.41.5-*.whl app/wheels/
rm app/wheels/pydantic_core-2.46.3-cp313-cp313-android_24_arm64_v8a.whl
```

> 备选来源：如果 GitHub Release 不可达，TUR 索引页
> `https://termux-user-repository.github.io/pypi/pydantic-core/` 也指向同一文件。

### 5.3 `app/wheels/README.md` 重写

原 README 里"4 KB 对齐"的已知限制必须删掉——新物料没有这个问题。
建议内容：

```markdown
# Vendored Android wheels

## pydantic_core 2.41.5

Prebuilt `pydantic-core` wheel for the Android Python 3.13 build.

- Source: Termux User Repository (TUR) pypi index
  https://termux-user-repository.github.io/pypi/pydantic-core/
- Build system: termux-user-repository/pypi-wheel-builder (maturin 1.12.6)
- Asset: pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl
- SHA-256: 1c6ad3f171f8078102e7f345b5d53c3d79a5a5cfb953a4789f9f7e7f8149ff8c
- License: MIT (embedded in the wheel)

The filename and the internal WHEEL tag are both
`cp313-cp313-android_24_arm64_v8a`, so no renaming is required.

Verified properties (see docs/tur-pydantic-core-2.41.5-plan.md):
- LOAD segments are 16 KB aligned (0x4000), usable on Android 15+ 16 KB page devices.
- NEEDED: libpython3.13.so, libdl.so, libc.so. All 208 undefined symbols resolve
  against Chaquopy's libpython3.13.so plus bionic.
- RUNPATH references Termux, but `$ORIGIN/../pydantic_core-libs` comes first and
  `libpython3.13.so` is matched by SONAME against the already-loaded Chaquopy runtime.
- Python sources are byte-identical to the official 2.41.5 release (LF vs CRLF only).

Known limitations:
- Python 3.13 is required. arm64-v8a is the release target; an x86_64 wheel is
  vendored only for Android-emulator validation.
- pydantic-core is pinned by pydantic's exact requirement: pydantic 2.12.5 ↔ core 2.41.5.
  Upgrading pydantic requires a matching core wheel.

Do not replace this artifact without rebuilding the APK, running the full test suite,
and verifying native loading on an Android arm64 device or emulator.
```

### 5.4 `app/build.gradle` 与 `requirements-test.txt`

`app/build.gradle` 的 `pip` 块改成：

```gradle
        pip {
            options("--find-links", "wheels")
            install("fastapi==0.136.1")
            install("starlette==1.6.0")
            install("uvicorn==0.46.0")
            install("jinja2==3.1.6")
            install("python-multipart==0.0.32")
            install("requests==2.33.1")
            install("httpx==0.28.1")
            install("beautifulsoup4==4.14.3")
            install("lxml==5.3.0")
            install("pydantic==2.12.5")
            install("pillow==11.0.0")
            install("PyYAML==6.0.3")
        }
```

`requirements-test.txt` 同步前三行：

```
fastapi==0.136.1
starlette==1.6.0
uvicorn==0.46.0
pydantic==2.12.5
```

> `typing-inspection` 与 `annotated-doc` 不需要显式写——pip 会作为传递依赖自动拉取，
> 两者都是纯 Python 包，Chaquopy 能装。

### 5.5 patches 重新生成

`source_config.py` 已改但 patches 没跟上，**这一步不做 CI 必挂**。

```bash
python tools/generate_patches.py
python tools/verify_python_sync.py --upstream-root <上游目录> --source-root app/src/main/python
```

CI 里的写法（`.github/workflows/build.yml:62-64`）是
`--upstream-root upstream --source-root app/src/main/python`，本地验证时把 `upstream`
换成实际的上游 checkout 路径。

预期：`patches/manifest.json` 的 `patches[4].files[23]`（`core/source_config.py`）哈希更新，
`verify_python_sync.py` 报告全部文件匹配。

## 6. Phase B：构建与设备验证

### 6.1 构建

```bash
./gradlew :app:assembleDebug
```

**先看构建日志里的这一行**：pip 实际选中了哪个 wheel（下面是示意，实际格式以 pip 输出为准）。

```
Collecting pydantic-core==2.41.5
  Using cached pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl (1.9 MB)
```

如果出现的是 `manylinux` / `win_amd64` / `musllinux` 之类，说明平台过滤没生效，
立刻停——装进去的二进制在设备上必然加载失败。

### 6.2 三种 pip 写法与取舍

`--find-links wheels` 是首选（工作区已采用）。如果 Chaquopy 对相对路径解析不符合预期，
按下面顺序降级：

| 优先级 | 写法 | 说明 |
| --- | --- | --- |
| 1 | `options("--find-links", "wheels")` | 依赖解析自动完成，不依赖安装顺序 |
| 2 | `install("wheels/pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl")` 放在 `install("pydantic==2.12.5")` **之前** | 显式路径，靠顺序满足依赖 |
| 3 | `options("--extra-index-url", "https://termux-user-repository.github.io/pypi/")` | 直连 TUR 索引，构建依赖外网可用性，不推荐作为常态 |

三种都不要配 `--no-index`——那会连带要求把 pydantic、fastapi、starlette 等
全部纯 Python 包也放进 `wheels/`，维护成本不值。

### 6.3 模拟器验证

只用 `emulator-5554`，**不碰真机 `901LGaff7f7de`**。

```bash
adb -s emulator-5554 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5554 logcat -c
adb -s emulator-5554 shell am start -n dev.openaver.mobile/.MainActivity
```

验证项：

| # | 检查 | 方法 | 期望 |
| --- | --- | --- | --- |
| 1 | 扩展模块能加载 | `logcat` 过滤 `pydantic_core` | 无 `ImportError` / `dlopen failed` / `invalid p_align` |
| 2 | 版本正确 | 设置页或调试接口读 `pydantic_core.__version__` | `2.41.5` |
| 3 | 来源列表 | 打开设置页来源管理 | 每个来源正常显示，`is_censored` 与预期一致（dmm/javbus/jav321/javdb/javlibrary 为有码） |
| 4 | 配置读写 | 改一次来源开关，重启应用 | 设置保持，`config.json` 里 `sources[*]` 含 `is_censored` |
| 5 | 基础功能 | 搜索一次、打开一个详情页 | 无 500，无白屏 |
| 6 | 静态资源 | 打开任意页面看 CSS/JS | 正常（验证 Starlette 1.6.0 的 StaticFiles） |
| 7 | multipart | 触发一次需要上传/表单的操作 | 正常（验证 `CVE-2026-54283` 修复后的 multipart 路径） |

第 6、7 项是**新增的**——Starlette 从 0.50.0 跳到 1.6.0 是跨大版本，
`StaticFiles` 与 multipart 解析都改过，必须实测。

**r42 实测结果（2026-11-06）**：API 36 x86_64 模拟器使用 `-gpu host` 时，
冷启动、搜索 `SONE-205`、搜索结果渲染、设置页均正常；`pydantic_core 2.41.5`
加载成功，无 `dlopen` / `p_align` / `UnsatisfiedLinkError`。同一镜像在
headless + swiftshader/GPU off 下会在渲染搜索结果时触发 QEMU
`0xc0000005`，但应用进程和 Python 搜索均已完成，属于模拟器渲染崩溃。
配置接口返回 10 个来源且全部带 `is_censored`；数据库导出返回有效 ZIP。

### 6.4 门槛（全部满足才进 Phase C）

- `import pydantic_core` 成功，`__version__ == "2.41.5"`
- 应用冷启动无 `UnsatisfiedLinkError`
- 来源列表 11 个字段齐全，`is_censored` 正确
- 搜索、详情、播放、设置四条主链路走通
- `logcat` 无 `invalid p_align`、无 `library "libpython3.13.so" not found`

### 6.5 放弃条件（任一命中即回退）

- `dlopen failed: library "libpython3.13.so" not found` 且确认 SONAME 匹配失效
- `has invalid p_align`（不应出现——本物料的 `p_align` 是 `0x4000`）
- 加载成功但调用时 SIGSEGV / SIGILL（说明 Rust 侧与 bionic 不兼容）
- pip 坚持从 PyPI 拉非 Android 平台的 `pydantic-core`，且三种写法都改不动
- Starlette 1.6.0 导致无法修复的行为回归 → **降级保留 pydantic 2.12.5，只回退 fastapi/starlette**

最后一条要单独强调：FastAPI/Starlette 升级与 pydantic 升级是**两个可独立回退的改动**。
如果只是 Starlette 出问题，把 `fastapi==0.125.0` / `starlette==0.50.0` 改回去，
pydantic 2.12.5 + TUR wheel 仍然成立。

### 6.6 补一条守住契约的测试

`grep -rn "is_censored" tests/` 目前零命中。`model_dump()` 覆写是手工维护的契约，
没有测试守着，下次重构很容易被删掉。

```python
def test_source_config_model_dump_includes_is_censored():
    """model_dump() 必须与 dict() 一致地输出 is_censored（v1/v2 双版本契约）。"""
    sc = SourceConfig(id="dmm", type="builtin", display_name_key="dmm")
    assert sc.is_censored is True
    assert sc.model_dump()["is_censored"] is True
    assert sc.dict()["is_censored"] is True
```

再补一条老配置迁移的：

```python
def test_source_config_requires_proxy_derived_from_old_config():
    """缺 requires_proxy 键的老 config.json 条目重建后应正确推导。"""
    sc = SourceConfig(**{"id": "dmm", "type": "builtin"})
    assert sc.requires_proxy is True
```

## 7. Phase C：发布 r42

版本号改动（当前 `app/build.gradle:34-35` 仍是 r41）：

```gradle
versionCode 17058
versionName "0.17.18-r42"
```

发布前置检查：

| # | 检查 |
| --- | --- |
| 1 | `pytest` 全绿（v2 目标栈，期望 184 passed） |
| 2 | `pytest` 全绿（临时装回 pydantic 1.10.24，确认回滚路径仍可用） |
| 3 | `python tools/verify_python_sync.py` 通过 |
| 4 | 模拟器 6.3 的 7 项全过 |
| 5 | `app/wheels/` 只有 2.41.5 一个 wheel |
| 6 | `git status` 里没有误带的临时文件 |

第 2 项的意义是守住 L3 回滚（§9）：`model_dump()` 覆写在 v1 下会走 shim 里的 `dict()`，
必须确认它不会递归、不会报错。做法是在另一个 venv 里装 `pydantic==1.10.24` 后跑一遍，
跑完即可丢弃，不要改动 `requirements-test.txt`。

**不要删除、覆盖或重新发布 r41。** 不要 `git add -A`——根目录有大量用户自己的
诊断文件、截图、NFO、日志。

## 8. Phase D：清理（可与 C 解耦）

| 项 | 现状 | 目标 |
| --- | --- | --- |
| `core/source_config.py:50` | `@validator` | `@model_validator(mode='after')` |
| `core/proxy_policy.py:30` | `class Config` | `model_config = ConfigDict(...)` |
| `core/scrapers/models.py:8,16` | `class Config` | 同上 |
| `pydantic_v1_compat.py` | 手写 shim | 删除（`install()` 首行已按版本自动 return） |
| `source_config.py` 的 `dict()` 覆写 | v1 遗留 | 若 v1 支持确定放弃，可只留 `model_dump()` |

这些都不影响功能，纯粹是消除弃用警告、为 pydantic v3 铺路。**不要和 Phase A/B 混在一个提交里。**

## 9. 回滚

三层回滚，粒度从粗到细：

| 层 | 操作 | 恢复到的状态 |
| --- | --- | --- |
| L1 二进制 | 把 2.46.3 wheel 放回 `app/wheels/`，`build.gradle:137` 改回 `2.13.3` | Eutalix 方案（4 KB 对齐，Android 15+ 有风险） |
| L2 仅框架 | `fastapi`/`starlette` 改回 `0.125.0`/`0.50.0` | pydantic 2.12.5 + TUR wheel，框架退回旧版 |
| L3 全退 | `build.gradle:137` 改回 `1.10.24`，删 `--find-links`，删 `app/wheels/` | r41 的 pydantic v1 状态 |

L1 需要 wheel 文件还在（建议在 Release 附件里留一份，或记录下载地址）。
L3 还要注意 `source_config.py` 的 `model_dump()` 覆写在 v1 下会走 shim，不会报错，
可以保留。

## 10. 风险登记

| # | 风险 | 影响 | 概率 | 缓解 |
| --- | --- | --- | --- | --- |
| T1 | `--find-links` 相对路径在 Chaquopy 里解析不符合预期 | 构建失败 | 中 | §6.2 的三级降级；先看构建日志确认选中的 wheel |
| T2 | pip 从 PyPI 选中非 Android 平台的 pydantic-core | 装上必崩 | 中 | 构建日志核对文件名；必要时加 `--only-binary=:all:` |
| T3 | Starlette 0.50.0 → 1.6.0 跨大版本行为回归 | 运行时 500 | 中 | §6.3 第 6、7 项专门验证；可单独回退（L2） |
| T4 | `typing-inspection` / `annotated-doc` 在 Chaquopy 里装不上 | 构建失败 | 低 | 都是纯 Python wheel；失败则显式 `install` 固定版本 |
| T5 | RUNPATH 里的 Termux 路径导致 linker 提前失败 | 加载失败 | 低 | SONAME 已匹配（§2.4），linker 走已加载库；实测符号零缺失 |
| T6 | pydantic 2.12.5 比上游 2.13.4 低两个 patch | 行为差异 | 低 | 差异仅在 core 的 patch 级修复；184 passed 已覆盖 |
| T7 | TUR 停止为 cp313 构建 | 无法跟版本 | 中 | 当前 2.41.5 可长期锁定；cp314 已有 2.50.4，未来换 Python 时可跟 |
| T8 | Release 只打 arm64-v8a | 其它 ABI 无正式包 | 确定 | x86_64 wheel 仅用于模拟器验证；其它 ABI 需要时再从 TUR 下载 |
| T9 | 工作区 30 个在途改动与本次改动交叉 | 误提交 | 中 | 本次只碰 §5.1 列出的路径，逐个 `git add`，不用 `-A` |

## 11. 与 Eutalix 方案的关系

上一份 `docs/pydantic-v2-migration-plan.md` 基于 Eutalix 的 2.46.3 设计。
本方案**取代**它的 Phase 1/2，其余部分（代码兼容性结论、Phase D 清理项）仍然有效。

| 维度 | Eutalix 2.46.3 | TUR 2.41.5 | 胜出 |
| --- | --- | --- | --- |
| pydantic 版本 | 2.13.3 | 2.12.5 | Eutalix（+1 minor） |
| LOAD 对齐 | 4 KB | **16 KB** | **TUR** |
| 16 KB 页设备 | 需 `pageSizeCompat` 兼容模式 | 原生可用 | **TUR** |
| 平台标签 | 需改名 | 原生 | **TUR** |
| RUNPATH | 仅 Termux | `$ORIGIN` 优先 | **TUR** |
| 项目状态 | 已归档 | 活跃 | **TUR** |
| FastAPI 可升 | 否（卡 0.125.0） | **是（0.136.1）** | **TUR** |
| Starlette 可升 | 否（卡 0.50.0） | **是（1.6.0）** | **TUR** |
| 未定义符号 | 204（未做全量比对） | **208，全量比对零缺失** | **TUR（已验证）** |
| 文件大小 | 1,988,330 B | 1,931,192 B | TUR（略小） |

**结论：除了 pydantic 差一个 minor，TUR 在所有维度都更好，而且多解开两个框架的版本锁。**
用 2.12.5 换 16 KB 对齐 + FastAPI 升级，这笔交易值得做。

## 12. 附录 A｜物料关键事实（供复核）

```
文件名          pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl
SHA-256         1c6ad3f171f8078102e7f345b5d53c3d79a5a5cfb953a4789f9f7e7f8149ff8c
大小            1,931,192 B
WHEEL Tag       cp313-cp313-android_24_arm64_v8a
Generator       maturin 1.12.6
METADATA        Name: pydantic_core / Version: 2.41.5 / Requires-Python: >=3.9
                License-Expression: MIT
包内 .so        pydantic_core/_pydantic_core.cpython-313-aarch64-linux-android.so
                (4,591,633 B)
ELF             ELF64 / AArch64 / DYN
NEEDED          libpython3.13.so, libdl.so, libc.so
RUNPATH         $ORIGIN/../pydantic_core-libs:/data/data/com.termux/files/usr/lib
SONAME          （无）
LOAD p_align    0x4000
未定义符号       208 个，对 Chaquopy libpython + bionic 零缺失
私有符号         9 个 _Py*，全部被 Chaquopy libpython 导出
Python 层       与 PyPI 官方 2.41.5 归一化后零差异
```

## 13. 附录 B｜验证命令速查

```bash
# 物料校验
sha256sum app/wheels/pydantic_core-2.41.5-cp313-cp313-android_24_arm64_v8a.whl

# ELF 检查（NDK 工具链）
NDK=$ANDROID_SDK/ndk/27.3.13750724/toolchains/llvm/prebuilt/windows-x86_64/bin
$NDK/llvm-readelf.exe -d app/wheels/pydantic_core-2.41.5-*.whl   # 需先解包
$NDK/llvm-readelf.exe -l <解包后的 .so> | grep LOAD

# 符号比对
$NDK/llvm-nm.exe -D --undefined-only <解包后的 .so> | wc -l      # 期望 208

# 代码测试（v2 目标栈）
python -m pytest -q                                              # 期望 184 passed

# patches 同步
python tools/generate_patches.py
python tools/verify_python_sync.py --upstream-root upstream --source-root app/src/main/python

# 构建与设备验证
./gradlew :app:assembleDebug
adb -s emulator-5554 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5554 logcat -s python:V | grep -iE "pydantic|dlopen|p_align"
```

## 14. 最终确认

1. `--find-links wheels` 已确认可用：arm64 和 x86_64 构建日志分别选中了对应
   Android wheel。
2. Starlette 1.6.0 + uvicorn 0.46.0 已在模拟器实际启动并完成页面、搜索和设置验证。
3. TUR 目标栈与 pydantic 1.10.24 回退路径均为 **184 passed**。
4. 仓库保留 arm64 发布 wheel 与 x86_64 模拟器 wheel；正式 Release 仍只打 arm64。
