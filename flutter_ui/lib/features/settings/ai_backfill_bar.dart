import 'dart:async';
import 'package:flutter/material.dart';
import '../../core/api_client.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import '../../core/native_bridge.dart';
import '../task_center/task_center.dart';

class AiBackfillBar extends StatefulWidget {
  const AiBackfillBar({
    super.key,
    required this.api,
    required this.strings,
    required this.statusEndpoint,
    required this.startEndpoint,
    required this.stopEndpoint,
    required this.rebuildEndpoint,
  });

  final ApiClient api;
  final AppStrings strings;
  final String statusEndpoint;
  final String startEndpoint;
  final String stopEndpoint;
  final String rebuildEndpoint;

  @override
  State<AiBackfillBar> createState() => _AiBackfillBarState();
}

// Both Settings and Task Center use this observer, which can outlive its panels.
class AiBackfillTask extends ChangeNotifier {
  AiBackfillTask._(this.api, this.statusEndpoint)
    : _definition = _known[statusEndpoint];

  static const _known = {
    '/api/ai/similar/status': (
      kind: TaskKind.similar,
      start: '/api/ai/similar/index',
      stop: '/api/ai/similar/index/stop',
    ),
    '/api/ai/faces/status': (
      kind: TaskKind.faces,
      start: '/api/ai/faces/recompute',
      stop: '/api/ai/faces/recompute/stop',
    ),
    '/api/ai/tags/backfill/status': (
      kind: TaskKind.aiTags,
      start: '/api/ai/tags/backfill',
      stop: '/api/ai/tags/backfill/stop',
    ),
  };
  static final _tasksByApi = Expando<Map<String, AiBackfillTask>>();

  static AiBackfillTask forEndpoint(ApiClient api, String statusEndpoint) {
    final tasks = _tasksByApi[api] ??= {};
    return tasks.putIfAbsent(
      statusEndpoint,
      () => AiBackfillTask._(api, statusEndpoint),
    );
  }

  static Future<void> refreshKnown(ApiClient api) async {
    await Future.wait([
      for (final endpoint in _known.keys) forEndpoint(api, endpoint).refresh(),
    ]);
  }

  final ApiClient api;
  final String statusEndpoint;
  final ({TaskKind kind, String start, String stop})? _definition;
  Map<String, dynamic>? status;
  bool busy = false;
  bool _stopRequested = false;
  Timer? _pollTimer;
  TaskKeepAliveLease? _keepAlive;
  Future<void>? _refreshing;
  TaskJob? _job;
  TaskJob? _latestJob;

  bool get canStop => !busy && !_stopRequested && status?['running'] == true;

  Future<void> refresh() async {
    if (busy) return;
    final current = _refreshing;
    if (current != null) return current;
    final refresh = _refreshing = _readStatus();
    try {
      await refresh;
    } finally {
      _refreshing = null;
    }
  }

  Future<void> _readStatus({bool afterAction = false}) async {
    try {
      final response = await api.getJson(statusEndpoint);
      final running = response['running'];
      if (running is! bool) return;
      status = response;
      if (running) {
        _startObserving();
      } else if (!busy || afterAction) {
        _pollTimer?.cancel();
        _pollTimer = null;
        _keepAlive?.release();
        _keepAlive = null;
      }
      _updateJob(response, running: running, terminal: !busy || afterAction);
      notifyListeners();
    } catch (e) {
      debugPrint('AI backfill status $statusEndpoint error: ${e.runtimeType}');
    }
  }

  void _startObserving() {
    _keepAlive ??= NativeBridge.instance.acquireTaskKeepAlive();
    _pollTimer ??= Timer.periodic(const Duration(seconds: 3), (_) {
      unawaited(refresh());
    });
  }

  void _beginJob(TaskStatus status) {
    final definition = _definition;
    if (definition == null || _job != null) return;
    final job = TaskCenter.forApi(api).begin(definition.kind, status: status);
    _latestJob = _job = job;
    job.setCancel(
      () => _runCenterAction(definition.stop, mayStart: false),
      available: () => canStop && identical(_job, job),
    );
    job.setRetry(
      () => _runCenterAction(definition.start, mayStart: true),
      available: () => !busy && _job == null && identical(_latestJob, job) &&
          statusForRetry(job),
    );
  }

