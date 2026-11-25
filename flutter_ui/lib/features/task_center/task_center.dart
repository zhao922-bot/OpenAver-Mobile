import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../../core/api_client.dart';
import '../../core/native_bridge.dart';

enum TaskKind { scan, metadataBackfill, batchTag, batchTagPreview, similar, faces, aiTags }

enum TaskStatus {
  starting,
  running,
  cancelling,
  succeeded,
  failed,
  cancelled,
  stopped,
  interrupted;

  bool get isActive => switch (this) {
    starting || running || cancelling => true,
    _ => false,
  };
}

/// Task owners retain control of live jobs. Restored jobs are history only.
class TaskCenter extends ChangeNotifier {
  TaskCenter._() {
    _scheduleSync();
  }

  static final _byApi = Expando<TaskCenter>();

  static TaskCenter forApi(ApiClient api) => _byApi[api] ??= TaskCenter._();

  final _jobs = <TaskJob>[];
  File? _file;
  Future<void>? _syncing;
  bool _hydrated = false;
  bool _dirty = false;

  @visibleForTesting
  Future<void> get historySettled => _syncing ?? Future<void>.value();

  void _historyChanged() {
    _dirty = true;
    _scheduleSync();
  }

  void _scheduleSync() {
    _syncing ??= _sync();
  }

  Future<void> _sync() async {
    try {
      if (_file == null) {
        final info = await NativeBridge.instance.getBootstrapInfo();
        if (info.dataDir.isEmpty) return;
        _file = File('${info.dataDir}/task_history_v1.json');
      }
      final file = _file!;
      // Read before the first write. Jobs started or finished while reading
      // already occupy the front of the list and keep their live callbacks.
      if (!_hydrated) {
        await _restore(file);
        _hydrated = true;
      }
      while (_dirty) {
        _dirty = false;
        final data = jsonEncode([for (final job in _jobs) job._toJson()]);
        final temp = File('${file.path}.tmp');
        await temp.writeAsString(data, flush: true);
        await temp.rename(file.path);
      }
    } on Exception catch (error) {
      // Retry on the next history change, including the read if that failed.
      _dirty = true;
      debugPrint('Task history unavailable: ${error.runtimeType}');
    } finally {
      _syncing = null;
    }
  }

  Future<void> _restore(File file) async {
    Object? records;
    try {
      records = jsonDecode(await file.readAsString());
    } on PathNotFoundException {
      return;
    } on FormatException {
      return;
    }
    if (records is! List) return;
    final interrupted = <TaskJob>[];
    final finished = <TaskJob>[];
    for (final record in records) {
      final job = TaskJob._fromJson(this, record);
      if (job == null) continue;
      if (job.isActive) {
        job._status = TaskStatus.interrupted;
        interrupted.add(job);
      } else {
        finished.add(job);
      }
    }
    _jobs.addAll(interrupted);
    _jobs.addAll(finished);
    final previousLength = _jobs.length;
    _trimHistory();
    if (interrupted.isNotEmpty || _jobs.length != previousLength) _dirty = true;
    if (interrupted.isNotEmpty || finished.isNotEmpty) actionsChanged();
  }

  List<TaskJob> get jobs => List.unmodifiable(_jobs);

  TaskJob begin(
    TaskKind kind, {
    TaskStatus status = TaskStatus.running,
    String? subject,
  }) {
    final job = TaskJob._(this, kind, status, subject, DateTime.now());
    _jobs.insert(0, job);
    if (!job.isActive) _trimHistory();
    _historyChanged();
    actionsChanged();
    return job;
  }

  void actionsChanged() => notifyListeners();

  void _finish(TaskJob job) {
    _jobs.remove(job);
    _jobs.insert(0, job);
    _trimHistory();
    _historyChanged();
    actionsChanged();
  }

  void _trimHistory() {
    var recent = 0;
    _jobs.removeWhere((job) => !job.isActive && ++recent > 20);
  }
}

class TaskJob {
  TaskJob._(
    this._center,
    this.kind,
    this._status,
    this.subject,
    this.startedAt,
  );

  final TaskCenter _center;
  final TaskKind kind;
  final String? subject;
  final DateTime startedAt;
  DateTime? _finishedAt;
  TaskStatus _status;
  int? _current;
  int? _total;
  String? _message;
  String? _reason;
  int _failureCount = 0;
  final _failureExamples = <String>[];
  int _warningCount = 0;
  final _warningExamples = <String>[];
  AsyncCallback? _cancel;
  AsyncCallback? _retry;
  bool Function()? _cancelAvailable;
  bool Function()? _retryAvailable;

