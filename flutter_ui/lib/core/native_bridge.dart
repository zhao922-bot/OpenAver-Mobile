import 'package:flutter/services.dart';

class BootstrapInfo {
  const BootstrapInfo({
    required this.ready,
    required this.port,
    required this.token,
    required this.cookieName,
    required this.dataDir,
    required this.version,
    required this.openaverRelease,
    required this.abi,
    required this.uiLocale,
    required this.theme,
    required this.hasStorageAccess,
    required this.hasTreeAccess,
    required this.treeDescription,
  });

  final bool ready;
  final int port;
  final String token;
  final String cookieName;
  final String dataDir;
  final String version;
  final String openaverRelease;
  final String abi;
  final String uiLocale;
  final String theme;
  final bool hasStorageAccess;
  final bool hasTreeAccess;
  final String treeDescription;

  factory BootstrapInfo.fromMap(Map<Object?, Object?> map) {
    return BootstrapInfo(
      ready: map['ready'] == true,
      port: (map['port'] as int?) ?? 8765,
      token: (map['token'] as String?) ?? '',
      cookieName: (map['cookieName'] as String?) ?? 'openaver_loopback',
      dataDir: (map['dataDir'] as String?) ?? '',
      version: (map['version'] as String?) ?? '',
      openaverRelease: (map['openaverRelease'] as String?) ?? '',
      abi: (map['abi'] as String?) ?? '',
      uiLocale: (map['uiLocale'] as String?) ?? 'zh-CN',
      theme: (map['theme'] as String?) ?? 'dim',
      hasStorageAccess: map['hasStorageAccess'] == true,
      hasTreeAccess: map['hasTreeAccess'] == true,
      treeDescription: (map['treeDescription'] as String?) ?? '',
    );
  }
}

class PickedFileInfo {
  const PickedFileInfo({
    required this.path,
    required this.name,
    required this.size,
  });

  final String path;
  final String name;
  final int size;
}

class TreeAccessInfo {
  const TreeAccessInfo({
    required this.granted,
    required this.description,
    this.error,
  });

  final bool granted;
  final String description;
  final String? error;
}

typedef BuiltInPlayerCallback = void Function(String path, int part);

class NativeBridge {
  NativeBridge._() {
    _channel.setMethodCallHandler(_handleIncoming);
  }

  static final NativeBridge instance = NativeBridge._();
  static const MethodChannel _channel = MethodChannel('dev.openaver.mobile/bridge');

  BuiltInPlayerCallback? onOpenBuiltInPlayer;

  Future<void> _handleIncoming(MethodCall call) async {
    if (call.method == 'openBuiltInPlayer') {
      final args = call.arguments as Map<Object?, Object?>?;
      final path = (args?['path'] as String?) ?? '';
      final part = (args?['part'] as int?) ?? 1;
      if (path.isNotEmpty) {
        onOpenBuiltInPlayer?.call(path, part);
      }
    }
  }

  Future<BootstrapInfo> getBootstrapInfo() async {
    final raw = await _channel.invokeMapMethod<Object?, Object?>('getBootstrapInfo');
    return BootstrapInfo.fromMap(raw ?? const {});
  }

  Future<bool> openExternalPlayer({required String path, String? partsJson}) async {
    final result = await _channel.invokeMethod<bool>('openExternalPlayer', {
      'path': path,
      'parts': ?partsJson,
    });
    return result ?? false;
  }

  Future<void> setTaskKeepAlive(bool active) async {
    await _channel.invokeMethod<void>('setTaskKeepAlive', {'active': active});
  }

  Future<bool> hasStorageAccess() async {
    final result = await _channel.invokeMethod<bool>('hasStorageAccess');
    return result ?? false;
  }

  Future<bool> openStoragePermission() async {
    final result = await _channel.invokeMethod<bool>('openStoragePermission');
    return result ?? false;
  }

  Future<TreeAccessInfo> getStorageTreeInfo() async {
    final raw = await _channel.invokeMapMethod<Object?, Object?>('getStorageTreeInfo');
    return TreeAccessInfo(
      granted: raw?['granted'] == true,
      description: (raw?['description'] as String?) ?? '',
    );
  }

  Future<TreeAccessInfo?> openStorageTreePicker() async {
    final raw = await _channel.invokeMapMethod<Object?, Object?>('openStorageTreePicker');
    if (raw == null) return null;
    return TreeAccessInfo(
      granted: raw['granted'] == true,
      description: (raw['description'] as String?) ?? '',
      error: raw['error'] as String?,
    );
  }

  Future<void> clearStorageTree() async {
    await _channel.invokeMethod<void>('clearStorageTree');
  }

  Future<PickedFileInfo?> pickFile({List<String>? mimeTypes}) async {
    final raw = await _channel.invokeMapMethod<Object?, Object?>('pickFile', {
      'mimeTypes': ?mimeTypes,
    });
    if (raw == null) return null;
    return PickedFileInfo(
      path: (raw['path'] as String?) ?? '',
      name: (raw['name'] as String?) ?? 'upload.bin',
      size: (raw['size'] as int?) ?? 0,
    );
  }

  Future<String?> saveTempFileToDownloads({
    required String tempPath,
    required String filename,
    required String mimeType,
  }) async {
    return _channel.invokeMethod<String>('saveTempFileToDownloads', {
      'tempPath': tempPath,
      'filename': filename,
      'mimeType': mimeType,
    });
  }

  Future<void> syncNativeTheme(String theme) async {
    await _channel.invokeMethod<void>('syncNativeTheme', {'theme': theme});
  }

  Future<void> syncUiLocale(String locale) async {
    await _channel.invokeMethod<void>('syncUiLocale', {'locale': locale});
  }

  Future<bool> openExternalUrl(String url) async {
    final result = await _channel.invokeMethod<bool>('openExternalUrl', {'url': url});
    return result ?? false;
  }

  Future<void> switchToClassicWeb({String path = '/showcase'}) async {
    await _channel.invokeMethod<void>('switchToClassicWeb', {'path': path});
  }

  Future<void> exitApp() async {
    await _channel.invokeMethod<void>('exitApp');
  }
}
