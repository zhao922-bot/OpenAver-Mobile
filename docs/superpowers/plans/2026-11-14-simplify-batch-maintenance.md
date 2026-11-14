# 精简批量标签更换与 NFO 备份 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans 在当前功能分支完成实现与验证。

**Goal:** 批量更换标签仅保留一个入口，选择来源即执行；删除 NFO 备份选项、提醒和备份文件生成。

**Architecture:** 复用现有标签更新 SSE，跳过前端预览和确认阶段。移除 NFO 更新与标签更新的备份参数和辅助逻辑，保留原子写入及原有字段保留规则。

**Tech Stack:** Python / FastAPI、Alpine.js、Android WebView。

**Spec:** 用户本轮明确要求一个标签更换按钮直接执行，以及删除所有 NFO 相关备份选项。

## Global Constraints

- 继续 feature/cloud-vision-adapters 分支；不升版、不合并、不发布。
- 数据库导出/导入不属于 NFO 备份选项；不清理用户已有备份。
- 来源选择规则保持一致：启用的扫描来源，加上始终可选的 JavLibrary、FC2-javten、Jable。
- 保留取消、逐项进度、失败重试和分段影片按一部计数。

## Review Focus

- 选择来源后仅发起一次更新请求，无预览或确认弹窗。
- 重试只处理失败影片，沿用原任务来源。
- 忙碌期间重复点击不得发起第二个任务。
- NFO 更新和标签更新均不创建 .openaver-backup；既有字段仍保留。
- 删除前端状态后，返回键、Escape 和模板表达式没有残留引用。

## Task 1: 实现和验证

- [x] 更新现有来源分发回归并添加直接更新/重试行为验证，先确认失败。
- [x] 精简标签按钮、确认弹窗、JS 状态及移动端返回处理。
- [x] 删除 NFO 备份参数、文件生成、样式和五语言文案，调整原有测试。
- [x] 运行两套 Python 全量、JS 语法、补丁回放、Debug 构建和专用模拟器验证。
- [x] 审阅变更，记录结果，显式提交相关文件。

## 实施与验证记录

- 来源分发和真实前端方法测试先出现预览/确认请求，再改为更新请求，RED→GREEN；包括忙碌互斥、原来源和失败番号重试。
- 后端 HTTP 回归先复现旧 backup=true 覆盖已有备份，再确认该参数被忽略且不创建新备份；既有标签以外的 NFO 字段保持原有保护。
- 多语言检查发现复用已有 tag_source_update_btn 时产生重复键，已修复并通过严格重复键回归。
- TUR：449 passed，2 个依赖弃用警告；Cleanup：449 passed，1 个依赖弃用警告。
- 129 个 JS 模块语法检查通过；Python sync 为 456 files match upstream + patches。
- 独立只读审阅未发现 Critical / Important / Minor 问题；git diff --check 通过。
- 最新 x86_64 testDebugUnitTest assembleDebug 构建成功（原生服务修复后 19 秒）。

模拟器 emulator-5554 / OpenAver_SettingsFields_20261114 中，使用内存中的两部统计和七条 NFO 候选检查界面，没有替换配置或数据库。标签行显示一个橙色“一键更换”按钮，点击来源后关闭弹层、仅发出更新请求，无 backup 参数和额外确认；此处拦截 SSE，未向真实来源发送批量更换任务。NFO 确认框无备份字样，七条候选分页为 6+1。真实 NFO 写入和不备份由后端文件测试覆盖。截图和日志位于 app/build/maintenance-simplify/；浏览器测试覆盖已撤销、端口映射已移除。

## 模拟器发现的原生服务问题

快速完成测试先实际触发 ForegroundServiceDidNotStartInTimeException：stopService 抢在 onStartCommand 的 startForeground 前到达。TaskKeepAliveService 现在记录任务是否仍需要保活，尚未启动时延后停止，让服务完成 startForeground 后再自行退出。修复后相同单按钮流程通过，额外连续 10 次 start/20ms/stop 循环并等待超过系统期限，App 保持运行，无超时和 Alpine 错误，也无残留保活服务。原始和修复后的日志均已保留；这是模拟器验证中发现并修复的任务执行崩溃，不改变后台任务范围。

本次未升版、未合并、未上传 GitHub。
