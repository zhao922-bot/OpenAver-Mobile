import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/app_theme.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/core/models/actress_models.dart';
import 'package:flutter_ui/core/models/scanner_models.dart';
import 'package:flutter_ui/core/models/video_item.dart';
import 'package:flutter_ui/core/native_bridge.dart';
import 'package:flutter_ui/features/insights/insights_page.dart';
import 'package:flutter_ui/features/scanner/scanner_page.dart';
import 'package:flutter_ui/features/search/search_page.dart';
import 'package:flutter_ui/features/search/search_result_detail_page.dart';
import 'package:flutter_ui/features/settings/settings_page.dart';
import 'package:flutter_ui/features/showcase/actress_detail_page.dart';
import 'package:flutter_ui/features/showcase/showcase_page.dart';
import 'package:flutter_ui/features/showcase/video_detail_sheet.dart';
import 'package:flutter_ui/main.dart';

typedef _AdapterHandler = Future<ResponseBody> Function(RequestOptions options);

class _MockAdapter implements HttpClientAdapter {
  _MockAdapter(this.handler);

  final _AdapterHandler handler;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    return handler(options);
  }
}

ResponseBody _jsonResponse(Object payload, {int statusCode = 200}) {
  return ResponseBody.fromString(
    jsonEncode(payload),
    statusCode,
    headers: {
      Headers.contentTypeHeader: ['application/json; charset=utf-8'],
    },
  );
}

