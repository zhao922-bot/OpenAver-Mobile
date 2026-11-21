import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/core/native_bridge.dart';
import 'package:flutter_ui/features/scanner/scanner_page.dart';
import 'package:flutter_ui/features/settings/ai_backfill_bar.dart';
import 'package:flutter_ui/features/task_center/task_center.dart';
import 'package:flutter_ui/features/task_center/task_center_page.dart';
import 'package:flutter_ui/main.dart';

const _channel = MethodChannel('dev.openaver.mobile/bridge');
const _similarStatus = '/api/ai/similar/status';
const _similarStart = '/api/ai/similar/index';
const _similarStop = '/api/ai/similar/index/stop';
final _strings = AppStrings('en');

class _FakeApi extends ApiClient {
  _FakeApi() : super(port: 8765, token: 'test');

  final reads = <String, int>{};
  final posts = <String>[];
  final streams =
      <(String, Map<String, dynamic>?, StreamController<SseEvent>)>[];
  Completer<void>? delaySimilarStatus;
  Map<String, dynamic> similar = {'running': false};

  @override
  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    reads.update(path, (value) => value + 1, ifAbsent: () => 1);
    if (path == _similarStatus) {
      await delaySimilarStatus?.future;
      return similar;
    }
    if (path.startsWith('/api/ai/')) return {'running': false};
    if (path == '/api/search/favorite-files') return {'files': []};
    return {
      'success': true,
      'data': <String, dynamic>{},
      'videos': <dynamic>[],
      'total': 0,
    };
  }

  @override
  Future<List<dynamic>> getJsonList(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async => [];

  @override
  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? data,
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    posts.add(path);
    if (path == _similarStart) similar = {...similar, 'running': true};
    return {'ok': true};
  }

  @override
  Stream<SseEvent> streamSse(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? queryParameters,
    Object? data,
    CancelToken? cancelToken,
  }) {
    final events = StreamController<SseEvent>();
    streams.add((path, queryParameters, events));
    unawaited(
      cancelToken?.whenCancel.then((error) {
        if (!events.isClosed) {
          events.addError(error);
          unawaited(events.close());
        }
      }),
    );
    return events.stream;
  }
}

Widget _scope(_FakeApi api, Widget child) => ProviderScope(
  overrides: [apiClientProvider.overrideWithValue(api)],
  child: child,
);

void _finish(StreamController<SseEvent> events, Map<String, dynamic> data) {
  events.add(SseEvent(data));
  unawaited(events.close());
}

