import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'l10n.dart';

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
    this.openaverCommit = '',
  });

  final bool ready;
  final int port;
  final String token;
  final String cookieName;
  final String dataDir;
  final String version;
  final String openaverRelease;
  final String openaverCommit;
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
      openaverCommit: (map['openaverCommit'] as String?) ?? '',
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
    this.mimeType,
  });

  final String path;
  final String name;
  final int size;
  final String? mimeType;
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

class BuiltInPlayerPart {
  const BuiltInPlayerPart({
    required this.path,
    this.label = '',
  });

  final String path;
  final String label;

  static List<BuiltInPlayerPart> parseList(
    Object? rawParts, {
    String fallbackPath = '',
  }) {
    final parsed = <BuiltInPlayerPart>[];
    if (rawParts is List) {
      for (final entry in rawParts) {
        if (entry is Map) {
          final p = (entry['path'] ?? '').toString().trim();
          final l = (entry['label'] ?? '').toString().trim();
          if (p.isNotEmpty) {
            parsed.add(BuiltInPlayerPart(path: p, label: l));
          }
        }
      }
    }
    if (parsed.isEmpty && fallbackPath.trim().isNotEmpty) {
      parsed.add(BuiltInPlayerPart(path: fallbackPath.trim()));
    }
    return parsed;
  }
}

typedef BuiltInPlayerCallback = void Function(
  String path,
  int part,
  List<BuiltInPlayerPart> parts,
);

typedef RuntimeReadyCallback = void Function(BootstrapInfo info);

class TaskKeepAliveLease {
  TaskKeepAliveLease._(this._bridge);

  final NativeBridge _bridge;

  void updateProgress(int? current, int? total) =>
      _bridge._updateTaskProgress(this, current, total);

  void release() => _bridge._releaseTaskKeepAlive(this);
}

class NativeBridge {
  NativeBridge._() {
    _channel.setMethodCallHandler(_handleIncoming);
  }

  static final NativeBridge instance = NativeBridge._();
  static const MethodChannel _channel = MethodChannel('dev.openaver.mobile/bridge');

  BuiltInPlayerCallback? onOpenBuiltInPlayer;
  RuntimeReadyCallback? onRuntimeReady;
  VoidCallback? onTaskCenterRequested;

  Future<bool> consumeTaskCenterRequest() async {
    try {
      return await _channel.invokeMethod<bool>('consumeTaskCenterRequest') == true;
    } catch (e) {
      debugPrint('Task Center request unavailable: ${e.runtimeType}');
      return false;
    }
  }

  Future<void> _handleIncoming(MethodCall call) async {
    if (call.method == 'openBuiltInPlayer') {
      final args = call.arguments as Map<Object?, Object?>?;
      final path = (args?['path'] as String?) ?? '';
      final part = (args?['part'] as int?) ?? 1;
      final parts = BuiltInPlayerPart.parseList(args?['parts'], fallbackPath: path);
      if (parts.isNotEmpty) {
        onOpenBuiltInPlayer?.call(path.isNotEmpty ? path : parts.first.path, part, parts);
      }
    } else if (call.method == 'taskCenterRequested') {
      onTaskCenterRequested?.call();
    } else if (call.method == 'onRuntimeReady') {
      final raw = call.arguments as Map<Object?, Object?>?;
      if (raw != null) {
        onRuntimeReady?.call(BootstrapInfo.fromMap(raw));
      }
    }
  }

  Future<BootstrapInfo> getBootstrapInfo() async {
    final raw = await _channel.invokeMapMethod<Object?, Object?>('getBootstrapInfo');
    return BootstrapInfo.fromMap(raw ?? const {});
  }

  Future<Duration> readPlaybackPosition(String path) async {
    try {
      final milliseconds = await _channel.invokeMethod<int>(
        'readPlaybackPosition',
        {'path': path},
      );
      return Duration(milliseconds: milliseconds ?? 0);
    } catch (_) {
      return Duration.zero;
    }
  }

