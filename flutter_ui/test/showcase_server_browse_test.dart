import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/features/showcase/showcase_page.dart';

class _EnglishLocale extends LocaleNotifier {
  @override
  String build() => 'en';
}

class _ShowcaseAdapter implements HttpClientAdapter {
  _ShowcaseAdapter(this.reply);

  final Map<String, dynamic> Function(RequestOptions) reply;
  final requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    return ResponseBody.fromString(
      jsonEncode(reply(options)),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

Map<String, dynamic> _video(String number, {String? path}) => {
  'path': path ?? 'file:///library/$number.mp4',
  'number': number,
  'title': 'Title for $number',
};

Map<String, dynamic> _page(int page, int totalPages, String number) => {
  'success': true,
  'videos': [_video(number)],
  'total': totalPages,
  'page': page,
  'total_pages': totalPages,
  'per_page': 45,
  'paged': true,
};

Future<ProviderContainer> _pumpShowcase(
  WidgetTester tester,
  _ShowcaseAdapter adapter,
) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(520, 800);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  final container = ProviderContainer(
    overrides: [
      localeProvider.overrideWith(_EnglishLocale.new),
      apiClientProvider.overrideWithValue(
        ApiClient(port: 8765, token: 'test', httpClientAdapter: adapter),
      ),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: ShowcasePage()),
    ),
  );
  await tester.pumpAndSettle();
  return container;
}

Finder _detailHeading(String number) =>
    find.descendant(of: find.byType(AppBar), matching: find.text(number));

void main() {
  testWidgets(
    'filtered random paging keeps the same query when swiping detail',
    (tester) async {
      final adapter = _ShowcaseAdapter((options) {
        if (options.path == '/api/showcase/videos') {
          final query = options.queryParameters;
          final page = query['page'] as int;
          return _page(page, query['sort'] == 'random' ? 2 : 1, 'PAGE-$page');
        }
        return {'success': true};
      });
      final container = await _pumpShowcase(tester, adapter);
      container
          .read(showcaseActressFilterProvider.notifier)
          .setActress('Performer');
      container.read(showcaseTagFilterProvider.notifier).setTag('Été');
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '  Café  ');
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Favorites'));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.tune_rounded));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Random'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('PAGE-1'));
      await tester.pumpAndSettle();
      expect(_detailHeading('PAGE-1'), findsOneWidget);
      expect(find.text('1 / 2'), findsOneWidget);
      await tester.fling(find.byType(PageView), const Offset(-420, 0), 1000);
      await tester.pumpAndSettle();
      expect(_detailHeading('PAGE-2'), findsOneWidget);

      final requests = adapter.requests
          .where(
            (request) =>
                request.path == '/api/showcase/videos' &&
                request.queryParameters['sort'] == 'random',
          )
          .toList();
      expect(requests, hasLength(2));
      final seed = requests.first.queryParameters['random_seed'];
      expect(seed, isA<int>());
      for (var i = 0; i < requests.length; i++) {
        expect(requests[i].queryParameters, {
          'paged': true,
          'page': i + 1,
          'per_page': 45,
          'sort': 'random',
          'order': 'desc',
          'q': 'Café',
          'actress': 'Performer',
          'tag': 'Été',
          'favorites_only': true,
          'random_seed': seed,
        });
      }
    },
  );

  testWidgets(
    'Similar opens the exact record without replacing the source detail',
    (tester) async {
      const targetPath = 'file:///library/edition%20two/TGT-002.mp4';
      final adapter = _ShowcaseAdapter((options) {
        switch (options.path) {
          case '/api/showcase/videos':
            return _page(1, 1, 'SRC-001');
          case '/api/similar-covers/by-number/SRC-001':
            return {
              'results': [_video('TGT-002', path: targetPath)],
            };
          case '/api/showcase/video/lookup':
            return {
              'success': true,
              'video': _video('TGT-002', path: targetPath),
            };
          default:
            return {'success': true};
        }
      });
      await _pumpShowcase(tester, adapter);
      await tester.tap(find.text('SRC-001'));
      await tester.pumpAndSettle();
      final vertical = find.byWidgetPredicate(
        (widget) =>
            widget is Scrollable && widget.axisDirection == AxisDirection.down,
      );
      final recommendation = find.text('TGT-002').hitTestable();
      await tester.scrollUntilVisible(recommendation, 250, scrollable: vertical);
      await tester.pumpAndSettle();
      await tester.tap(recommendation);
      await tester.pumpAndSettle();
      expect(_detailHeading('TGT-002'), findsOneWidget);
      final lookup = adapter.requests.singleWhere(
        (request) => request.path == '/api/showcase/video/lookup',
      );
      expect(lookup.queryParameters, {
        'path': targetPath,
        'number': 'TGT-002',
        'title': 'Title for TGT-002',
      });
      expect(
        adapter.requests.where(
          (request) => request.path == '/api/showcase/videos',
        ),
        hasLength(1),
      );

      await tester.tap(find.byIcon(Icons.favorite_border_rounded));
      await tester.pumpAndSettle();
      expect(find.byIcon(Icons.favorite_rounded), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(_detailHeading('SRC-001'), findsOneWidget);
    },
  );
}