  bool statusForRetry(TaskJob job) =>
      job.status != TaskStatus.succeeded &&
      job.reason != 'no_target' &&
      job.reason != 'nothing_pending' &&
      job.reason != 'nothing_to_do' &&
      (_count(status?['pending']) != 0 || job.status == TaskStatus.failed);

  Future<void> _runCenterAction(String endpoint, {required bool mayStart}) async {
    final response = await runAction(endpoint, mayStart: mayStart);
    final failure = _actionFailure(response);
    if (!mayStart && failure != null) throw StateError(failure);
  }

  void _updateJob(Map<String, dynamic> data, {required bool running, required bool terminal}) {
    final current = _count(data['processed'] ?? data['indexed'] ?? data['tagged'] ?? data['done']);
    final total = _count(data['total']);
    if (running) {
      _keepAlive?.updateProgress(current, total);
      _beginJob(TaskStatus.running);
    }
    final job = _job;
    if (job == null || (!running && !terminal)) return;
    final pending = _count(data['pending']);
    final outcome = _code(data['outcome']);
    final reason = _code(data['stopped_reason']) ?? _code(data['stop_reason']) ??
        (data['model_changed'] == true ? 'model_changed' : null) ??
        (_definition?.kind == TaskKind.similar && pending != 0 ? _code(data['kind']) : null) ??
        (data['unreachable'] == true && pending != 0 ? 'unreachable' : null);
    final next = switch ((running, outcome, reason)) {
      (true, _, _) => _stopRequested ? TaskStatus.cancelling : TaskStatus.running,
      (false, 'drained', _) => TaskStatus.succeeded,
      (false, 'stopped', _) => _stopRequested ? TaskStatus.cancelled : TaskStatus.stopped,
      (false, _, 'disabled' || 'connection_changed' || 'model_changed') => TaskStatus.stopped,
      (false, _, final String _) => TaskStatus.failed,
      (false, final String _, _) => TaskStatus.failed,
      _ when _stopRequested && pending != 0 => TaskStatus.cancelled,
      _ when pending == 0 => TaskStatus.succeeded,
      _ => TaskStatus.stopped,
    };
    job.report(
      status: next,
      current: current,
      total: total,
      reason: running || next == TaskStatus.succeeded ? null : reason ?? outcome,
      failureCount: _count(data['unreadable']),
    );
    if (!running) {
      _job = null;
      _stopRequested = false;
    }
  }

  Future<Map<String, dynamic>> runAction(
    String endpoint, {
    required bool mayStart,
  }) async {
    if (busy || (!mayStart && _stopRequested)) return const {};
    busy = true;
    // Keep the worker observed even if the panel closes during the POST.
    if (mayStart) _startObserving();
    _actionsChanged();
    try {
      await _refreshing;
      if (mayStart) _beginJob(TaskStatus.starting);
      final response = await api.postJson(endpoint);
      final failure = _actionFailure(response);
      if (!mayStart && failure == null) {
        _stopRequested = true;
        _job?.report(status: TaskStatus.cancelling);
      } else if (mayStart && failure != null && failure != 'already_running') {
        _failStart(failure);
      }
      return response;
    } catch (_) {
      if (mayStart) _failStart('request_failed');
      rethrow;
    } finally {
      await _readStatus(afterAction: true);
      busy = false;
      _actionsChanged();
    }
  }

  void _failStart(String reason) {
    if (_job?.status != TaskStatus.starting) return;
    _job!.report(
      status: reason == 'nothing_pending' || reason == 'nothing_to_do'
          ? TaskStatus.succeeded
          : TaskStatus.failed,
      reason: reason,
    );
    _job = null;
  }

  void _actionsChanged() {
    if (_definition != null) TaskCenter.forApi(api).actionsChanged();
    notifyListeners();
  }

  static int? _count(Object? value) => value is num ? value.toInt() : null;
  static String? _code(Object? value) => value is String && value.isNotEmpty ? value : null;

  static String? _actionFailure(Map<String, dynamic> response) {
    final code = _code(response['reason'] ?? response['status']);
    if (code == 'already_running') return code;
    if (response['ok'] != false && response['started'] != false &&
        response['success'] != false && response['error'] == null &&
        response['detail'] == null) {
      return null;
    }
    return _code(response['kind']) ?? code ?? 'request_failed';
  }
}

