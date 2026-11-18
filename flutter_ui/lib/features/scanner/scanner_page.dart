import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/scanner_models.dart';
import '../../core/native_bridge.dart';

class ScannerPage extends ConsumerStatefulWidget {
  const ScannerPage({super.key});

  @override
  ConsumerState<ScannerPage> createState() => _ScannerPageState();
}

class _ScannerPageState extends ConsumerState<ScannerPage> {
  int _totalVideos = 0;
  MissingCheckSummary? _missing;
  bool _checkingMissing = false;

  bool _runningTask = false;
  String _taskLabel = '';
  double? _progress;
  String _statusLine = '';
  final List<String> _logs = [];
  CancelToken? _taskCancel;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadStats();
      _checkMissing();
    });
  }

  @override
  void dispose() {
    _taskCancel?.cancel();
    super.dispose();
  }

  Future<void> _loadStats() async {
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/gallery/stats');
      if (!mounted) return;
      final data = (resp['data'] as Map?) ?? const {};
      setState(() {
        _totalVideos = (data['total'] as num?)?.toInt() ?? 0;
      });
    } catch (_) {}
  }

  Future<void> _checkMissing() async {
    setState(() => _checkingMissing = true);
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/gallery/missing-check');
      if (!mounted) return;
      if (resp['success'] == true) {
        setState(() => _missing = MissingCheckSummary.fromJson(resp));
      }
    } finally {
      if (mounted) setState(() => _checkingMissing = false);
    }
  }

  Future<void> _runSseTask({
    required String label,
    required String path,
    String method = 'GET',
    Map<String, dynamic>? queryParameters,
    Object? data,
  }) async {
    if (_runningTask) return;
    final cancel = CancelToken();
    _taskCancel = cancel;
    setState(() {
      _runningTask = true;
      _taskLabel = label;
      _progress = null;
      _statusLine = '正在启动…';
      _logs.clear();
    });
    await NativeBridge.instance.setTaskKeepAlive(true);

    try {
      final api = ref.read(apiClientProvider);
      await for (final event in api.streamSse(
        path,
        method: method,
        queryParameters: queryParameters,
        data: data,
        cancelToken: cancel,
      )) {
        if (!mounted) break;
        final msg = (event.data['message'] ?? event.data['status'] ?? '').toString();
        if (event.type == 'progress') {
          final current = (event.data['current'] as num?)?.toDouble() ?? 0;
          final total = (event.data['total'] as num?)?.toDouble() ?? 0;
          setState(() {
            _progress = total > 0 ? (current / total).clamp(0.0, 1.0) : null;
            _statusLine = msg.isNotEmpty ? msg : '${current.toInt()} / ${total.toInt()}';
          });
        } else if (event.type == 'log') {
          if (msg.isNotEmpty) {
            setState(() {
              _logs.add(msg);
              if (_logs.length > 200) _logs.removeAt(0);
            });
          }
        } else if (event.type == 'done') {
          setState(() {
            _progress = 1.0;
            _statusLine = msg.isNotEmpty ? msg : '任务完成';
            if (msg.isNotEmpty) _logs.add('✔ $msg');
          });
        } else if (event.type == 'error') {
          setState(() {
            _statusLine = msg.isNotEmpty ? msg : '执行失败';
            if (msg.isNotEmpty) _logs.add('✖ $msg');
          });
        }
      }
    } catch (e) {
      if (!cancel.isCancelled && mounted) {
        setState(() {
          _statusLine = '连接中断: $e';
          _logs.add('✖ $e');
        });
      }
    } finally {
      await NativeBridge.instance.setTaskKeepAlive(false);
      if (mounted) {
        setState(() => _runningTask = false);
        _loadStats();
        _checkMissing();
      }
    }
  }

  Future<void> _openRenameSheet() async {
    final api = ref.read(apiClientProvider);
    final resp = await api.getJson('/api/gallery/rename-preview', queryParameters: {'scope': 'files'});
    if (!mounted) return;
    if (resp['success'] != true) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text((resp['error'] ?? '获取重命名预览失败').toString())),
      );
      return;
    }
    final data = (resp['data'] as Map?)?.cast<String, dynamic>() ?? const {};
    final planId = (data['plan_id'] ?? '').toString();
    final items = ((data['items'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .where((e) => e['status'] == 'ready')
        .toList();

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => SizedBox(
        height: MediaQuery.of(ctx).size.height * 0.72,
        child: Column(
          children: [
            ListTile(
              title: Text('文件名整理预览 (${items.length} 项待修改)', style: const TextStyle(fontWeight: FontWeight.w700)),
              trailing: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.of(ctx).pop()),
            ),
            const Divider(height: 1),
            Expanded(
              child: items.isEmpty
                  ? const Center(child: Text('所有文件命名均已规范'))
                  : ListView.builder(
                      itemCount: items.length,
                      itemBuilder: (_, idx) {
                        final item = items[idx];
                        return ListTile(
                          title: Text((item['old_name'] ?? '').toString(), style: const TextStyle(fontSize: 12.5)),
                          subtitle: Text('→ ${item['new_name'] ?? ''}', style: const TextStyle(fontSize: 12.5)),
                        );
                      },
                    ),
            ),
            if (items.isNotEmpty)
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: () async {
                        Navigator.of(ctx).pop();
                        final execResp = await api.postJson('/api/gallery/rename-execute', data: {
                          'plan_id': planId,
                          'scope': 'files',
                        });
                        if (mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(execResp['success'] == true ? '批量命名整理完成' : (execResp['error'] ?? '执行失败').toString()),
                            ),
                          );
                        }
                      },
                      child: const Text('确认执行重命名'),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmClearCache() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('清空片库索引'),
        content: const Text('清空本地 SQLite 索引后需重新扫描片库，不会删除您的视频或 NFO 文件。'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('确认清空')),
        ],
      ),
    );
    if (ok != true) return;
    await ref.read(apiClientProvider).deleteJson('/api/gallery/cache');
    _loadStats();
    _checkMissing();
  }

  @override
  Widget build(BuildContext context) {
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);
    final missing = _missing;

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 28),
          children: [
            // Summary header card
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: palette.surface,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: palette.stroke),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.folder_copy_outlined, color: palette.accent),
                      const SizedBox(width: 8),
                      Text(
                        '当前片库 $_totalVideos 部影片',
                        style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: palette.textPrimary),
                      ),
                      const Spacer(),
                      IconButton(
                        onPressed: () {
                          _loadStats();
                          _checkMissing();
                        },
                        icon: const Icon(Icons.refresh_rounded, size: 20),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: _runningTask
                              ? null
                              : () => _runSseTask(label: strings.scanLibrary, path: '/api/gallery/generate'),
                          icon: const Icon(Icons.radar_rounded),
                          label: Text(strings.scanLibrary),
                        ),
                      ),
                      if (_runningTask) ...[
                        const SizedBox(width: 10),
                        FilledButton.tonalIcon(
                          onPressed: () {
                            _taskCancel?.cancel();
                            setState(() {
                              _runningTask = false;
                              _logs.add('■ 用户已请求中止任务');
                            });
                          },
                          icon: const Icon(Icons.stop_rounded),
                          label: Text(strings.stopTask),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),

            // Live task progress & console
            if (_runningTask || _logs.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: palette.surface,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: palette.stroke),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(_taskLabel, style: TextStyle(fontWeight: FontWeight.w700, color: palette.accent)),
                        const Spacer(),
                        if (_progress != null)
                          Text('${(_progress! * 100).toStringAsFixed(0)}%', style: TextStyle(color: palette.textMuted, fontSize: 12)),
                      ],
                    ),
                    const SizedBox(height: 6),
                    LinearProgressIndicator(value: _runningTask ? _progress : 1.0, minHeight: 5),
                    const SizedBox(height: 6),
                    Text(_statusLine, style: TextStyle(fontSize: 12, color: palette.textSecondary)),
                    if (_logs.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Container(
                        height: 140,
                        width: double.infinity,
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: palette.canvas,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: ListView.builder(
                          reverse: true,
                          itemCount: _logs.length,
                          itemBuilder: (_, idx) {
                            final line = _logs[_logs.length - 1 - idx];
                            return Text(line, style: TextStyle(fontSize: 11, color: palette.textSecondary));
                          },
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],

            // Missing check & batch backfill actions
            const SizedBox(height: 16),
            Row(
              children: [
                Text('缺失检测与一键补全', style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                const Spacer(),
                if (_checkingMissing)
                  const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                else
                  TextButton(onPressed: _checkMissing, child: Text(strings.checkMissing)),
              ],
            ),
            const SizedBox(height: 6),
            _BackfillTile(
              icon: Icons.description_outlined,
              title: strings.backfillNfo,
              subtitle: missing == null ? '检查中…' : '缺 NFO/封面共 ${missing.totalMissing} 项',
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(label: strings.backfillNfo, path: '/api/gallery/update'),
            ),
            _BackfillTile(
              icon: Icons.article_outlined,
              title: strings.backfillPlots,
              subtitle: missing == null ? '检查中…' : '待补简介 ${missing.missingPlots} 项',
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(
                        label: strings.backfillPlots,
                        path: '/api/gallery/backfill-plots',
                        method: 'POST',
                        queryParameters: {'source': 'auto'},
                      ),
            ),
            _BackfillTile(
              icon: Icons.translate_rounded,
              title: strings.backfillTitles,
              subtitle: missing == null ? '检查中…' : '待翻译标题 ${missing.untranslatedTitles} 项',
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(
                        label: strings.backfillTitles,
                        path: '/api/gallery/backfill-titles',
                        method: 'POST',
                      ),
            ),
            _BackfillTile(
              icon: Icons.photo_library_outlined,
              title: strings.backfillSamples,
              subtitle: missing == null ? '检查中…' : '缺剧照 ${missing.missingSamples} 项',
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(
                        label: strings.backfillSamples,
                        path: '/api/gallery/backfill-samples',
                        method: 'POST',
                        queryParameters: {'source': 'auto'},
                      ),
            ),
            _BackfillTile(
              icon: Icons.image_outlined,
              title: strings.backfillJellyfin,
              subtitle: '生成 -poster / -fanart 媒体服务器图像',
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(label: strings.backfillJellyfin, path: '/api/gallery/jellyfin-update'),
            ),

            const SizedBox(height: 14),
            Text('高级维护', style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
            const SizedBox(height: 6),
            _BackfillTile(
              icon: Icons.drive_file_rename_outline_rounded,
              title: strings.renameNormalize,
              subtitle: '预览并规范化视频文件命名',
              onTap: _runningTask ? null : _openRenameSheet,
            ),
            _BackfillTile(
              icon: Icons.delete_sweep_outlined,
              title: strings.clearCache,
              subtitle: '清空 SQLite 索引（不删物理文件）',
              onTap: _runningTask ? null : _confirmClearCache,
            ),
          ],
        ),
      ),
    );
  }
}

class _BackfillTile extends StatelessWidget {
  const _BackfillTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Icon(icon, color: palette.accent),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(subtitle, style: TextStyle(fontSize: 12, color: palette.textMuted)),
        trailing: const Icon(Icons.play_circle_outline_rounded),
        onTap: onTap,
      ),
    );
  }
}
