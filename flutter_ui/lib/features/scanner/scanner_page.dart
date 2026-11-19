import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import '../../core/models/scanner_models.dart';
import '../../core/native_bridge.dart';
import '../shared/prompt_dialog.dart';

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
          var doneLine = msg;
          if (doneLine.isEmpty && (event.data['video_count'] is num || event.data['stats'] is Map)) {
            final stats = event.data['stats'] is Map
                ? Map<String, dynamic>.from(event.data['stats'] as Map)
                : const <String, dynamic>{};
            final totalCount = (event.data['video_count'] as num?)?.toInt() ?? 0;
            final inserted = (stats['inserted'] as num?)?.toInt() ?? 0;
            final updated = (stats['updated'] as num?)?.toInt() ?? 0;
            final deleted = (stats['deleted'] as num?)?.toInt() ?? 0;
            doneLine = strings.scanSummary(totalCount, inserted, updated, deleted);
          }
          setState(() {
            _progress = 1.0;
            _statusLine = doneLine.isNotEmpty ? doneLine : strings.taskDone;
            if (doneLine.isNotEmpty) _logs.add('✔ $doneLine');
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
        ref.read(libraryRevisionProvider.notifier).bump();
      }
    }
  }

  Future<void> _openTagSourceSheet() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);

    const reserved = <(String, String)>[
      ('javlibrary', 'JavLibrary'),
      ('fc-javten', 'FC2-javten'),
      ('jable', 'Jable'),
    ];
    const fallbackEnabled = <(String, String)>[
      ('javbus', 'JavBus'),
      ('javdb', 'JavDB'),
      ('dmm', 'DMM'),
      ('jav321', 'Jav321'),
    ];

    final options = <(String, String)>[];
    final seen = <String>{'auto', ...reserved.map((e) => e.$1)};
    try {
      final resp = await api.getJson('/api/config');
      final cfgData = (resp['data'] as Map?)?.cast<String, dynamic>() ?? resp;
      final rawSources = (cfgData['sources'] as List?) ?? const [];
      final enabledRows = rawSources
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .where((s) => s['enabled'] == true && s['manual_only'] != true)
          .toList()
        ..sort((a, b) => ((a['order'] as num?)?.toInt() ?? 0).compareTo((b['order'] as num?)?.toInt() ?? 0));
      for (final s in enabledRows) {
        final id = (s['id'] ?? '').toString().trim();
        if (id.isEmpty || seen.contains(id)) continue;
        seen.add(id);
        final rawName = (s['display_name_raw'] ?? '').toString().trim();
        final keyName = (s['display_name_key'] ?? '').toString().trim();
        final label = rawName.isNotEmpty ? rawName : (keyName.isNotEmpty ? keyName : id);
        options.add((id, label));
      }
    } catch (e) {
      debugPrint('openTagSourceSheet config error: $e');
    }

    if (options.isEmpty) {
      for (final item in fallbackEnabled) {
        if (seen.add(item.$1)) options.add(item);
      }
    }
    options.addAll(reserved);
    if (!mounted) return;

    var selectedId = options.first.$1;
    if (_scrapeSource != 'auto' && options.any((o) => o.$1 == _scrapeSource)) {
      selectedId = _scrapeSource;
    }

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => StatefulBuilder(
        builder: (sheetCtx, setSheetState) {
          final palette = OpenAverPalette.of(sheetCtx);
          final selectedLabel = options
              .firstWhere((o) => o.$1 == selectedId, orElse: () => (selectedId, selectedId))
              .$2;
          return ConstrainedBox(
            constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(sheetCtx).height * 0.85),
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.sell_outlined, color: palette.accent),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          strings.batchTagSourceTitle,
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close_rounded),
                        onPressed: () => Navigator.of(sheetCtx).pop(),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    strings.batchTagSourceSelectHint,
                    style: TextStyle(fontSize: 12.5, color: palette.textMuted),
                  ),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: options.map((opt) {
                      return ChoiceChip(
                        label: Text(opt.$2),
                        selected: selectedId == opt.$1,
                        onSelected: (_) => setSheetState(() => selectedId = opt.$1),
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 18),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _runningTask
                              ? null
                              : () {
                                  Navigator.of(sheetCtx).pop();
                                  _runSseTask(
                                    label: '${strings.batchTagSourcePreviewBtn} ($selectedLabel)',
                                    path: '/api/gallery/tag-source-preview',
                                    queryParameters: {'source': selectedId},
                                  );
                                },
                          icon: const Icon(Icons.visibility_outlined, size: 18),
                          label: Text(strings.batchTagSourcePreviewBtn),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: _runningTask
                              ? null
                              : () {
                                  Navigator.of(sheetCtx).pop();
                                  _runSseTask(
                                    label: '${strings.batchTagSourceTitle} ($selectedLabel)',
                                    path: '/api/gallery/tag-source-update',
                                    queryParameters: {'source': selectedId},
                                  );
                                },
                          icon: const Icon(Icons.sell_outlined, size: 18),
                          label: Text(strings.batchTagSourceRunBtn),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
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
                            if (execResp['success'] == true) {
                              ref.read(libraryRevisionProvider.notifier).bump();
                            }
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
      if (resp['success'] == false) {
        _toast((resp['error'] ?? strings.taskFailed).toString());
        return;
      }
      final data = (resp['data'] as Map?)?.cast<String, dynamic>() ?? resp;
      final rows = <(String, String)>[];
      final rawGroups = data['groups'] as List?;
      if (rawGroups != null && rawGroups.isNotEmpty) {
        for (final g in rawGroups.whereType<Map>()) {
          final title = (g['label'] ?? g['type'] ?? g['name'] ?? '').toString();
          final count = (g['count'] ?? '').toString();
          if (title.isNotEmpty) rows.add((title, count));
        }
      } else {
        if (data['total_videos'] is num) {
          rows.add((strings.analysisTotalVideos, '${(data['total_videos'] as num).toInt()}'));
        }
        final nfoStatus = data['nfo_status'];
        if (nfoStatus is Map && nfoStatus['missing_nfo'] is num) {
          rows.add((strings.analysisMissingNfo, '${(nfoStatus['missing_nfo'] as num).toInt()}'));
        }
        final corrupted = data['corrupted_numbers'];
        if (corrupted is Map && corrupted['total'] is num) {
          rows.add((strings.analysisCorruptedNumbers, '${(corrupted['total'] as num).toInt()}'));
        }
        final jpTags = data['japanese_tags'];
        if (jpTags is Map && jpTags['total'] is num) {
          rows.add((strings.analysisJapaneseTags, '${(jpTags['total'] as num).toInt()}'));
        }
        final emptyArr = data['empty_array_fields'];
        if (emptyArr is Map) {
          if (emptyArr['actresses'] is num) {
            rows.add((strings.analysisEmptyActresses, '${(emptyArr['actresses'] as num).toInt()}'));
          }
          if (emptyArr['tags'] is num) {
            rows.add((strings.analysisEmptyTags, '${(emptyArr['tags'] as num).toInt()}'));
          }
        }
        final missingFields = data['missing_fields'];
        if (missingFields is Map) {
          missingFields.forEach((k, v) {
            final count = (v is num) ? v.toInt() : 0;
            if (count > 0) {
              rows.add((strings.analysisMissingField(k.toString()), '$count'));
            }
          });
        }
      }
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
                child: rows.isEmpty
                    ? Center(child: Text(strings.renameAllClean))
                    : ListView.builder(
                        itemCount: rows.length,
                        itemBuilder: (_, idx) {
                          final (title, count) = rows[idx];
                          return ListTile(
                            title: Text(title),
                            trailing: count.isNotEmpty
                                ? Text(count, style: const TextStyle(fontWeight: FontWeight.w600))
                                : null,
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
                        final preview = await api.postJson(
                          '/api/collection/fix-numbers/preview',
                          data: {'rules': <String>[]},
                        );
                        if (!ctx.mounted) return;
                        final affected = ((preview['affected'] ?? preview['items']) as List?)
                                ?.whereType<Map>()
                                .map((e) => Map<String, dynamic>.from(e))
                                .toList() ??
                            const <Map<String, dynamic>>[];
                        if (affected.isEmpty) {
                          Navigator.of(ctx).pop();
                          _toast(strings.renameAllClean);
                          return;
                        }
                        final confirm = await showDialog<bool>(
                          context: ctx,
                          builder: (dCtx) => AlertDialog(
                            title: Text(strings.fixNumbersPreviewTitle(affected.length)),
                            content: SizedBox(
                              width: double.maxFinite,
                              child: ListView.builder(
                                shrinkWrap: true,
                                itemCount: affected.length > 30 ? 30 : affected.length,
                                itemBuilder: (_, i) {
                                  final row = affected[i];
                                  return Padding(
                                    padding: const EdgeInsets.symmetric(vertical: 2),
                                    child: Text(
                                      '${row['old_number']} -> ${row['new_number']}',
                                      style: const TextStyle(fontSize: 12.5),
                                    ),
                                  );
                                },
                              ),
                            ),
                            actions: [
                              TextButton(
                                onPressed: () => Navigator.of(dCtx).pop(false),
                                child: Text(strings.cancel),
                              ),
                              FilledButton(
                                onPressed: () => Navigator.of(dCtx).pop(true),
                                child: Text(strings.apply),
                              ),
                            ],
                          ),
                        );
                        if (confirm != true || !ctx.mounted) return;
                        final ids = affected
                            .map((e) => (e['id'] as num?)?.toInt())
                            .whereType<int>()
                            .toList();
                        final applied = await api.postJson(
                          '/api/collection/fix-numbers/apply',
                          data: {'ids': ids},
                        );
                        if (ctx.mounted) Navigator.of(ctx).pop();
                        final updated = (applied['updated'] as num?)?.toInt() ?? ids.length;
                        final failed = (applied['failed'] as num?)?.toInt() ?? 0;
                        _toast(strings.fixNumbersApplied(updated, failed));
                        _loadStats();
                        ref.read(libraryRevisionProvider.notifier).bump();
                      },
                      child: Text(strings.fixNumbersBtn),
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
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _AliasManagerSheet(
        api: api,
        strings: strings,
        actressMode: actressMode,
      ),
    );
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
      ref.read(libraryRevisionProvider.notifier).bump();
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
              icon: Icons.sell_outlined,
              title: strings.batchTagSourceTitle,
              subtitle: strings.batchTagSourceDesc,
              onTap: _runningTask ? null : _openTagSourceSheet,
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

class _AliasManagerSheet extends StatefulWidget {
  const _AliasManagerSheet({
    required this.api,
    required this.strings,
    required this.actressMode,
  });

  final ApiClient api;
  final AppStrings strings;
  final bool actressMode;

  @override
  State<_AliasManagerSheet> createState() => _AliasManagerSheetState();
}

class _AliasManagerSheetState extends State<_AliasManagerSheet> {
  final TextEditingController _primaryCtrl = TextEditingController();
  final TextEditingController _aliasesCtrl = TextEditingController();
  List<Map<String, dynamic>> _groups = const [];
  bool _loading = true;
  bool _busy = false;
  String? _error;

  String get _baseEndpoint => widget.actressMode ? '/api/actress-aliases' : '/api/tag-aliases';

  @override
  void initState() {
    super.initState();
    _loadGroups();
  }

  @override
  void dispose() {
    _primaryCtrl.dispose();
    _aliasesCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadGroups() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await widget.api.getJson(_baseEndpoint);
      if (!mounted) return;
      final list = ((resp['groups'] ?? resp['aliases'] ?? resp['data']) as List?) ?? const [];
      setState(() {
        _groups = list.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
        _loading = false;
      });
    } catch (e) {
      debugPrint('AliasManagerSheet load error: $e');
      if (mounted) {
        setState(() {
          _loading = false;
          _error = widget.strings.requestFailed('$e');
        });
      }
    }
  }

  Future<void> _searchOnline() async {
    final name = _primaryCtrl.text.trim();
    if (!widget.actressMode || name.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final resp = await widget.api.postJson(
        '/api/actress-aliases/search-online',
        data: {'name': name},
      );
      if (!mounted) return;
      final suggested = (resp['suggested_aliases'] as List?)
              ?.map((e) => e.toString().trim())
              .where((e) => e.isNotEmpty)
              .toList() ??
          const <String>[];
      if (suggested.isNotEmpty) {
        _aliasesCtrl.text = suggested.join(', ');
      } else {
        setState(() => _error = (resp['message'] ?? widget.strings.aliasEmptyList).toString());
      }
    } catch (e) {
      debugPrint('AliasManagerSheet searchOnline error: $e');
      if (mounted) setState(() => _error = widget.strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _createGroup() async {
    final primary = _primaryCtrl.text.trim();
    if (primary.isEmpty || _busy) return;
    final aliases = _aliasesCtrl.text
        .split(RegExp(r'[,，\n]'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final resp = await widget.api.postJson(
        _baseEndpoint,
        data: {'primary_name': primary, 'aliases': aliases},
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        _primaryCtrl.clear();
        _aliasesCtrl.clear();
        await _loadGroups();
      } else {
        setState(() => _error = (resp['error'] ?? widget.strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('AliasManagerSheet createGroup error: $e');
      if (mounted) setState(() => _error = widget.strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addAliasToGroup(String primaryName) async {
    final raw = await showPromptTextDialog(
      context: context,
      title: '${widget.strings.addSingleAlias}: $primaryName',
      cancelLabel: widget.strings.cancel,
      confirmLabel: widget.strings.confirm,
    );
    final alias = raw?.trim();
    if (alias == null || alias.isEmpty) return;
    try {
      final resp = await widget.api.postJson(
        '$_baseEndpoint/${Uri.encodeComponent(primaryName)}/alias',
        data: {'alias': alias},
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        await _loadGroups();
      } else {
        setState(() => _error = (resp['error'] ?? widget.strings.saveFailed).toString());
      }
    } catch (e) {
      if (mounted) setState(() => _error = widget.strings.requestFailed('$e'));
    }
  }

  Future<void> _removeAlias(String primaryName, String alias) async {
    try {
      await widget.api.deleteJson(
        '$_baseEndpoint/${Uri.encodeComponent(primaryName)}/alias/${Uri.encodeComponent(alias)}',
      );
      if (mounted) await _loadGroups();
    } catch (e) {
      if (mounted) setState(() => _error = widget.strings.requestFailed('$e'));
    }
  }

  Future<void> _deleteGroup(String primaryName) async {
    try {
      await widget.api.deleteJson('$_baseEndpoint/${Uri.encodeComponent(primaryName)}');
      if (mounted) await _loadGroups();
    } catch (e) {
      if (mounted) setState(() => _error = widget.strings.requestFailed('$e'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final title = widget.actressMode
        ? widget.strings.actressAliasesManage
        : widget.strings.tagAliasesManage;

    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.82,
      child: Column(
        children: [
          ListTile(
            title: Text('$title (${_groups.length})', style: const TextStyle(fontWeight: FontWeight.w700)),
            trailing: IconButton(
              icon: const Icon(Icons.close_rounded),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 8),
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _primaryCtrl,
                        decoration: InputDecoration(
                          isDense: true,
                          labelText: widget.strings.aliasPrimaryHint,
                        ),
                      ),
                    ),
                    if (widget.actressMode) ...[
                      const SizedBox(width: 8),
                      OutlinedButton(
                        onPressed: _busy ? null : _searchOnline,
                        child: Text(widget.strings.aliasSearchOnline),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _aliasesCtrl,
                        decoration: InputDecoration(
                          isDense: true,
                          labelText: widget.strings.aliasValuesHint,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(
                      onPressed: _busy ? null : _createGroup,
                      child: Text(widget.strings.addAliasGroup),
                    ),
                  ],
                ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text(_error!, style: TextStyle(color: palette.danger, fontSize: 12)),
                    ),
                  ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _groups.isEmpty
                    ? Center(child: Text(widget.strings.aliasEmptyList, style: TextStyle(color: palette.textMuted)))
                    : ListView.builder(
                        itemCount: _groups.length,
                        itemBuilder: (_, idx) {
                          final g = _groups[idx];
                          final primary = (g['primary_name'] ?? g['name'] ?? '').toString();
                          final aliases = ((g['aliases'] as List?) ?? const [])
                              .map((e) => e.toString())
                              .where((e) => e.isNotEmpty)
                              .toList();
                          return Card(
                            margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                            child: Padding(
                              padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Expanded(
                                        child: Text(primary, style: const TextStyle(fontWeight: FontWeight.w700)),
                                      ),
                                      IconButton(
                                        icon: const Icon(Icons.add_rounded, size: 18),
                                        tooltip: widget.strings.addSingleAlias,
                                        onPressed: () => _addAliasToGroup(primary),
                                      ),
                                      IconButton(
                                        icon: Icon(Icons.delete_outline_rounded, size: 18, color: palette.danger),
                                        onPressed: () => _deleteGroup(primary),
                                      ),
                                    ],
                                  ),
                                  if (aliases.isNotEmpty)
                                    Wrap(
                                      spacing: 6,
                                      runSpacing: 4,
                                      children: aliases
                                          .map(
                                            (a) => InputChip(
                                              label: Text(a, style: const TextStyle(fontSize: 12)),
                                              visualDensity: VisualDensity.compact,
                                              onDeleted: () => _removeAlias(primary, a),
                                            ),
                                          )
                                          .toList(),
                                    ),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}
