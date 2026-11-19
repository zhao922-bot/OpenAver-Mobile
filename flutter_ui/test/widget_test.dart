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

    // Preserves non-zero fallback videoCount even when detail API returns video_count: 0
    final merged = ActressProfile.fromJson(
      {'name': 'Sakura', 'video_count': 0, 'is_favorite': true},
      fallbackVideoCount: 7,
    );
    expect(merged.videoCount, 7);

    // Parses backend /api/actresses/library `names` list into aliases excluding primary_name
    final group = LibraryActressGroup.fromJson({
      'primary_name': 'Sakura',
      'names': ['Sakura', 'Saku', 'Sakura-Old'],
      'video_count': 7,
      'is_favorite': true,
    });
    expect(group.aliases, ['Saku', 'Sakura-Old']);
    expect(group.videoCount, 7);
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
        if (opts.path == '/api/wishlist' && opts.method == 'POST') {
          return _jsonResponse({'success': false, 'already_owned': true});
        }
        if (opts.path == '/api/wishlist') {
          return _jsonResponse([]);
        }
        if (opts.path == '/api/translate') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['force'], true);
          return _jsonResponse({'success': true, 'skipped': true, 'reason': 'already_target_language'});
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
    var focalSaved = false;
    var aiTagged = false;
    var rescraped = false;

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
        if (opts.path == '/api/actresses/Sakura') {
          if (!favoritedSakura) {
            return _jsonResponse({'error': 'not_found'}, statusCode: 404);
          }
          return _jsonResponse({
            'actress': {
              'name': 'Sakura',
              'aliases': ['Saku'],
              'photo_url': '',
              'photo_source': 'wiki',
              'video_count': 0,
              'is_favorite': true,
            },
            'is_favorite': true,
          });
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
              'video_count': 0,
              'is_favorite': true,
            },
          });
        }
        if (opts.path == '/api/showcase/video/detect-focal') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['path'], '/lib/ABC-001.mp4');
          return _jsonResponse({
            'success': true,
            'auto_focal': '0.3500,0.5000',
            'cover_path': 'file:///covers/ABC-001.jpg',
            'reason': '',
          });
        }
        if (opts.path == '/api/showcase/video/save-focal') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['path'], '/lib/ABC-001.mp4');
          expect(map['expected_cover_path'], 'file:///covers/ABC-001.jpg');
          focalSaved = true;
          return _jsonResponse({'success': true, 'auto_focal': map['focal']});
        }
        if (opts.path == '/api/ai/tags/videos') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['file_path'], '/lib/ABC-001.mp4');
          aiTagged = true;
          return _jsonResponse({'success': true, 'added': ['Solo'], 'user_tags': ['Keep', 'Solo']});
        }
        if (opts.path == '/api/rescrape/preview') {
          return _jsonResponse({
            'success': true,
            'number': 'ABC-001',
            'title': 'Fresh Title',
            'maker': 'S1',
            'date': '2025-02-01',
          });
        }
        if (opts.path == '/api/enrich-single') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['mode'], 'refresh_full');
          expect(map['write_cover'], true);
          expect(map['overwrite_existing'], true);
          expect(map['allow_number_change'], false);
          expect((map['metadata'] as Map).containsKey('success'), false);
          rescraped = true;
          return _jsonResponse({'success': true});
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

    // Pop back to ABC-001 detail, test Focal Crop Sheet, and tap Tag chip 'Drama'
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('Face / Crop Focus'),
      -200,
      scrollable: detailScrollable,
    );
    await tester.tap(find.text('Face / Crop Focus'));
    await tester.pumpAndSettle();
    expect(find.text('Save Focus'), findsOneWidget);
    await tester.tap(find.text('Save Focus'));
    await tester.pumpAndSettle();
    expect(focalSaved, true);

    await tester.tap(find.text('AI Tags'));
    await tester.pumpAndSettle();
    expect(aiTagged, true);

    await tester.tap(find.text('Rescrape'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Preview'));
    await tester.pumpAndSettle();
    expect(find.text('Fresh Title'), findsOneWidget);
    await tester.tap(find.text('Overwrite'));
    await tester.pumpAndSettle();
    expect(rescraped, true);

    await tester.scrollUntilVisible(
      find.text('Drama'),
      200,
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
    expect(find.text('Face / Crop Focus'), findsNothing);
    expect(find.text('View Videos (3)'), findsOneWidget);

    // Favorite & Change Photo flow (preserves video count 3!)
    await tester.tap(find.text('Favorite'));
    await tester.pumpAndSettle();
    expect(favoritedSakura, true);
    expect(find.text('View Videos (3)'), findsOneWidget);

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
            'maker_search_enabled': true,
            'makers': [
              {'maker': 'S1', 'total': 12},
              {'maker': 'HiddenMaker', 'total': 4},
            ],
            'hidden_keys': ['hiddenmaker'],
          });
        }
        if (opts.path == '/api/search/recent-actresses') {
          return _jsonResponse({'available': false});
        }
        if (opts.path == '/api/search/favorite-files') {
          return _jsonResponse({'files': []});
        }
        if (opts.path == '/api/wishlist' && opts.method == 'POST') {
          return _jsonResponse({'success': false, 'already_owned': true});
        }
        if (opts.path == '/api/wishlist') {
          return _jsonResponse([]);
        }
        if (opts.path == '/api/translate') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['force'], true);
          return _jsonResponse({'success': true, 'skipped': true, 'reason': 'already_target_language'});
        }
        if (opts.path == '/api/search/stream') {
          final offset = (opts.queryParameters['offset'] as num?)?.toInt() ?? 0;
          if (offset == 0) {
            return _sseResponse([
              'data: {"type":"result","has_more":true,"cursor":"cur-2","data":[{"number":"SSIS-001","title":"Search Hit","cover":"","source":"javbus","actors":["Yua"],"tags":["Solo"]}]}\n\n',
            ]);
          }
          expect(opts.queryParameters['cursor'], 'cur-2');
          return _sseResponse([
            'data: {"type":"result","has_more":false,"data":[{"number":"SSIS-002","title":"Page Two Hit","cover":"","source":"javbus","actors":["Yua"],"tags":["Solo"]}]}\n\n',
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
    expect(find.text('HiddenMaker (4)'), findsNothing);
    await tester.tap(find.text('S1 (12)'));
    await tester.pumpAndSettle();

    expect(find.text('SSIS-001'), findsOneWidget);
    expect(find.text('Back to Search Home'), findsOneWidget);
    expect(find.text('Load More Results'), findsOneWidget);
    await tester.tap(find.text('Load More Results'));
    await tester.pumpAndSettle();
    expect(find.text('SSIS-002'), findsOneWidget);

    // Tap result card -> opens SearchResultDetailPage
    await tester.tap(find.text('Search Hit'));
    await tester.pumpAndSettle();
    expect(find.byType(SearchResultDetailPage), findsOneWidget);

    // Bookmark rejected with already_owned should NOT turn bookmark icon filled
    await tester.tap(find.byIcon(Icons.bookmark_add_outlined));
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.bookmark_rounded), findsNothing);
    expect(find.text('Already in local library'), findsOneWidget);

    // Dismiss snackbar before tapping Translate chip, then verify force=true + skipped handling
    ScaffoldMessenger.of(tester.element(find.byType(SearchResultDetailPage))).hideCurrentSnackBar();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('AI Translate'));
    await tester.tap(find.text('AI Translate'));
    await tester.pumpAndSettle();
    expect(find.text('Already in target language'), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();

    // Tap Back to Search Home -> returns to Maker Releases screen!
    await tester.tap(find.text('Back to Search Home'));
    await tester.pumpAndSettle();
    expect(find.text('S1 (12)'), findsOneWidget);
  });

  testWidgets('ScannerPage, InsightsPage, and SettingsPage render populated and error states', (tester) async {
    var fixNumbersAppliedIds = <int>[];
    var aliasListRequested = false;
    var similarBackfillStarted = false;
    var metatubeConnected = false;
    var sourcesProbed = false;

    final mockApi = ApiClient(
      port: 8765,
      token: 't',
      httpClientAdapter: _MockAdapter((opts) async {
        if (opts.path == '/api/gallery/stats') {
          return _jsonResponse({'data': {'total': 42}});
        }
        if (opts.path == '/api/gallery/generate') {
          return _sseResponse([
            'data: {"type":"done","video_count":42,"stats":{"inserted":3,"updated":2,"deleted":1}}\n\n',
          ]);
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
              'metatube': {'enabled': true, 'url': 'https://mt.example', 'token': 'tok', 'allow_lan': false},
              'translate': {
                'enabled': true,
                'provider': 'openai',
                'openai': {'base_url': 'https://api.openai.com/v1', 'api_key': 'k', 'model': ''},
              },
              'focal_device': {'disabled': false},
              'ai_services': {
                'image_similar': {'enabled': true, 'provider': 'endpoint', 'url': 'http://127.0.0.1:9000'},
                'faces': {},
                'tags': {},
              },
            },
          });
        }
        if (opts.path == '/api/actress-aliases') {
          aliasListRequested = true;
          return _jsonResponse({
            'success': true,
            'groups': [
              {'primary_name': 'Sakura', 'aliases': ['Saku']},
            ],
          });
        }
        if (opts.path == '/api/collection/analysis') {
          return _jsonResponse({
            'total_videos': 42,
            'nfo_status': {'has_nfo': 40, 'missing_nfo': 2},
            'corrupted_numbers': {'total': 1, 'patterns': []},
            'japanese_tags': {'total': 5},
            'empty_array_fields': {'actresses': 1, 'tags': 2},
            'missing_fields': {'title': 0, 'maker': 3},
          });
        }
        if (opts.path == '/api/collection/fix-numbers/preview') {
          return _jsonResponse({
            'affected': [
              {'id': 99, 'old_number': 'ABC001-C', 'new_number': 'ABC-001'},
            ],
            'total': 1,
          });
        }
        if (opts.path == '/api/collection/fix-numbers/apply') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          fixNumbersAppliedIds = ((map['ids'] as List?) ?? const []).map((e) => (e as num).toInt()).toList();
          return _jsonResponse({'updated': fixNumbersAppliedIds.length, 'failed': 0});
        }
        if (opts.path == '/api/settings/metatube/status') {
          return _jsonResponse({'connected': metatubeConnected, 'providers': []});
        }
        if (opts.path == '/api/settings/metatube/connect') {
          metatubeConnected = true;
          return _jsonResponse({'success': true, 'provider_count': 5});
        }
        if (opts.path == '/api/sources/probe') {
          final map = Map<String, dynamic>.from(opts.data as Map);
          expect(map['source_ids'], ['javbus']);
          expect(map['proxy_scope'], 'dmm');
          sourcesProbed = true;
          return _jsonResponse({
            'results': {
              'javbus': {'state': 'ok', 'reason': 'ok', 'status': 200},
            },
          });
        }
        if (opts.path == '/api/ai/similar/status') {
          return _jsonResponse({'running': false, 'pending': 10, 'processed': 0, 'total': 10});
        }
        if (opts.path == '/api/ai/similar/index') {
          similarBackfillStarted = true;
          return _jsonResponse({'status': 'started'});
        }
        if (opts.path == '/api/openai/models') {
          return _jsonResponse({'success': true, 'models': ['deepseek-chat', 'qwen-plus']});
        }
        if (opts.path == '/api/openai/test') {
          return _jsonResponse({'success': true, 'translation': 'Test OK'});
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

    // Scanner: Scan Library formats done event stats cleanly
    await tester.tap(find.text('Scan Library'));
    await tester.pumpAndSettle();
    expect(find.text('42 videos (+3 / ~2 / -1)'), findsOneWidget);

    // Scanner: Collection Analysis -> Fix Corrupted Numbers (uses real backend schema + affected + ids)
    final scannerScroll = find.byType(Scrollable).first;
    await tester.scrollUntilVisible(find.text('Library Health & Number Fix').first, 250, scrollable: scannerScroll);
    await tester.tap(find.text('Library Health & Number Fix').first);
    await tester.pumpAndSettle();
    expect(find.text('Total Videos'), findsOneWidget);
    expect(find.text('Missing NFO'), findsOneWidget);
    expect(find.text('Corrupted Numbers'), findsOneWidget);
    expect(find.text('Missing field: maker'), findsOneWidget);
    await tester.tap(find.text('Scan & Fix Corrupted Numbers'));
    await tester.pumpAndSettle();
    expect(find.text('ABC001-C -> ABC-001'), findsOneWidget);
    await tester.tap(find.text('Apply'));
    await tester.pumpAndSettle();
    expect(fixNumbersAppliedIds, [99]);

    // Scanner: Actress Aliases uses plural /api/actress-aliases
    await tester.scrollUntilVisible(find.text('Actress Aliases').first, 250, scrollable: scannerScroll);
    await tester.tap(find.text('Actress Aliases').first);
    await tester.pumpAndSettle();
    expect(aliasListRequested, true);
    expect(find.text('Saku'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.close_rounded));
    await tester.pumpAndSettle();

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

    // AI Settings section: presets, model quick-select, and connection test
    await tester.tap(find.text('AI Services & Face Focus').first);
    await tester.pumpAndSettle();
    expect(find.text('DeepSeek'), findsOneWidget);
    await tester.tap(find.text('Fetch Models'));
    await tester.pumpAndSettle();
    expect(find.text('qwen-plus'), findsOneWidget);
    await tester.tap(find.text('qwen-plus'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Test Translate'));
    await tester.pumpAndSettle();
    expect(find.text('Connection succeeded: Test OK'), findsWidgets);

    // AI BackfillBar start button
    final settingsScroll = find.byType(Scrollable).last;
    await tester.scrollUntilVisible(find.text('Start Backfill').first, 250, scrollable: settingsScroll);
    await tester.tap(find.text('Start Backfill').first);
    await tester.pumpAndSettle();
    expect(similarBackfillStarted, true);

    // Metatube Connect + Source Probe (Map response) + Pending Scrape Folder typing
    await tester.tap(find.text('Search, Proxy & Sources').first);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Pending Scrape Folder'),
      '/storage/downloads',
    );
    await tester.pump();
    expect(find.text('/storage/downloads'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Test Sources').first, 250, scrollable: settingsScroll);
    await tester.tap(find.text('Test Sources').first);
    await tester.pumpAndSettle();
    expect(sourcesProbed, true);
    expect(find.text('OK'), findsWidgets);
    await tester.scrollUntilVisible(find.text('Connect').first, 250, scrollable: settingsScroll);
    await tester.tap(find.text('Connect').first);
    await tester.pumpAndSettle();
    expect(metatubeConnected, true);
  });
}

class _FixedLocaleNotifier extends LocaleNotifier {
  _FixedLocaleNotifier(this._fixed);
  final String _fixed;

  @override
  String build() => _fixed;
}
