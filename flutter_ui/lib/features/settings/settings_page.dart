import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import '../../core/native_bridge.dart';
import '../shared/browse_dir_sheet.dart';
import 'ai_backfill_bar.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});

  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  bool _loading = true;
  bool _saving = false;
  bool _dirty = false;
  String? _error;
  String _activeSection = 'all';

  Map<String, dynamic> _config = {};
  TreeAccessInfo _treeInfo = const TreeAccessInfo(granted: false, description: '');
  bool _storageGranted = true;
  bool _probingSources = false;
  Map<String, String> _probeResults = const {};
  int _presetRev = 0;

  bool _testingAi = false;
  bool _fetchingTranslateModels = false;
  List<String> _translateModels = const [];
  String? _translateStatus;
  bool _translateStatusOk = true;

  bool _testingSimilar = false;
  String? _similarStatus;
  bool _similarStatusOk = true;

  bool _testingFaces = false;
  bool _fetchingFacesModels = false;
  List<String> _facesModels = const [];
  String? _facesStatus;
  bool _facesStatusOk = true;

  bool _testingTags = false;
  bool _fetchingTagsModels = false;
  List<String> _tagsModels = const [];
  String? _tagsStatus;
  bool _tagsStatusOk = true;

  bool _metatubeBusy = false;
  bool _metatubeConnected = false;
  int _metatubeProviderCount = 0;
  String? _metatubeStatusText;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadAll());
  }

  Future<void> _loadAll({bool syncUiPrefs = false}) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.getJson('/api/config');
      final mtStatus = await api.getJson('/api/settings/metatube/status').catchError((Object _) => <String, dynamic>{});
      final tree = await NativeBridge.instance.getStorageTreeInfo();
      final storage = await NativeBridge.instance.hasStorageAccess();
      if (!mounted) return;
      final data = resp['data'];
      if (data is Map) {
        final decoded = jsonDecode(jsonEncode(data)) as Map<String, dynamic>;
        final general = decoded['general'];
        if (general is Map) {
          final savedFont = (general['font_size'] ?? '').toString();
          if (savedFont.isNotEmpty) {
            ref.read(fontSizeProvider.notifier).setFontSize(savedFont);
          }
          if (syncUiPrefs) {
            final savedTheme = AppThemeMode.fromString(general['theme']?.toString());
            ref.read(themeModeProvider.notifier).setTheme(savedTheme);
            NativeBridge.instance.syncNativeTheme(savedTheme.id);
            final savedLocale = (general['locale'] ?? '').toString();
            if (AppStrings.supportedLocales.contains(savedLocale)) {
              ref.read(localeProvider.notifier).setLocale(savedLocale);
              NativeBridge.instance.syncUiLocale(savedLocale);
            }
          }
        }
        setState(() {
          _config = decoded;
          _metatubeConnected = mtStatus['connected'] == true;
          _metatubeProviderCount = (mtStatus['providers'] as List?)?.length ?? 0;
          _treeInfo = tree;
          _storageGranted = storage;
          _dirty = false;
          _loading = false;
        });
      } else {
        setState(() {
          _loading = false;
          _error = strings.loadLibraryFailed;
        });
      }
    } catch (e) {
      debugPrint('Settings _loadAll error: $e');
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  void _markDirty(VoidCallback mutate) {
    setState(() {
      mutate();
      _dirty = true;
    });
  }

  Map<String, dynamic> _section(String name) {
    final val = _config[name];
    if (val is Map<String, dynamic>) return val;
    if (val is Map) {
      final copy = Map<String, dynamic>.from(val);
      _config[name] = copy;
      return copy;
    }
    final created = <String, dynamic>{};
    _config[name] = created;
    return created;
  }

  Map<String, dynamic> _nestedSection(Map<String, dynamic> parent, String name) {
    final val = parent[name];
    if (val is Map<String, dynamic>) return val;
    if (val is Map) {
      final copy = Map<String, dynamic>.from(val);
      parent[name] = copy;
      return copy;
    }
    final created = <String, dynamic>{};
    parent[name] = created;
    return created;
  }

  Future<void> _saveConfig() async {
    final strings = ref.read(stringsProvider);
    setState(() => _saving = true);
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.dio.put<dynamic>('/api/config', data: _config);
      final body = resp.data is Map ? Map<String, dynamic>.from(resp.data as Map) : const <String, dynamic>{};
      if (!mounted) return;
      if (resp.statusCode == 200 && body['success'] != false) {
        setState(() => _dirty = false);
        ref.read(libraryRevisionProvider.notifier).bump();
        _toast(strings.saved);
      } else {
        _toast((body['detail'] ?? body['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('Settings _saveConfig error: $e');
      _toast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _applyTheme(AppThemeMode mode) async {
    ref.read(themeModeProvider.notifier).setTheme(mode);
    await NativeBridge.instance.syncNativeTheme(mode.id);
    _markDirty(() {
      _section('general')['theme'] = mode.id;
    });
  }

  Future<void> _applyLocale(String locale) async {
    ref.read(localeProvider.notifier).setLocale(locale);
    await NativeBridge.instance.syncUiLocale(locale);
    _markDirty(() {
      _section('general')['locale'] = locale;
    });
  }

  Future<void> _addGalleryDir() async {
    final path = await BrowseDirSheet.pickFolder(context, ref.read(apiClientProvider));
    if (path == null || path.isEmpty) return;
    _markDirty(() {
      final gallery = _section('gallery');
      final dirs = ((gallery['directories'] as List?) ?? []).toList();
      dirs.add({'path': path, 'readonly': false, 'output_path': ''});
      gallery['directories'] = dirs;
    });
  }

  Future<void> _connectMetatube(Map<String, dynamic> metatube) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _metatubeBusy = true;
      _metatubeStatusText = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/settings/metatube/connect',
        data: {
          'url': (metatube['url'] ?? '').toString().trim(),
          'token': (metatube['token'] ?? '').toString().trim(),
          'allow_lan': metatube['allow_lan'] == true,
        },
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        final count = (resp['provider_count'] as num?)?.toInt() ?? 0;
        final freshCfg = await ref
            .read(apiClientProvider)
            .getJson('/api/config')
            .catchError((Object _) => <String, dynamic>{});
        if (!mounted) return;
        final freshData = freshCfg['data'];
        setState(() {
          if (freshData is Map) {
            if (freshData['sources'] is List) {
              _config['sources'] = jsonDecode(jsonEncode(freshData['sources']));
            }
            if (freshData['metatube'] is Map) {
              _config['metatube'] = jsonDecode(jsonEncode(freshData['metatube']));
            }
          }
          _metatubeConnected = true;
          _metatubeProviderCount = count;
          _metatubeStatusText = strings.metatubeConnectedCount(count);
        });
      } else {
        setState(() {
          _metatubeConnected = false;
          _metatubeStatusText = (resp['error'] ?? strings.connectFailed).toString();
        });
      }
    } catch (e) {
      debugPrint('connectMetatube error: $e');
      if (mounted) {
        setState(() => _metatubeStatusText = strings.requestFailed('$e'));
      }
    } finally {
      if (mounted) setState(() => _metatubeBusy = false);
    }
  }

  Future<void> _disconnectMetatube() async {
    final strings = ref.read(stringsProvider);
    setState(() => _metatubeBusy = true);
    try {
      await ref.read(apiClientProvider).postJson('/api/settings/metatube/disconnect');
      if (!mounted) return;
      setState(() {
        _metatubeConnected = false;
        _metatubeProviderCount = 0;
        _metatubeStatusText = strings.metatubeDisconnected;
      });
    } catch (e) {
      debugPrint('disconnectMetatube error: $e');
    } finally {
      if (mounted) setState(() => _metatubeBusy = false);
    }
  }

  Future<void> _retestMetatube() async {
    final strings = ref.read(stringsProvider);
    setState(() => _metatubeBusy = true);
    try {
      final resp = await ref.read(apiClientProvider).postJson('/api/settings/metatube/test');
      if (!mounted) return;
      _toast((resp['message'] ?? strings.connectSuccess).toString());
    } catch (e) {
      debugPrint('retestMetatube error: $e');
      _toast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _metatubeBusy = false);
    }
  }

  Future<void> _probeSources() async {
    final strings = ref.read(stringsProvider);
    final searchCfg = _section('search');
    final proxyUrl = (searchCfg['proxy_url'] ?? '').toString().trim();
    final proxyScope = searchCfg['proxy_scope'] == 'all' ? 'all' : 'dmm';
    final rawSources = (_config['sources'] as List?)
            ?.whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList() ??
        const <Map<String, dynamic>>[];
    var sourceIds = rawSources
        .where((s) => s['enabled'] == true)
        .map((s) => (s['id'] ?? '').toString().trim())
        .where((id) => id.isNotEmpty)
        .toList();
    if (sourceIds.isEmpty) {
      sourceIds = rawSources
          .map((s) => (s['id'] ?? '').toString().trim())
          .where((id) => id.isNotEmpty)
          .toList();
    }
    setState(() {
      _probingSources = true;
      _probeResults = const {};
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/sources/probe',
        data: {
          'proxy_url': proxyUrl,
          'proxy_scope': proxyScope,
          'source_ids': sourceIds,
        },
      );
      if (!mounted) return;
      final mapped = <String, String>{};
      String formatRow(Map<dynamic, dynamic> item) {
        final state = (item['state'] ?? '').toString();
        final reason = (item['reason'] ?? '').toString();
        final ok = item['ok'] == true || item['reachable'] == true || state == 'ok';
        final latency = item['latency_ms'];
        if (ok) {
          return latency != null ? 'OK (${latency}ms)' : 'OK';
        }
        if (state == 'skipped') {
          return reason.isNotEmpty ? 'SKIP ($reason)' : 'SKIP';
        }
        final label = state.isNotEmpty ? state.toUpperCase() : 'ERR';
        return reason.isNotEmpty && reason != state ? '$label ($reason)' : label;
      }

      final rawResults = resp['results'] ?? resp['sources'];
      if (rawResults is Map) {
        rawResults.forEach((k, v) {
          final id = k.toString();
          if (id.isNotEmpty && v is Map) {
            mapped[id] = formatRow(v);
          }
        });
      } else if (rawResults is List) {
        for (final item in rawResults.whereType<Map>()) {
          final id = (item['id'] ?? item['source'] ?? '').toString();
          if (id.isNotEmpty) {
            mapped[id] = formatRow(item);
          }
        }
      }
      setState(() {
        _probeResults = mapped;
        _probingSources = false;
      });
    } catch (e) {
      debugPrint('Settings _probeSources error: $e');
      if (mounted) {
        setState(() => _probingSources = false);
        _toast(strings.requestFailed('$e'));
      }
    }
  }

  List<String> _extractModelNames(dynamic raw) {
    if (raw is! List) return const [];
    final out = <String>[];
    for (final item in raw) {
      if (item is String && item.trim().isNotEmpty) {
        out.add(item.trim());
      } else if (item is Map && item['name'] != null) {
        final name = item['name'].toString().trim();
        if (name.isNotEmpty) out.add(name);
      }
    }
    return out;
  }

  Future<void> _fetchTranslateModels(String provider) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final sub = _nestedSection(_section('translate'), provider);
    setState(() {
      _fetchingTranslateModels = true;
      _translateStatus = null;
    });
    try {
      final endpoint = switch (provider) {
        'ollama' => '/api/ollama/models',
        'gemini' => '/api/gemini/test',
        'claude' => '/api/claude/models',
        'openai_official' => '/api/openai/official/models',
        _ => '/api/openai/models',
      };
      final payload = switch (provider) {
        'ollama' => {
          'url': (sub['url'] ?? '').toString().trim(),
          'api_key': (sub['api_key'] ?? '').toString(),
        },
        _ => {
          'base_url': (sub['base_url'] ?? '').toString().trim(),
          'api_key': (sub['api_key'] ?? '').toString(),
        },
      };
      final resp = await api.postJson(endpoint, data: payload);
      if (!mounted) return;
      final models = _extractModelNames(resp['models']);
      if (resp['success'] == true && models.isNotEmpty) {
        setState(() {
          _translateModels = models;
          if ((sub['model'] ?? '').toString().trim().isEmpty) {
            sub['model'] = (resp['default_model'] ?? models.first).toString();
            _presetRev++;
            _dirty = true;
          }
          _translateStatus = strings.modelsLoadedCount(models.length);
          _translateStatusOk = true;
        });
      } else {
        setState(() {
          _translateStatus = (resp['error'] ?? resp['message'] ?? strings.modelsFetchFailed).toString();
          _translateStatusOk = false;
        });
      }
    } catch (e) {
      debugPrint('fetchTranslateModels error: $e');
      if (mounted) {
        setState(() {
          _translateStatus = strings.requestFailed('$e');
          _translateStatusOk = false;
        });
      }
    } finally {
      if (mounted) setState(() => _fetchingTranslateModels = false);
    }
  }

  Future<void> _testTranslateConnection(String provider) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final tCfg = _section('translate');
    final sub = _nestedSection(tCfg, provider);
    setState(() {
      _testingAi = true;
      _translateStatus = null;
    });
    try {
      final endpoint = switch (provider) {
        'ollama' => '/api/ollama/test',
        'gemini' => '/api/gemini/test-translate',
        'claude' => '/api/claude/test',
        'openai_official' => '/api/openai/official/test',
        _ => '/api/openai/test',
      };
      final resp = await api.postJson(endpoint, data: sub);
      if (!mounted) return;
      if (resp['success'] == true || resp['ok'] == true) {
        final preview = (resp['translation'] ?? resp['result'] ?? '').toString().trim();
        final msg = preview.isNotEmpty ? '${strings.connectSuccess}: $preview' : strings.connectSuccess;
        setState(() {
          _translateStatus = msg;
          _translateStatusOk = true;
        });
        _toast(msg);
      } else {
        final msg = (resp['error'] ?? resp['message'] ?? strings.connectFailed).toString();
        setState(() {
          _translateStatus = msg;
          _translateStatusOk = false;
        });
        _toast(msg);
      }
    } catch (e) {
      debugPrint('testTranslateConnection error: $e');
      if (mounted) {
        setState(() {
          _translateStatus = strings.requestFailed('$e');
          _translateStatusOk = false;
        });
      }
      _toast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _testingAi = false);
    }
  }

  Future<void> _testSimilarConnection(Map<String, dynamic> aiSimilar) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _testingSimilar = true;
      _similarStatus = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/ai/similar/test',
        data: {
          'provider': (aiSimilar['provider'] ?? 'endpoint').toString(),
          'url': (aiSimilar['url'] ?? '').toString().trim(),
          'api_key': (aiSimilar['api_key'] ?? '').toString(),
          'model': (aiSimilar['model'] ?? '').toString().trim(),
        },
      );
      if (!mounted) return;
      if (resp['ok'] == true) {
        final model = (resp['model'] ?? '').toString();
        final dim = resp['dim'];
        final detail = [
          strings.connectSuccess,
          if (model.isNotEmpty) model,
          if (dim != null) 'dim=$dim',
        ].join(' · ');
        setState(() {
          _similarStatus = detail;
          _similarStatusOk = true;
        });
      } else {
        final err = [
          resp['kind']?.toString(),
          resp['check']?.toString(),
        ].where((s) => s != null && s.isNotEmpty).join(': ');
        setState(() {
          _similarStatus = err.isNotEmpty ? '${strings.connectFailed} ($err)' : strings.connectFailed;
          _similarStatusOk = false;
        });
      }
    } catch (e) {
      debugPrint('testSimilarConnection error: $e');
      if (mounted) {
        setState(() {
          _similarStatus = strings.requestFailed('$e');
          _similarStatusOk = false;
        });
      }
    } finally {
      if (mounted) setState(() => _testingSimilar = false);
    }
  }

  Future<void> _fetchFacesModels(Map<String, dynamic> aiFaces) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _fetchingFacesModels = true;
      _facesStatus = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/ai/faces/models',
        data: {
          'provider': (aiFaces['provider'] ?? 'openai').toString(),
          'url': (aiFaces['url'] ?? '').toString().trim(),
          'api_key': (aiFaces['api_key'] ?? '').toString(),
          'model': (aiFaces['model'] ?? '').toString().trim(),
        },
      );
      if (!mounted) return;
      final models = _extractModelNames(resp['models']);
      if (resp['success'] == true && models.isNotEmpty) {
        setState(() {
          _facesModels = models;
          if ((aiFaces['model'] ?? '').toString().trim().isEmpty) {
            aiFaces['model'] = models.first;
            _presetRev++;
            _dirty = true;
          }
          _facesStatus = strings.modelsLoadedCount(models.length);
          _facesStatusOk = true;
        });
      } else {
        setState(() {
          _facesStatus = strings.modelsFetchFailed;
          _facesStatusOk = false;
        });
      }
    } catch (e) {
      debugPrint('fetchFacesModels error: $e');
      if (mounted) {
        setState(() {
          _facesStatus = strings.requestFailed('$e');
          _facesStatusOk = false;
        });
      }
    } finally {
      if (mounted) setState(() => _fetchingFacesModels = false);
    }
  }

  Future<void> _testFacesConnection(Map<String, dynamic> aiFaces) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _testingFaces = true;
      _facesStatus = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/ai/faces/test',
        data: {
          'provider': (aiFaces['provider'] ?? 'endpoint').toString(),
          'url': (aiFaces['url'] ?? '').toString().trim(),
          'api_key': (aiFaces['api_key'] ?? '').toString(),
          'model': (aiFaces['model'] ?? '').toString().trim(),
        },
      );
      if (!mounted) return;
      if (resp['ok'] == true) {
        final model = (resp['model'] ?? '').toString();
        final boxes = (resp['boxes'] as List?)?.length ?? 0;
        setState(() {
          _facesStatus = '${strings.connectSuccess}${model.isNotEmpty ? ' · $model' : ''} (boxes=$boxes)';
          _facesStatusOk = true;
        });
      } else {
        final err = [
          resp['kind']?.toString(),
          resp['check']?.toString(),
        ].where((s) => s != null && s.isNotEmpty).join(': ');
        setState(() {
          _facesStatus = err.isNotEmpty ? '${strings.connectFailed} ($err)' : strings.connectFailed;
          _facesStatusOk = false;
        });
      }
    } catch (e) {
      debugPrint('testFacesConnection error: $e');
      if (mounted) {
        setState(() {
          _facesStatus = strings.requestFailed('$e');
          _facesStatusOk = false;
        });
      }
    } finally {
      if (mounted) setState(() => _testingFaces = false);
    }
  }

  Future<void> _fetchTagsModels(Map<String, dynamic> aiTags) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _fetchingTagsModels = true;
      _tagsStatus = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/ai/tags/models',
        data: {
          'provider': (aiTags['provider'] ?? '').toString(),
          'base_url': (aiTags['base_url'] ?? '').toString().trim(),
          'api_key': (aiTags['api_key'] ?? '').toString(),
          'model': (aiTags['model'] ?? '').toString().trim(),
        },
      );
      if (!mounted) return;
      final models = _extractModelNames(resp['models']);
      if (resp['success'] == true && models.isNotEmpty) {
        setState(() {
          _tagsModels = models;
          if ((aiTags['model'] ?? '').toString().trim().isEmpty) {
            aiTags['model'] = models.first;
            _presetRev++;
            _dirty = true;
          }
          _tagsStatus = strings.modelsLoadedCount(models.length);
          _tagsStatusOk = true;
        });
      } else {
        setState(() {
          _tagsStatus = (resp['error'] ?? strings.modelsFetchFailed).toString();
          _tagsStatusOk = false;
        });
      }
    } catch (e) {
      debugPrint('fetchTagsModels error: $e');
      if (mounted) {
        setState(() {
          _tagsStatus = strings.requestFailed('$e');
          _tagsStatusOk = false;
        });
      }
    } finally {
      if (mounted) setState(() => _fetchingTagsModels = false);
    }
  }

  Future<void> _testTagsConnection(Map<String, dynamic> aiTags) async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _testingTags = true;
      _tagsStatus = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/ai/tags/test',
        data: {
          'provider': (aiTags['provider'] ?? '').toString(),
          'base_url': (aiTags['base_url'] ?? '').toString().trim(),
          'api_key': (aiTags['api_key'] ?? '').toString(),
          'model': (aiTags['model'] ?? '').toString().trim(),
        },
      );
      if (!mounted) return;
      if (resp['ok'] == true) {
        final tags = (resp['tags'] as List?)?.map((e) => e.toString()).join(', ') ?? '';
        setState(() {
          _tagsStatus = tags.isNotEmpty ? '${strings.connectSuccess}: $tags' : strings.connectSuccess;
          _tagsStatusOk = true;
        });
      } else {
        final err = [
          resp['outcome']?.toString(),
          resp['detail']?.toString(),
        ].where((s) => s != null && s.isNotEmpty).join(': ');
        setState(() {
          _tagsStatus = err.isNotEmpty ? '${strings.connectFailed} ($err)' : strings.connectFailed;
          _tagsStatusOk = false;
        });
      }
    } catch (e) {
      debugPrint('testTagsConnection error: $e');
      if (mounted) {
        setState(() {
          _tagsStatus = strings.requestFailed('$e');
          _tagsStatusOk = false;
        });
      }
    } finally {
      if (mounted) setState(() => _testingTags = false);
    }
  }

  Future<void> _toggleFocalDeviceDisabled(bool disabled) async {
    final strings = ref.read(stringsProvider);
    try {
      final resp = await ref.read(apiClientProvider).putJson(
        '/api/config/focal-device/disabled',
        data: {'value': disabled},
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        setState(() {
          _section('focal_device')['disabled'] = disabled;
        });
      } else {
        _toast((resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('toggleFocalDeviceDisabled error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _exportDatabase() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    _toast(strings.loading);
    try {
      final tempFile = File('${Directory.systemTemp.path}/openaver_export.zip');
      await api.dio.download('/api/database/export', tempFile.path);
      final name = 'openaver-db-${DateTime.now().millisecondsSinceEpoch}.zip';
      final saved = await NativeBridge.instance.saveTempFileToDownloads(
        tempPath: tempFile.path,
        filename: name,
        mimeType: 'application/zip',
      );
      _toast(saved != null ? '${strings.exportDone}: $saved' : strings.saveFailed);
    } catch (e) {
      debugPrint('exportDatabase error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _importDatabase() async {
    final strings = ref.read(stringsProvider);
    final picked = await NativeBridge.instance.pickFile(
      mimeTypes: const ['application/zip', 'application/octet-stream'],
    );
    if (picked == null || picked.path.isEmpty) return;
    try {
      final form = FormData.fromMap({
        'file': await MultipartFile.fromFile(picked.path, filename: picked.name),
      });
      final resp = await ref.read(apiClientProvider).dio.post<dynamic>('/api/database/import', data: form);
      final body = resp.data is Map ? Map<String, dynamic>.from(resp.data as Map) : const <String, dynamic>{};
      if (body['ok'] == true) {
        ref.read(libraryRevisionProvider.notifier).bump();
        _toast(strings.restoreDone);
      } else {
        _toast((body['detail'] ?? body['error'] ?? strings.taskFailed).toString());
      }
    } catch (e) {
      debugPrint('importDatabase error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _resetFactoryConfig() async {
    final strings = ref.read(stringsProvider);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(strings.resetFactoryTitle),
        content: Text(strings.resetFactoryConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(strings.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(strings.confirm)),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(apiClientProvider).deleteJson('/api/config');
      if (!mounted) return;
      _toast(strings.saved);
      _loadAll(syncUiPrefs: true);
    } catch (e) {
      debugPrint('resetFactoryConfig error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _clearThumbnails() async {
    final strings = ref.read(stringsProvider);
    try {
      await ref.read(apiClientProvider).postJson('/api/gallery/thumb/clear');
      PaintingBinding.instance.imageCache.clear();
      PaintingBinding.instance.imageCache.clearLiveImages();
      ref.read(libraryRevisionProvider.notifier).bump();
      _toast(strings.thumbCacheCleared);
    } catch (e) {
      debugPrint('clearThumbnails error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  bool _showSec(String key) => _activeSection == 'all' || _activeSection == key;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final strings = ref.watch(stringsProvider);
    final activeTheme = ref.watch(themeModeProvider);
    final activeLocale = ref.watch(localeProvider);
    final boot = ref.watch(bootstrapProvider);

    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(_error!, style: TextStyle(color: palette.danger)),
                const SizedBox(height: 12),
                FilledButton(onPressed: _loadAll, child: Text(strings.retry)),
              ],
            ),
          ),
        ),
      );
    }

    final general = _section('general');
    final fontSize = (general['font_size'] ?? 'md').toString();
    final defaultPage = (general['default_page'] ?? 'search').toString();

    final gallery = _section('gallery');
    final dirs = ((gallery['directories'] as List?) ?? const []).toList();
    final minSizeMb = (gallery['min_size_mb'] as num?)?.toInt() ?? 0;
    final outputDir = (gallery['output_dir'] ?? '').toString();
    final thumbEnabled = _config['thumbnail_cache_enabled'] == true;
    final coverBadges = _nestedSection(gallery, 'cover_badges');
    final coverBadgesEnabled = coverBadges['enabled'] == true;

    final scraper = _section('scraper');
    final createFolder = scraper['create_folder'] != false;
    final folderFormat = (scraper['folder_format'] ?? '{actor}').toString();
    final filenameFormat = (scraper['filename_format'] ?? '{num} {title}').toString();
    final nfoTitleFormat = (scraper['nfo_title_format'] ?? '[{num}]{title}').toString();
    final coverFilename = (scraper['cover_filename'] ?? 'poster.jpg').toString();
    final downloadCover = scraper['download_cover'] != false;
    final createNfo = scraper['create_nfo'] != false;
    final downloadSamples = scraper['download_sample_images'] == true;
    final externalManager = (scraper['external_manager'] ?? 'off').toString();
    final maxTitleLength = (scraper['max_title_length'] as num?)?.toInt() ?? 50;
    final maxFilenameLength = (scraper['max_filename_length'] as num?)?.toInt() ?? 60;
    final videoExts = ((scraper['video_extensions'] as List?) ?? const []).join(', ');
    final suffixKeywords = ((scraper['suffix_keywords'] as List?) ?? const []).join(', ');

    final searchCfg = _section('search');
    final uncensored = searchCfg['uncensored_mode_enabled'] == true;
    final proxyUrl = (searchCfg['proxy_url'] ?? '').toString();
    final proxyScope = (searchCfg['proxy_scope'] ?? 'dmm').toString();
    final favoriteFolder = (searchCfg['favorite_folder'] ?? '').toString();
    final sourceLinks = _section('source_links');
    final metatube = _section('metatube');

    final translateCfg = _section('translate');
    final translateEnabled = translateCfg['enabled'] == true;
    final translateProvider = (translateCfg['provider'] ?? 'ollama').toString();
    final translateProviderCfg = _nestedSection(translateCfg, translateProvider);
    final focalDevice = _section('focal_device');
    final focalDisabled = focalDevice['disabled'] == true;
    final aiServices = _section('ai_services');
    final aiSimilar = _nestedSection(aiServices, 'image_similar');
    final aiFaces = _nestedSection(aiServices, 'faces');
    final aiTags = _nestedSection(aiServices, 'tags');

    final sources = ((_config['sources'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();

    final sections = [
      ('all', strings.allVideos),
      ('appearance', strings.secAppearance),
      ('gallery', strings.secGallery),
      ('scraper', strings.secScraper),
      ('sources', strings.secSearchSources),
      ('ai', strings.secAiServices),
      ('backup', strings.secBackupAbout),
    ];

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
              child: Row(
                children: sections
                    .map(
                      (s) => Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: ChoiceChip(
                          label: Text(s.$2),
                          selected: _activeSection == s.$1,
                          onSelected: (_) => setState(() => _activeSection = s.$1),
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 8, 14, 32),
                children: [
                  if (_showSec('appearance')) ...[
                    _SectionHeader(title: strings.secAppearance, palette: palette),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(strings.themeTitle, style: const TextStyle(fontWeight: FontWeight.w600)),
                            const SizedBox(height: 8),
                            SegmentedButton<AppThemeMode>(
                              segments: [
                                ButtonSegment(value: AppThemeMode.dim, label: Text(strings.themeDim)),
                                ButtonSegment(value: AppThemeMode.dark, label: Text(strings.themeDark)),
                                ButtonSegment(value: AppThemeMode.light, label: Text(strings.themeLight)),
                              ],
                              selected: {activeTheme},
                              onSelectionChanged: (v) => _applyTheme(v.first),
                            ),
                            const SizedBox(height: 14),
                            Text(strings.languageTitle, style: const TextStyle(fontWeight: FontWeight.w600)),
                            const SizedBox(height: 8),
                            Wrap(
                              spacing: 8,
                              children: AppStrings.supportedLocales.map((loc) {
                                return ChoiceChip(
                                  label: Text(loc),
                                  selected: activeLocale == loc,
                                  onSelected: (_) => _applyLocale(loc),
                                );
                              }).toList(),
                            ),
                            const SizedBox(height: 14),
                            Text(strings.fontSizeTitle, style: const TextStyle(fontWeight: FontWeight.w600)),
                            const SizedBox(height: 8),
                            SegmentedButton<String>(
                              segments: const [
                                ButtonSegment(value: 'xs', label: Text('XS')),
                                ButtonSegment(value: 'sm', label: Text('S')),
                                ButtonSegment(value: 'md', label: Text('M')),
                                ButtonSegment(value: 'lg', label: Text('L')),
                                ButtonSegment(value: 'xl', label: Text('XL')),
                              ],
                              selected: {const {'xs', 'sm', 'md', 'lg', 'xl'}.contains(fontSize) ? fontSize : 'md'},
                              onSelectionChanged: (v) {
                                ref.read(fontSizeProvider.notifier).setFontSize(v.first);
                                _markDirty(() => general['font_size'] = v.first);
                              },
                            ),
                            const SizedBox(height: 14),
                            _SettingsDropdown(
                              label: strings.defaultPageTitle,
                              initialValue: const {'search', 'gallery', 'showcase'}.contains(defaultPage) ? defaultPage : 'search',
                              items: [
                                DropdownMenuItem(value: 'search', child: Text(strings.tabSearch)),
                                DropdownMenuItem(value: 'gallery', child: Text(strings.tabScanner)),
                                DropdownMenuItem(value: 'showcase', child: Text(strings.tabShowcase)),
                              ],
                              onChanged: (v) {
                                if (v != null) _markDirty(() => general['default_page'] = v);
                              },
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  if (_showSec('gallery')) ...[
                    _SectionHeader(title: strings.secGallery, palette: palette),
                    Card(
                      child: Column(
                        children: [
                          ListTile(
                            leading: Icon(
                              _storageGranted ? Icons.verified_user_outlined : Icons.warning_amber_rounded,
                              color: _storageGranted ? palette.success : palette.warning,
                            ),
                            title: Text(strings.storagePermissionTitle),
                            subtitle: Text(_storageGranted ? strings.granted : strings.notGranted),
                            trailing: TextButton(
                              onPressed: () async {
                                await NativeBridge.instance.openStoragePermission();
                                final granted = await NativeBridge.instance.hasStorageAccess();
                                if (mounted) setState(() => _storageGranted = granted);
                              },
                              child: Text(strings.tabSettings),
                            ),
                          ),
                          const Divider(height: 1),
                          ListTile(
                            leading: Icon(Icons.sd_storage_outlined, color: palette.accent),
                            title: Text(strings.safTreeTitle),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(_treeInfo.granted ? _treeInfo.description : strings.safNotConfigured),
                                Wrap(
                                  spacing: 8,
                                  crossAxisAlignment: WrapCrossAlignment.center,
                                  children: [
                                    TextButton(
                                      onPressed: () async {
                                        final updated = await NativeBridge.instance.openStorageTreePicker();
                                        if (updated != null && mounted) {
                                          setState(() => _treeInfo = updated);
                                        }
                                      },
                                      child: Text(strings.authorize),
                                    ),
                                    if (_treeInfo.granted)
                                      IconButton(
                                        icon: const Icon(Icons.link_off_rounded, size: 18),
                                        onPressed: () async {
                                          await NativeBridge.instance.clearStorageTree();
                                          final updated = await NativeBridge.instance.getStorageTreeInfo();
                                          if (mounted) setState(() => _treeInfo = updated);
                                        },
                                      ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                          const Divider(height: 1),
                          for (var i = 0; i < dirs.length; i++)
                            Builder(
                              builder: (_) {
                                final raw = dirs[i];
                                final map = raw is Map
                                    ? Map<String, dynamic>.from(raw)
                                    : <String, dynamic>{'path': raw.toString(), 'readonly': false};
                                final path = (map['path'] ?? '').toString();
                                final ro = map['readonly'] == true;
                                return ListTile(
                                  title: Text(path, style: const TextStyle(fontSize: 13)),
                                  subtitle: Text(ro ? strings.readonlySource : strings.writableSource),
                                  trailing: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Switch(
                                        value: ro,
                                        onChanged: (v) => _markDirty(() {
                                          map['readonly'] = v;
                                          dirs[i] = map;
                                          gallery['directories'] = dirs;
                                        }),
                                      ),
                                      IconButton(
                                        icon: const Icon(Icons.delete_outline_rounded),
                                        onPressed: () => _markDirty(() {
                                          dirs.removeAt(i);
                                          gallery['directories'] = dirs;
                                        }),
                                      ),
                                    ],
                                  ),
                                );
                              },
                            ),
                          Padding(
                            padding: const EdgeInsets.all(10),
                            child: SizedBox(
                              width: double.infinity,
                              child: OutlinedButton.icon(
                                onPressed: _addGalleryDir,
                                icon: const Icon(Icons.add_rounded),
                                label: Text(strings.addScanDir),
                              ),
                            ),
                          ),
                          const Divider(height: 1),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                            child: _SettingsTextField(
                              label: strings.outputDirTitle,
                              note: strings.outputDirHelp,
                              initialValue: outputDir,
                              onChanged: (v) => _markDirty(() => gallery['output_dir'] = v.trim()),
                            ),
                          ),
                          SwitchListTile(
                            title: Text(strings.thumbCacheTitle),
                            subtitle: Text(strings.thumbCacheSub),
                            value: thumbEnabled,
                            onChanged: (v) => _markDirty(() => _config['thumbnail_cache_enabled'] = v),
                          ),
                          SwitchListTile(
                            title: Text(strings.coverBadgesTitle),
                            value: coverBadgesEnabled,
                            onChanged: (v) => _markDirty(() => coverBadges['enabled'] = v),
                          ),
                          ListTile(
                            title: Text(strings.minVideoSizeTitle),
                            subtitle: Text('$minSizeMb MB'),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.remove_circle_outline),
                                  onPressed: minSizeMb <= 0
                                      ? null
                                      : () => _markDirty(() => gallery['min_size_mb'] = (minSizeMb - 50).clamp(0, 5000)),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.add_circle_outline),
                                  onPressed: () => _markDirty(() => gallery['min_size_mb'] = minSizeMb + 50),
                                ),
                              ],
                            ),
                          ),
                          ListTile(
                            title: Text(strings.clearThumbCache),
                            trailing: OutlinedButton(onPressed: _clearThumbnails, child: Text(strings.clear)),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  if (_showSec('scraper')) ...[
                    _SectionHeader(title: strings.secScraper, palette: palette),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          children: [
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.createFolderTitle),
                              value: createFolder,
                              onChanged: (v) => _markDirty(() => scraper['create_folder'] = v),
                            ),
                            _SettingsTextField(
                              label: strings.folderFormatTitle,
                              note: strings.folderFormatHelp,
                              initialValue: folderFormat,
                              onChanged: (v) => _markDirty(() => scraper['folder_format'] = v),
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              label: strings.filenameFormatTitle,
                              note: strings.filenameFormatHelp,
                              initialValue: filenameFormat,
                              onChanged: (v) => _markDirty(() => scraper['filename_format'] = v),
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              label: strings.nfoTitleFormatTitle,
                              initialValue: nfoTitleFormat,
                              onChanged: (v) => _markDirty(() => scraper['nfo_title_format'] = v),
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              label: strings.coverFilenameTitle,
                              initialValue: coverFilename,
                              onChanged: (v) => _markDirty(() => scraper['cover_filename'] = v.trim()),
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.downloadCoverTitle),
                              value: downloadCover,
                              onChanged: (v) => _markDirty(() => scraper['download_cover'] = v),
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.createNfoTitle),
                              value: createNfo,
                              onChanged: (v) => _markDirty(() => scraper['create_nfo'] = v),
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.downloadSamplesTitle),
                              value: downloadSamples,
                              onChanged: (v) => _markDirty(() => scraper['download_sample_images'] = v),
                            ),
                            _SettingsDropdown(
                              label: strings.externalManagerTitle,
                              initialValue: const {'off', 'jellyfin', 'emby', 'kodi'}.contains(externalManager)
                                  ? externalManager
                                  : 'off',
                              items: const [
                                DropdownMenuItem(value: 'off', child: Text('Off')),
                                DropdownMenuItem(value: 'jellyfin', child: Text('Jellyfin')),
                                DropdownMenuItem(value: 'emby', child: Text('Emby')),
                                DropdownMenuItem(value: 'kodi', child: Text('Kodi')),
                              ],
                              onChanged: (v) {
                                if (v != null) _markDirty(() => scraper['external_manager'] = v);
                              },
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            LayoutBuilder(
                              builder: (context, constraints) {
                                final width = constraints.maxWidth;
                                final labelScale = MediaQuery.textScalerOf(context).scale(14) / 14;
                                final fieldWidth = width >= 360 * labelScale
                                    ? (width - _settingsFieldSpacing) / 2
                                    : width;
                                final fields = [
                                  _SettingsTextField(
                                    label: strings.maxTitleLengthTitle,
                                    initialValue: '$maxTitleLength',
                                    keyboardType: TextInputType.number,
                                    onChanged: (v) {
                                      final parsed = int.tryParse(v.trim());
                                      if (parsed != null && parsed > 0) {
                                        _markDirty(() => scraper['max_title_length'] = parsed);
                                      }
                                    },
                                  ),
                                  _SettingsTextField(
                                    label: strings.maxFilenameLengthTitle,
                                    initialValue: '$maxFilenameLength',
                                    keyboardType: TextInputType.number,
                                    onChanged: (v) {
                                      final parsed = int.tryParse(v.trim());
                                      if (parsed != null && parsed > 0) {
                                        _markDirty(() => scraper['max_filename_length'] = parsed);
                                      }
                                    },
                                  ),
                                ];
                                return Wrap(
                                  spacing: _settingsFieldSpacing,
                                  runSpacing: _settingsFieldSpacing,
                                  children: [
                                    for (final field in fields)
                                      SizedBox(width: fieldWidth, child: field),
                                  ],
                                );
                              },
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              label: strings.videoExtensionsTitle,
                              note: strings.commaSeparatedHelp,
                              initialValue: videoExts,
                              onChanged: (v) => _markDirty(() {
                                scraper['video_extensions'] = v
                                    .split(',')
                                    .map((e) => e.trim())
                                    .where((e) => e.isNotEmpty)
                                    .toList();
                              }),
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              label: strings.suffixKeywordsTitle,
                              note: strings.commaSeparatedHelp,
                              initialValue: suffixKeywords,
                              onChanged: (v) => _markDirty(() {
                                scraper['suffix_keywords'] = v
                                    .split(',')
                                    .map((e) => e.trim())
                                    .where((e) => e.isNotEmpty)
                                    .toList();
                              }),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  if (_showSec('sources')) ...[
                    _SectionHeader(title: strings.secSearchSources, palette: palette),
                    Card(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          SwitchListTile(
                            title: Text(strings.uncensoredModeTitle),
                            value: uncensored,
                            onChanged: (v) => _markDirty(() => searchCfg['uncensored_mode_enabled'] = v),
                          ),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 4, 16, 14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              spacing: _settingsFieldSpacing,
                              children: [
                                _SettingsTextField(
                                  label: strings.proxyUrlTitle,
                                  initialValue: proxyUrl,
                                  onChanged: (v) => _markDirty(() => searchCfg['proxy_url'] = v.trim()),
                                ),
                                _SettingsDropdown(
                                  label: strings.proxyScopeTitle,
                                  initialValue: proxyScope == 'all' ? 'all' : 'dmm',
                                  items: const [
                                    DropdownMenuItem(value: 'dmm', child: Text('DMM')),
                                    DropdownMenuItem(value: 'all', child: Text('All')),
                                  ],
                                  onChanged: (v) {
                                    if (v != null) _markDirty(() => searchCfg['proxy_scope'] = v);
                                  },
                                ),
                                _SettingsTextField(
                                  key: ValueKey('fav_$_presetRev'),
                                  label: strings.favoriteFolderTitle,
                                  initialValue: favoriteFolder,
                                  onChanged: (v) => _markDirty(() => searchCfg['favorite_folder'] = v.trim()),
                                  trailing: IconButton.filledTonal(
                                    icon: const Icon(Icons.folder_open_rounded),
                                    tooltip: strings.chooseFolder,
                                    onPressed: () async {
                                      final picked = await BrowseDirSheet.pickFolder(
                                        context,
                                        ref.read(apiClientProvider),
                                        initialPath: favoriteFolder.isNotEmpty ? favoriteFolder : null,
                                      );
                                      if (!mounted || picked == null || picked.isEmpty) return;
                                      _markDirty(() {
                                        searchCfg['favorite_folder'] = picked;
                                        _presetRev++;
                                      });
                                    },
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const Divider(height: 1),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    strings.sourceCapHint,
                                    style: TextStyle(fontSize: 11.5, color: palette.textMuted),
                                  ),
                                ),
                                TextButton.icon(
                                  onPressed: _probingSources ? null : _probeSources,
                                  icon: _probingSources
                                      ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                      : const Icon(Icons.network_check_rounded, size: 16),
                                  label: Text(strings.testSources),
                                ),
                              ],
                            ),
                          ),
                          ReorderableListView.builder(
                            shrinkWrap: true,
                            physics: const NeverScrollableScrollPhysics(),
                            itemCount: sources.length,
                            onReorderItem: (oldIndex, newIndex) {
                              _markDirty(() {
                                final moved = sources.removeAt(oldIndex);
                                sources.insert(newIndex, moved);
                                for (var i = 0; i < sources.length; i++) {
                                  sources[i]['order'] = i;
                                }
                                _config['sources'] = sources;
                              });
                            },
                            itemBuilder: (_, idx) {
                              final src = sources[idx];
                              final id = (src['id'] ?? '').toString();
                              final enabled = src['enabled'] == true;
                              final manualOnly = src['manual_only'] == true;
                              final probeState = _probeResults[id];
                              return SwitchListTile(
                                key: ValueKey('src_$id'),
                                secondary: const Icon(Icons.drag_handle_rounded),
                                title: Row(
                                  children: [
                                    Text(id.toUpperCase()),
                                    if (probeState != null) ...[
                                      const SizedBox(width: 8),
                                      Flexible(
                                        child: Text(
                                          probeState,
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            fontSize: 11,
                                            color: probeState.startsWith('OK')
                                                ? palette.success
                                                : probeState.startsWith('SKIP')
                                                    ? palette.textMuted
                                                    : palette.danger,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ],
                                ),
                                value: enabled,
                                onChanged: (v) {
                                  if (v && !manualOnly) {
                                    final activeCount = sources
                                        .where((s) => s['enabled'] == true && s['manual_only'] != true)
                                        .length;
                                    if (activeCount >= 10) {
                                      _toast(strings.sourceCapHint);
                                      return;
                                    }
                                  }
                                  _markDirty(() {
                                    sources[idx]['enabled'] = v;
                                    _config['sources'] = sources;
                                  });
                                },
                              );
                            },
                          ),
                          const Divider(height: 1),
                          Padding(
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(strings.sourceLinksTitle, style: const TextStyle(fontWeight: FontWeight.w600)),
                                const SizedBox(height: 8),
                                Wrap(
                                  spacing: 8,
                                  runSpacing: 6,
                                  children: ['dmm', 'd2pass', 'heyzo', 'fc2', 'javbus', 'jav321', 'javdb', 'avsox']
                                      .map((k) {
                                        final on = sourceLinks[k] == true;
                                        return FilterChip(
                                          label: Text(k.toUpperCase()),
                                          selected: on,
                                          onSelected: (v) => _markDirty(() => sourceLinks[k] = v),
                                        );
                                      })
                                      .toList(),
                                ),
                                const SizedBox(height: 14),
                                SwitchListTile(
                                  contentPadding: EdgeInsets.zero,
                                  title: Text(strings.metatubeSectionTitle),
                                  value: metatube['enabled'] == true,
                                  onChanged: (v) => _markDirty(() => metatube['enabled'] = v),
                                ),
                                if (metatube['enabled'] == true) ...[
                                  _SettingsTextField(
                                    label: strings.serviceUrlLabel,
                                    initialValue: (metatube['url'] ?? '').toString(),
                                    onChanged: (v) => _markDirty(() => metatube['url'] = v.trim()),
                                  ),
                                  const SizedBox(height: _settingsFieldSpacing),
                                  _SettingsTextField(
                                    label: strings.accessTokenLabel,
                                    initialValue: (metatube['token'] ?? '').toString(),
                                    obscureText: true,
                                    onChanged: (v) => _markDirty(() => metatube['token'] = v.trim()),
                                  ),
                                  SwitchListTile(
                                    contentPadding: EdgeInsets.zero,
                                    title: Text(strings.metatubeAllowLan),
                                    value: metatube['allow_lan'] == true,
                                    onChanged: (v) => _markDirty(() => metatube['allow_lan'] = v),
                                  ),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 6,
                                    children: [
                                      FilledButton.tonalIcon(
                                        onPressed: _metatubeBusy ? null : () => _connectMetatube(metatube),
                                        icon: _metatubeBusy
                                            ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                            : const Icon(Icons.link_rounded, size: 16),
                                        label: Text(strings.metatubeConnect),
                                      ),
                                      if (_metatubeConnected)
                                        OutlinedButton.icon(
                                          onPressed: _metatubeBusy ? null : _retestMetatube,
                                          icon: const Icon(Icons.network_check_rounded, size: 16),
                                          label: Text(strings.metatubeRetest),
                                        ),
                                      if (_metatubeConnected)
                                        TextButton(
                                          onPressed: _metatubeBusy ? null : _disconnectMetatube,
                                          child: Text(strings.metatubeDisconnect),
                                        ),
                                    ],
                                  ),
                                  _AiStatusBanner(
                                    message: _metatubeStatusText ??
                                        (_metatubeConnected ? strings.metatubeConnectedCount(_metatubeProviderCount) : null),
                                    ok: _metatubeConnected,
                                    palette: palette,
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  if (_showSec('ai')) ...[
                    _SectionHeader(title: strings.secAiServices, palette: palette),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.enableAiTranslateTitle),
                              value: translateEnabled,
                              onChanged: (v) => _markDirty(() => translateCfg['enabled'] = v),
                            ),
                            _SettingsDropdown(
                              label: strings.translateProviderTitle,
                              initialValue: const {'ollama', 'gemini', 'openai', 'openai_official', 'claude'}
                                      .contains(translateProvider)
                                  ? translateProvider
                                  : 'ollama',
                              items: const [
                                DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
                                DropdownMenuItem(value: 'openai', child: Text('OpenAI Compatible')),
                                DropdownMenuItem(value: 'openai_official', child: Text('OpenAI Official')),
                                DropdownMenuItem(value: 'gemini', child: Text('Google Gemini')),
                                DropdownMenuItem(value: 'claude', child: Text('Anthropic Claude')),
                              ],
                              onChanged: (v) {
                                if (v != null) {
                                  _markDirty(() {
                                    translateCfg['provider'] = v;
                                    _translateModels = const [];
                                    _translateStatus = null;
                                  });
                                }
                              },
                            ),
                            if (translateProvider == 'openai') ...[
                              const SizedBox(height: 8),
                              _AiPresetChips(
                                label: strings.presetsLabel,
                                palette: palette,
                                presets: const [
                                  ('DeepSeek', 'https://api.deepseek.com/v1', 'deepseek-chat'),
                                  ('Qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'),
                                  ('OpenRouter', 'https://openrouter.ai/api/v1', 'google/gemini-2.5-flash'),
                                  ('SiliconFlow', 'https://api.siliconflow.cn/v1', 'deepseek-ai/DeepSeek-V3'),
                                ],
                                onSelect: (url, model) => _markDirty(() {
                                  translateProviderCfg['base_url'] = url;
                                  if (model.isNotEmpty) translateProviderCfg['model'] = model;
                                  _translateModels = const [];
                                  _translateStatus = null;
                                  _presetRev++;
                                }),
                              ),
                            ],
                            const SizedBox(height: _settingsFieldSpacing),
                            if (translateProviderCfg.containsKey('url') || translateProvider == 'ollama')
                              _SettingsTextField(
                                label: strings.serviceUrlLabel,
                                key: ValueKey('tr_url_${translateProvider}_$_presetRev'),
                                initialValue: (translateProviderCfg['url'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => translateProviderCfg['url'] = v.trim()),
                              )
                            else
                              _SettingsTextField(
                                label: strings.baseUrlLabel,
                                key: ValueKey('tr_base_${translateProvider}_$_presetRev'),
                                initialValue: (translateProviderCfg['base_url'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => translateProviderCfg['base_url'] = v.trim()),
                              ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              label: strings.apiKeyLabel,
                              key: ValueKey('tr_key_${translateProvider}_$_presetRev'),
                              initialValue: (translateProviderCfg['api_key'] ?? '').toString(),
                              obscureText: true,
                              onChanged: (v) => _markDirty(() => translateProviderCfg['api_key'] = v.trim()),
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            _SettingsTextField(
                              key: ValueKey('tr_model_${translateProvider}_$_presetRev'),
                              label: strings.modelLabel,
                              initialValue: (translateProviderCfg['model'] ?? '').toString(),
                              onChanged: (v) => _markDirty(() => translateProviderCfg['model'] = v.trim()),
                            ),
                            const SizedBox(height: _settingsFieldSpacing),
                            Wrap(
                              spacing: 8,
                              runSpacing: 6,
                              children: [
                                OutlinedButton.icon(
                                  onPressed: _fetchingTranslateModels
                                      ? null
                                      : () => _fetchTranslateModels(translateProvider),
                                  icon: _fetchingTranslateModels
                                      ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                      : const Icon(Icons.cloud_download_outlined, size: 16),
                                  label: Text(strings.fetchModelsBtn),
                                ),
                                OutlinedButton.icon(
                                  onPressed: _testingAi ? null : () => _testTranslateConnection(translateProvider),
                                  icon: _testingAi
                                      ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                      : const Icon(Icons.bolt_rounded, size: 16),
                                  label: Text(strings.testTranslateBtn),
                                ),
                              ],
                            ),
                            _AiModelChips(
                              models: _translateModels,
                              currentModel: (translateProviderCfg['model'] ?? '').toString(),
                              title: strings.quickModelSelectLabel,
                              palette: palette,
                              onSelected: (m) => _markDirty(() {
                                translateProviderCfg['model'] = m;
                                _presetRev++;
                              }),
                            ),
                            _AiStatusBanner(
                              message: _translateStatus,
                              ok: _translateStatusOk,
                              palette: palette,
                            ),
                            const Divider(height: 24),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.focalAutoEnabledTitle),
                              value: focalDisabled,
                              onChanged: _toggleFocalDeviceDisabled,
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.aiImageSimilarTitle),
                              value: aiSimilar['enabled'] == true,
                              onChanged: (v) => _markDirty(() => aiSimilar['enabled'] = v),
                            ),
                            if (aiSimilar['enabled'] == true) ...[
                              _SettingsDropdown(
                                label: strings.serviceTypeLabel,
                                initialValue: aiSimilar['provider'] == 'qwen' ? 'qwen' : 'endpoint',
                                items: [
                                  DropdownMenuItem(value: 'endpoint', child: Text(strings.legacyEndpointType)),
                                  DropdownMenuItem(value: 'qwen', child: Text(strings.qwenEmbeddingType)),
                                ],
                                onChanged: (v) {
                                  if (v == null) return;
                                  _markDirty(() {
                                    aiSimilar['provider'] = v;
                                    if (v == 'qwen') {
                                      aiSimilar['url'] = 'https://dashscope.aliyuncs.com';
                                      aiSimilar['model'] = 'qwen3-vl-embedding';
                                    } else if (aiSimilar['url'] == 'https://dashscope.aliyuncs.com') {
                                      aiSimilar['url'] = '';
                                      aiSimilar['model'] = '';
                                    }
                                    _similarStatus = null;
                                    _presetRev++;
                                  });
                                },
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.serviceUrlLabel,
                                key: ValueKey('sim_url_$_presetRev'),
                                initialValue: (aiSimilar['url'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => aiSimilar['url'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.apiKeyLabel,
                                key: ValueKey('sim_key_$_presetRev'),
                                initialValue: (aiSimilar['api_key'] ?? '').toString(),
                                obscureText: true,
                                onChanged: (v) => _markDirty(() => aiSimilar['api_key'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.modelLabel,
                                key: ValueKey('sim_model_$_presetRev'),
                                initialValue: (aiSimilar['model'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => aiSimilar['model'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              OutlinedButton.icon(
                                onPressed: _testingSimilar ? null : () => _testSimilarConnection(aiSimilar),
                                icon: _testingSimilar
                                    ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                    : const Icon(Icons.network_check_rounded, size: 16),
                                label: Text(strings.testConnection),
                              ),
                              _AiStatusBanner(
                                message: _similarStatus,
                                ok: _similarStatusOk,
                                palette: palette,
                              ),
                              AiBackfillBar(
                                api: ref.read(apiClientProvider),
                                strings: strings,
                                statusEndpoint: '/api/ai/similar/status',
                                startEndpoint: '/api/ai/similar/index',
                                stopEndpoint: '/api/ai/similar/index/stop',
                                rebuildEndpoint: '/api/ai/similar/index/rebuild',
                              ),
                              const SizedBox(height: 6),
                            ],
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.aiFacesTitle),
                              value: aiFaces['enabled'] == true,
                              onChanged: (v) => _markDirty(() => aiFaces['enabled'] = v),
                            ),
                            if (aiFaces['enabled'] == true) ...[
                              _SettingsDropdown(
                                label: strings.serviceTypeLabel,
                                initialValue: aiFaces['provider'] == 'openai' ? 'openai' : 'endpoint',
                                items: [
                                  DropdownMenuItem(value: 'endpoint', child: Text(strings.legacyEndpointType)),
                                  DropdownMenuItem(value: 'openai', child: Text(strings.openaiVisionType)),
                                ],
                                onChanged: (v) {
                                  if (v == null) return;
                                  _markDirty(() {
                                    aiFaces['provider'] = v;
                                    _facesModels = const [];
                                    _facesStatus = null;
                                  });
                                },
                              ),
                              if (aiFaces['provider'] == 'openai') ...[
                                const SizedBox(height: 8),
                                _AiPresetChips(
                                  label: strings.presetsLabel,
                                  palette: palette,
                                  presets: const [
                                    ('Qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3-vl-plus'),
                                    ('DeepSeek', 'https://api.deepseek.com', 'deepseek-flash'),
                                    ('B.AI', 'https://api.b.ai/v1', ''),
                                  ],
                                  onSelect: (url, model) => _markDirty(() {
                                    aiFaces['url'] = url;
                                    aiFaces['model'] = model;
                                    _facesModels = const [];
                                    _facesStatus = null;
                                    _presetRev++;
                                  }),
                                ),
                              ],
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.serviceUrlLabel,
                                key: ValueKey('faces_url_$_presetRev'),
                                initialValue: (aiFaces['url'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => aiFaces['url'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.apiKeyLabel,
                                key: ValueKey('faces_key_$_presetRev'),
                                initialValue: (aiFaces['api_key'] ?? '').toString(),
                                obscureText: true,
                                onChanged: (v) => _markDirty(() => aiFaces['api_key'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.modelLabel,
                                key: ValueKey('faces_model_$_presetRev'),
                                initialValue: (aiFaces['model'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => aiFaces['model'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              Wrap(
                                spacing: 8,
                                runSpacing: 6,
                                children: [
                                  if (aiFaces['provider'] == 'openai')
                                    OutlinedButton.icon(
                                      onPressed: _fetchingFacesModels ? null : () => _fetchFacesModels(aiFaces),
                                      icon: _fetchingFacesModels
                                          ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                          : const Icon(Icons.cloud_download_outlined, size: 16),
                                      label: Text(strings.fetchModelsBtn),
                                    ),
                                  OutlinedButton.icon(
                                    onPressed: _testingFaces ? null : () => _testFacesConnection(aiFaces),
                                    icon: _testingFaces
                                        ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                        : const Icon(Icons.network_check_rounded, size: 16),
                                    label: Text(strings.testConnection),
                                  ),
                                ],
                              ),
                              _AiModelChips(
                                models: _facesModels,
                                currentModel: (aiFaces['model'] ?? '').toString(),
                                title: strings.quickModelSelectLabel,
                                palette: palette,
                                onSelected: (m) => _markDirty(() {
                                  aiFaces['model'] = m;
                                  _presetRev++;
                                }),
                              ),
                              _AiStatusBanner(
                                message: _facesStatus,
                                ok: _facesStatusOk,
                                palette: palette,
                              ),
                              AiBackfillBar(
                                api: ref.read(apiClientProvider),
                                strings: strings,
                                statusEndpoint: '/api/ai/faces/status',
                                startEndpoint: '/api/ai/faces/recompute',
                                stopEndpoint: '/api/ai/faces/recompute/stop',
                                rebuildEndpoint: '/api/ai/faces/rebuild',
                              ),
                              const SizedBox(height: 6),
                            ],
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.aiTagsTitle),
                              value: aiTags['enabled'] == true,
                              onChanged: (v) => _markDirty(() {
                                aiTags['enabled'] = v;
                                if (v && (aiTags['provider'] ?? '').toString().isEmpty) {
                                  aiTags['provider'] = translateProvider;
                                  aiTags['base_url'] = switch (translateProvider) {
                                    'ollama' => 'http://localhost:11434',
                                    'gemini' => 'https://generativelanguage.googleapis.com/v1beta',
                                    'claude' => 'https://api.anthropic.com',
                                    'openai_official' => 'https://api.openai.com/v1',
                                    _ => '',
                                  };
                                  _presetRev++;
                                }
                              }),
                            ),
                            if (aiTags['enabled'] == true) ...[
                              _SettingsDropdown(
                                label: strings.translateProviderTitle,
                                initialValue: const {'', 'ollama', 'gemini', 'claude', 'openai_official', 'openai'}
                                        .contains((aiTags['provider'] ?? '').toString())
                                    ? (aiTags['provider'] ?? '').toString()
                                    : '',
                                items: [
                                  DropdownMenuItem(value: '', child: Text(strings.providerPlaceholder)),
                                  const DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
                                  const DropdownMenuItem(value: 'openai', child: Text('OpenAI Compatible')),
                                  const DropdownMenuItem(value: 'openai_official', child: Text('OpenAI Official')),
                                  const DropdownMenuItem(value: 'gemini', child: Text('Google Gemini')),
                                  const DropdownMenuItem(value: 'claude', child: Text('Anthropic Claude')),
                                ],
                                onChanged: (v) {
                                  if (v == null) return;
                                  _markDirty(() {
                                    aiTags['provider'] = v;
                                    aiTags['base_url'] = switch (v) {
                                      'ollama' => 'http://localhost:11434',
                                      'gemini' => 'https://generativelanguage.googleapis.com/v1beta',
                                      'claude' => 'https://api.anthropic.com',
                                      'openai_official' => 'https://api.openai.com/v1',
                                      _ => '',
                                    };
                                    _tagsModels = const [];
                                    _tagsStatus = null;
                                    _presetRev++;
                                  });
                                },
                              ),
                              if (aiTags['provider'] == 'openai') ...[
                                const SizedBox(height: 8),
                                _AiPresetChips(
                                  label: strings.presetsLabel,
                                  palette: palette,
                                  presets: const [
                                    ('Qwen', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-vl-plus'),
                                    ('OpenRouter', 'https://openrouter.ai/api/v1', 'google/gemini-2.5-flash'),
                                    ('B.AI', 'https://api.b.ai/v1', ''),
                                  ],
                                  onSelect: (url, model) => _markDirty(() {
                                    aiTags['base_url'] = url;
                                    if (model.isNotEmpty) aiTags['model'] = model;
                                    _tagsModels = const [];
                                    _tagsStatus = null;
                                    _presetRev++;
                                  }),
                                ),
                              ],
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.baseUrlLabel,
                                key: ValueKey('tags_url_$_presetRev'),
                                initialValue: (aiTags['base_url'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => aiTags['base_url'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.apiKeyLabel,
                                key: ValueKey('tags_key_$_presetRev'),
                                initialValue: (aiTags['api_key'] ?? '').toString(),
                                obscureText: true,
                                onChanged: (v) => _markDirty(() => aiTags['api_key'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              _SettingsTextField(
                                label: strings.modelLabel,
                                key: ValueKey('tags_model_$_presetRev'),
                                initialValue: (aiTags['model'] ?? '').toString(),
                                onChanged: (v) => _markDirty(() => aiTags['model'] = v.trim()),
                              ),
                              const SizedBox(height: _settingsFieldSpacing),
                              Wrap(
                                spacing: 8,
                                runSpacing: 6,
                                children: [
                                  OutlinedButton.icon(
                                    onPressed: _fetchingTagsModels ? null : () => _fetchTagsModels(aiTags),
                                    icon: _fetchingTagsModels
                                        ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                        : const Icon(Icons.cloud_download_outlined, size: 16),
                                    label: Text(strings.fetchModelsBtn),
                                  ),
                                  OutlinedButton.icon(
                                    onPressed: _testingTags ? null : () => _testTagsConnection(aiTags),
                                    icon: _testingTags
                                        ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                        : const Icon(Icons.network_check_rounded, size: 16),
                                    label: Text(strings.testConnection),
                                  ),
                                ],
                              ),
                              _AiModelChips(
                                models: _tagsModels,
                                currentModel: (aiTags['model'] ?? '').toString(),
                                title: strings.quickModelSelectLabel,
                                palette: palette,
                                onSelected: (m) => _markDirty(() {
                                  aiTags['model'] = m;
                                  _presetRev++;
                                }),
                              ),
                              _AiStatusBanner(
                                message: _tagsStatus,
                                ok: _tagsStatusOk,
                                palette: palette,
                              ),
                              AiBackfillBar(
                                api: ref.read(apiClientProvider),
                                strings: strings,
                                statusEndpoint: '/api/ai/tags/backfill/status',
                                startEndpoint: '/api/ai/tags/backfill',
                                stopEndpoint: '/api/ai/tags/backfill/stop',
                                rebuildEndpoint: '/api/ai/tags/backfill/rebuild',
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  if (_showSec('backup')) ...[
                    _SectionHeader(title: strings.secBackupAbout, palette: palette),
                    Card(
                      child: Column(
                        children: [
                          ListTile(
                            leading: Icon(Icons.download_rounded, color: palette.accent),
                            title: Text(strings.exportDbTitle),
                            onTap: _exportDatabase,
                          ),
                          const Divider(height: 1),
                          ListTile(
                            leading: Icon(Icons.upload_file_rounded, color: palette.accent),
                            title: Text(strings.importDbTitle),
                            onTap: _importDatabase,
                          ),
                          const Divider(height: 1),
                          ListTile(
                            leading: Icon(Icons.restore_rounded, color: palette.warning),
                            title: Text(strings.resetFactoryTitle),
                            onTap: _resetFactoryConfig,
                          ),
                          const Divider(height: 1),
                          ListTile(
                            leading: const Icon(Icons.info_outline_rounded),
                            title: Text('OpenAver Mobile v${boot.version}'),
                            subtitle: Text('Port ${boot.port} · ${boot.abi} · ${boot.openaverRelease}'),
                          ),
                          const Divider(height: 1),
                          ListTile(
                            leading: Icon(Icons.web_rounded, color: palette.blue),
                            title: Text(strings.switchClassicWebTitle),
                            subtitle: Text(strings.switchClassicWebSub),
                            onTap: () => NativeBridge.instance.switchToClassicWeb(path: '/settings'),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),

            if (_dirty)
              Container(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
                decoration: BoxDecoration(
                  color: palette.surface,
                  border: Border(top: BorderSide(color: palette.stroke)),
                ),
                child: OverflowBar(
                  alignment: MainAxisAlignment.spaceBetween,
                  overflowAlignment: OverflowBarAlignment.start,
                  spacing: 12,
                  overflowSpacing: 4,
                  children: [
                    Text(strings.unsavedChanges, style: TextStyle(color: palette.warning, fontWeight: FontWeight.w600)),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        TextButton(
                          onPressed: _saving ? null : () => _loadAll(syncUiPrefs: true),
                          child: Text(strings.discardChanges),
                        ),
                        FilledButton.icon(
                          onPressed: _saving ? null : _saveConfig,
                          icon: const Icon(Icons.save_rounded, size: 18),
                          label: Text(_saving ? strings.saving : strings.saveSettings),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

const double _settingsFieldSpacing = 14;

const _settingsInputDecoration = InputDecoration(
  contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 12),
  constraints: BoxConstraints(minHeight: 48),
);

class _SettingsField extends StatelessWidget {
  const _SettingsField({
    required this.label,
    required this.child,
    this.note,
    this.trailing,
  });

  final String label;
  final Widget child;
  final String? note;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final textTheme = Theme.of(context).textTheme;
    final input = MergeSemantics(
      child: Semantics(label: label, hint: note, child: child),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ExcludeSemantics(
          child: Text(
            label,
            style: textTheme.bodyMedium?.copyWith(
              color: palette.textPrimary,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(height: 6),
        if (trailing case final action?)
          Row(
            spacing: 8,
            children: [Expanded(child: input), action],
          )
        else
          input,
        if (note case final help?) ...[
          const SizedBox(height: 4),
          ExcludeSemantics(
            child: Text(
              help,
              style: textTheme.bodySmall?.copyWith(color: palette.textSecondary),
            ),
          ),
        ],
      ],
    );
  }
}

class _SettingsTextField extends StatelessWidget {
  const _SettingsTextField({
    super.key,
    required this.label,
    required this.initialValue,
    required this.onChanged,
    this.note,
    this.trailing,
    this.keyboardType,
    this.obscureText = false,
  });

  final String label;
  final String initialValue;
  final ValueChanged<String> onChanged;
  final String? note;
  final Widget? trailing;
  final TextInputType? keyboardType;
  final bool obscureText;

  @override
  Widget build(BuildContext context) => _SettingsField(
        label: label,
        note: note,
        trailing: trailing,
        child: TextFormField(
          initialValue: initialValue,
          decoration: _settingsInputDecoration,
          keyboardType: keyboardType,
          obscureText: obscureText,
          onChanged: onChanged,
        ),
      );
}

class _SettingsDropdown extends StatelessWidget {
  const _SettingsDropdown({
    required this.label,
    required this.initialValue,
    required this.items,
    required this.onChanged,
  });

  final String label;
  final String initialValue;
  final List<DropdownMenuItem<String>> items;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) => _SettingsField(
        label: label,
        child: DropdownButtonFormField<String>(
          initialValue: initialValue,
          decoration: _settingsInputDecoration,
          isExpanded: true,
          itemHeight: null,
          items: items,
          onChanged: onChanged,
        ),
      );
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.palette});

  final String title;
  final OpenAverPalette palette;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 6),
      child: Text(
        title,
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w700,
          color: palette.textSecondary,
        ),
      ),
    );
  }
}

class _AiPresetChips extends StatelessWidget {
  const _AiPresetChips({
    required this.label,
    required this.palette,
    required this.presets,
    required this.onSelect,
  });

  final String label;
  final OpenAverPalette palette;
  final List<(String, String, String)> presets;
  final void Function(String url, String model) onSelect;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 11.5, color: palette.textMuted)),
        const SizedBox(height: 4),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: presets
              .map(
                (p) => ActionChip(
                  label: Text(p.$1, style: const TextStyle(fontSize: 12)),
                  visualDensity: VisualDensity.compact,
                  onPressed: () => onSelect(p.$2, p.$3),
                ),
              )
              .toList(),
        ),
      ],
    );
  }
}

class _AiModelChips extends StatelessWidget {
  const _AiModelChips({
    required this.models,
    required this.currentModel,
    required this.title,
    required this.palette,
    required this.onSelected,
  });

  final List<String> models;
  final String currentModel;
  final String title;
  final OpenAverPalette palette;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    if (models.isEmpty) return const SizedBox.shrink();
    final shown = models.take(24).toList();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: TextStyle(fontSize: 11.5, color: palette.textMuted)),
          const SizedBox(height: 4),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: shown
                .map(
                  (m) => ChoiceChip(
                    label: Text(m, style: const TextStyle(fontSize: 11.5)),
                    selected: m == currentModel,
                    visualDensity: VisualDensity.compact,
                    onSelected: (_) => onSelected(m),
                  ),
                )
                .toList(),
          ),
        ],
      ),
    );
  }
}

class _AiStatusBanner extends StatelessWidget {
  const _AiStatusBanner({
    required this.message,
    required this.ok,
    required this.palette,
  });

  final String? message;
  final bool ok;
  final OpenAverPalette palette;

  @override
  Widget build(BuildContext context) {
    if (message == null || message!.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Text(
        message!,
        style: TextStyle(
          fontSize: 12,
          color: ok ? palette.success : palette.danger,
        ),
      ),
    );
  }
}
