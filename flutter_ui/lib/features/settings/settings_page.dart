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

  Map<String, dynamic> _config = {};
  TreeAccessInfo _treeInfo = const TreeAccessInfo(granted: false, description: '');
  bool _storageGranted = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadAll());
  }

  Future<void> _loadAll() async {
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
          _error = '读取配置失败';
        });
      }
    } catch (e) {
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

  Future<void> _saveConfig() async {
    setState(() => _saving = true);
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.dio.put<dynamic>('/api/config', data: _config);
      final body = resp.data is Map ? Map<String, dynamic>.from(resp.data as Map) : const <String, dynamic>{};
      if (!mounted) return;
      if (resp.statusCode == 200 && body['success'] != false) {
        setState(() => _dirty = false);
        _toast('设置已保存');
      } else {
        _toast((body['detail'] ?? body['error'] ?? '保存失败').toString());
      }
    } catch (e) {
      _toast('保存失败: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _applyTheme(AppThemeMode mode) async {
    ref.read(themeModeProvider.notifier).state = mode;
    await NativeBridge.instance.syncNativeTheme(mode.id);
    _markDirty(() {
      _section('general')['theme'] = mode.id;
    });
  }

  Future<void> _applyLocale(String locale) async {
    ref.read(localeProvider.notifier).state = locale;
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

  Future<void> _exportDatabase() async {
    final api = ref.read(apiClientProvider);
    _toast('正在导出数据库备份…');
    try {
      final tempFile = File('${Directory.systemTemp.path}/openaver_export.zip');
      await api.dio.download('/api/database/export', tempFile.path);
      final name = 'openaver-db-${DateTime.now().millisecondsSinceEpoch}.zip';
      final saved = await NativeBridge.instance.saveTempFileToDownloads(
        tempPath: tempFile.path,
        filename: name,
        mimeType: 'application/zip',
      );
      _toast(saved != null ? '已保存到 $saved' : '导出失败');
    } catch (e) {
      _toast('导出失败: $e');
    }
  }

  Future<void> _importDatabase() async {
    final picked = await NativeBridge.instance.pickFile(mimeTypes: const ['application/zip', 'application/octet-stream']);
    if (picked == null || picked.path.isEmpty) return;
    try {
      final form = FormData.fromMap({
        'file': await MultipartFile.fromFile(picked.path, filename: picked.name),
      });
      final resp = await ref.read(apiClientProvider).dio.post<dynamic>('/api/database/import', data: form);
      final body = resp.data is Map ? Map<String, dynamic>.from(resp.data as Map) : const <String, dynamic>{};
      if (body['ok'] == true) {
        _toast('数据库恢复成功');
      } else {
        _toast((body['detail'] ?? body['error'] ?? '恢复失败').toString());
      }
    } catch (e) {
      _toast('恢复失败: $e');
    }
  }

  Future<void> _clearThumbnails() async {
    await ref.read(apiClientProvider).postJson('/api/gallery/thumb/clear');
    _toast('缩略图缓存已清空');
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final activeTheme = ref.watch(themeModeProvider);
    final activeLocale = ref.watch(localeProvider);
    final boot = ref.watch(bootstrapProvider);

    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, style: TextStyle(color: palette.danger)),
              const SizedBox(height: 12),
              FilledButton(onPressed: _loadAll, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    final gallery = _section('gallery');
    final dirs = ((gallery['directories'] as List?) ?? const []).toList();
    final minSizeMb = (gallery['min_size_mb'] as num?)?.toInt() ?? 100;
    final thumbEnabled = _config['thumbnail_cache_enabled'] == true;

    final searchCfg = _section('search');
    final uncensored = searchCfg['uncensored_mode'] == true;
    final proxyUrl = (searchCfg['proxy_url'] ?? '').toString();

    final translateCfg = _section('translate');
    final translateEnabled = translateCfg['enabled'] == true;
    final translateProvider = (translateCfg['provider'] ?? 'ollama').toString();

    final sources = ((_config['sources'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 32),
                children: [
                  _SectionHeader(title: '外观与语言', palette: palette),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('界面主题', style: TextStyle(fontWeight: FontWeight.w600)),
                          const SizedBox(height: 8),
                          SegmentedButton<AppThemeMode>(
                            segments: const [
                              ButtonSegment(value: AppThemeMode.dim, label: Text('影院灰')),
                              ButtonSegment(value: AppThemeMode.dark, label: Text('纯黑')),
                              ButtonSegment(value: AppThemeMode.light, label: Text('浅色')),
                            ],
                            selected: {activeTheme},
                            onSelectionChanged: (v) => _applyTheme(v.first),
                          ),
                          const SizedBox(height: 14),
                          const Text('界面语言', style: TextStyle(fontWeight: FontWeight.w600)),
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
                        ],
                      ),
                    ),
                  ),

                  const SizedBox(height: 16),
                  _SectionHeader(title: '片库目录与存储权限', palette: palette),
                  Card(
                    child: Column(
                      children: [
                        ListTile(
                          leading: Icon(
                            _storageGranted ? Icons.verified_user_outlined : Icons.warning_amber_rounded,
                            color: _storageGranted ? palette.success : palette.warning,
                          ),
                          title: const Text('所有文件访问权限'),
                          subtitle: Text(_storageGranted ? '已授权' : '未授权'),
                          trailing: TextButton(
                            onPressed: () async {
                              await NativeBridge.instance.openStoragePermission();
                              final granted = await NativeBridge.instance.hasStorageAccess();
                              if (mounted) setState(() => _storageGranted = granted);
                            },
                            child: const Text('设置'),
                          ),
                        ),
                        const Divider(height: 1),
                        ListTile(
                          leading: Icon(Icons.sd_storage_outlined, color: palette.accent),
                          title: const Text('SAF 可写目录授权 (SD 卡)'),
                          subtitle: Text(_treeInfo.granted ? _treeInfo.description : '未配置（仅 SD 卡写回时需要）'),
                          trailing: TextButton(
                            onPressed: () async {
                              final updated = await NativeBridge.instance.openStorageTreePicker();
                              if (updated != null && mounted) {
                                setState(() => _treeInfo = updated);
                              }
                            },
                            child: const Text('授权'),
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
                                subtitle: Text(ro ? '只读来源 (Media Server 模式)' : '本地可写来源'),
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
                              label: const Text('添加扫描目录'),
                            ),
                          ),
                        ),
                        const Divider(height: 1),
                        SwitchListTile(
                          title: const Text('本地 WebP 缩略图缓存'),
                          subtitle: const Text('加速封面墙滑动帧率'),
                          value: thumbEnabled,
                          onChanged: (v) => _markDirty(() => _config['thumbnail_cache_enabled'] = v),
                        ),
                        ListTile(
                          title: const Text('最小视频大小过滤 (MB)'),
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
                          title: const Text('清空缩略图缓存'),
                          trailing: OutlinedButton(onPressed: _clearThumbnails, child: const Text('清空')),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 16),
                  _SectionHeader(title: '刮削来源与网络 (长按拖动排序)', palette: palette),
                  Card(
                    child: Column(
                      children: [
                        SwitchListTile(
                          title: const Text('无码优先模式'),
                          value: uncensored,
                          onChanged: (v) => _markDirty(() => searchCfg['uncensored_mode'] = v),
                        ),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
                          child: TextFormField(
                            initialValue: proxyUrl,
                            decoration: const InputDecoration(
                              labelText: 'HTTP / SOCKS5 代理地址',
                              hintText: '如 http://127.0.0.1:7890 (留空直连)',
                            ),
                            onChanged: (v) => _markDirty(() => searchCfg['proxy_url'] = v.trim()),
                          ),
                        ),
                        const Divider(height: 1),
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
                            return SwitchListTile(
                              key: ValueKey('src_$id'),
                              secondary: const Icon(Icons.drag_handle_rounded),
                              title: Text(id.toUpperCase()),
                              value: enabled,
                              onChanged: (v) => _markDirty(() {
                                sources[idx]['enabled'] = v;
                                _config['sources'] = sources;
                              }),
                            );
                          },
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 16),
                  _SectionHeader(title: 'AI 翻译服务', palette: palette),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          SwitchListTile(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('启用 AI 翻译标题 / 简介'),
                            value: translateEnabled,
                            onChanged: (v) => _markDirty(() => translateCfg['enabled'] = v),
                          ),
                          DropdownButtonFormField<String>(
                            initialValue: const {'ollama', 'gemini', 'openai', 'claude'}.contains(translateProvider)
                                ? translateProvider
                                : 'ollama',
                            decoration: const InputDecoration(labelText: '翻译提供方'),
                            items: const [
                              DropdownMenuItem(value: 'ollama', child: Text('Ollama')),
                              DropdownMenuItem(value: 'openai', child: Text('OpenAI / 兼容接口')),
                              DropdownMenuItem(value: 'gemini', child: Text('Google Gemini')),
                              DropdownMenuItem(value: 'claude', child: Text('Anthropic Claude')),
                            ],
                            onChanged: (v) {
                              if (v != null) _markDirty(() => translateCfg['provider'] = v);
                            },
                          ),
                        ],
                      ),
                    ),
                  ),

                  const SizedBox(height: 16),
                  _SectionHeader(title: '数据备份、经典视图与诊断', palette: palette),
                  Card(
                    child: Column(
                      children: [
                        ListTile(
                          leading: Icon(Icons.download_rounded, color: palette.accent),
                          title: const Text('导出数据库备份 (ZIP)'),
                          onTap: _exportDatabase,
                        ),
                        const Divider(height: 1),
                        ListTile(
                          leading: Icon(Icons.upload_file_rounded, color: palette.accent),
                          title: const Text('从备份恢复数据库'),
                          onTap: _importDatabase,
                        ),
                        const Divider(height: 1),
                        ListTile(
                          leading: Icon(Icons.web_rounded, color: palette.blue),
                          title: const Text('切换到 Web 经典视图'),
                          subtitle: const Text('当需要操作实验性/高级设置时可临时切回原 WebView 界面'),
                          onTap: () => NativeBridge.instance.switchToClassicWeb(path: '/settings'),
                        ),
                        const Divider(height: 1),
                        ListTile(
                          leading: const Icon(Icons.info_outline_rounded),
                          title: Text('OpenAver Mobile v${boot.version}'),
                          subtitle: Text('端口: ${boot.port} · 架构: ${boot.abi}'),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),

            // Sticky save bar when dirty
            if (_dirty)
              Container(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
                decoration: BoxDecoration(
                  color: palette.surface,
                  border: Border(top: BorderSide(color: palette.stroke)),
                ),
                child: Row(
                  children: [
                    Text('有未保存的更改', style: TextStyle(color: palette.warning, fontWeight: FontWeight.w600)),
                    const Spacer(),
                    TextButton(
                      onPressed: _saving ? null : _loadAll,
                      child: const Text('放弃'),
                    ),
                    const SizedBox(width: 8),
                    FilledButton.icon(
                      onPressed: _saving ? null : _saveConfig,
                      icon: const Icon(Icons.save_rounded, size: 18),
                      label: Text(_saving ? '保存中…' : '保存设置'),
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
