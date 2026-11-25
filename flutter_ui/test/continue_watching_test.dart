import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/features/player/builtin_player_page.dart';
import 'package:flutter_ui/features/showcase/showcase_page.dart';

const _disc1 = 'file:///library/Film%20CD1.mp4';
const _disc2 = 'file:///library/Film%20CD2.mp4';
const _disc3 = 'file:///library/Film%20CD3.mp4';
const _title = 'The saved film';
const _latest = {
  'path': _disc2,
  'title': _title,
  'partLabel': 'CD2',
  'partIndex': 1,
  'milliseconds': 65000,
  'revision': 12,
};
const _heading = 'Continue Watching';
const _remove = 'Remove from Continue Watching';

Map<String, dynamic> _lookup({bool reordered = false}) => {
  'success': true,
  'video': {
    'title': _title,
    'path': _disc1,
    'part_paths': reordered ? [_disc1, _disc3, _disc2] : [_disc1, _disc2],
    'part_tokens': reordered ? ['CD1', 'CD3', 'CD2'] : ['CD1', 'CD2'],
  },
};

class _Library implements HttpClientAdapter {
  final queries = <Map<String, dynamic>>[];
  FutureOr<Map<String, dynamic>> Function() lookup = () => _lookup();

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final Map<String, dynamic> body;
    switch (options.path) {
      case '/api/showcase/videos':
        body = {'success': true, 'videos': []};
      case '/api/showcase/video/lookup':
        queries.add(Map.of(options.queryParameters));
        body = await lookup();
      default:
        throw StateError('Unexpected endpoint ${options.path}');
    }
    return ResponseBody.fromString(
      jsonEncode(body),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _EnglishLocale extends LocaleNotifier {
  @override
  String build() => 'en';
}

class _Playback {
  Map<String, Object>? latest = _latest;
  final calls = <MethodCall>[];

  void install() {
    const channel = MethodChannel('dev.openaver.mobile/bridge');
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      switch (call.method) {
        case 'readLatestPlayback':
          return latest;
        case 'removeLatestPlayback':
          final args = call.arguments as Map;
          if (latest == null ||
              args['path'] != latest!['path'] ||
              args['revision'] != latest!['revision']) {
            return false;
          }
          latest = null;
          return true;
        default:
          throw MissingPluginException(call.method);
      }
    });
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));
  }
}

class _Routes extends NavigatorObserver {
  final pushed = <Route<dynamic>>[];

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    if (previousRoute != null) pushed.add(route);
  }
}