  Future<void> savePlaybackPosition(String path, Duration position) async {
    try {
      await _channel.invokeMethod<void>('savePlaybackPosition', {
        'path': path,
        'milliseconds': position.inMilliseconds,
      });
    } catch (error) {
      debugPrint('Unable to save playback position: ${error.runtimeType}');
    }
  }

  Future<bool> openExternalPlayer({required String path, String? partsJson}) async {
    final result = await _channel.invokeMethod<bool>('openExternalPlayer', {
      'path': path,
      'parts': ?partsJson,
    });
    return result ?? false;
  }

  final _taskKeepAliveLeases = <TaskKeepAliveLease, (int, int)?>{};
  (int, (int, int)?, String)? _lastTaskNotification;
  AppStrings _taskNotificationStrings = AppStrings('zh-CN');

  void setTaskNotificationStrings(AppStrings strings) {
    _taskNotificationStrings = strings;
    _publishTaskNotification();
  }

  TaskKeepAliveLease acquireTaskKeepAlive() {
    final lease = TaskKeepAliveLease._(this);
    _taskKeepAliveLeases[lease] = null;
    if (_taskKeepAliveLeases.length == 1) {
      unawaited(_setTaskKeepAlive(true));
    }
    _publishTaskNotification();
    return lease;
  }

  void _updateTaskProgress(TaskKeepAliveLease lease, int? current, int? total) {
    if (!_taskKeepAliveLeases.containsKey(lease)) return;
    _taskKeepAliveLeases[lease] = current != null && total != null && total > 0
        ? (current.clamp(0, total), total)
        : null;
    _publishTaskNotification();
  }

  void _releaseTaskKeepAlive(TaskKeepAliveLease lease) {
    if (!_taskKeepAliveLeases.containsKey(lease)) return;
    _taskKeepAliveLeases.remove(lease);
    if (_taskKeepAliveLeases.isEmpty) {
      _lastTaskNotification = null;
      unawaited(_setTaskKeepAlive(false));
    } else {
      _publishTaskNotification();
    }
  }

  void _publishTaskNotification() {
    final count = _taskKeepAliveLeases.length;
    if (count == 0) return;
    // Different workers may count different units. Display the task count
    // when several are active, and the remaining worker's progress when alone.
    final progress = count == 1 ? _taskKeepAliveLeases.values.single : null;
    final summary = _taskNotificationStrings.taskCenterNotificationCount(count);
    final notification = (count, progress, summary);
    if (notification == _lastTaskNotification) return;
    _lastTaskNotification = notification;
    unawaited(_sendTaskNotification(count, progress, summary));
  }

  Future<void> _sendTaskNotification(int count, (int, int)? progress, String summary) async {
    try {
      await _channel.invokeMethod<void>('updateTaskNotification', {
        'taskCount': count,
        if (progress != null) 'progressCurrent': progress.$1,
        if (progress != null) 'progressTotal': progress.$2,
        'taskSummary': summary,
      });
    } catch (e) {
      debugPrint('Task notification update unavailable: ${e.runtimeType}');
    }
  }

  Future<void> _setTaskKeepAlive(bool active) async {
    try {
      await _channel.invokeMethod<void>('setTaskKeepAlive', {'active': active});
    } catch (e) {
      debugPrint('setTaskKeepAlive error: $e');
    }
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
      mimeType: raw['mimeType'] as String?,
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
    try {
      await _channel.invokeMethod<void>('syncNativeTheme', {'theme': theme});
    } catch (e) {
      debugPrint('syncNativeTheme error: $e');
    }
  }

  Future<void> syncUiLocale(String locale) async {
    try {
      await _channel.invokeMethod<void>('syncUiLocale', {'locale': locale});
    } catch (e) {
      debugPrint('syncUiLocale error: $e');
    }
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
