import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/features/task_center/task_center.dart';

void main() {
  final messenger =
      TestWidgetsFlutterBinding.ensureInitialized().defaultBinaryMessenger;
  const channel = MethodChannel('dev.openaver.mobile/bridge');
  late Directory directory;
  Completer<void>? bootstrapGate;
  TaskCenter restart() => TaskCenter.forApi(ApiClient(port: 8765, token: ''));
  Future<File> savedFile() async => (await directory.list().single) as File;

  setUp(() async {
    directory = await Directory.systemTemp.createTemp('openaver_task_history_');
    bootstrapGate = null;
    messenger.setMockMethodCallHandler(channel, (call) async {
      expect(call.method, 'getBootstrapInfo');
      await bootstrapGate?.future;
      return {'dataDir': directory.path};
    });
  });

  tearDown(() async {
    messenger.setMockMethodCallHandler(channel, null);
    await directory.delete(recursive: true);
  });

  test(
    'restart retains terminal outcomes, details, and original timestamps',
    () async {
      final center = restart();
      final statuses = TaskStatus.values.where((status) => !status.isActive);
      for (final status in statuses) {
        center.begin(TaskKind.batchTag, subject: 'javbus')
          ..setRetry(() async {})
          ..report(warningExample: 'source warning')
          ..report(
            status: status,
            current: 9,
            total: 10,
            message: 'detail',
            reason: 'model_changed',
            failureCount: 12,
            failureExamples: List.generate(12, (i) => 'item $i'),
          );
      }
      await center.historySettled;
      final recovered = restart();
      await recovered.historySettled;
      expect(
        recovered.jobs.map((job) => job.status),
        statuses.toList().reversed,
      );
      for (final (i, job) in recovered.jobs.indexed) {
        expect(job.kind, TaskKind.batchTag);
        expect(job.subject, 'javbus');
        expect(job.startedAt, center.jobs[i].startedAt);
        expect(job.finishedAt, center.jobs[i].finishedAt);
        expect(job.finishedAt, isNotNull);
        expect((job.current, job.total), (9, 10));
        expect((job.message, job.reason), ('detail', 'model_changed'));
        expect(job.failureCount, 12);
        expect(job.failureExamples, List.generate(5, (i) => 'item $i'));
        expect(job.warningCount, 1);
        expect(job.warningExamples, ['source warning']);
        expect(job.canRetry || job.canCancel, isFalse);
      }
    },
  );

  test(
    'hydration merges live activity and recovers all previous active states once',
    () async {
      final old = restart();
      for (final status in TaskStatus.values.where(
        (status) => status.isActive,
      )) {
        old.begin(TaskKind.scan, subject: status.name, status: status)
          ..setCancel(() async {})
          ..report(current: 2, total: 5, failureExample: 'unreadable');
      }
      await old.historySettled;

      bootstrapGate = Completer<void>();
      final center = restart();
      final live = center.begin(TaskKind.faces)..setCancel(() async {});
      final done = center.begin(TaskKind.similar)
        ..report(status: TaskStatus.succeeded);
      expect(center.jobs, [done, live]);
      bootstrapGate!.complete();
      await center.historySettled;
      expect(center.jobs.take(2), [done, live]);
      expect(live.canCancel, isTrue);
      final interrupted = center.jobs.skip(2).toList();
      expect(interrupted.map((job) => job.subject), [
        'cancelling',
        'running',
        'starting',
      ]);
      for (final (i, job) in interrupted.indexed) {
        expect(job.status, TaskStatus.interrupted);
        expect(job.startedAt, old.jobs[i].startedAt);
        expect(job.finishedAt, isNull);
        expect(job.failureExamples, ['unreadable']);
        expect(job.canCancel || job.canRetry, isFalse);
      }
      final file = await savedFile();
      final records = jsonDecode(await file.readAsString()) as List;
      expect(
        records.skip(2).map((row) => row['status']),
        everyElement('interrupted'),
      );
      final again = restart();
      await again.historySettled;
      expect(again.jobs, hasLength(5));
      expect(
        again.jobs.where((job) => job.status == TaskStatus.interrupted),
        hasLength(4),
      );
    },
  );

  test('progress and action availability do not write history', () async {
    final center = restart();
    final live = center.begin(TaskKind.scan);
    await center.historySettled;
    final file = await savedFile();
    final content = await file.readAsString();
    await file.setLastModified(DateTime(2001));
    final timestamp = await file.lastModified();
    for (var i = 0; i < 5; i++) {
      live.report(
        status: TaskStatus.running,
        current: i,
        total: 10,
        message: 'file $i',
        failureCount: 0,
      );
      live.setCancel(() async {});
      await center.historySettled;
    }
    expect(await file.readAsString(), content);
    expect(await file.lastModified(), timestamp);
    live.report(status: TaskStatus.failed, message: 'read failed');
    await center.historySettled;
    final next = restart();
    await next.historySettled;
    expect(next.jobs.single.current, 4);
    expect(next.jobs.single.message, 'read failed');
  });

  test(
    'bounds apply after merging and recovering without evicting live tasks',
    () async {
      final center = restart();
      center.begin(TaskKind.aiTags, subject: 'previously active');
      for (var i = 0; i < 25; i++) {
        center
            .begin(TaskKind.scan, subject: '$i')
            .report(status: TaskStatus.succeeded);
      }
      await center.historySettled;
      expect(center.jobs, hasLength(21));
      final recovered = restart();
      final live = recovered.begin(TaskKind.batchTagPreview);
      await recovered.historySettled;
      expect(recovered.jobs, hasLength(21));
      expect(recovered.jobs.first, live);
      expect(recovered.jobs[1].subject, 'previously active');
      expect(recovered.jobs[1].status, TaskStatus.interrupted);
      expect(recovered.jobs.last.subject, '6');
    },
  );

  test(
    'bad records do not hide valid siblings or prevent later writes',
    () async {
      final first = restart();
      first.begin(TaskKind.scan).report(status: TaskStatus.failed);
      await first.historySettled;
      final file = await savedFile();
      final good =
          (jsonDecode(await file.readAsString()) as List).single as Map;
      await file.writeAsString(
        jsonEncode([
          null,
          {...good, 'status': 'new'},
          {...good, 'startedAt': false},
          {...good, 'kind': 'unknown'},
          good,
        ]),
      );
      final recovered = restart();
      await recovered.historySettled;
      expect(recovered.jobs.single.status, TaskStatus.failed);
      await file.writeAsString('{broken');
      final clean = restart();
      clean.begin(TaskKind.faces).report(status: TaskStatus.stopped);
      await clean.historySettled;
      final again = restart();
      await again.historySettled;
      expect(again.jobs.single.status, TaskStatus.stopped);
    },
  );
}
