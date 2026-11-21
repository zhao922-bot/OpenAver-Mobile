import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/api_client.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/features/settings/settings_page.dart';

final _strings = AppStrings('en');
const _channel = MethodChannel('dev.openaver.mobile/bridge');

class _SettingsApi extends ApiClient {
  _SettingsApi() : super(port: 8765, token: '') {
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final Map<String, dynamic> response;
          if (options.path == '/api/config' && options.method == 'PUT') {
            final reply = Completer<Map<String, dynamic>>();
            saves.add((options, reply));
            response = await reply.future;
          } else if (options.path == '/api/config') {
            response = {
              'data': {
                'scraper': {'folder_format': '{actor}'},
              },
            };
          } else {
            response = {};
          }
          handler.resolve(
            Response(requestOptions: options, statusCode: 200, data: response),
          );
        },
      ),
    );
  }

  final saves = <(RequestOptions, Completer<Map<String, dynamic>>)>[];

  Object? savedFolderFormat(int index) =>
      (saves[index].$1.data as Map)['scraper']['folder_format'];
}

Future<Finder> _openScraperSettings(
  WidgetTester tester,
  _SettingsApi api,
) async {
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  messenger.setMockMethodCallHandler(_channel, (_) async => null);
  addTearDown(() => messenger.setMockMethodCallHandler(_channel, null));
  addTearDown(api.dio.close);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        stringsProvider.overrideWithValue(_strings),
      ],
      child: const MaterialApp(home: SettingsPage()),
    ),
  );
  await tester.pumpAndSettle();
  final scraperTab = find.widgetWithText(ChoiceChip, _strings.secScraper);
  await tester.ensureVisible(scraperTab);
  await tester.tap(scraperTab);
  await tester.pumpAndSettle();
  return find.widgetWithText(TextFormField, '{actor}');
}

void main() {
  testWidgets('a save owns its snapshot while the next edit stays dirty', (
    tester,
  ) async {
    final api = _SettingsApi();
    final initialField = await _openScraperSettings(tester, api);
    final save = find.widgetWithText(FilledButton, _strings.saveSettings);

    await tester.enterText(initialField, '{maker}');
    await tester.pump();
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.savedFolderFormat(0), '{maker}');
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, _strings.saving),
          )
          .onPressed,
      isNull,
    );

    await tester.enterText(
      find.widgetWithText(TextFormField, '{maker}'),
      '{year}',
    );
    await tester.pump();
    expect(api.savedFolderFormat(0), '{maker}');
    api.saves.single.$2.complete({'success': true});
    await tester.pumpAndSettle();

    expect(find.widgetWithText(TextFormField, '{year}'), findsOneWidget);
    expect(find.text(_strings.unsavedChanges), findsOneWidget);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.savedFolderFormat(1), '{year}');
    api.saves[1].$2.complete({'success': true});
    await tester.pumpAndSettle();
    expect(find.text(_strings.unsavedChanges), findsNothing);
  });

  testWidgets('a failed save preserves the latest draft for retry', (
    tester,
  ) async {
    final api = _SettingsApi();
    final initialField = await _openScraperSettings(tester, api);
    final save = find.widgetWithText(FilledButton, _strings.saveSettings);

    await tester.enterText(initialField, '{maker}');
    await tester.pump();
    await tester.tap(save);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextFormField, '{maker}'),
      '{title}',
    );
    await tester.pump();
    api.saves.single.$2.complete({'success': false, 'error': 'Save rejected'});
    await tester.pumpAndSettle();

    expect(find.text('Save rejected'), findsOneWidget);
    expect(find.widgetWithText(TextFormField, '{title}'), findsOneWidget);
    expect(find.text(_strings.unsavedChanges), findsOneWidget);
    ScaffoldMessenger.of(
      tester.element(find.byType(SettingsPage)),
    ).hideCurrentSnackBar();
    await tester.pumpAndSettle();
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.savedFolderFormat(1), '{title}');
    api.saves[1].$2.complete({'success': true});
    await tester.pumpAndSettle();
    expect(find.text(_strings.unsavedChanges), findsNothing);
  });
}
