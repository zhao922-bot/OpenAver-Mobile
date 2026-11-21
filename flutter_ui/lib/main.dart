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
import 'features/settings/ai_backfill_bar.dart';
import 'features/settings/settings_page.dart';
import 'features/showcase/showcase_page.dart';
import 'features/task_center/task_center_page.dart';

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
  static const _taskCenterTab = 5;

  final GlobalKey<NavigatorState> _navKey = GlobalKey<NavigatorState>();
  final GlobalKey<SearchPageState> _searchKey = GlobalKey<SearchPageState>();
  bool _initialized = false;
  bool _bootstrapApplied = false;
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
    NativeBridge.instance.onTaskCenterRequested = _onTaskCenterRequested;
    ref.listenManual(stringsProvider, (_, strings) {
      NativeBridge.instance.setTaskNotificationStrings(strings);
    }, fireImmediately: true);
    _onTaskCenterRequested();
    _bootstrap();
  }

  @override
  void dispose() {
    _bootstrapPoll?.cancel();
    final bridge = NativeBridge.instance;
    if (bridge.onTaskCenterRequested == _onTaskCenterRequested) {
      bridge.onTaskCenterRequested = null;
    }
    if (bridge.onRuntimeReady == _applyBootstrapInfo) {
      bridge.onRuntimeReady = null;
    }
    super.dispose();
  }

  void _onTaskCenterRequested() => unawaited(_openTaskCenter());

  Future<void> _openTaskCenter() async {
    if (!await NativeBridge.instance.consumeTaskCenterRequest() || !mounted) return;
    _navKey.currentState?.popUntil((route) => route.isFirst);
    _selectTab(_taskCenterTab);
  }

  void _selectTab(int index) {
    ref.read(activeTabProvider.notifier).setTab(index);
    if (index == _taskCenterTab && _initialized && _bootstrapApplied) {
      unawaited(AiBackfillTask.refreshKnown(ref.read(apiClientProvider)));
    }
  }

  Future<void> _applyBootstrapInfo(BootstrapInfo info) async {
    if (!mounted || !info.ready || _bootstrapApplied) return;
    _bootstrapApplied = true;
    _bootstrapPoll?.cancel();
    ref.read(bootstrapProvider.notifier).setBootstrap(info);
    final theme = AppThemeMode.fromString(info.theme);
    ref.read(themeModeProvider.notifier).setTheme(theme);
    ref.read(localeProvider.notifier).setLocale(info.uiLocale);
    await NativeBridge.instance.syncNativeTheme(theme.id);
    if (!mounted) return;
    setState(() => _initialized = true);
    unawaited(AiBackfillTask.refreshKnown(ref.read(apiClientProvider)));
    unawaited(_loadStartupGeneralPrefs());
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
      if (!mounted || _bootstrapApplied) return;
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

    final tabs = [
      const ShowcasePage(),
      SearchPage(key: _searchKey),
      const ScannerPage(),
      const InsightsPage(),
      const SettingsPage(),
      const TaskCenterPage(),
    ];
    final destinations = [
      (Icons.grid_view_rounded, strings.tabShowcase),
      (Icons.search_rounded, strings.tabSearch),
      (Icons.radar_rounded, strings.tabScanner),
      (Icons.pie_chart_outline_rounded, strings.tabInsights),
      (Icons.settings_outlined, strings.tabSettings),
      (Icons.task_alt_rounded, strings.taskCenterTab),
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
                if (activeTab == 1 && _searchKey.currentState?.clearSearchResults() == true) {
                  return;
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
                  return Scaffold(
                    body: Row(
                      children: [
                        if (useRail) ...[
                          SafeArea(
                            right: false,
                            child: NavigationRail(
                              scrollable: true,
                              selectedIndex: activeTab,
                              labelType: NavigationRailLabelType.all,
                              onDestinationSelected: _selectTab,
                              destinations: [
                                for (final (icon, label) in destinations)
                                  NavigationRailDestination(
                                    icon: Icon(icon),
                                    label: Text(label),
                                  ),
                              ],
                            ),
                          ),
                          const VerticalDivider(width: 1),
                        ],
                        Expanded(
                          key: const ValueKey('app-tabs'),
                          child: IndexedStack(index: activeTab, children: tabs),
                        ),
                      ],
                    ),
                    bottomNavigationBar: useRail
                        ? null
                        : NavigationBar(
                            selectedIndex: activeTab,
                            labelBehavior: constraints.maxWidth < 420
                                ? NavigationDestinationLabelBehavior.onlyShowSelected
                                : NavigationDestinationLabelBehavior.alwaysShow,
                            onDestinationSelected: _selectTab,
                            destinations: [
                              for (final (icon, label) in destinations)
                                NavigationDestination(icon: Icon(icon), label: label),
                            ],
                          ),
                  );
                },
              ),
            ),
    );
  }
}
