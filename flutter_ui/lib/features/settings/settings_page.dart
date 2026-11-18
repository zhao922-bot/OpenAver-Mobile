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
  bool _testingAi = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadAll());
  }

  Future<void> _loadAll() async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.getJson('/api/config');
      final tree = await NativeBridge.instance.getStorageTreeInfo();
      final storage = await NativeBridge.instance.hasStorageAccess();
      if (!mounted) return;
      final data = resp['data'];
      if (data is Map) {
        setState(() {
          _config = jsonDecode(jsonEncode(data)) as Map<String, dynamic>;
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

  Future<void> _probeSources() async {
    final strings = ref.read(stringsProvider);
    setState(() {
      _probingSources = true;
      _probeResults = const {};
    });
    try {
      final resp = await ref.read(apiClientProvider).postJson('/api/sources/probe');
      if (!mounted) return;
      final results = (resp['results'] as List?) ?? (resp['sources'] as List?) ?? const [];
      final mapped = <String, String>{};
      for (final item in results.whereType<Map>()) {
        final id = (item['id'] ?? item['source'] ?? '').toString();
        final ok = item['ok'] == true || item['reachable'] == true || item['state'] == 'ok';
        final latency = item['latency_ms'];
        if (id.isNotEmpty) {
          mapped[id] = ok
              ? (latency != null ? 'OK (${latency}ms)' : 'OK')
              : (item['state'] ?? 'ERR').toString();
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

  Future<void> _testTranslateConnection(String provider) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final tCfg = _section('translate');
    final sub = _nestedSection(tCfg, provider);
    setState(() => _testingAi = true);
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
        _toast(strings.saved);
      } else {
        _toast((resp['error'] ?? resp['message'] ?? strings.taskFailed).toString());
      }
    } catch (e) {
      debugPrint('testTranslateConnection error: $e');
      _toast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _testingAi = false);
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
      _loadAll();
    } catch (e) {
      debugPrint('resetFactoryConfig error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _clearThumbnails() async {
    final strings = ref.read(stringsProvider);
    try {
      await ref.read(apiClientProvider).postJson('/api/gallery/thumb/clear');
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
    final autoCheckUpdate = general['auto_check_update'] != false;

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
                              onSelectionChanged: (v) => _markDirty(() => general['font_size'] = v.first),
                            ),
                            const SizedBox(height: 14),
                            DropdownButtonFormField<String>(
                              initialValue: const {'search', 'gallery', 'showcase'}.contains(defaultPage) ? defaultPage : 'search',
                              decoration: InputDecoration(labelText: strings.defaultPageTitle),
                              items: [
                                DropdownMenuItem(value: 'search', child: Text(strings.tabSearch)),
                                DropdownMenuItem(value: 'gallery', child: Text(strings.tabScanner)),
                                DropdownMenuItem(value: 'showcase', child: Text(strings.tabShowcase)),
                              ],
                              onChanged: (v) {
                                if (v != null) _markDirty(() => general['default_page'] = v);
                              },
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.autoCheckUpdateTitle),
                              value: autoCheckUpdate,
                              onChanged: (v) => _markDirty(() => general['auto_check_update'] = v),
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
                            subtitle: Text(_treeInfo.granted ? _treeInfo.description : strings.safNotConfigured),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                if (_treeInfo.granted)
                                  IconButton(
                                    icon: const Icon(Icons.link_off_rounded, size: 18),
                                    onPressed: () async {
                                      await NativeBridge.instance.clearStorageTree();
                                      final updated = await NativeBridge.instance.getStorageTreeInfo();
                                      if (mounted) setState(() => _treeInfo = updated);
                                    },
                                  ),
                                TextButton(
                                  onPressed: () async {
                                    final updated = await NativeBridge.instance.openStorageTreePicker();
                                    if (updated != null && mounted) {
                                      setState(() => _treeInfo = updated);
                                    }
                                  },
                                  child: Text(strings.authorize),
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
                            child: TextFormField(
                              initialValue: outputDir,
                              decoration: InputDecoration(labelText: strings.outputDirTitle),
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
                            TextFormField(
                              initialValue: folderFormat,
                              decoration: InputDecoration(labelText: strings.folderFormatTitle),
                              onChanged: (v) => _markDirty(() => scraper['folder_format'] = v),
                            ),
                            const SizedBox(height: 8),
                            TextFormField(
                              initialValue: filenameFormat,
                              decoration: InputDecoration(labelText: strings.filenameFormatTitle),
                              onChanged: (v) => _markDirty(() => scraper['filename_format'] = v),
                            ),
                            const SizedBox(height: 8),
                            TextFormField(
                              initialValue: nfoTitleFormat,
                              decoration: InputDecoration(labelText: strings.nfoTitleFormatTitle),
                              onChanged: (v) => _markDirty(() => scraper['nfo_title_format'] = v),
                            ),
                            const SizedBox(height: 8),
                            TextFormField(
                              initialValue: coverFilename,
                              decoration: InputDecoration(labelText: strings.coverFilenameTitle),
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
                            DropdownButtonFormField<String>(
                              initialValue: const {'off', 'jellyfin', 'emby', 'kodi'}.contains(externalManager)
                                  ? externalManager
                                  : 'off',
                              decoration: InputDecoration(labelText: strings.externalManagerTitle),
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
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                Expanded(
                                  child: TextFormField(
                                    initialValue: '$maxTitleLength',
                                    keyboardType: TextInputType.number,
                                    decoration: InputDecoration(labelText: strings.maxTitleLengthTitle),
                                    onChanged: (v) {
                                      final parsed = int.tryParse(v.trim());
                                      if (parsed != null && parsed > 0) {
                                        _markDirty(() => scraper['max_title_length'] = parsed);
                                      }
                                    },
                                  ),
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: TextFormField(
                                    initialValue: '$maxFilenameLength',
                                    keyboardType: TextInputType.number,
                                    decoration: InputDecoration(labelText: strings.maxFilenameLengthTitle),
                                    onChanged: (v) {
                                      final parsed = int.tryParse(v.trim());
                                      if (parsed != null && parsed > 0) {
                                        _markDirty(() => scraper['max_filename_length'] = parsed);
                                      }
                                    },
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            TextFormField(
                              initialValue: videoExts,
                              decoration: InputDecoration(labelText: strings.videoExtensionsTitle),
                              onChanged: (v) => _markDirty(() {
                                scraper['video_extensions'] = v
                                    .split(',')
                                    .map((e) => e.trim())
                                    .where((e) => e.isNotEmpty)
                                    .toList();
                              }),
                            ),
                            const SizedBox(height: 8),
                            TextFormField(
                              initialValue: suffixKeywords,
                              decoration: InputDecoration(labelText: strings.suffixKeywordsTitle),
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
                            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                            child: TextFormField(
                              initialValue: proxyUrl,
                              decoration: InputDecoration(labelText: strings.proxyUrlTitle),
                              onChanged: (v) => _markDirty(() => searchCfg['proxy_url'] = v.trim()),
                            ),
                          ),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                            child: DropdownButtonFormField<String>(
                              initialValue: proxyScope == 'all' ? 'all' : 'dmm',
                              decoration: InputDecoration(labelText: strings.proxyScopeTitle),
                              items: const [
                                DropdownMenuItem(value: 'dmm', child: Text('DMM')),
                                DropdownMenuItem(value: 'all', child: Text('All')),
                              ],
                              onChanged: (v) {
                                if (v != null) _markDirty(() => searchCfg['proxy_scope'] = v);
                              },
                            ),
                          ),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
                            child: Row(
                              children: [
                                Expanded(
                                  child: TextFormField(
                                    key: ValueKey('fav_$favoriteFolder'),
                                    initialValue: favoriteFolder,
                                    decoration: InputDecoration(labelText: strings.favoriteFolderTitle),
                                    onChanged: (v) => _markDirty(() => searchCfg['favorite_folder'] = v.trim()),
                                  ),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.folder_open_rounded),
                                  onPressed: () async {
                                    final picked = await BrowseDirSheet.pickFolder(
                                      context,
                                      ref.read(apiClientProvider),
                                      initialPath: favoriteFolder.isNotEmpty ? favoriteFolder : null,
                                    );
                                    if (picked != null && picked.isNotEmpty) {
                                      _markDirty(() => searchCfg['favorite_folder'] = picked);
                                    }
                                  },
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
                                      Text(
                                        probeState,
                                        style: TextStyle(
                                          fontSize: 11,
                                          color: probeState.startsWith('OK') ? palette.success : palette.danger,
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
                                Text(strings.metatubeSectionTitle, style: const TextStyle(fontWeight: FontWeight.w600)),
                                SwitchListTile(
                                  contentPadding: EdgeInsets.zero,
                                  title: Text(strings.metatubeSectionTitle),
                                  value: metatube['enabled'] == true,
                                  onChanged: (v) => _markDirty(() => metatube['enabled'] = v),
                                ),
                                if (metatube['enabled'] == true) ...[
                                  TextFormField(
                                    initialValue: (metatube['url'] ?? '').toString(),
                                    decoration: const InputDecoration(labelText: 'Metatube URL'),
                                    onChanged: (v) => _markDirty(() => metatube['url'] = v.trim()),
                                  ),
                                  const SizedBox(height: 8),
                                  TextFormField(
                                    initialValue: (metatube['token'] ?? '').toString(),
                                    decoration: const InputDecoration(labelText: 'Token'),
                                    onChanged: (v) => _markDirty(() => metatube['token'] = v.trim()),
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
                            DropdownButtonFormField<String>(
                              initialValue: const {'ollama', 'gemini', 'openai', 'openai_official', 'claude'}
                                      .contains(translateProvider)
                                  ? translateProvider
                                  : 'ollama',
                              decoration: InputDecoration(labelText: strings.translateProviderTitle),
                              items: const [
                                DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
                                DropdownMenuItem(value: 'openai', child: Text('OpenAI Compatible')),
                                DropdownMenuItem(value: 'openai_official', child: Text('OpenAI Official')),
                                DropdownMenuItem(value: 'gemini', child: Text('Google Gemini')),
                                DropdownMenuItem(value: 'claude', child: Text('Anthropic Claude')),
                              ],
                              onChanged: (v) {
                                if (v != null) _markDirty(() => translateCfg['provider'] = v);
                              },
                            ),
                            const SizedBox(height: 8),
                            if (translateProviderCfg.containsKey('url') || translateProvider == 'ollama')
                              TextFormField(
                                key: ValueKey('tr_url_$translateProvider'),
                                initialValue: (translateProviderCfg['url'] ?? '').toString(),
                                decoration: const InputDecoration(labelText: 'Endpoint URL'),
                                onChanged: (v) => _markDirty(() => translateProviderCfg['url'] = v.trim()),
                              )
                            else
                              TextFormField(
                                key: ValueKey('tr_base_$translateProvider'),
                                initialValue: (translateProviderCfg['base_url'] ?? '').toString(),
                                decoration: const InputDecoration(labelText: 'Base URL'),
                                onChanged: (v) => _markDirty(() => translateProviderCfg['base_url'] = v.trim()),
                              ),
                            const SizedBox(height: 8),
                            TextFormField(
                              key: ValueKey('tr_key_$translateProvider'),
                              initialValue: (translateProviderCfg['api_key'] ?? '').toString(),
                              decoration: const InputDecoration(labelText: 'API Key'),
                              onChanged: (v) => _markDirty(() => translateProviderCfg['api_key'] = v.trim()),
                            ),
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                Expanded(
                                  child: TextFormField(
                                    key: ValueKey('tr_model_$translateProvider'),
                                    initialValue: (translateProviderCfg['model'] ?? '').toString(),
                                    decoration: const InputDecoration(labelText: 'Model'),
                                    onChanged: (v) => _markDirty(() => translateProviderCfg['model'] = v.trim()),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                OutlinedButton(
                                  onPressed: _testingAi ? null : () => _testTranslateConnection(translateProvider),
                                  child: Text(_testingAi ? strings.requesting : strings.testConnection),
                                ),
                              ],
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
                              TextFormField(
                                initialValue: (aiSimilar['url'] ?? '').toString(),
                                decoration: const InputDecoration(labelText: 'Similarity Endpoint URL'),
                                onChanged: (v) => _markDirty(() => aiSimilar['url'] = v.trim()),
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
                              TextFormField(
                                initialValue: (aiFaces['url'] ?? '').toString(),
                                decoration: const InputDecoration(labelText: 'Faces Endpoint URL'),
                                onChanged: (v) => _markDirty(() => aiFaces['url'] = v.trim()),
                              ),
                              const SizedBox(height: 6),
                            ],
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(strings.aiTagsTitle),
                              value: aiTags['enabled'] == true,
                              onChanged: (v) => _markDirty(() => aiTags['enabled'] = v),
                            ),
                            if (aiTags['enabled'] == true) ...[
                              TextFormField(
                                initialValue: (aiTags['base_url'] ?? '').toString(),
                                decoration: const InputDecoration(labelText: 'Tags Base URL'),
                                onChanged: (v) => _markDirty(() => aiTags['base_url'] = v.trim()),
                              ),
                              const SizedBox(height: 6),
                              TextFormField(
                                initialValue: (aiTags['model'] ?? '').toString(),
                                decoration: const InputDecoration(labelText: 'Tags Model'),
                                onChanged: (v) => _markDirty(() => aiTags['model'] = v.trim()),
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
                child: Row(
                  children: [
                    Text(strings.unsavedChanges, style: TextStyle(color: palette.warning, fontWeight: FontWeight.w600)),
                    const Spacer(),
                    TextButton(
                      onPressed: _saving ? null : _loadAll,
                      child: Text(strings.discardChanges),
                    ),
                    const SizedBox(width: 8),
                    FilledButton.icon(
                      onPressed: _saving ? null : _saveConfig,
                      icon: const Icon(Icons.save_rounded, size: 18),
                      label: Text(_saving ? strings.saving : strings.saveSettings),
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
