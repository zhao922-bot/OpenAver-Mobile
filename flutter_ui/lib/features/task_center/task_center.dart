import 'package:flutter/foundation.dart';

import '../../core/api_client.dart';

enum TaskKind { scan, batchTag, batchTagPreview, similar, faces, aiTags }

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

/// Session history for one local runtime. Task owners publish observations from
/// their existing streams or status readers and retain control of those jobs.
class TaskCenter extends ChangeNotifier {
  TaskCenter._();

  static final _byApi = Expando<TaskCenter>();

  static TaskCenter forApi(ApiClient api) => _byApi[api] ??= TaskCenter._();

  final _jobs = <TaskJob>[];

  List<TaskJob> get jobs => List.unmodifiable(_jobs);

  TaskJob begin(
    TaskKind kind, {
    TaskStatus status = TaskStatus.running,
    String? subject,
  }) {
    final job = TaskJob._(this, kind, status, subject);
    _jobs.insert(0, job);
    actionsChanged();
    return job;
  }

  void actionsChanged() => notifyListeners();

  void _finish(TaskJob job) {
    _jobs.remove(job);
    _jobs.insert(0, job);
    var recent = 0;
    _jobs.removeWhere((job) => !job.isActive && ++recent > 20);
    actionsChanged();
  }
}

class TaskJob {
  TaskJob._(this._center, this.kind, this._status, this.subject);

  final TaskCenter _center;
  final TaskKind kind;
  final String? subject;
  final DateTime startedAt = DateTime.now();
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
      _center.actionsChanged();
    } else {
      _finishedAt = DateTime.now();
      _cancel = null;
      _cancelAvailable = null;
      _center._finish(this);
    }
  }
}