void main() {
  final messenger =
      TestWidgetsFlutterBinding.ensureInitialized().defaultBinaryMessenger;
  late List<MethodCall> bridgeCalls;
  late bool pendingTaskCenter;
  late bool runtimeReady;

  Map<String, dynamic> bootstrap() => {'ready': runtimeReady, 'uiLocale': 'en'};

  setUp(() {
    bridgeCalls = [];
    pendingTaskCenter = false;
    runtimeReady = true;
    messenger.setMockMethodCallHandler(_channel, (call) async {
      bridgeCalls.add(call);
      if (call.method == 'getBootstrapInfo') return bootstrap();
      if (call.method == 'consumeTaskCenterRequest') {
        final pending = pendingTaskCenter;
        pendingTaskCenter = false;
        return pending;
      }
      return null;
    });
  });

  tearDown(() => messenger.setMockMethodCallHandler(_channel, null));

  Future<void> nativeEvent(String method, [Object? args]) async {
    await messenger.handlePlatformMessage(
      _channel.name,
      const StandardMethodCodec().encodeMethodCall(MethodCall(method, args)),
      (_) {},
    );
  }

  testWidgets('cold and warm task taps select Tasks in both layouts', (
    tester,
  ) async {
    final api = _FakeApi();
    runtimeReady = false;
    pendingTaskCenter = true;
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(360, 720);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(_scope(api, const OpenAverApp()));
    await tester.pump();
    expect(find.text(_strings.startingServer), findsOneWidget);
    runtimeReady = true;
    await nativeEvent('onRuntimeReady', bootstrap());
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.text(_strings.taskCenterTitle), findsOneWidget);

    final scannerTab = find.widgetWithIcon(
      NavigationDestination,
      Icons.radar_rounded,
    );
    await tester.tap(scannerTab);
    await tester.pumpAndSettle();
    await tester.tap(
      find.widgetWithIcon(NavigationDestination, Icons.task_alt_rounded),
    );
    await tester.pumpAndSettle();
    expect(find.text(_strings.taskCenterTitle), findsOneWidget);
    await tester.tap(scannerTab);
    await tester.pumpAndSettle();
    await tester.tap(find.text(_strings.scanLibrary));
    await tester.pump();
    final stream = api.streams.single.$3;
    stream.add(const SseEvent({'type': 'progress', 'current': 1, 'total': 4}));
    stream.add(
      const SseEvent({
        'type': 'log',
        'level': 'warn',
        'message': 'Could not read a file',
      }),
    );
    await tester.pump();
    expect(find.text('25%'), findsOneWidget);

    tester.view.physicalSize = const Size(1100, 720);
    await tester.pump();
    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.text('25%'), findsOneWidget);

    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    unawaited(
      navigator.push<void>(
        MaterialPageRoute(
          builder: (_) => const Scaffold(body: Text('Open detail')),
        ),
      ),
    );
    await tester.pumpAndSettle();
    pendingTaskCenter = true;
    await nativeEvent('taskCenterRequested');
    await tester.pumpAndSettle();
    expect(find.text('Open detail'), findsNothing);
    expect(find.text(_strings.taskCenterProgress(1, 4)), findsOneWidget);
    expect(find.text(_strings.taskCenterScan), findsOneWidget);
    expect(find.text(_strings.taskCenterWarningCount(1)), findsOneWidget);
    expect(TaskCenter.forApi(api).jobs.single.warningExamples, [
      'Could not read a file',
    ]);
    expect(api.streams, hasLength(1));

    await tester.tap(find.text(_strings.cancel));
    await tester.pumpAndSettle();
    expect(TaskCenter.forApi(api).jobs.single.status, TaskStatus.cancelled);
    expect(find.text(_strings.taskCenterRecent), findsOneWidget);

    await tester.tap(find.text(_strings.tabScanner));
    await tester.pumpAndSettle();
    await nativeEvent('taskCenterRequested');
    await tester.pumpAndSettle();
    expect(
      find.widgetWithText(FilledButton, _strings.scanLibrary),
      findsOneWidget,
    );
    await tester.tap(find.text(_strings.taskCenterTab));
    await tester.pumpAndSettle();
    expect(find.text(_strings.taskCenterTitle), findsOneWidget);
  });

  testWidgets(
    'batch tags preserve partial failures and retry only failed numbers',
    (tester) async {
      final api = _FakeApi();
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(800, 900);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      final page = ValueNotifier(0);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(api),
            stringsProvider.overrideWithValue(_strings),
          ],
          child: MaterialApp(
            home: ValueListenableBuilder<int>(
              valueListenable: page,
              builder: (_, value, _) => IndexedStack(
                index: value,
                children: const [ScannerPage(), TaskCenterPage()],
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final batch = find.text(_strings.batchTagSourceTitle);
      await tester.ensureVisible(batch);
      await tester.tap(batch);
      await tester.pumpAndSettle();
      await tester.tap(find.text(_strings.batchTagSourceRunBtn));
      await tester.pump();

      final (path, query, events) = api.streams.single;
      expect(path, '/api/gallery/tag-source-update');
      expect(query, {'source': 'javbus'});
      events.add(
        const SseEvent({'type': 'progress', 'current': 3, 'total': 4}),
      );
      _finish(events, {
        'type': 'done',
        'summary': {
          'total': 4,
          'failed': 2,
          'failed_items': [
            {'number': 'A-01', 'error': 'First failure'},
            {'number': 'B-02', 'error': 'Second failure'},
          ],
        },
      });
      page.value = 1;
      await tester.pumpAndSettle();
      expect(
        find.text(_strings.taskCenterCompletedWithFailures),
        findsOneWidget,
      );
      expect(find.text(_strings.taskCenterFailureCount(2)), findsOneWidget);
      expect(find.text(_strings.taskCenterProgress(4, 4)), findsOneWidget);
      await tester.tap(find.text(_strings.taskCenterDetails));
      await tester.pumpAndSettle();
      expect(find.text('A-01 · First failure'), findsOneWidget);
      expect(find.text(_strings.cancel), findsNothing);

      await tester.tap(find.text(_strings.retry));
      await tester.pump();
      final (retryPath, retryQuery, retryEvents) = api.streams.last;
      expect(retryPath, path);
      expect(retryQuery, {'source': 'javbus', 'numbers': 'A-01,B-02'});
      _finish(retryEvents, {
        'type': 'done',
        'summary': {'total': 2},
      });
      await tester.pumpAndSettle();
      expect(TaskCenter.forApi(api).jobs, hasLength(2));
      await tester.pumpWidget(const SizedBox.shrink());
      page.dispose();
    },
  );

  testWidgets(
    'AI task and settings share polling, stop and retry, and the task lease',
    (tester) async {
      final api = _FakeApi()
        ..delaySimilarStatus = Completer<void>()
        ..similar = {'running': true, 'indexed': 2, 'total': 5, 'pending': 3};
      unawaited(AiBackfillTask.refreshKnown(api));
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(api),
            stringsProvider.overrideWithValue(_strings),
          ],
          child: MaterialApp(
            home: IndexedStack(
              index: 1,
              children: [
                AiBackfillBar(
                  api: api,
                  strings: _strings,
                  statusEndpoint: _similarStatus,
                  startEndpoint: _similarStart,
                  stopEndpoint: _similarStop,
                  rebuildEndpoint: '$_similarStart/rebuild',
                ),
                const TaskCenterPage(),
              ],
            ),
          ),
        ),
      );
      expect(api.reads[_similarStatus], 1);
      api.delaySimilarStatus!.complete();
      await tester.pumpAndSettle();
      expect(find.text(_strings.taskCenterProgress(2, 5)), findsOneWidget);
      expect(api.reads[_similarStatus], 1);

      Map<Object?, Object?> notification() =>
          bridgeCalls
                  .lastWhere((call) => call.method == 'updateTaskNotification')
                  .arguments
              as Map<Object?, Object?>;
      expect(notification()['progressCurrent'], 2);
      expect(notification()['progressTotal'], 5);
      final otherLease = NativeBridge.instance.acquireTaskKeepAlive();
      otherLease.updateProgress(1, 2);
      await tester.pump();
      expect(notification()['taskCount'], 2);
      expect(notification().containsKey('progressTotal'), false);
      otherLease.release();
      await tester.pump();
      expect(notification()['taskCount'], 1);
      expect(notification()['progressCurrent'], 2);

      await tester.pump(const Duration(seconds: 3));
      expect(api.reads[_similarStatus], 2);
      await tester.tap(find.text(_strings.backfillStopBtn));
      await tester.pump();
      expect(api.posts, [_similarStop]);
      expect(find.text(_strings.taskCenterCancelling), findsOneWidget);
      expect(find.text(_strings.backfillStopBtn), findsNothing);

      api.similar = {...api.similar, 'running': false};
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.text(_strings.taskCenterCancelled), findsOneWidget);
      await tester.tap(find.text(_strings.retry));
      await tester.pumpAndSettle();
      expect(api.posts, [_similarStop, _similarStart]);
      expect(TaskCenter.forApi(api).jobs, hasLength(2));

      api.similar = {'running': false, 'indexed': 5, 'total': 5, 'pending': 0};
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(TaskCenter.forApi(api).jobs.first.status, TaskStatus.succeeded);
      expect(
        bridgeCalls
            .where((call) => call.method == 'setTaskKeepAlive')
            .map((call) => call.arguments['active']),
        [true, false, true, false],
      );
    },
  );
}