Future<void> _pump(
  WidgetTester tester,
  _Library library,
  _Playback playback, {
  _Routes? observer,
}) async {
  playback.install();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        localeProvider.overrideWith(_EnglishLocale.new),
        apiClientProvider.overrideWithValue(
          ApiClient(port: 8765, token: 'test', httpClientAdapter: library),
        ),
      ],
      child: MaterialApp(
        home: const ShowcasePage(),
        navigatorObservers: [?observer],
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('empty history skips the library lookup', (tester) async {
    final library = _Library();
    final playback = _Playback()..latest = null;
    await _pump(tester, library, playback);
    expect(
      playback.calls.map((call) => call.method),
      contains('readLatestPlayback'),
    );
    expect(find.text(_heading), findsNothing);
    expect(library.queries, isEmpty);
  });

  testWidgets('saved metadata stays hidden until its exact path is in scope', (
    tester,
  ) async {
    final result = Completer<Map<String, dynamic>>();
    final library = _Library()..lookup = () => result.future;
    await _pump(tester, library, _Playback());
    expect(library.queries, [
      {'path': _disc2},
    ]);
    expect(find.text(_heading), findsNothing);
    expect(find.text(_title), findsNothing);

    // A same-title result for another file cannot authorize the saved path.
    result.complete({
      'success': true,
      'video': {'path': _disc1, 'title': _title},
    });
    await tester.pumpAndSettle();
    expect(find.text(_heading), findsNothing);
    expect(find.text(_title), findsNothing);
    expect(find.byTooltip(_remove), findsNothing);
  });

  testWidgets('resume uses the saved path in the current playlist order', (
    tester,
  ) async {
    final library = _Library();
    final routes = _Routes();
    await _pump(tester, library, _Playback(), observer: routes);
    expect(find.text(_title), findsOneWidget);
    expect(find.text('CD2 · 1:05'), findsOneWidget);

    library.lookup = () => _lookup(reordered: true);
    await tester.tap(find.text(_heading));
    // Flush the lookup and push without building the native player on a frame.
    await tester.idle();
    final route = routes.pushed.single as MaterialPageRoute<void>;
    final player =
        route.builder(tester.element(find.byType(ShowcasePage)))
            as BuiltInPlayerPage;
    routes.navigator!.removeRoute(route);
    await tester.pumpAndSettle();
    expect(player.title, _title);
    expect(player.partPaths, [_disc1, _disc3, _disc2]);
    expect(player.partTokens, ['CD1', 'CD3', 'CD2']);
    expect(player.initialPartIndex, 2);
    expect(library.queries.length, greaterThanOrEqualTo(2));
    expect(library.queries, everyElement({'path': _disc2}));
  });

  testWidgets(
    'scope revoked before tap hides the card and keeps Showcase open',
    (tester) async {
      final library = _Library();
      final routes = _Routes();
      await _pump(tester, library, _Playback(), observer: routes);
      library.lookup = () => {'success': false, 'video': null};
      await tester.tap(find.text(_heading));
      await tester.pumpAndSettle();
      expect(library.queries, [
        {'path': _disc2},
        {'path': _disc2},
      ]);
      expect(routes.pushed, isEmpty);
      expect(find.text(_heading), findsNothing);
      expect(find.text(_title), findsNothing);
    },
  );

  testWidgets(
    'remove sends the displayed revision and reloads without changing bookmarks',
    (tester) async {
      final playback = _Playback();
      await _pump(tester, _Library(), playback);
      playback.calls.clear();
      await tester.tap(find.byTooltip(_remove));
      await tester.pumpAndSettle();
      expect(playback.calls.map((call) => call.method), [
        'removeLatestPlayback',
        'readLatestPlayback',
      ]);
      expect(playback.calls.first.arguments, {'path': _disc2, 'revision': 12});
      expect(find.text(_heading), findsNothing);
    },
  );

  testWidgets('removing an outdated card preserves newer progress', (
    tester,
  ) async {
    final playback = _Playback();
    await _pump(tester, _Library(), playback);
    expect(find.text('CD2 · 1:05'), findsOneWidget);

    playback.latest = {..._latest, 'milliseconds': 127000, 'revision': 13};
    playback.calls.clear();
    await tester.tap(find.byTooltip(_remove));
    await tester.pumpAndSettle();

    expect(playback.calls.map((call) => call.method), [
      'removeLatestPlayback',
      'readLatestPlayback',
    ]);
    expect(playback.calls.first.arguments, {'path': _disc2, 'revision': 12});
    expect(find.text(_heading), findsOneWidget);
    expect(find.text('CD2 · 2:07'), findsOneWidget);
    expect(find.text('CD2 · 1:05'), findsNothing);
  });

  testWidgets('returning to Showcase displays newly saved progress', (
    tester,
  ) async {
    final playback = _Playback()..latest = null;
    final routes = _Routes();
    await _pump(tester, _Library(), playback, observer: routes);
    expect(find.text(_heading), findsNothing);
    unawaited(
      routes.navigator!.push<void>(
        MaterialPageRoute<void>(builder: (_) => const Scaffold()),
      ),
    );
    await tester.pumpAndSettle();
    playback.latest = _latest;
    routes.navigator!.pop();
    await tester.pumpAndSettle();
    expect(find.text(_title), findsOneWidget);
    expect(find.text('CD2 · 1:05'), findsOneWidget);
  });
}
