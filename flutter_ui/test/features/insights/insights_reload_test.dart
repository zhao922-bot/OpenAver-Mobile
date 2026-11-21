import 'dart:async';

import 'package:dio/dio.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/features/insights/insights_page.dart';

final _strings = AppStrings('en');

class _InsightsApi extends ApiClient {
  _InsightsApi() : super(port: 8765, token: '');

  final requests = <Completer<Map<String, dynamic>>>[];

  @override
  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) {
    expect(path, '/api/insights/snapshot');
    final request = Completer<Map<String, dynamic>>();
    requests.add(request);
    return request.future;
  }
}

Map<String, dynamic> _snapshot(int year, String maker) => {
  'success': true,
  'records': [
    {'year': year, 'maker': maker},
  ],
};

Future<LibraryRevisionNotifier> _openInsights(
  WidgetTester tester,
  _InsightsApi api,
) async {
  tester.view.physicalSize = const Size(800, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(api.dio.close);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        stringsProvider.overrideWithValue(_strings),
      ],
      child: const MaterialApp(home: InsightsPage()),
    ),
  );
  final container = ProviderScope.containerOf(
    tester.element(find.byType(InsightsPage)),
    listen: false,
  );
  return container.read(libraryRevisionProvider.notifier);
}

void main() {
  testWidgets('refresh keeps charts and filters through failure and retry', (
    tester,
  ) async {
    final api = _InsightsApi();
    final revision = await _openInsights(tester, api);
    api.requests.single.complete(_snapshot(2024, 'Studio'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Studio'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(BarChart));
    await tester.pumpAndSettle();
    final yearFilter = find.widgetWithText(
      InputChip,
      '${_strings.insightsYears}: 2024',
    );
    final makerFilter = find.widgetWithText(
      InputChip,
      '${_strings.makerLabel}: Studio',
    );
    expect(yearFilter, findsOneWidget);
    expect(makerFilter, findsOneWidget);
    final scrollable = tester.state<ScrollableState>(
      find.byType(Scrollable).first,
    );

    revision.bump();
    await tester.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.byType(BarChart), findsOneWidget);
    expect(yearFilter, findsOneWidget);
    expect(makerFilter, findsOneWidget);
    expect(tester.state(find.byType(Scrollable).first), same(scrollable));

    api.requests[1].completeError(StateError('Offline'));
    await tester.pumpAndSettle();
    expect(find.byType(LinearProgressIndicator), findsNothing);
    expect(find.text(_strings.loadLibraryFailed), findsOneWidget);
    expect(find.byType(BarChart), findsOneWidget);
    expect(yearFilter, findsOneWidget);
    expect(makerFilter, findsOneWidget);
    expect(tester.state(find.byType(Scrollable).first), same(scrollable));

    await tester.tap(find.widgetWithText(TextButton, _strings.retry));
    await tester.pump();
    expect(find.text(_strings.loadLibraryFailed), findsNothing);
    expect(find.byType(BarChart), findsOneWidget);
    api.requests[2].complete(_snapshot(2024, 'Studio'));
    await tester.pumpAndSettle();
    expect(yearFilter, findsOneWidget);
    expect(makerFilter, findsOneWidget);

    revision.bump();
    api.requests[3].complete(_snapshot(2025, 'Studio'));
    await tester.pumpAndSettle();
    expect(yearFilter, findsNothing);
    expect(makerFilter, findsOneWidget);
    expect(find.text('2025'), findsOneWidget);
  });

  testWidgets(
    'stale failures and successes leave the latest refresh in control',
    (tester) async {
      final api = _InsightsApi();
      final revision = await _openInsights(tester, api);
      api.requests.single.complete(_snapshot(2021, 'First'));
      await tester.pumpAndSettle();

      revision.bump();
      revision.bump();
      revision.bump();
      await tester.pump();
      api.requests[1].complete({'success': false, 'error': 'Stale failure'});
      await tester.pump();
      expect(find.text('Stale failure'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      expect(find.text('First'), findsOneWidget);

      api.requests[3].complete(_snapshot(2024, 'Latest'));
      await tester.pumpAndSettle();
      expect(find.text('Latest'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNothing);

      api.requests[2].complete(_snapshot(2022, 'Stale result'));
      await tester.pumpAndSettle();
      expect(find.text('Latest'), findsOneWidget);
      expect(find.text('Stale result'), findsNothing);
    },
  );
}
