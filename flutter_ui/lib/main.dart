import 'dart:async';
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
  bool _appliedStartupPrefs = false;
  DateTime? _lastBackPress;
  Timer? _bootstrapPoll;

  @override
  void initState() {
    super.initState();
    NativeBridge.instance.onOpenBuiltInPlayer = (path, part, parts) {
      final api = ref.read(apiClientProvider);
      final partPaths = parts.isNotEmpty ? parts.map((e) => e.path).toList() : [path];
      final partTokens = parts.map((e) => e.label).toList();
      final maxIdx = partPaths.isEmpty ? 0 : partPaths.length - 1;
      final selectedIdx = (part - 1).clamp(0, maxIdx);
      final displayTitle = (selectedIdx < partPaths.length ? partPaths[selectedIdx] : path).split('/').last;

      _navKey.currentState?.push(
        MaterialPageRoute<void>(
          builder: (_) => BuiltInPlayerPage(
            api: api,
            title: displayTitle,
            partPaths: partPaths,
            partTokens: partTokens,
            initialPartIndex: selectedIdx,
          ),
        ),
      );
    };
    NativeBridge.instance.onRuntimeReady = _applyBootstrapInfo;
    _bootstrap();
  }

  @override
  void dispose() {
    _bootstrapPoll?.cancel();
    super.dispose();
  }

  Future<void> _applyBootstrapInfo(BootstrapInfo info) async {
    if (!info.ready) return;
    _bootstrapPoll?.cancel();
    ref.read(bootstrapProvider.notifier).setBootstrap(info);
    final theme = AppThemeMode.fromString(info.theme);
    ref.read(themeModeProvider.notifier).setTheme(theme);
    ref.read(localeProvider.notifier).setLocale(info.uiLocale);
    await NativeBridge.instance.syncNativeTheme(theme.id);
    if (mounted) {
      setState(() => _initialized = true);
    }
    if (!_appliedStartupPrefs) {
      _appliedStartupPrefs = true;
      _loadStartupGeneralPrefs();
    }
  }

  Future<void> _loadStartupGeneralPrefs() async {
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/config');
      if (!mounted) return;
      final data = resp['data'];
      if (data is! Map) return;
      final general = data['general'];
      if (general is! Map) return;
      final fontSize = (general['font_size'] ?? '').toString();
      if (fontSize.isNotEmpty) {
        ref.read(fontSizeProvider.notifier).setFontSize(fontSize);
      }
      final defaultPage = (general['default_page'] ?? '').toString();
      final targetTab = switch (defaultPage) {
        'search' => 1,
        'gallery' => 2,
        'showcase' => 0,
        _ => null,
      };
      if (targetTab != null && ref.read(activeTabProvider) == 0 && targetTab != 0) {
        ref.read(activeTabProvider.notifier).setTab(targetTab);
      }
    } catch (e) {
      debugPrint('loadStartupGeneralPrefs skipped: $e');
    }
  }

  Future<void> _bootstrap() async {
    try {
      final info = await NativeBridge.instance.getBootstrapInfo();
      if (info.ready) {
        await _applyBootstrapInfo(info);
        return;
      }
      // Engine was pre-warmed while Chaquopy Python was still booting: apply visual theme early
      // and wait for onRuntimeReady (with a light polling safety net).
      final earlyTheme = AppThemeMode.fromString(info.theme);
      ref.read(themeModeProvider.notifier).setTheme(earlyTheme);
      ref.read(localeProvider.notifier).setLocale(info.uiLocale);
      _bootstrapPoll = Timer.periodic(const Duration(milliseconds: 300), (_) async {
        try {
          final fresh = await NativeBridge.instance.getBootstrapInfo();
          if (fresh.ready) {
            await _applyBootstrapInfo(fresh);
          }
        } catch (e) {
          debugPrint('Bootstrap poll error: $e');
        }
      });
    } catch (e) {
      debugPrint('Bootstrap error: $e');
      if (mounted) {
        setState(() => _initialized = true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(themeModeProvider);
    final fontSize = ref.watch(fontSizeProvider);
    final strings = ref.watch(stringsProvider);
    final activeTab = ref.watch(activeTabProvider);

    const tabs = [
      ShowcasePage(),
      SearchPage(),
      ScannerPage(),
      InsightsPage(),
      SettingsPage(),
    ];

    final scale = fontScaleFor(fontSize);
    return MaterialApp(
      navigatorKey: _navKey,
      debugShowCheckedModeBanner: false,
      title: 'OpenAver Mobile',
      theme: buildOpenAverTheme(mode),
      builder: (context, child) {
        if (child == null || scale == 1.0) return child ?? const SizedBox.shrink();
        final media = MediaQuery.of(context);
        return MediaQuery(
          data: media.copyWith(textScaler: TextScaler.linear(scale)),
          child: child,
        );
      },
      home: !_initialized
          ? Scaffold(
              body: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const CircularProgressIndicator(),
                    const SizedBox(height: 16),
                    Text(strings.startingServer),
                  ],
                ),
              ),
            )
          : PopScope(
              canPop: false,
              onPopInvokedWithResult: (didPop, _) {
                if (didPop) return;
                if (activeTab == 1) {
                  final resetHook = ref.read(searchResetHookProvider);
                  if (resetHook.value) {
                    resetHook.value = false;
                    return;
                  }
                }
                if (activeTab != 0) {
                  ref.read(activeTabProvider.notifier).setTab(0);
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
              child: LayoutBuilder(
                builder: (_, constraints) {
                  final useRail = constraints.maxWidth >= 840;
                  final bodyStack = IndexedStack(
                    index: activeTab,
                    children: tabs,
                  );

                  if (useRail) {
                    return Scaffold(
                      body: Row(
                        children: [
                          SafeArea(
                            right: false,
                            child: NavigationRail(
                              selectedIndex: activeTab,
                              labelType: NavigationRailLabelType.all,
                              onDestinationSelected: (idx) =>
                                  ref.read(activeTabProvider.notifier).setTab(idx),
                              destinations: [
                                NavigationRailDestination(
                                  icon: const Icon(Icons.grid_view_rounded),
                                  label: Text(strings.tabShowcase),
                                ),
                                NavigationRailDestination(
                                  icon: const Icon(Icons.search_rounded),
                                  label: Text(strings.tabSearch),
                                ),
                                NavigationRailDestination(
                                  icon: const Icon(Icons.radar_rounded),
                                  label: Text(strings.tabScanner),
                                ),
                                NavigationRailDestination(
                                  icon: const Icon(Icons.pie_chart_outline_rounded),
                                  label: Text(strings.tabInsights),
                                ),
                                NavigationRailDestination(
                                  icon: const Icon(Icons.settings_outlined),
                                  label: Text(strings.tabSettings),
                                ),
                              ],
                            ),
                          ),
                          const VerticalDivider(width: 1),
                          Expanded(child: bodyStack),
                        ],
                      ),
                    );
                  }

                  return Scaffold(
                    body: bodyStack,
                    bottomNavigationBar: NavigationBar(
                      selectedIndex: activeTab,
                      onDestinationSelected: (idx) =>
                          ref.read(activeTabProvider.notifier).setTab(idx),
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
                  );
                },
              ),
            ),
    );
  }
}
