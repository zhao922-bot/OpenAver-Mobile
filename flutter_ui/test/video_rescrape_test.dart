import 'dart:async';
import 'dart:convert';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/core/models/video_item.dart';
import 'package:flutter_ui/features/showcase/video_detail_sheet.dart';

const _path = 'content://library/document/Movies%2FABC%20%2302.mp4';
const _neighbor = '/other/ABC.mp4';
const _catalog = '/api/gallery/backfill-elements/sources';
const _rescrape = '/api/gallery/rescrape-elements';
const _lookup = '/api/showcase/video';
const _plot = '/api/showcase/video/plot';
const _video = {
  'path': _path,
  'number': 'ABC',
  'title': 'Current video',
  'tags': ['Existing tag'],
};

class _ImageCache extends Fake implements BaseCacheManager {
  final removed = <String>[];

  @override
  Future<void> removeFile(String key) async => removed.add(key);

  @override
  Stream<FileResponse> getFileStream(
    String url, {
    String? key,
    Map<String, String>? headers,
    bool withProgress = false,
  }) => const Stream.empty();
}

class _DetailServer implements HttpClientAdapter {
  _DetailServer(this.video);
  final Map<String, dynamic> video;
  final requests = <RequestOptions>[];
  final stream = StreamController<Uint8List>();
  final updated = <VideoItem>[];
  Map<String, dynamic> get fresh => {
    ...video,
    'tags': ['Replacement tag'],
  };
  bool wroteMetadata = false;

