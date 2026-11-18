import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'api_client.dart';
import 'app_theme.dart';
import 'l10n.dart';
import 'native_bridge.dart';

class BootstrapNotifier extends Notifier<BootstrapInfo> {
  @override
  BootstrapInfo build() => const BootstrapInfo(
        ready: false,
        port: 8765,
        token: '',
        cookieName: 'openaver_loopback',
        dataDir: '',
        version: '',
        openaverRelease: '',
        abi: '',
        uiLocale: 'zh-CN',
        theme: 'dim',
        hasStorageAccess: false,
        hasTreeAccess: false,
        treeDescription: '',
      );

  void setBootstrap(BootstrapInfo info) => state = info;
}

final bootstrapProvider = NotifierProvider<BootstrapNotifier, BootstrapInfo>(
  BootstrapNotifier.new,
);

final apiClientProvider = Provider<ApiClient>((ref) {
  final boot = ref.watch(bootstrapProvider);
  return ApiClient(port: boot.port, token: boot.token);
});

class ThemeModeNotifier extends Notifier<AppThemeMode> {
  @override
  AppThemeMode build() => AppThemeMode.dim;

  void setTheme(AppThemeMode mode) => state = mode;
}

final themeModeProvider = NotifierProvider<ThemeModeNotifier, AppThemeMode>(
  ThemeModeNotifier.new,
);

class LocaleNotifier extends Notifier<String> {
  @override
  String build() => 'zh-CN';

  void setLocale(String locale) => state = locale;
}

final localeProvider = NotifierProvider<LocaleNotifier, String>(
  LocaleNotifier.new,
);

final stringsProvider = Provider<AppStrings>((ref) {
  return AppStrings(ref.watch(localeProvider));
});

class ActiveTabNotifier extends Notifier<int> {
  @override
  int build() => 0;

  void setTab(int index) => state = index;
}

final activeTabProvider = NotifierProvider<ActiveTabNotifier, int>(
  ActiveTabNotifier.new,
);

class ShowcaseActressFilterNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void setActress(String? actress) => state = actress;
}

final showcaseActressFilterProvider =
    NotifierProvider<ShowcaseActressFilterNotifier, String?>(
  ShowcaseActressFilterNotifier.new,
);

class ShowcaseTagFilterNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void setTag(String? tag) => state = tag;
}

final showcaseTagFilterProvider =
    NotifierProvider<ShowcaseTagFilterNotifier, String?>(
  ShowcaseTagFilterNotifier.new,
);

/// Optional GlobalKey used to let device back button clear active search results
/// before switching tabs.
final searchResetHookProvider = Provider<ValueNotifier<bool>>((ref) {
  final notifier = ValueNotifier<bool>(false);
  ref.onDispose(notifier.dispose);
  return notifier;
});
