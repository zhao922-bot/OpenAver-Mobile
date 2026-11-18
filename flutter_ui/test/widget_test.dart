import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/app_providers.dart';
import 'package:flutter_ui/core/app_theme.dart';
import 'package:flutter_ui/core/l10n.dart';
import 'package:flutter_ui/core/models/scanner_models.dart';
import 'package:flutter_ui/core/models/video_item.dart';
import 'package:flutter_ui/features/insights/insights_page.dart';
import 'package:flutter_ui/features/scanner/scanner_page.dart';
import 'package:flutter_ui/features/search/search_page.dart';
import 'package:flutter_ui/features/settings/settings_page.dart';
import 'package:flutter_ui/features/showcase/showcase_page.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('dev.openaver.mobile/bridge');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'getBootstrapInfo') {
        return {
          'ready': true,
          'port': 8765,
          'token': 'test-token',
          'cookieName': 'openaver_loopback',
          'dataDir': '/data/user/0/dev.openaver.mobile/files',
          'version': '0.18.17',
          'openaverRelease': 'v0.18.17',
          'abi': 'arm64-v8a',
          'uiLocale': 'zh-CN',
          'theme': 'dim',
          'hasStorageAccess': true,
          'hasTreeAccess': false,
          'treeDescription': '',
        };
      }
      return null;
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('VideoItem focalAlignment clamps focus coordinates', () {
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
    expect(item.number, 'ABC-123');
    expect(item.focalAlignment.x, 1.0);
    expect(item.focalAlignment.y, -1.0);
    expect(item.sampleImages.length, 2);
  });

  test('AppThemeMode and AppStrings support all themes and locales', () {
    expect(AppThemeMode.fromString('light'), AppThemeMode.light);
    expect(AppThemeMode.fromString('dark'), AppThemeMode.dark);
    expect(AppThemeMode.fromString('unknown'), AppThemeMode.dim);

    final lightTheme = buildOpenAverTheme(AppThemeMode.light);
    final darkTheme = buildOpenAverTheme(AppThemeMode.dark);
    expect(lightTheme.brightness, Brightness.light);
    expect(darkTheme.brightness, Brightness.dark);

    final en = AppStrings('en');
    final ja = AppStrings('ja');
    expect(en.tabShowcase, 'Showcase');
    expect(ja.tabSettings, '設定');
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
      },
    });
    expect(summary.totalMissing, 6);
    expect(summary.untranslatedTitles, 4);
    expect(summary.missingPlots, 7);

    final dir = BrowseDirResponse.fromJson({
      'current_path': '/storage/emulated/0',
      'parent_path': '/storage/emulated',
      'entries': [
        {'name': 'Movies', 'path': '/storage/emulated/0/Movies'},
      ],
    });
    expect(dir.entries.single.name, 'Movies');
  });

  testWidgets('NavigationBar displays localized 5 tabs', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: Consumer(
          builder: (context, ref, _) {
            final strings = ref.watch(stringsProvider);
            final tab = ref.watch(activeTabProvider);
            return MaterialApp(
              theme: buildOpenAverTheme(AppThemeMode.dim),
              home: Scaffold(
                body: Center(
                  child: Text('Tab:$tab-$ShowcasePage-$SearchPage-$ScannerPage-$InsightsPage-$SettingsPage'),
                ),
                bottomNavigationBar: NavigationBar(
                  selectedIndex: tab,
                  onDestinationSelected: (i) =>
                      ref.read(activeTabProvider.notifier).state = i,
                  destinations: [
                    NavigationDestination(icon: const Icon(Icons.grid_view), label: strings.tabShowcase),
                    NavigationDestination(icon: const Icon(Icons.search), label: strings.tabSearch),
                    NavigationDestination(icon: const Icon(Icons.radar), label: strings.tabScanner),
                    NavigationDestination(icon: const Icon(Icons.bar_chart), label: strings.tabInsights),
                    NavigationDestination(icon: const Icon(Icons.settings), label: strings.tabSettings),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );

    expect(find.text('浏览'), findsOneWidget);
    expect(find.text('搜索'), findsOneWidget);
    expect(find.text('片库'), findsOneWidget);
    expect(find.text('分析'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);

    await tester.tap(find.text('分析'));
    await tester.pump();
    expect(find.textContaining('Tab:3-'), findsOneWidget);
  });
}