  Iterable<RequestOptions> calls(String path) =>
      requests.where((r) => r.path == path);
  Iterable<RequestOptions> get writes =>
      requests.where((r) => r.method != 'GET');

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (options.path == _rescrape) {
      return ResponseBody(
        stream.stream,
        200,
        headers: {
          Headers.contentTypeHeader: ['text/event-stream'],
        },
      );
    }
    final result = switch (options.path) {
      _catalog => {
        'success': true,
        'sources': {
          'cover': [
            {'id': 'javbus', 'label': 'JavBus'},
          ],
          'plot': [
            {'id': 'dmm', 'label': 'DMM'},
          ],
          'samples': [
            {'id': 'javdb', 'label': 'JavDB'},
          ],
          'tags': [
            {'id': 'jable', 'label': 'Jable'},
          ],
        },
      },
      _plot => {
        'success': true,
        'plot': wroteMetadata ? 'Replacement plot' : 'Existing plot',
      },
      _lookup => {'success': true, 'video': wroteMetadata ? fresh : video},
      '/api/similar-covers/by-number/ABC' => {'results': []},
      _ => throw StateError(
        'Unexpected request ${options.method} ${options.path}',
      ),
    };
    return ResponseBody.fromString(
      jsonEncode(result),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  void event(Map<String, dynamic> value) {
    stream.add(
      Uint8List.fromList(utf8.encode('data: ${jsonEncode(value)}\n\n')),
    );
  }

  void finish({
    required int success,
    required int failed,
    required Map<String, int> filled,
    List<Map<String, String>> failures = const [],
  }) {
    event({
      'type': 'done',
      'summary': {
        'total': 1,
        'success': success,
        'failed': failed,
        'skipped': 0,
        'fields_filled': filled,
        'failed_items': failures,
      },
    });
    unawaited(stream.close());
  }

  @override
  void close({bool force = false}) {}
}

Future<_DetailServer> _detail(
  WidgetTester tester, {
  Map<String, dynamic> video = _video,
}) async {
  final server = _DetailServer(video);
  final api = ApiClient(port: 8765, token: 'test', httpClientAdapter: server);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        stringsProvider.overrideWithValue(AppStrings('en')),
      ],
      child: MaterialApp(
        home: VideoDetailPage(
          videos: [
            VideoItem.fromJson({
              ..._video,
              'path': _neighbor,
              'title': 'Other copy',
            }),
            VideoItem.fromJson(video),
          ],
          initialIndex: 1,
          onVideoUpdated: server.updated.add,
          onSelectActress: (_) {},
          onVideoDeleted: (_) {},
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return server;
}

final _confirm = find.widgetWithText(FilledButton, 'Replace Selected Fields');

Future<void> _open(WidgetTester tester) async {
  final chip = find.widgetWithText(ActionChip, 'Rescrape');
  await tester.ensureVisible(chip);
  await tester.tap(chip);
  await tester.pumpAndSettle();
}

Future<void> _select(WidgetTester tester, String field, String label) async {
  final dropdown = find.byKey(ValueKey(field));
  await tester.ensureVisible(dropdown);
  await tester.tap(dropdown);
  await tester.pumpAndSettle();
  await tester.tap(find.text(label).hitTestable().last);
  await tester.pumpAndSettle();
}

Future<void> _submit(WidgetTester tester, {bool doubleTap = false}) async {
  await tester.ensureVisible(_confirm);
  final submit = tester.widget<FilledButton>(_confirm).onPressed!;
  await tester.tap(_confirm);
  if (doubleTap) submit();
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  await tester.pump();
}

void main() {
  testWidgets(
    'all fields start skipped, deselecting disables submission, and closing discards choices',
    (tester) async {
      final server = await _detail(tester);
      expect(server.calls(_catalog), isEmpty);
      await _open(tester);
      for (final field in ['cover', 'plot', 'samples', 'tags']) {
        final input = find.descendant(
          of: find.byKey(ValueKey(field)),
          matching: find.byType(DropdownButton<String>),
        );
        expect(tester.widget<DropdownButton<String>>(input).value, '');
      }
      expect(tester.widget<FilledButton>(_confirm).onPressed, isNull);
      await _select(tester, 'cover', 'JavBus');
      await _select(tester, 'cover', 'Skip');
      expect(tester.widget<FilledButton>(_confirm).onPressed, isNull);
      await _select(tester, 'samples', 'JavDB');
      final close = find.byType(CloseButton);
      await tester.ensureVisible(close);
      await tester.tap(close);
      await tester.pumpAndSettle();
      await _open(tester);
      expect(tester.widget<FilledButton>(_confirm).onPressed, isNull);
      expect(server.calls(_catalog).map((r) => r.method), ['GET', 'GET']);
      expect(server.writes, isEmpty);
    },
  );

  for (final partial in [false, true]) {
    testWidgets(
      '${partial ? 'Partial' : 'Successful'} field replacement refreshes only the current video and its plot',
      (tester) async {
        final server = await _detail(tester);
        await _open(tester);
        await _select(tester, 'plot', 'DMM');
        await _select(tester, 'tags', 'Jable');
        if (partial) await _select(tester, 'cover', 'JavBus');
        await _submit(tester, doubleTap: true);
        final request = server.writes.single;
        expect(request.path, _rescrape);
        expect(request.method, 'POST');
        expect(request.data, {
          'file_path': _path,
          'sources': {
            'plot': 'dmm',
            'tags': 'jable',
            if (partial) 'cover': 'javbus',
          },
        });
        expect(request.queryParameters, isEmpty);
        expect(server.calls(_lookup), isEmpty);
        final beforeRefresh = server.calls(_plot).length;
        server.event({
          'type': 'progress',
          'current': 0,
          'total': 1,
          'element': 'plot',
        });
        await tester.pump(const Duration(milliseconds: 25));
        await tester.pump(const Duration(milliseconds: 25));
        expect(find.text('Synopsis · DMM'), findsOneWidget);
        expect(
          tester
              .widget<ActionChip>(find.widgetWithText(ActionChip, 'Rescrape'))
              .onPressed,
          isNull,
        );
        expect(server.updated, isEmpty);
        server.wroteMetadata = true;
        server.finish(
          success: partial ? 0 : 1,
          failed: partial ? 1 : 0,
          filled: {'plot': 1, 'tags': 1},
          failures: [
            if (partial)
              {
                'element': 'cover',
                'source': 'javbus',
                'error': 'Image unavailable',
                'number': 'ABC',
              },
          ],
        );
        await tester.pumpAndSettle();
        expect(server.calls(_lookup), hasLength(1));
        expect(server.calls(_lookup).single.queryParameters['path'], _path);
        expect(
          server
              .calls(_plot)
              .skip(beforeRefresh)
              .map((r) => r.queryParameters['file_path']),
          [_path],
        );
        expect(server.updated.single.path, _path);
        expect(server.updated.single.tags, ['Replacement tag']);
        expect(find.text('Replacement tag'), findsOneWidget);
        expect(find.text('Replacement plot'), findsOneWidget);
        expect(find.text('Existing tag'), findsNothing);
        expect(server.writes, hasLength(1));
        expect(
          find.textContaining(
            AppStrings('en').rescrapeSummary(2, partial ? 1 : 0, 0),
          ),
          findsOneWidget,
        );
        if (partial) {
          expect(find.textContaining('Image unavailable'), findsOneWidget);
        }
      },
    );
  }

  for (final disconnected in [false, true]) {
    testWidgets(
      '${disconnected ? 'Disconnected stream' : 'Failed source'} keeps metadata and allows reopening',
      (tester) async {
        final server = await _detail(tester);
        await _open(tester);
        await _select(tester, 'tags', 'Jable');
        await _submit(tester);
        if (disconnected) {
          unawaited(server.stream.close());
        } else {
          server.finish(
            success: 0,
            failed: 1,
            filled: {},
            failures: [
              {
                'element': 'tags',
                'source': 'jable',
                'error': 'No tags found',
                'number': 'ABC',
              },
            ],
          );
        }
        await tester.pumpAndSettle();
        expect(find.text('Existing tag'), findsOneWidget);
        expect(find.text('Existing plot'), findsOneWidget);
        if (disconnected) {
          expect(
            find.textContaining(AppStrings('en').taskStreamInterrupted),
            findsOneWidget,
          );
          expect(server.calls(_lookup), hasLength(1));
          expect(server.calls(_lookup).single.queryParameters['path'], _path);
          expect(server.updated.single.path, _path);
          expect(server.updated.single.tags, ['Existing tag']);
        } else {
          expect(server.calls(_lookup), isEmpty);
          expect(server.updated, isEmpty);
          expect(find.textContaining('No tags found'), findsOneWidget);
        }
        await _open(tester);
        expect(server.calls(_catalog), hasLength(2));
        expect(tester.widget<FilledButton>(_confirm).onPressed, isNull);
        expect(server.writes, hasLength(1));
      },
    );
  }

  testWidgets(
    'replacing images changes the cache keys at stable cover and sample URLs',
    (tester) async {
      final cache = _ImageCache();
      final previous = CachedNetworkImageProvider.defaultCacheManager;
      CachedNetworkImageProvider.defaultCacheManager = cache;
      addTearDown(
        () => CachedNetworkImageProvider.defaultCacheManager = previous,
      );
      final server = await _detail(
        tester,
        video: {
          ..._video,
          'cover_url': '/images/thumb',
          'cover_full_url': '/images/full',
          'sample_images': ['/images/sample'],
        },
      );
      Map<String, String?> keys() => {
        for (final image in tester.widgetList<CachedNetworkImage>(
          find.byType(CachedNetworkImage),
        ))
          Uri.parse(image.imageUrl).path: image.cacheKey,
      };
      final before = keys();
      expect(before.keys, containsAll(['/images/full', '/images/sample']));
      await _open(tester);
      await _select(tester, 'cover', 'JavBus');
      await _select(tester, 'samples', 'JavDB');
      await _submit(tester);
      server.finish(success: 1, failed: 0, filled: {'cover': 1, 'samples': 1});
      await tester.pumpAndSettle();
      expect(
        cache.removed.map((url) => Uri.parse(url).path),
        unorderedEquals(['/images/thumb', '/images/full', '/images/sample']),
      );
      final after = keys();
      for (final url in before.keys) {
        expect(after[url], isNot(before[url]));
      }
    },
  );

  testWidgets(
    'late completion after paging away cannot update the other video',
    (tester) async {
      final server = await _detail(tester);
      await _open(tester);
      await _select(tester, 'tags', 'Jable');
      await _submit(tester);
      await tester.fling(find.byType(PageView), const Offset(650, 0), 1500);
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('1 / 2'), findsOneWidget);
      server.finish(success: 1, failed: 0, filled: {'tags': 1});
      await tester.pumpAndSettle();
      expect(find.text('Other copy'), findsOneWidget);
      expect(find.text('Replacement tag'), findsNothing);
      expect(server.updated.where((v) => v.path == _neighbor), isEmpty);
      expect(
        server
            .calls(_lookup)
            .where((r) => r.queryParameters['path'] == _neighbor),
        isEmpty,
      );
      expect(tester.takeException(), isNull);
    },
  );
}
