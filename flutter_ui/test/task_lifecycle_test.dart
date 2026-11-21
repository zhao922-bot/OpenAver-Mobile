import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/features/scanner/scanner_page.dart';
import 'package:flutter_ui/features/settings/ai_backfill_bar.dart';

final _strings = AppStrings('en');
const _channel = MethodChannel('dev.openaver.mobile/bridge');

class _TaskApi extends ApiClient {
  _TaskApi() : super(port: 8765, token: 'test');

  final scanStreams = <StreamController<SseEvent>>[];
  final aiRunning = <String, bool>{};
  Completer<void>? scanCleanup;
  Completer<void>? aiStart;

  @override
  Stream<SseEvent> streamSse(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? queryParameters,
    Object? data,
    CancelToken? cancelToken,
  }) {
    final cleanup = scanCleanup;
    final events = StreamController<SseEvent>(onCancel: () => cleanup?.future);
    scanStreams.add(events);
    unawaited(
      cancelToken?.whenCancel.then((error) {
        if (!events.isClosed) events.addError(error);
      }),
    );
    return events.stream;
  }

  @override
  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) async => {if (aiRunning.containsKey(path)) 'running': aiRunning[path]};

  @override
  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? data,
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    await aiStart?.future;
    aiRunning['/similar/status'] = true;
    return {'status': 'started'};
  }
}

Widget _app(_TaskApi api, Widget home) => ProviderScope(
  overrides: [
    apiClientProvider.overrideWithValue(api),
    stringsProvider.overrideWithValue(_strings),
  ],
  child: MaterialApp(home: home),
);

AiBackfillBar _backfill(_TaskApi api, String service) => AiBackfillBar(
  api: api,
  strings: _strings,
  statusEndpoint: '/$service/status',
  startEndpoint: '/$service/start',
  stopEndpoint: '/$service/stop',
  rebuildEndpoint: '/$service/rebuild',
);

void _progress(StreamController<SseEvent> events, int current, int total) {
  events.add(
    SseEvent({'type': 'progress', 'current': current, 'total': total}),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late List<bool> keepAlive;

  setUp(() {
    keepAlive = [];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, (call) async {
          if (call.method == 'setTaskKeepAlive') {
            keepAlive.add(call.arguments['active'] as bool);
          }
          return null;
        });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, null);
  });

  testWidgets(
    'Scanner completes at 100% only after a successful terminal event',
    (tester) async {
      final api = _TaskApi();
      await tester.pumpWidget(_app(api, const ScannerPage()));
      await tester.tap(find.text(_strings.scanLibrary));
      await tester.pump();

      final events = api.scanStreams.single;
      _progress(events, 5, 5);
      await tester.pump();
      expect(find.text('99%'), findsOneWidget);
      expect(find.text('100%'), findsNothing);
      events.add(const SseEvent({'type': 'done', 'video_count': 5}));
      unawaited(events.close());
      await tester.pump();
      expect(find.text('100%'), findsOneWidget);
      expect(keepAlive, [true, false]);
    },
  );

  for (final (terminal, line) in <(Map<String, dynamic>?, String)>[
    ({'type': 'done', 'cancelled': true}, _strings.taskCancelled),
    (
      {
        'type': 'done',
        'summary': {'cancelled': true},
        'message': 'Batch cancelled',
      },
      'Batch cancelled',
    ),
    ({'type': 'error', 'message': 'Scan failed'}, 'Scan failed'),
    (null, _strings.taskStreamInterrupted),
  ]) {
    testWidgets('Scanner preserves progress on $line', (tester) async {
      final api = _TaskApi();
      await tester.pumpWidget(_app(api, const ScannerPage()));
      await tester.tap(find.text(_strings.scanLibrary));
      await tester.pump();

      final events = api.scanStreams.single;
      _progress(events, 3, 5);
      if (terminal != null) events.add(SseEvent(terminal));
      unawaited(events.close());
      await tester.pump();
      expect(find.text(line), findsOneWidget);
      expect(find.text('60%'), findsOneWidget);
      expect(
        tester
            .widget<LinearProgressIndicator>(
              find.byType(LinearProgressIndicator),
            )
            .value,
        0.6,
      );
      expect(keepAlive, [true, false]);
    });
  }

  testWidgets('Scanner waits for cancellation cleanup before a rapid restart', (
    tester,
  ) async {
    final api = _TaskApi()..scanCleanup = Completer<void>();
    await tester.pumpWidget(_app(api, const ScannerPage()));
    final scanButton = find.widgetWithText(FilledButton, _strings.scanLibrary);
    final staleStart = tester.widget<FilledButton>(scanButton).onPressed!;
    staleStart();
    await tester.pump();
    _progress(api.scanStreams.single, 1, 4);
    await tester.pump();

    await tester.tap(find.text(_strings.stopTask));
    await tester.pump();
    staleStart();
    expect(tester.widget<FilledButton>(scanButton).onPressed, isNull);
    expect(api.scanStreams, hasLength(1));
    expect(find.text('25%'), findsOneWidget);
    expect(find.text(_strings.taskAborted), findsWidgets);
    expect(keepAlive, [true]);

    api.scanCleanup!.complete();
    await tester.pump();
    expect(tester.widget<FilledButton>(scanButton).onPressed, isNotNull);
    expect(keepAlive, [true, false]);
    await tester.tap(scanButton);
    await tester.pump();
    final restarted = api.scanStreams.last;
    restarted.add(const SseEvent({'type': 'done'}));
    unawaited(restarted.close());
    await tester.pump();
    expect(api.scanStreams, hasLength(2));
    expect(find.text('100%'), findsOneWidget);
    expect(keepAlive, [true, false, true, false]);
  });

  testWidgets('AI backfills keep independent leases after leaving settings', (
    tester,
  ) async {
    final api = _TaskApi()
      ..aiStart = Completer<void>()
      ..aiRunning.addAll({'/similar/status': false, '/faces/status': true});
    final showSettings = ValueNotifier(true);
    await tester.pumpWidget(
      _app(
        api,
        ValueListenableBuilder<bool>(
          valueListenable: showSettings,
          builder: (context, showing, child) => showing
              ? Scaffold(
                  body: Column(
                    children: [
                      _backfill(api, 'similar'),
                      _backfill(api, 'faces'),
                    ],
                  ),
                )
              : const ScannerPage(),
        ),
      ),
    );
    await tester.pump();
    expect(keepAlive, [true]);
    await tester.tap(find.text(_strings.backfillStartBtn));
    await tester.pump();

    showSettings.value = false;
    await tester.pump();
    api.aiStart!.complete();
    await tester.tap(find.text(_strings.scanLibrary));
    await tester.pump();
    final scanner = api.scanStreams.single;
    scanner.add(const SseEvent({'type': 'done'}));
    unawaited(scanner.close());
    await tester.pump();
    expect(keepAlive, [true]);

    api.aiRunning['/faces/status'] = false;
    await tester.pump(const Duration(seconds: 3));
    expect(keepAlive, [true]);
    api.aiRunning['/similar/status'] = false;
    await tester.pump(const Duration(seconds: 3));
    expect(keepAlive, [true, false]);
    await tester.pumpWidget(const SizedBox.shrink());
    showSettings.dispose();
  });
}
