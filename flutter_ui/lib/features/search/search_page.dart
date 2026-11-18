import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/search_models.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';

class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});

  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final TextEditingController _queryCtrl = TextEditingController();
  CancelToken? _searchCancel;

  bool _searching = false;
  String? _searchError;
  String _searchMode = '';
  final Map<String, String> _sourceStatuses = {};
  List<SearchResultItem> _results = const [];
  Map<String, LocalStatusInfo> _localStatus = const {};
  Set<String> _wishlisted = const {};
  List<Map<String, dynamic>> _makerCapsules = const [];
  List<FavoriteFileItem> _favoriteFiles = const [];
  bool _loadingFavorites = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadMakerCapsules();
      _loadFavoriteFiles();
      _refreshWishlistMembership();
    });
  }

  @override
  void dispose() {
    _searchCancel?.cancel();
    _queryCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadMakerCapsules() async {
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/search/maker-capsules');
      if (!mounted) return;
      final list = (resp['makers'] as List?) ?? const [];
      setState(() {
        _makerCapsules = list
            .whereType<Map>()
            .take(16)
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
      });
    } catch (_) {}
  }

  Future<void> _loadFavoriteFiles() async {
    setState(() => _loadingFavorites = true);
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/search/favorite-files');
      if (!mounted) return;
      final list = (resp['files'] as List?) ?? (resp['data'] as List?) ?? const [];
      setState(() {
        _favoriteFiles = list
            .whereType<Map>()
            .map((e) => FavoriteFileItem.fromJson(Map<String, dynamic>.from(e)))
            .toList();
        _loadingFavorites = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingFavorites = false);
    }
  }

  Future<void> _refreshWishlistMembership() async {
    try {
      final list = await ref.read(apiClientProvider).getJsonList('/api/wishlist');
      if (!mounted) return;
      setState(() {
        _wishlisted = list
            .whereType<Map>()
            .map((e) => (e['number'] ?? '').toString().toUpperCase())
            .where((n) => n.isNotEmpty)
            .toSet();
      });
    } catch (_) {}
  }

  Future<void> _startSearch({String? overrideQuery, String? makerKey, String? makerName}) async {
    final q = (overrideQuery ?? _queryCtrl.text).trim();
    if (makerKey == null && q.length < 2) return;
    if (overrideQuery != null) {
      _queryCtrl.text = overrideQuery;
    }
    _searchCancel?.cancel();
    final cancel = CancelToken();
    _searchCancel = cancel;

    setState(() {
      _searching = true;
      _searchError = null;
      _results = const [];
      _localStatus = const {};
      _sourceStatuses.clear();
      _searchMode = makerKey != null ? 'maker' : '';
    });

    final api = ref.read(apiClientProvider);
    try {
      await for (final event in api.streamSse(
        '/api/search/stream',
        queryParameters: {
          'maker_key': ?makerKey,
          'maker': ?makerName,
          if (makerKey == null) 'q': q,
          'limit': 24,
        },
        cancelToken: cancel,
      )) {
        if (!mounted) break;
        switch (event.type) {
          case 'mode':
            setState(() => _searchMode = (event.data['mode'] ?? '').toString());
            break;
          case 'status':
            final src = (event.data['source'] ?? '').toString();
            final st = (event.data['status'] ?? '').toString();
            if (src.isNotEmpty) {
              setState(() => _sourceStatuses[src] = st);
            }
            break;
          case 'result':
            final rawList = (event.data['data'] as List?) ?? const [];
            final parsed = rawList
                .whereType<Map>()
                .map((e) => SearchResultItem.fromJson(Map<String, dynamic>.from(e)))
                .toList();
            setState(() {
              _results = parsed;
              _searching = false;
            });
            _checkLocalStatus(parsed);
            break;
          case 'error':
            setState(() {
              _searchError = (event.data['message'] ?? '搜索失败').toString();
              _searching = false;
            });
            break;
        }
      }
    } catch (e) {
      if (!cancel.isCancelled && mounted) {
        setState(() {
          _searching = false;
          _searchError = e.toString();
        });
      }
    } finally {
      if (mounted && _searching) {
        setState(() => _searching = false);
      }
    }
  }

  Future<void> _checkLocalStatus(List<SearchResultItem> items) async {
    final numbers = items.map((e) => e.number).where((n) => n.isNotEmpty).toSet().toList();
    if (numbers.isEmpty) return;
    try {
      final resp = await ref.read(apiClientProvider).getJson(
        '/api/search/local-status',
        queryParameters: {'numbers': numbers.join(',')},
      );
      if (!mounted) return;
      final parsed = <String, LocalStatusInfo>{};
      resp.forEach((k, v) {
        if (v is Map) {
          parsed[k.toUpperCase()] = LocalStatusInfo.fromJson(Map<String, dynamic>.from(v));
        }
      });
      setState(() => _localStatus = parsed);
    } catch (_) {}
  }

  Future<void> _pickAndImageSearch() async {
    final picked = await NativeBridge.instance.pickFile(
      mimeTypes: const ['image/jpeg', 'image/png', 'image/webp'],
    );
    if (picked == null || picked.path.isEmpty) return;
    final api = ref.read(apiClientProvider);

    if (!mounted) return;
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const AlertDialog(
        content: Row(
          children: [
            CircularProgressIndicator(),
            SizedBox(width: 16),
            Text('正在以图搜番…'),
          ],
        ),
      ),
    );

    try {
      final form = FormData.fromMap({
        'file': await MultipartFile.fromFile(picked.path, filename: picked.name),
      });
      final resp = await api.dio.post<dynamic>('/api/image-search', data: form);
      if (mounted) Navigator.of(context).pop();
      final body = resp.data is Map ? Map<String, dynamic>.from(resp.data as Map) : const <String, dynamic>{};
      if (body['success'] != true) {
        _toast((body['message'] ?? body['error'] ?? '识别失败').toString());
        return;
      }
      final candidates = ((body['candidates'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (!mounted) return;
      if (candidates.isEmpty) {
        _toast('未识别到匹配番号');
        return;
      }
      await showModalBottomSheet<void>(
        context: context,
        builder: (ctx) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const ListTile(
                title: Text('以图搜番候选结果', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
              ...candidates.map((c) {
                final candidateNumber = (c['number'] ?? c['code'] ?? '').toString();
                final sim = ((c['similarity'] as num?)?.toDouble() ?? 0.0) * 100;
                final inLib = c['in_library'] == true;
                return ListTile(
                  title: Text(candidateNumber, style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text('匹配度 ${sim.toStringAsFixed(1)}%${inLib ? " · 已入库" : ""}'),
                  trailing: const Icon(Icons.search_rounded),
                  onTap: () {
                    Navigator.of(ctx).pop();
                    _startSearch(overrideQuery: candidateNumber);
                  },
                );
              }),
            ],
          ),
        ),
      );
    } catch (e) {
      if (mounted) Navigator.of(context).pop();
      _toast('以图搜番失败: $e');
    }
  }

  Future<void> _toggleWishlist(SearchResultItem item) async {
    final key = item.number.toUpperCase();
    final api = ref.read(apiClientProvider);
    if (_wishlisted.contains(key)) {
      await api.deleteJson('/api/wishlist/${Uri.encodeComponent(item.number)}');
      setState(() => _wishlisted = {..._wishlisted}..remove(key));
    } else {
      final resp = await api.postJson('/api/wishlist', data: {
        'number': item.number,
        'title': item.title,
        'actors': item.actors,
        'tags': item.tags,
        'maker': item.maker,
        'director': item.director,
        'series': item.series,
        'label': item.label,
        'duration': item.duration,
        'date': item.date,
        'cover': item.cover,
        'sample_images': item.sampleImages,
        'source': item.source,
        'url': item.url,
      });
      if (resp['success'] == true) {
        setState(() => _wishlisted = {..._wishlisted, key});
      } else if (resp['already_owned'] == true) {
        _toast('本地片库已有此影片');
      }
    }
  }

  Future<void> _openWishlistSheet() async {
    final list = await ref.read(apiClientProvider).getJsonList('/api/wishlist');
    if (!mounted) return;
    final items = list.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.72,
        builder: (_, scrollCtrl) => Column(
          children: [
            ListTile(
              title: Text('待看书签 (${items.length})', style: const TextStyle(fontWeight: FontWeight.w700)),
              trailing: IconButton(
                icon: const Icon(Icons.close_rounded),
                onPressed: () => Navigator.of(ctx).pop(),
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: items.isEmpty
                  ? const Center(child: Text('书签列表为空'))
                  : ListView.builder(
                      controller: scrollCtrl,
                      itemCount: items.length,
                      itemBuilder: (_, idx) {
                        final w = items[idx];
                        final num = (w['number'] ?? '').toString();
                        final title = (w['title'] ?? '').toString();
                        return ListTile(
                          title: Text(num, style: const TextStyle(fontWeight: FontWeight.w700)),
                          subtitle: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline_rounded),
                            onPressed: () async {
                              await ref
                                  .read(apiClientProvider)
                                  .deleteJson('/api/wishlist/${Uri.encodeComponent(num)}');
                              if (ctx.mounted) Navigator.of(ctx).pop();
                              _refreshWishlistMembership();
                            },
                          ),
                          onTap: () {
                            Navigator.of(ctx).pop();
                            _startSearch(overrideQuery: num);
                          },
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _scrapeFavoriteFile(FavoriteFileItem file) async {
    final ctrl = TextEditingController(text: file.number);
    final number = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('刮削整理文件'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(file.name, style: const TextStyle(fontSize: 12)),
            const SizedBox(height: 10),
            TextField(
              controller: ctrl,
              decoration: const InputDecoration(labelText: '识别番号'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(ctrl.text), child: const Text('开始整理')),
        ],
      ),
    );
    ctrl.dispose();
    if (number == null || number.trim().isEmpty) return;
    _toast('正在刮削整理 ${number.trim()}…');
    final resp = await ref.read(apiClientProvider).postJson('/api/scrape-single', data: {
      'file_path': file.path,
      'number': number.trim(),
    });
    if (resp['success'] == true) {
      _toast('整理完成');
      _loadFavoriteFiles();
    } else {
      _toast((resp['error'] ?? '整理失败').toString());
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiClientProvider);
    final palette = OpenAverPalette.of(context);

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _queryCtrl,
                      textInputAction: TextInputAction.search,
                      decoration: InputDecoration(
                        hintText: '搜索番号、女优或关键字…',
                        prefixIcon: const Icon(Icons.search_rounded),
                        suffixIcon: _searching
                            ? IconButton(
                                icon: const Icon(Icons.stop_circle_outlined),
                                onPressed: () {
                                  _searchCancel?.cancel();
                                  setState(() => _searching = false);
                                },
                              )
                            : (_queryCtrl.text.isEmpty
                                ? null
                                : IconButton(
                                    icon: const Icon(Icons.clear_rounded, size: 18),
                                    onPressed: () {
                                      _queryCtrl.clear();
                                      setState(() {
                                        _results = const [];
                                        _searchError = null;
                                      });
                                    },
                                  )),
                      ),
                      onChanged: (_) => setState(() {}),
                      onSubmitted: (_) => _startSearch(),
                    ),
                  ),
                  const SizedBox(width: 6),
                  IconButton.filledTonal(
                    tooltip: '以图搜番',
                    onPressed: _pickAndImageSearch,
                    icon: const Icon(Icons.image_search_rounded),
                  ),
                  const SizedBox(width: 4),
                  IconButton.filledTonal(
                    tooltip: '书签 (${_wishlisted.length})',
                    onPressed: _openWishlistSheet,
                    icon: Badge(
                      isLabelVisible: _wishlisted.isNotEmpty,
                      label: Text('${_wishlisted.length}'),
                      child: const Icon(Icons.bookmark_border_rounded),
                    ),
                  ),
                ],
              ),
            ),

            if (_sourceStatuses.isNotEmpty)
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                child: Row(
                  children: [
                    if (_searchMode.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: Chip(label: Text(_searchMode.toUpperCase())),
                      ),
                    ..._sourceStatuses.entries.map(
                      (e) => Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: Chip(
                          label: Text('${e.key}: ${e.value}'),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

            if (_searching) const LinearProgressIndicator(minHeight: 2),

            if (_searchError != null)
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text(_searchError!, style: TextStyle(color: palette.danger)),
              ),

            Expanded(
              child: _results.isNotEmpty
                  ? ListView.separated(
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                      itemCount: _results.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 10),
                      itemBuilder: (_, index) {
                        final r = _results[index];
                        final local = _localStatus[r.number.toUpperCase()];
                        final saved = _wishlisted.contains(r.number.toUpperCase());
                        final coverProxy = r.cover.isNotEmpty
                            ? api.resolveUrl('/api/proxy-image?url=${Uri.encodeQueryComponent(r.cover)}')
                            : '';

                        return Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: palette.surface,
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: palette.stroke),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              ClipRRect(
                                borderRadius: BorderRadius.circular(8),
                                child: SizedBox(
                                  width: 108,
                                  height: 76,
                                  child: coverProxy.isNotEmpty
                                      ? Image.network(
                                          coverProxy,
                                          headers: api.authHeaders,
                                          fit: BoxFit.cover,
                                          errorBuilder: (_, _, _) => Container(
                                            color: palette.surfaceHigh,
                                            child: Icon(Icons.broken_image_outlined, color: palette.textMuted),
                                          ),
                                        )
                                      : Container(color: palette.surfaceHigh),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Text(
                                          r.number,
                                          style: TextStyle(
                                            fontWeight: FontWeight.w700,
                                            color: palette.accent,
                                          ),
                                        ),
                                        const SizedBox(width: 6),
                                        if (r.source.isNotEmpty)
                                          Text(
                                            r.source,
                                            style: TextStyle(fontSize: 11, color: palette.textMuted),
                                          ),
                                        const Spacer(),
                                        if (local?.exists == true)
                                          Container(
                                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                            decoration: BoxDecoration(
                                              color: palette.success.withValues(alpha: 0.16),
                                              borderRadius: BorderRadius.circular(6),
                                            ),
                                            child: Text(
                                              '已入库',
                                              style: TextStyle(fontSize: 10, color: palette.success, fontWeight: FontWeight.w600),
                                            ),
                                          ),
                                      ],
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      r.title,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(fontSize: 13, color: palette.textPrimary),
                                    ),
                                    const SizedBox(height: 4),
                                    if (r.actors.isNotEmpty)
                                      Text(
                                        r.actors.join(', '),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: TextStyle(fontSize: 11.5, color: palette.textMuted),
                                      ),
                                    const SizedBox(height: 6),
                                    Row(
                                      children: [
                                        if (local?.exists == true)
                                          TextButton.icon(
                                            onPressed: () {
                                              Navigator.of(context).push(
                                                MaterialPageRoute<void>(
                                                  builder: (_) => BuiltInPlayerPage(
                                                    api: api,
                                                    title: r.title,
                                                    partPaths: local!.partPaths,
                                                    partTokens: local.partTokens,
                                                  ),
                                                ),
                                              );
                                            },
                                            icon: const Icon(Icons.play_arrow_rounded, size: 16),
                                            label: const Text('播放'),
                                          )
                                        else
                                          TextButton.icon(
                                            onPressed: () => _toggleWishlist(r),
                                            icon: Icon(
                                              saved ? Icons.bookmark_rounded : Icons.bookmark_add_outlined,
                                              size: 16,
                                            ),
                                            label: Text(saved ? '已收藏' : '加入书签'),
                                          ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    )
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                      children: [
                        if (_makerCapsules.isNotEmpty) ...[
                          Text('片商新作速览', style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                          const SizedBox(height: 8),
                          Wrap(
                            spacing: 8,
                            runSpacing: 6,
                            children: _makerCapsules.map((m) {
                              final name = (m['maker'] ?? '').toString();
                              final total = (m['total'] ?? 0).toString();
                              return ActionChip(
                                label: Text('$name ($total)'),
                                onPressed: () => _startSearch(makerKey: name, makerName: name),
                              );
                            }).toList(),
                          ),
                          const SizedBox(height: 18),
                        ],
                        Row(
                          children: [
                            Text(
                              '待整理文件 (${_favoriteFiles.length})',
                              style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary),
                            ),
                            const Spacer(),
                            IconButton(
                              onPressed: _loadingFavorites ? null : _loadFavoriteFiles,
                              icon: const Icon(Icons.refresh_rounded, size: 18),
                            ),
                          ],
                        ),
                        if (_loadingFavorites)
                          const LinearProgressIndicator(minHeight: 2)
                        else if (_favoriteFiles.isEmpty)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 20),
                            child: Text('暂无待整理文件（可在设置中配置待整理文件夹）', style: TextStyle(color: palette.textMuted, fontSize: 12.5)),
                          )
                        else
                          ..._favoriteFiles.map(
                            (f) => Card(
                              margin: const EdgeInsets.only(bottom: 8),
                              child: ListTile(
                                title: Text(f.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                                subtitle: Text(f.number.isNotEmpty ? '推测番号: ${f.number}' : f.path, maxLines: 1, overflow: TextOverflow.ellipsis),
                                trailing: FilledButton.tonal(
                                  onPressed: () => _scrapeFavoriteFile(f),
                                  child: const Text('整理'),
                                ),
                                onTap: f.number.isEmpty ? null : () => _startSearch(overrideQuery: f.number),
                              ),
                            ),
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
