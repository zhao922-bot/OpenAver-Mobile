import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'api_client.dart';
import 'app_theme.dart';
import 'l10n.dart';
import 'native_bridge.dart';

final bootstrapProvider = StateProvider<BootstrapInfo>((ref) {
  return const BootstrapInfo(
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
});

final apiClientProvider = Provider<ApiClient>((ref) {
  final boot = ref.watch(bootstrapProvider);
  return ApiClient(port: boot.port, token: boot.token);
});

final themeModeProvider = StateProvider<AppThemeMode>((ref) {
  return AppThemeMode.dim;
});

final localeProvider = StateProvider<String>((ref) {
  return 'zh-CN';
});

final stringsProvider = Provider<AppStrings>((ref) {
  return AppStrings(ref.watch(localeProvider));
});

final activeTabProvider = StateProvider<int>((ref) => 0);

final showcaseActressFilterProvider = StateProvider<String?>((ref) => null);