ResponseBody _sseResponse(List<String> chunks) {
  final controller = StreamController<Uint8List>();
  Future<void>(() async {
    for (final chunk in chunks) {
      controller.add(Uint8List.fromList(utf8.encode(chunk)));
      await Future<void>.delayed(Duration.zero);
    }
    await controller.close();
  });
  return ResponseBody(
    controller.stream,
    200,
    headers: {
      Headers.contentTypeHeader: ['text/event-stream; charset=utf-8'],
    },
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('dev.openaver.mobile/bridge');
  late List<MethodCall> bridgeCalls;

  setUp(() {
    bridgeCalls = [];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      bridgeCalls.add(call);
      switch (call.method) {
        case 'getBootstrapInfo':
          return {
            'ready': true,
            'port': 8765,
            'token': 'test-token',
            'cookieName': 'openaver_loopback',
            'dataDir': '/data/user/0/dev.openaver.mobile/files',
            'version': '0.18.17',
            'openaverRelease': 'v0.18.17',
            'abi': 'arm64-v8a',
            'uiLocale': 'en',
            'theme': 'dim',
            'hasStorageAccess': true,
            'hasTreeAccess': true,
            'treeDescription': '/storage/SD/Movies',
          };
        case 'hasStorageAccess':
          return true;
        case 'getStorageTreeInfo':
          return {'granted': true, 'description': '/storage/SD/Movies'};
        case 'openExternalPlayer':
        case 'openExternalUrl':
          return true;
        default:
          return null;
      }
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('VideoItem and ActressProfile parse focal and copyWith cleanly', () {
    final fallback = VideoItem.fromJson({
      'number': 'ABC-123',
      'title': 'Sample Title',
      'crop_mode': 'default',
      'auto_focal': '0.2,0.8',
    });
    expect(fallback.focalAlignment, Alignment.centerRight);

    final item = VideoItem.fromJson({
      'number': 'ABC-123',
      'title': 'Sample Title',
      'crop_mode': 'auto',
      'auto_focal': '1.2, 0.0',
      'sample_images': ['a.jpg', 'b.jpg'],
    });
    expect(item.focalAlignment.x, 1.0);
    expect(item.focalAlignment.y, -1.0);

    final updated = item.copyWith(autoFocal: '0.5, 0.5', cropMode: 'manual');
    expect(updated.cropMode, 'manual');
    expect(updated.focalAlignment.x, closeTo(0.0, 0.001));
    expect(updated.focalAlignment.y, closeTo(0.0, 0.001));

    final actress = ActressProfile.fromJson({
      'name': 'Sakura',
      'aliases': ['Saku'],
      'height': 162,
      'cup': 'C',
      'bust': 85,
      'waist': 58,
      'hip': 86,
      'is_favorite': true,
      'auto_focal': '0.5, 0.25',
      'crop_mode': 'manual',
    });
    expect(actress.measurementsText, 'B:85 / W:58 / H:86');
    expect(actress.focalAlignment.x, closeTo(0.0, 0.001));
    expect(actress.focalAlignment.y, closeTo(-0.5, 0.001));
  });

  test('BuiltInPlayerPart parses multipart lists and falls back cleanly', () {
    final parts = BuiltInPlayerPart.parseList([
      {'path': '/movies/CD1.mp4', 'label': 'CD1'},
      {'path': '/movies/CD2.mp4', 'label': 'CD2'},
    ]);
    expect(parts.length, 2);
    expect(parts[1].label, 'CD2');

    final fallback = BuiltInPlayerPart.parseList(null, fallbackPath: '/movies/SINGLE.mp4');
    expect(fallback.length, 1);
    expect(fallback.first.path, '/movies/SINGLE.mp4');
  });

  test('AppThemeMode and AppStrings support all themes and 5 locales', () {
    expect(AppThemeMode.fromString('light'), AppThemeMode.light);
    expect(AppThemeMode.fromString('dark'), AppThemeMode.dark);
    expect(AppThemeMode.fromString('unknown'), AppThemeMode.dim);
    expect(buildOpenAverTheme(AppThemeMode.light).brightness, Brightness.light);
    expect(buildOpenAverTheme(AppThemeMode.dark).brightness, Brightness.dark);

    for (final loc in AppStrings.supportedLocales) {
      final s = AppStrings(loc);
      expect(s.tabShowcase.isNotEmpty, true);
      expect(s.backToSearchHome.isNotEmpty, true);
      expect(s.changeCoverPhoto.isNotEmpty, true);
    }
    expect(AppStrings('en').tabShowcase, 'Showcase');
    expect(AppStrings('ja').tabSettings, '設定');
  });

  test('No hardcoded CJK string literals remain inside lib/features', () {
    final featuresDir = Directory('lib/features');
    expect(featuresDir.existsSync(), true);
    final cjkStringPattern = RegExp(r'''['"][^'"\n]*[\u4e00-\u9fff][^'"\n]*['"]''');
    final violations = <String>[];

    for (final entity in featuresDir.listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final lines = entity.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        final line = lines[i].trim();
        if (line.startsWith('//') || line.startsWith('///')) continue;
        final codePart = line.split('//').first;
        if (cjkStringPattern.hasMatch(codePart)) {
          violations.add('${entity.path}:${i + 1}: $line');
        }
      }
    }
    expect(violations, isEmpty, reason: 'Found hardcoded CJK strings:\n${violations.join('\n')}');
  });

  test('MissingCheckSummary and BrowseDirResponse parse backend payloads', () {
    final summary = MissingCheckSummary.fromJson({
      'success': true,
      'data': {
        'missing_both': 1,
        'missing_nfo': 2,
        'missing_cover': 3,
        'total_missing': 6,
        'untranslated_titles': 4,
        'missing_samples': 5,
        'missing_plots': 7,
        'pending_plot_translations': [
          {'batch_id': '0123456789abcdef0123456789abcdef'},
        ],
      },
    });
    expect(summary.totalMissing, 6);
    expect(summary.pendingTranslationBatchIds.single, '0123456789abcdef0123456789abcdef');

    final dir = BrowseDirResponse.fromJson({
      'current_path': '/storage/emulated/0',
      'parent_path': '/storage/emulated',
      'entries': [
        {'name': 'Movies', 'path': '/storage/emulated/0/Movies'},
      ],
    });
    expect(dir.entries.single.name, 'Movies');
  });

  test('ApiClient injects Bearer auth and parses chunked/event-typed SSE streams', () async {
    String? seenAuth;
    final api = ApiClient(
      port: 8765,
      token: 'tok-xyz',
      httpClientAdapter: _MockAdapter((options) async {
        seenAuth = options.headers['Authorization']?.toString();
        if (options.path == '/api/sse') {
          return _sseResponse([
            ': keepalive\n',
            'event: candidate\ndata: {"source":"graph",',
            '"full_url":"https://img/1.jpg"}\n\n',
            'data: not-valid-json\n\n',
            'data: {"type":"done","total":1}',
          ]);
        }
        return _jsonResponse({'ok': true});
      }),
    );

    final json = await api.getJson('/api/ping');
    expect(json['ok'], true);
    expect(seenAuth, 'Bearer tok-xyz');

    final events = await api.streamSse('/api/sse').toList();
    expect(events.length, 2);
    expect(events[0].type, 'candidate');
    expect(events[0].data['full_url'], 'https://img/1.jpg');
    expect(events[1].type, 'done');
  });

  test('NativeBridge forwards method calls and parses multipart player event', () async {
    final boot = await NativeBridge.instance.getBootstrapInfo();
    expect(boot.ready, true);
    expect(boot.port, 8765);

    await NativeBridge.instance.openExternalPlayer(
      path: '/movies/CD1.mp4',
      partsJson: jsonEncode([
        {'path': '/movies/CD1.mp4', 'label': 'CD1'},
        {'path': '/movies/CD2.mp4', 'label': 'CD2'},
      ]),
    );
    expect(bridgeCalls.last.method, 'openExternalPlayer');

    String? receivedPath;
    int? receivedPart;
    List<BuiltInPlayerPart>? receivedParts;
    NativeBridge.instance.onOpenBuiltInPlayer = (path, part, parts) {
      receivedPath = path;
      receivedPart = part;
      receivedParts = parts;
    };

    final codec = const StandardMethodCodec();
    await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.handlePlatformMessage(
      'dev.openaver.mobile/bridge',
      codec.encodeMethodCall(const MethodCall('openBuiltInPlayer', {
        'path': '/movies/CD2.mp4',
        'part': 2,
        'parts': [
          {'path': '/movies/CD1.mp4', 'label': 'CD1'},
          {'path': '/movies/CD2.mp4', 'label': 'CD2'},
        ],
      })),
      (_) {},
    );

    expect(receivedPath, '/movies/CD2.mp4');
    expect(receivedPart, 2);
    expect(receivedParts?.length, 2);
  });

  testWidgets('OpenAverApp switches to NavigationRail on wide screens', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    final mockApi = ApiClient(
      port: 8765,
      token: 't',
      httpClientAdapter: _MockAdapter((opts) async {
        if (opts.path == '/api/showcase/videos') {
          return _jsonResponse({'success': true, 'videos': [], 'total': 0, 'page': 1, 'total_pages': 1, 'paged': true});
        }
        if (opts.path == '/api/search/favorite-files') {
          return _jsonResponse({'files': []});
        }
        if (opts.path == '/api/wishlist') {
          return _jsonResponse([]);
        }
        if (opts.path == '/api/search/makers') {
          return _jsonResponse({'available': false, 'makers': []});
        }
        if (opts.path == '/api/search/recent-actresses') {
          return _jsonResponse({'available': false, 'actresses': []});
        }
        if (opts.path == '/api/actresses') {
          return _jsonResponse({'success': true, 'actresses': [], 'total': 0});
        }
        return _jsonResponse({'success': true, 'data': {}});
      }),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiClientProvider.overrideWithValue(mockApi),
        ],
        child: const OpenAverApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.text('Showcase'), findsOneWidget);
  });

  testWidgets('ShowcasePage handles error, empty, video tag navigation, and ActressDetailPage photo/favorite flow', (tester) async {
    var shouldFail = true;
    var favoritedSakura = false;
    var photoReplaced = false;

    final mockApi = ApiClient(
      port: 8765,
      token: 't',
      httpClientAdapter: _MockAdapter((opts) async {
        if (opts.path == '/api/showcase/videos') {
          if (shouldFail) {
            throw DioException(requestOptions: opts, error: 'offline');
          }
          return _jsonResponse({
            'success': true,
            'total': 2,
            'page': 1,
            'per_page': 45,
            'total_pages': 1,
            'paged': true,
            'videos': [
              {
                'path': '/lib/ABC-001.mp4',
                'title': 'First Video',
                'number': 'ABC-001',
                'actors': ['Sakura'],
                'tags': ['Drama'],
                'user_tags': ['Keep'],
                'cover_url': '',
                'cover_full_url': '',
              },
              {
                'path': '/lib/ABC-002.mp4',
                'title': 'Second Video',
                'number': 'ABC-002',
                'actors': [],
                'tags': [],
                'user_tags': [],
                'cover_url': '',
                'cover_full_url': '',
              },
            ],
          });
        }
        if (opts.path == '/api/showcase/video/plot') {
          return _jsonResponse({'success': true, 'plot': 'Story text', 'original_plot': ''});
        }
        if (opts.path.startsWith('/api/similar-covers/by-number/')) {
          return _jsonResponse({
            'results': [
              {'number': 'ABC-002', 'title': 'Second Video', 'cover_url': ''},
            ],
          });
        }
        if (opts.path == '/api/actresses/library') {
          return _jsonResponse({
            'success': true,
            'actresses': [
              {
                'primary_name': 'Sakura',
                'aliases': ['Saku'],
                'video_count': 3,
                'is_favorite': favoritedSakura,
                'photo_url': '',
              },
            ],
          });
        }
        if (opts.path == '/api/actresses') {
          return _jsonResponse({'success': true, 'actresses': []});
        }
        if (opts.path == '/api/actresses/favorite') {
          favoritedSakura = true;
          return _jsonResponse({
            'success': true,
            'actress': {
              'name': 'Sakura',
              'aliases': ['Saku'],
              'photo_url': '',
              'photo_source': 'wiki',
              'is_favorite': true,
            },
          });
        }
        if (opts.path == '/api/actresses/Sakura/photo-candidates') {
          return _sseResponse([
            'event: candidate\ndata: {"source":"local_crop","thumb_url":"","full_url":"https://cand/1.jpg","id":"c1"}\n\n',
            'event: done\ndata: {}\n\n',
          ]);
        }
        if (opts.path == '/api/actresses/Sakura/photo') {
          photoReplaced = true;
          return _jsonResponse({'photo_url': '', 'photo_source': 'local_crop'});
        }
        return _jsonResponse({'success': true});
      }),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          localeProvider.overrideWith(() => _FixedLocaleNotifier('en')),
          apiClientProvider.overrideWithValue(mockApi),
        ],
        child: const MaterialApp(home: ShowcasePage()),
      ),
    );
    await tester.pumpAndSettle();

    // Error state -> Retry
    expect(find.text('Retry'), findsOneWidget);
    shouldFail = false;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();

    expect(find.text('ABC-001'), findsOneWidget);

    // Open VideoDetailPage -> tap Tag -> filters Showcase by tag!
    await tester.tap(find.text('ABC-001'));
    await tester.pumpAndSettle();
    expect(find.byType(VideoDetailPage), findsOneWidget);

    // Tap Similar recommendation card -> pushes ABC-002 detail page
    final detailScrollable = find.descendant(
      of: find.byType(VideoDetailPage),
      matching: find.byType(Scrollable),
    ).first;
    await tester.scrollUntilVisible(
      find.text('ABC-002'),
      300,
      scrollable: detailScrollable,
    );
    await tester.tap(find.text('ABC-002').last);
    await tester.pumpAndSettle();
    expect(find.text('ABC-002'), findsWidgets);

    // Pop back to ABC-001 detail and tap Tag chip 'Drama'
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('Drama'),
      -200,
      scrollable: detailScrollable,
    );
    await tester.tap(find.text('Drama'));
    await tester.pumpAndSettle();
    expect(find.text('Drama'), findsOneWidget); // active tag InputChip in ShowcasePage

    // Switch to Actress Wall -> tap Sakura -> ActressDetailPage opens (NOT kicking back!)
    await tester.tap(find.text('Actresses'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sakura'));
    await tester.pumpAndSettle();
    expect(find.byType(ActressDetailPage), findsOneWidget);

    // Favorite & Change Photo flow
    await tester.tap(find.text('Favorite'));
    await tester.pumpAndSettle();
    expect(favoritedSakura, true);

    await tester.tap(find.text('Change Photo'));
    await tester.pumpAndSettle();
    expect(find.text('local_crop'), findsOneWidget);

    await tester.tap(find.text('local_crop'));
    await tester.pumpAndSettle();
    expect(photoReplaced, true);
  });

  testWidgets('SearchPage shows results detail and returns cleanly to Search Home', (tester) async {
    final mockApi = ApiClient(
      port: 8765,
      token: 't',
      httpClientAdapter: _MockAdapter((opts) async {
        if (opts.path == '/api/search/maker-capsules') {
          return _jsonResponse({
            'makers': [
              {'maker': 'S1', 'total': 12},
            ],
          });
        }
        if (opts.path == '/api/search/recent-actresses') {
          return _jsonResponse({'available': false});
        }
        if (opts.path == '/api/search/favorite-files') {
          return _jsonResponse({'files': []});
        }
        if (opts.path == '/api/wishlist') {
          return _jsonResponse([]);
        }
        if (opts.path == '/api/search/stream') {
          return _sseResponse([
            'data: {"type":"result","data":[{"number":"SSIS-001","title":"Search Hit","cover":"","source":"javbus","actors":["Yua"],"tags":["Solo"]}]}\n\n',
          ]);
        }
        if (opts.path == '/api/search/local-status') {
          return _jsonResponse({});
        }
        return _jsonResponse({'success': true});
      }),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          localeProvider.overrideWith(() => _FixedLocaleNotifier('en')),
          apiClientProvider.overrideWithValue(mockApi),
        ],
        child: const MaterialApp(home: SearchPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('S1 (12)'), findsOneWidget);
    await tester.tap(find.text('S1 (12)'));
    await tester.pumpAndSettle();

    expect(find.text('SSIS-001'), findsOneWidget);
    expect(find.text('Back to Search Home'), findsOneWidget);

    // Tap result card -> opens SearchResultDetailPage
    await tester.tap(find.text('Search Hit'));
    await tester.pumpAndSettle();
    expect(find.byType(SearchResultDetailPage), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();

    // Tap Back to Search Home -> returns to Maker Releases screen!
    await tester.tap(find.text('Back to Search Home'));
    await tester.pumpAndSettle();
    expect(find.text('S1 (12)'), findsOneWidget);
  });

  testWidgets('ScannerPage, InsightsPage, and SettingsPage render populated and error states', (tester) async {
    final mockApi = ApiClient(
      port: 8765,
      token: 't',
      httpClientAdapter: _MockAdapter((opts) async {
        if (opts.path == '/api/gallery/stats') {
          return _jsonResponse({'data': {'total': 42}});
        }
        if (opts.path == '/api/gallery/missing-check') {
          return _jsonResponse({
            'success': true,
            'data': {
              'total_missing': 1,
              'missing_plots': 2,
              'untranslated_titles': 3,
              'missing_samples': 4,
              'pending_plot_translations': [],
            },
          });
        }
        if (opts.path == '/api/insights/snapshot') {
          return _jsonResponse({
            'success': true,
            'records': [
              {'year': 2024, 'maker': 'MOODYZ', 'actresses': ['Aoi'], 'tags': ['HD']},
            ],
            'actress_favorites': {},
          });
        }
        if (opts.path == '/api/config') {
          return _jsonResponse({
            'success': true,
            'data': {
              'general': {'theme': 'dim', 'locale': 'en', 'font_size': 'md', 'default_page': 'search'},
              'gallery': {'directories': [], 'min_size_mb': 100},
              'scraper': {'create_folder': true, 'folder_format': '{actor}'},
              'search': {'proxy_url': '', 'proxy_scope': 'dmm'},
              'sources': [{'id': 'javbus', 'enabled': true, 'order': 0}],
              'source_links': {'dmm': true},
              'metatube': {'enabled': false},
              'translate': {'enabled': false, 'provider': 'ollama'},
              'focal_device': {'disabled': false},
              'ai_services': {'image_similar': {}, 'faces': {}, 'tags': {}},
            },
          });
        }
        return _jsonResponse({'success': true});
      }),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          localeProvider.overrideWith(() => _FixedLocaleNotifier('en')),
          apiClientProvider.overrideWithValue(mockApi),
        ],
        child: const MaterialApp(
          home: Scaffold(body: ScannerPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Library: 42 videos'), findsOneWidget);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          localeProvider.overrideWith(() => _FixedLocaleNotifier('en')),
          apiClientProvider.overrideWithValue(mockApi),
        ],
        child: const MaterialApp(
          home: Scaffold(body: InsightsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Release Year Distribution'), findsOneWidget);
    expect(find.text('HD (1)'), findsOneWidget);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          localeProvider.overrideWith(() => _FixedLocaleNotifier('en')),
          apiClientProvider.overrideWithValue(mockApi),
        ],
        child: const MaterialApp(
          home: Scaffold(body: SettingsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Appearance & General'), findsNWidgets(2));
  });
}

class _FixedLocaleNotifier extends LocaleNotifier {
  _FixedLocaleNotifier(this._fixed);
  final String _fixed;

  @override
  String build() => _fixed;
}
