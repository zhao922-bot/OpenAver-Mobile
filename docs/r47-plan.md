# OpenAver Mobile r47 计划

> 基线：r46（`v0.17.18-android-r46`，versionCode 17062）
> 目标：`v0.17.18-android-r47`（versionCode 17063）

## 范围

r47 沿用 r46 计划中明确留到下一批的三项收尾任务，不增加新功能：

1. 数据库导入前检查可用磁盘空间。
2. 删除任务保活通知中从未使用的 `label` 参数。
3. 目视检查最后一个仍使用平台主题的 web menu 对话框。

## 1. 数据库导入磁盘空间预检

数据库导入在峰值时同时占用：

- 已落盘的备份 ZIP；
- 解压出的数据库与清单；
- 当前数据库的一致性快照。

原实现只依赖写入时的 `OSError`。空间不足时会被统一转换成“ZIP 格式无效”，
把存储问题错误归因成备份文件损坏。

本次在读取 ZIP 中央目录并完成白名单校验后、开始解压前检查可用空间：

- 需求按 `declared_total * 2` 估算；
- 低于需求时返回 HTTP 507；
- 返回本地化的 `runtime.database.import_no_space`，并带上所需 MB；
- `disk_usage()` 自身失败时不拦截，仍由实际写入报错兜底；
- 检查失败发生在替换现有数据库之前，原数据库保持不变。

新增四语言文案：

- `runtime.database.import_no_space`

新增测试：

- `test_database_import_rejects_when_disk_is_full`

## 2. 删除通知死参数

任务保活链路一直把内部任务类型编码成 `label`：

`state-scan.js -> task-keepalive.js -> MainActivity -> TaskKeepAliveService`

但 Service 从未读取这个值，通知标题始终是固定的“正在处理任务”。本次直接删除
不再使用的参数，而不是增加多套内部任务名文案：

- `TaskKeepAliveService` 删除 `EXTRA_LABEL`、`label` 形参和 `putExtra`；
- `MainActivity` 改为无参启动 Service；
- JS 改为 `start()` 和 `openaver-task://start`；
- 扫描页调用改为 `start()`；
- 更新静态回归测试，防止该参数重新出现。

## 3. web menu 对话框

检查 `dialog_web_menu.xml` 后确认：

- 8 个 `TextView` 均显式设置 `textColor`；
- “取消”按钮使用 `Widget.OpenAver.GhostButton`，文字颜色由样式指定；
- 背景由 `bg_sheet` 和透明窗口背景负责；
- 平台主题不会再决定可见文字颜色。

因此保留
`android.R.style.Theme_Material_Dialog_NoActionBar`，不做无收益的主题替换。
这一项以模拟器截图作为最终依据。

## 验证

- 聚焦测试：
  - 数据库导入回滚、备份轮转、首次建库、空间不足；
  - Android 任务保活静态约束；
  - 四语言 key 与占位符一致性。
- 全量 Python 测试：TUR 与 Cleanup 两套环境。
- 全部 JavaScript 执行 `node --check`。
- 重新生成 patches 并执行 `verify_python_sync.py`。
- 在 `emulator-5554` 安装 x86_64 Debug 包，检查：
  - 冷启动与扫描页；
  - 数据库备份设置入口；
  - web menu 的配色和文字对比度；
  - 开始/结束任务时前台服务可正常启停。

## 发布边界

本计划执行阶段不自动 commit、tag、push 或创建 GitHub Release。只有收到明确发布
指示后才执行版本发布流程。
