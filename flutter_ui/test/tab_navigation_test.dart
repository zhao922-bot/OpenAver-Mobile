import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/features/insights/insights_page.dart';
import 'package:flutter_ui/features/scanner/scanner_page.dart';
import 'package:flutter_ui/features/search/search_page.dart';
import 'package:flutter_ui/features/search/search_result_detail_page.dart';
import 'package:flutter_ui/features/settings/settings_page.dart';
import 'package:flutter_ui/features/showcase/showcase_page.dart';
import 'package:flutter_ui/features/task_center/task_center_page.dart';
import 'package:flutter_ui/main.dart';

const _config = '/api/config';
const _videos = '/api/showcase/videos';
const _taskStatus = [
  '/api/ai/similar/status',
  '/api/ai/faces/status',
  '/api/ai/tags/backfill/status',
];
const _searchHome = [
  '/api/search/maker-capsules',
  '/api/search/recent-actresses',
  '/api/search/favorite-files',
  '/api/wishlist',
];

class _TabApi implements HttpClientAdapter {
  final requests = <RequestOptions>[];
  final defaultPage = Completer<String>();
  Iterable<String> get paths => requests.map((request) => request.path);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? stream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (options.path == '/api/search/stream') {
      return ResponseBody.fromString(
        'data: {"type":"result","data":[{"number":"ABC-123","title":"Retained search hit"}]}\n\n',
        200,
        headers: {
          Headers.contentTypeHeader: ['text/event-stream'],
        },
      );
    }
    final Object json = switch (options.path) {
      _config => {
        'data': {
          'general': {'default_page': await defaultPage.future},
        },
      },
      '/api/insights/snapshot' => {
        'success': true,
        'records': [
          {
            'tags': ['Drama'],
          },
        ],
      },
      '/api/wishlist' => [],
      _ => {'success': true, 'running': false, 'videos': [], 'files': []},
    };
    return ResponseBody.fromString(
      jsonEncode(json),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  final messenger =
      TestWidgetsFlutterBinding.ensureInitialized().defaultBinaryMessenger;
  const channel = MethodChannel('dev.openaver.mobile/bridge');
  late _TabApi api;
  late bool pendingTask;
  Completer<void>? consumeGate;

  setUp(() {
    pendingTask = false;
    consumeGate = null;
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'consumeTaskCenterRequest') {
        await consumeGate?.future;
        final pending = pendingTask;
        pendingTask = false;
        return pending;
      }
      if (call.method == 'getBootstrapInfo') {
        return {'ready': true, 'uiLocale': 'en'};
      }
      return null;
    });
  });
  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  Future<void> start(WidgetTester tester, {String? defaultPage}) async {
    api = _TabApi();
    if (defaultPage != null) api.defaultPage.complete(defaultPage);
    final client = ApiClient(port: 8765, token: 'test', httpClientAdapter: api);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiClientProvider.overrideWithValue(client)],
        child: const OpenAverApp(),
      ),
    );
    await tester.pump();
    await tester.pump(Duration.zero);
  }

  Future<void> select(WidgetTester tester, IconData icon) async {
    await tester.tap(find.widgetWithIcon(NavigationDestination, icon));
    await tester.pumpAndSettle();
  }

  Future<void> back(WidgetTester tester) async {
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
  }

  void expectOnlyMounted(Type page) {
    for (final type in [
      ShowcasePage,
      SearchPage,
      ScannerPage,
      InsightsPage,
      SettingsPage,
      TaskCenterPage,
    ]) {
      expect(
        find.byType(type, skipOffstage: false),
        type == page ? findsOneWidget : findsNothing,
      );
    }
  }

  testWidgets(
    'ordinary launch requests only preferences and the visible library',
    (tester) async {
      await start(tester, defaultPage: 'showcase');
      await tester.pumpAndSettle();
      expectOnlyMounted(ShowcasePage);
      expect(api.paths, unorderedEquals([_config, _videos]));
    },
  );

  testWidgets(
    'cold task launch wins over a delayed default and Back opens Showcase once',
    (tester) async {
      tester.view.physicalSize = Size.zero;
      addTearDown(tester.view.resetPhysicalSize);
      await start(tester);
      expect(api.paths, isEmpty);

      // The background bridge can't consume the notification until Android
      // attaches the activity to the prewarmed engine.
      pendingTask = true;
      consumeGate = Completer<void>();
      tester.view.resetPhysicalSize();
      await tester.pump();
      expect(find.byType(ShowcasePage, skipOffstage: false), findsNothing);
      consumeGate!.complete();
      await tester.pumpAndSettle();
      expectOnlyMounted(TaskCenterPage);
      expect(api.paths, unorderedEquals([_config, ..._taskStatus]));

      await back(tester);
      api.defaultPage.complete('search');
      await tester.pumpAndSettle();
      expect(find.byType(ShowcasePage), findsOneWidget);
      expect(find.byType(SearchPage, skipOffstage: false), findsNothing);
      expect(api.paths, unorderedEquals([_config, ..._taskStatus, _videos]));
    },
  );

  testWidgets(
    'warm notification dismisses the route and Back restores Search results',
    (tester) async {
      await start(tester);
      expect(api.paths, [_config]);
      api.defaultPage.complete('search');
      await tester.pumpAndSettle();
      expectOnlyMounted(SearchPage);
      expect(api.paths, unorderedEquals([_config, ..._searchHome]));

      final search = tester.state(find.byType(SearchPage));
      await tester.enterText(find.byType(TextField), 'ABC-123');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Retained search hit'));
      await tester.pumpAndSettle();
      expect(find.byType(SearchResultDetailPage), findsOneWidget);
      pendingTask = true;
      await messenger.handlePlatformMessage(
        channel.name,
        const StandardMethodCodec().encodeMethodCall(
          const MethodCall('taskCenterRequested'),
        ),
        (_) {},
      );
      await tester.pumpAndSettle();
      expect(
        find.byType(SearchResultDetailPage, skipOffstage: false),
        findsNothing,
      );
      expect(find.byType(TaskCenterPage), findsOneWidget);

      await back(tester);
      expect(tester.state(find.byType(SearchPage)), same(search));
      expect(find.text('Retained search hit'), findsOneWidget);
      expect(
        api.paths.where(_searchHome.contains),
        unorderedEquals(_searchHome),
      );
      await back(tester);
      expect(find.byType(SearchPage), findsOneWidget);
      expect(find.text('Back to Search Home'), findsNothing);
      await back(tester);
      expect(find.byType(ShowcasePage), findsOneWidget);
    },
  );

  testWidgets(
    'Insights tag opens a never-visited Showcase with the filter on its first request',
    (tester) async {
      await start(tester);
      await select(tester, Icons.pie_chart_outline_rounded);
      api.defaultPage.complete('gallery');
      await tester.pumpAndSettle();
      expectOnlyMounted(InsightsPage);
      final tag = find.text('Drama (1)');
      await tester.scrollUntilVisible(
        tag,
        250,
        scrollable: find
            .descendant(
              of: find.byType(ListView),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await tester.tap(tag);
      await tester.pumpAndSettle();
      expect(find.byType(ShowcasePage), findsOneWidget);
      expect(
        api.requests
            .where((r) => r.path == _videos)
            .single
            .queryParameters['tag'],
        'Drama',
      );
      expect(find.text('Drama'), findsOneWidget);
    },
  );
}
