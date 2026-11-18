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
  String? _loadError;
  String _scrapeSource = 'auto';

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
        _loadError = null;
      });
    } catch (e) {
      debugPrint('Scanner _loadStats error: $e');
      if (mounted) {
        setState(() => _loadError = e.toString());
      }
    }
  }

  Future<void> _checkMissing() async {
    setState(() => _checkingMissing = true);
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/gallery/missing-check');
      if (!mounted) return;
      if (resp['success'] == true) {
        setState(() => _missing = MissingCheckSummary.fromJson(resp));
      }
    } catch (e) {
      debugPrint('Scanner _checkMissing error: $e');
      if (mounted) {
        _toast(ref.read(stringsProvider).requestFailed('$e'));
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
    final strings = ref.read(stringsProvider);
    final cancel = CancelToken();
    _taskCancel = cancel;
    setState(() {
      _runningTask = true;
      _taskLabel = label;
      _progress = null;
      _statusLine = strings.starting;
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
            _statusLine = msg.isNotEmpty ? msg : strings.taskDone;
            if (msg.isNotEmpty) _logs.add('✔ $msg');
          });
        } else if (event.type == 'error') {
          setState(() {
            _statusLine = msg.isNotEmpty ? msg : strings.taskFailed;
            if (msg.isNotEmpty) _logs.add('✖ $msg');
          });
        }
      }
    } catch (e) {
      debugPrint('Scanner SSE error: $e');
      if (!cancel.isCancelled && mounted) {
        setState(() {
          _statusLine = strings.requestFailed('$e');
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
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    try {
      final resp = await api.getJson('/api/gallery/rename-preview', queryParameters: {'scope': 'files'});
      if (!mounted) return;
      if (resp['success'] != true) {
        _toast((resp['error'] ?? strings.taskFailed).toString());
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
                title: Text(strings.renamePreviewTitle(items.length), style: const TextStyle(fontWeight: FontWeight.w700)),
                trailing: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.of(ctx).pop()),
              ),
              const Divider(height: 1),
              Expanded(
                child: items.isEmpty
                    ? Center(child: Text(strings.renameAllClean))
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
                            _toast(execResp['success'] == true
                                ? strings.renameCompleted
                                : (execResp['error'] ?? strings.taskFailed).toString());
                          }
                        },
                        child: Text(strings.renameExecute),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      );
    } catch (e) {
      debugPrint('openRenameSheet error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _openCollectionAnalysisSheet() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    try {
      final resp = await api.getJson('/api/collection/analysis');
      if (!mounted) return;
      final data = (resp['data'] as Map?)?.cast<String, dynamic>() ?? resp;
      final groups = (data['groups'] as List?) ?? const [];
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (ctx) => SizedBox(
          height: MediaQuery.of(ctx).size.height * 0.72,
          child: Column(
            children: [
              ListTile(
                title: Text(strings.collectionAnalysis, style: const TextStyle(fontWeight: FontWeight.w700)),
                trailing: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.of(ctx).pop()),
              ),
              const Divider(height: 1),
              Expanded(
                child: groups.isEmpty
                    ? Center(child: Text(strings.renameAllClean))
                    : ListView.builder(
                        itemCount: groups.length,
                        itemBuilder: (_, idx) {
                          final g = groups[idx];
                          if (g is! Map) return const SizedBox.shrink();
                          final title = (g['label'] ?? g['type'] ?? g['name'] ?? '').toString();
                          final count = (g['count'] ?? '').toString();
                          return ListTile(
                            title: Text(title),
                            trailing: count.isNotEmpty ? Text(count) : null,
                          );
                        },
                      ),
              ),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: SizedBox(
                    width: double.infinity,
                    child: FilledButton.tonal(
                      onPressed: () async {
                        final preview = await api.postJson('/api/collection/fix-numbers/preview');
                        if (!ctx.mounted) return;
                        final items = (preview['items'] as List?) ?? const [];
                        if (items.isEmpty) {
                          Navigator.of(ctx).pop();
                          _toast(strings.renameAllClean);
                          return;
                        }
                        await api.postJson('/api/collection/fix-numbers/apply', data: {'items': items});
                        if (ctx.mounted) Navigator.of(ctx).pop();
                        _toast(strings.saved);
                        _loadStats();
                      },
                      child: Text(strings.apply),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    } catch (e) {
      debugPrint('openCollectionAnalysisSheet error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _openAliasManager({required bool actressMode}) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final endpoint = actressMode ? '/api/actress-alias' : '/api/tag-alias';
    final title = actressMode ? strings.actressAliasesManage : strings.tagAliasesManage;
    try {
      final resp = await api.getJson(endpoint);
      if (!mounted) return;
      final list = ((resp['groups'] ?? resp['aliases'] ?? resp['data']) as List?) ?? const [];
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (ctx) => SizedBox(
          height: MediaQuery.of(ctx).size.height * 0.72,
          child: Column(
            children: [
              ListTile(
                title: Text('$title (${list.length})', style: const TextStyle(fontWeight: FontWeight.w700)),
                trailing: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.of(ctx).pop()),
              ),
              const Divider(height: 1),
              Expanded(
                child: list.isEmpty
                    ? Center(child: Text(strings.emptyActresses))
                    : ListView.builder(
                        itemCount: list.length,
                        itemBuilder: (_, idx) {
                          final g = list[idx];
                          if (g is! Map) return const SizedBox.shrink();
                          final primary = (g['primary_name'] ?? g['name'] ?? '').toString();
                          final aliases = ((g['aliases'] as List?) ?? const []).join(', ');
                          return ListTile(
                            title: Text(primary, style: const TextStyle(fontWeight: FontWeight.w600)),
                            subtitle: aliases.isNotEmpty ? Text(aliases) : null,
                          );
                        },
                      ),
              ),
            ],
          ),
        ),
      );
    } catch (e) {
      debugPrint('openAliasManager error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _confirmClearCache() async {
    final strings = ref.read(stringsProvider);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(strings.clearCache),
        content: Text(strings.clearCacheConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(strings.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(strings.confirm)),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(apiClientProvider).deleteJson('/api/gallery/cache');
      _loadStats();
      _checkMissing();
    } catch (e) {
      debugPrint('clearCache error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
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
                      Expanded(
                        child: Text(
                          strings.libraryTotalHeader(_totalVideos),
                          style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: palette.textPrimary),
                        ),
                      ),
                      IconButton(
                        onPressed: () {
                          _loadStats();
                          _checkMissing();
                        },
                        icon: const Icon(Icons.refresh_rounded, size: 20),
                      ),
                    ],
                  ),
                  if (_loadError != null) ...[
                    const SizedBox(height: 6),
                    Text(_loadError!, style: TextStyle(color: palette.danger, fontSize: 12)),
                  ],
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
                              _logs.add(strings.taskAborted);
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

            const SizedBox(height: 16),
            Row(
              children: [
                Text(strings.missingCheckTitle, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                const Spacer(),
                DropdownButton<String>(
                  value: _scrapeSource,
                  underline: const SizedBox.shrink(),
                  items: [
                    DropdownMenuItem(value: 'auto', child: Text('${strings.scrapeSourceLabel}: ${strings.autoLabel}')),
                    const DropdownMenuItem(value: 'javbus', child: Text('JavBus')),
                    const DropdownMenuItem(value: 'javdb', child: Text('JavDB')),
                    const DropdownMenuItem(value: 'dmm', child: Text('DMM')),
                    const DropdownMenuItem(value: 'jav321', child: Text('Jav321')),
                  ],
                  onChanged: (v) {
                    if (v != null) setState(() => _scrapeSource = v);
                  },
                ),
                if (_checkingMissing)
                  const Padding(
                    padding: EdgeInsets.only(left: 8),
                    child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                  )
                else
                  TextButton(onPressed: _checkMissing, child: Text(strings.checkMissing)),
              ],
            ),
            const SizedBox(height: 6),
            _BackfillTile(
              icon: Icons.description_outlined,
              title: strings.backfillNfo,
              subtitle: missing == null ? strings.checking : strings.backfillNfoDesc(missing.totalMissing),
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(label: strings.backfillNfo, path: '/api/gallery/update'),
            ),
            _BackfillTile(
              icon: Icons.article_outlined,
              title: strings.backfillPlots,
              subtitle: missing == null ? strings.checking : strings.backfillPlotsDesc(missing.missingPlots),
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(
                        label: strings.backfillPlots,
                        path: '/api/gallery/backfill-plots',
                        method: 'POST',
                        queryParameters: {'source': _scrapeSource},
                      ),
            ),
            if (missing != null && missing.pendingTranslationBatchIds.isNotEmpty)
              _BackfillTile(
                icon: Icons.g_translate_rounded,
                title: strings.translatePendingPlots,
                subtitle: '${missing.pendingTranslationBatchIds.length}',
                onTap: _runningTask
                    ? null
                    : () => _runSseTask(
                          label: strings.translatePendingPlots,
                          path: '/api/gallery/translate-backfilled-plots',
                          method: 'POST',
                          data: {'batch_id': missing.pendingTranslationBatchIds.first},
                        ),
              ),
            _BackfillTile(
              icon: Icons.translate_rounded,
              title: strings.backfillTitles,
              subtitle: missing == null ? strings.checking : strings.backfillTitlesDesc(missing.untranslatedTitles),
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
              subtitle: missing == null ? strings.checking : strings.backfillSamplesDesc(missing.missingSamples),
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(
                        label: strings.backfillSamples,
                        path: '/api/gallery/backfill-samples',
                        method: 'POST',
                        queryParameters: {'source': _scrapeSource},
                      ),
            ),
            _BackfillTile(
              icon: Icons.image_outlined,
              title: strings.backfillJellyfin,
              subtitle: strings.backfillJellyfinDesc,
              onTap: _runningTask
                  ? null
                  : () => _runSseTask(label: strings.backfillJellyfin, path: '/api/gallery/jellyfin-update'),
            ),

            const SizedBox(height: 14),
            Text(strings.advancedMaintenance, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
            const SizedBox(height: 6),
            _BackfillTile(
              icon: Icons.drive_file_rename_outline_rounded,
              title: strings.renameNormalize,
              subtitle: strings.renameNormalizeDesc,
              onTap: _runningTask ? null : _openRenameSheet,
            ),
            _BackfillTile(
              icon: Icons.health_and_safety_outlined,
              title: strings.collectionAnalysis,
              subtitle: strings.collectionAnalysis,
              onTap: _runningTask ? null : _openCollectionAnalysisSheet,
            ),
            _BackfillTile(
              icon: Icons.face_retouching_natural_outlined,
              title: strings.actressAliasesManage,
              subtitle: strings.actressAliasesManage,
              onTap: _runningTask ? null : () => _openAliasManager(actressMode: true),
            ),
            _BackfillTile(
              icon: Icons.label_outline_rounded,
              title: strings.tagAliasesManage,
              subtitle: strings.tagAliasesManage,
              onTap: _runningTask ? null : () => _openAliasManager(actressMode: false),
            ),
            _BackfillTile(
              icon: Icons.delete_sweep_outlined,
              title: strings.clearCache,
              subtitle: strings.clearCacheDesc,
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