  Map<String, Object?> _toJson() => {
    'kind': kind.name,
    'status': status.name,
    'startedAt': startedAt.toUtc().toIso8601String(),
    'finishedAt': ?finishedAt?.toUtc().toIso8601String(),
    'subject': ?subject,
    'current': ?current,
    'total': ?total,
    'message': ?message,
    'reason': ?reason,
    'failureCount': failureCount,
    'failureExamples': _failureExamples,
    'warningCount': warningCount,
    'warningExamples': _warningExamples,
  };

  static TaskJob? _fromJson(TaskCenter center, Object? record) {
    if (record is! Map<String, dynamic>) return null;
    T? field<T>(String key) => record[key] is T ? record[key] as T : null;
    DateTime? time(String key) =>
        DateTime.tryParse(field<String>(key) ?? '')?.toLocal();
    Iterable<String> examples(String key) => (field<List>(key) ?? const [])
        .whereType<String>()
        .where((s) => s.isNotEmpty)
        .take(5);
    final kind = TaskKind.values.asNameMap()[record['kind']];
    final status = TaskStatus.values.asNameMap()[record['status']];
    final startedAt = time('startedAt');
    if (kind == null || status == null || startedAt == null) return null;
    return TaskJob._(center, kind, status, field<String>('subject'), startedAt)
      .._finishedAt = time('finishedAt')
      .._current = field<int>('current')
      .._total = field<int>('total')
      .._message = field<String>('message')
      .._reason = field<String>('reason')
      .._failureExamples.addAll(examples('failureExamples'))
      .._failureCount = field<int>('failureCount') ?? 0
      .._warningExamples.addAll(examples('warningExamples'))
      .._warningCount = field<int>('warningCount') ?? 0;
  }

  DateTime? get finishedAt => _finishedAt;
  TaskStatus get status => _status;
  bool get isActive => status.isActive;
  int? get current => _current;
  int? get total => _total;
  String? get message => _message;
  String? get reason => _reason;
  int get failureCount => _failureCount;
  List<String> get failureExamples => List.unmodifiable(_failureExamples);
  int get warningCount => _warningCount;
  List<String> get warningExamples => List.unmodifiable(_warningExamples);
  double? get progress {
    if (current == null || total == null || total! <= 0) return null;
    return (current! / total!).clamp(0.0, 1.0);
  }

  bool get canCancel =>
      isActive && _cancel != null && (_cancelAvailable?.call() ?? true);
  bool get canRetry =>
      !isActive &&
      (status != TaskStatus.succeeded || failureCount > 0) &&
      _retry != null &&
      (_retryAvailable?.call() ?? true);

  void setCancel(AsyncCallback action, {bool Function()? available}) {
    _cancel = action;
    _cancelAvailable = available;
    _center.actionsChanged();
  }

  void setRetry(AsyncCallback action, {bool Function()? available}) {
    _retry = action;
    _retryAvailable = available;
    _center.actionsChanged();
  }

  Future<void> cancel() async {
    if (canCancel) await _cancel!();
  }

  Future<void> retry() async {
    if (canRetry) await _retry!();
  }

  void report({
    TaskStatus? status,
    int? current,
    int? total,
    String? message,
    String? reason,
    int? failureCount,
    String? failureExample,
    Iterable<String>? failureExamples,
    String? warningExample,
  }) {
    if (!isActive) return;
    final previousStatus = _status;
    final previousFailures = _failureCount;
    final previousReason = _reason;
    _status = status ?? _status;
    _current = current ?? _current;
    _total = total ?? _total;
    _message = message ?? _message;
    _reason = reason ?? _reason;
    if (failureExample != null && failureExample.isNotEmpty) {
      if (failureCount == null) _failureCount++;
      if (_failureExamples.length < 5) _failureExamples.add(failureExample);
    }
    if (failureExamples != null) {
      _failureExamples
        ..clear()
        ..addAll(failureExamples.where((text) => text.isNotEmpty).take(5));
    }
    if (failureCount != null && failureCount >= 0) _failureCount = failureCount;
    if (warningExample != null && warningExample.isNotEmpty) {
      _warningCount++;
      if (_warningExamples.length < 5) _warningExamples.add(warningExample);
    }
    if (isActive) {
      if (_status != previousStatus ||
          _failureCount != previousFailures ||
          _reason != previousReason ||
          failureExamples != null ||
          failureExample?.isNotEmpty == true ||
          warningExample?.isNotEmpty == true) {
        _center._historyChanged();
      }
      _center.actionsChanged();
    } else {
      _finishedAt = DateTime.now();
      _cancel = null;
      _cancelAvailable = null;
      _center._finish(this);
    }
  }
}
