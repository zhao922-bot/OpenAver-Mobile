import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:media_kit/media_kit.dart';
import 'core/app_providers.dart';
import 'core/app_theme.dart';
import 'core/native_bridge.dart';
import 'features/insights/insights_page.dart';
import 'features/player/builtin_player_page.dart';
import 'features/scanner/scanner_page.dart';
import 'features/search/search_page.dart';
import 'features/settings/settings_page.dart';
import 'features/showcase/showcase_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  runApp(const ProviderScope(child: OpenAverApp()));
}

class OpenAverApp extends ConsumerStatefulWidget {
  const OpenAverApp({super.key});

  @override
  ConsumerState<OpenAverApp> createState() => _OpenAverAppState();
}

class _OpenAverAppState extends ConsumerState<OpenAverApp> {
  final GlobalKey<NavigatorState> _navKey = GlobalKey<NavigatorState>();
  bool _initialized = false;
  DateTime? _lastBackPress;

  @override
  void initState() {
    super.initState();
    NativeBridge.instance.onOpenBuiltInPlayer = (path, part) {
      final api = ref.read(apiClientProvider);
      _navKey.currentState?.push(
        MaterialPageRoute<void>(
          builder: (_) => BuiltInPlayerPage(
            api: api,
            title: path.split('/').last,
            partPaths: [path],
            initialPartIndex: (part - 1).clamp(0, 0),
          ),
        ),
      );
    };
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    try {
      final info = await NativeBridge.instance.getBootstrapInfo();
      ref.read(bootstrapProvider.notifier).state = info;
      final theme = AppThemeMode.fromString(info.theme);
      ref.read(themeModeProvider.notifier).state = theme;
      ref.read(localeProvider.notifier).state = info.uiLocale;
      await NativeBridge.instance.syncNativeTheme(theme.id);
    } finally {
      if (mounted) {
        setState(() => _initialized = true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(themeModeProvider);
    final strings = ref.watch(stringsProvider);
    final activeTab = ref.watch(activeTabProvider);

    return MaterialApp(
      navigatorKey: _navKey,
      debugShowCheckedModeBanner: false,
      title: 'OpenAver Mobile',
      theme: buildOpenAverTheme(mode),
      home: !_initialized
          ? const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            )
          : PopScope(
              canPop: false,
              onPopInvokedWithResult: (didPop, _) {
                if (didPop) return;
                if (activeTab != 0) {
                  ref.read(activeTabProvider.notifier).state = 0;
                  return;
                }
                final now = DateTime.now();
                if (_lastBackPress != null &&
                    now.difference(_lastBackPress!) <= const Duration(seconds: 2)) {
                  NativeBridge.instance.exitApp();
                } else {
                  _lastBackPress = now;
                  final navCtx = _navKey.currentContext;
                  if (navCtx != null) {
                    ScaffoldMessenger.of(navCtx).showSnackBar(
                      SnackBar(
                        content: Text(strings.exitHint),
                        duration: const Duration(seconds: 2),
                      ),
                    );
                  }
                }
              },
              child: Scaffold(
                body: IndexedStack(
                  index: activeTab,
                  children: const [
                    ShowcasePage(),
                    SearchPage(),
                    ScannerPage(),
                    InsightsPage(),
                    SettingsPage(),
                  ],
                ),
                bottomNavigationBar: NavigationBar(
                  selectedIndex: activeTab,
                  onDestinationSelected: (idx) =>
                      ref.read(activeTabProvider.notifier).state = idx,
                  destinations: [
                    NavigationDestination(
                      icon: const Icon(Icons.grid_view_rounded),
                      label: strings.tabShowcase,
                    ),
                    NavigationDestination(
                      icon: const Icon(Icons.search_rounded),
                      label: strings.tabSearch,
                    ),
                    NavigationDestination(
                      icon: const Icon(Icons.radar_rounded),
                      label: strings.tabScanner,
                    ),
                    NavigationDestination(
                      icon: const Icon(Icons.pie_chart_outline_rounded),
                      label: strings.tabInsights,
                    ),
                    NavigationDestination(
                      icon: const Icon(Icons.settings_outlined),
                      label: strings.tabSettings,
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}