class _AiBackfillBarState extends State<AiBackfillBar> {
  late AiBackfillTask _task;
  String? _message;

  @override
  void initState() {
    super.initState();
    _attachTask();
  }

  @override
  void didUpdateWidget(covariant AiBackfillBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api ||
        oldWidget.statusEndpoint != widget.statusEndpoint) {
      _task.removeListener(_taskChanged);
      _message = null;
      _attachTask();
    }
  }

  void _attachTask() {
    _task = AiBackfillTask.forEndpoint(widget.api, widget.statusEndpoint);
    _task.addListener(_taskChanged);
    unawaited(_task.refresh());
  }

  void _taskChanged() => setState(() {});

  @override
  void dispose() {
    _task.removeListener(_taskChanged);
    super.dispose();
  }

  Future<void> _runAction(String endpoint, {bool confirmRebuild = false}) async {
    final task = _task;
    if (task.busy) return;
    if (confirmRebuild) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(widget.strings.backfillRebuildBtn),
          content: Text(widget.strings.backfillRebuildConfirm),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(widget.strings.cancel)),
            FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(widget.strings.confirm)),
          ],
        ),
      );
      if (ok != true || !mounted || !identical(task, _task) || task.busy) return;
    }

    setState(() => _message = null);
    try {
      final resp = await task.runAction(
        endpoint,
        mayStart: endpoint != widget.stopEndpoint,
      );
      if (!mounted || !identical(task, _task)) return;
      final detail = (resp['status'] ?? resp['reason'] ?? resp['error'] ?? '').toString();
      if (detail.isNotEmpty) {
        setState(() => _message = detail);
      }
    } catch (e) {
      debugPrint('AiBackfillBar action $endpoint error: $e');
      if (mounted && identical(task, _task)) {
        setState(() => _message = widget.strings.requestFailed('$e'));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final status = _task.status;
    final running = status?['running'] == true;
    final completedRaw = status?['processed'] ??
        status?['indexed'] ??
        status?['tagged'] ??
        status?['done'];
    final completed = (completedRaw as num?)?.toInt() ?? 0;
    final total = (status?['total'] as num?)?.toInt() ?? 0;
    final pending = (status?['pending'] as num?)?.toInt() ?? 0;
    final stoppedReason =
        (status?['stopped_reason'] ?? status?['stop_reason'] ?? status?['kind'] ?? '').toString();

    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: palette.surfaceHigh,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: palette.stroke),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (status != null) ...[
            Text(
              running
                  ? widget.strings.backfillRunningLabel(completed, total)
                  : '${widget.strings.backfillPendingLabel(pending)}${stoppedReason.isNotEmpty ? ' ($stoppedReason)' : ''}',
              style: TextStyle(fontSize: 12, color: palette.textSecondary),
            ),
            if (running) ...[
              const SizedBox(height: 6),
              LinearProgressIndicator(
                value: (total > 0 && completed > 0) ? (completed / total).clamp(0.0, 1.0) : null,
                minHeight: 4,
              ),
            ],
          ],
          if (_message != null && _message!.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(_message!, style: TextStyle(fontSize: 11.5, color: palette.textMuted)),
          ],
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              if (!running)
                FilledButton.tonalIcon(
                  onPressed: _task.busy ? null : () => _runAction(widget.startEndpoint),
                  icon: const Icon(Icons.play_arrow_rounded, size: 16),
                  label: Text(widget.strings.backfillStartBtn),
                )
              else
                FilledButton.tonalIcon(
                  onPressed: _task.canStop ? () => _runAction(widget.stopEndpoint) : null,
                  icon: const Icon(Icons.stop_rounded, size: 16),
                  label: Text(widget.strings.backfillStopBtn),
                ),
              if (!running)
                OutlinedButton.icon(
                  onPressed: _task.busy ? null : () => _runAction(widget.rebuildEndpoint, confirmRebuild: true),
                  icon: const Icon(Icons.refresh_rounded, size: 16),
                  label: Text(widget.strings.backfillRebuildBtn),
                ),
              TextButton.icon(
                onPressed: _task.busy ? null : _task.refresh,
                icon: const Icon(Icons.sync_rounded, size: 15),
                label: Text(widget.strings.backfillRefreshBtn),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
