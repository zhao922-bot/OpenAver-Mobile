import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/search_models.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';
import '../shared/openaver_image.dart';
import 'search_result_detail_page.dart';

class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});

  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final TextEditingController _queryCtrl = TextEditingController();
  CancelToken? _searchCancel;

  bool _searching = false;
  bool _inResultsMode = false;
  String _activeSearchLabel = '';
  String? _searchError;
  String _searchMode = '';
  final Map<String, String> _sourceStatuses = {};
  List<SearchResultItem> _results = const [];
  Map<String, LocalStatusInfo> _localStatus = const {};
  Set<String> _wishlisted = const {};
  List<Map<String, dynamic>> _makerCapsules = const [];
  bool _recentActressesAvailable = false;
  String _recentActressesKey = '';
  List<FavoriteFileItem> _favoriteFiles = const [];
  bool _loadingFavorites = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadMakerCapsules();
      _loadRecentActressesAvailability();
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

  void _syncBackHook() {
    ref.read(searchResetHookProvider).value = _inResultsMode;
  }

  void _returnToHome() {
    _searchCancel?.cancel();
    _queryCtrl.clear();
    setState(() {
      _searching = false;
      _inResultsMode = false;
      _activeSearchLabel = '';
      _searchError = null;
      _searchMode = '';
      _sourceStatuses.clear();
      _results = const [];
      _localStatus = const {};
    });
    _syncBackHook();
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
    } catch (e) {
      debugPrint('loadMakerCapsules error: $e');
    }
  }

  Future<void> _loadRecentActressesAvailability() async {
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/search/recent-actresses');
      if (!mounted) return;
      setState(() {
        _recentActressesAvailable = resp['available'] == true;
        _recentActressesKey = (resp['key'] ?? '').toString();
      });
    } catch (e) {
      debugPrint('loadRecentActressesAvailability error: $e');
    }
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
    } catch (e) {
      debugPrint('loadFavoriteFiles error: $e');
      if (mounted) {
        setState(() => _loadingFavorites = false);
      }
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
    } catch (e) {
      debugPrint('refreshWishlistMembership error: $e');
    }
  }

  Future<void> _startSearch({String? overrideQuery, String? makerKey, String? makerName}) async {
    final q = (overrideQuery ?? _queryCtrl.text).trim();
    if (makerKey == null && q.length < 2) return;
    if (overrideQuery != null) {
      _queryCtrl.text = overrideQuery;
    } else if (makerName != null && makerName.isNotEmpty) {
      _queryCtrl.text = makerName;
    }
    _searchCancel?.cancel();
    final cancel = CancelToken();
    _searchCancel = cancel;

    setState(() {
      _searching = true;
      _inResultsMode = true;
      _activeSearchLabel = makerName ?? q;
      _searchError = null;
      _results = const [];
      _localStatus = const {};
      _sourceStatuses.clear();
      _searchMode = makerKey != null ? 'maker' : '';
    });
    _syncBackHook();

    final api = ref.read(apiClientProvider);
    final strings = ref.read(stringsProvider);
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
              _searchError = (event.data['message'] ?? strings.taskFailed).toString();
              _searching = false;
            });
            break;
        }
      }
    } catch (e) {
      debugPrint('stream search error: $e');
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

  Future<void> _openBatchSearchDialog() async {
    final strings = ref.read(stringsProvider);
    final ctrl = TextEditingController();
    final submitted = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(strings.batchSearch),
        content: TextField(
          controller: ctrl,
          maxLines: 6,
          minLines: 3,
          decoration: InputDecoration(hintText: strings.batchSearchHint),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: Text(strings.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(ctrl.text), child: Text(strings.startBatchSearch)),
        ],
      ),
    );
    ctrl.dispose();
    if (submitted == null || submitted.trim().isEmpty) return;

    final numbers = submitted
        .split(RegExp(r'[\s,;\n\r]+'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();
    if (numbers.isEmpty) return;

    setState(() {
      _searching = true;
      _inResultsMode = true;
      _activeSearchLabel = '${strings.batchSearch} (${numbers.length})';
      _searchError = null;
      _results = const [];
      _localStatus = const {};
      _sourceStatuses.clear();
      _searchMode = 'batch';
    });
    _syncBackHook();

    try {
      final resp = await ref.read(apiClientProvider).postJson(
        '/api/batch-search',
        data: {'numbers': numbers, 'include_covers': true},
      );
      if (!mounted) return;
      final rawResults = (resp['results'] as Map?) ?? const {};
      final items = <SearchResultItem>[];
      rawResults.forEach((_, val) {
        if (val is Map && val['found'] == true) {
          items.add(SearchResultItem.fromJson(Map<String, dynamic>.from(val)));
        }
      });
      setState(() {
        _results = items;
        _searching = false;
      });
      _checkLocalStatus(items);
    } catch (e) {
      debugPrint('batchSearch error: $e');
      if (!mounted) return;
      setState(() {
        _searching = false;
        _searchError = e.toString();
      });
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
    } catch (e) {
      debugPrint('checkLocalStatus error: $e');
    }
  }

  Future<void> _pickAndImageSearch() async {
    final strings = ref.read(stringsProvider);
    final picked = await NativeBridge.instance.pickFile(
      mimeTypes: const ['image/jpeg', 'image/png', 'image/webp'],
    );
    if (picked == null || picked.path.isEmpty) return;
    final api = ref.read(apiClientProvider);

    if (!mounted) return;
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => AlertDialog(
        content: Row(
          children: [
            const CircularProgressIndicator(),
            const SizedBox(width: 16),
            Text(strings.imageSearching),
          ],
        ),
      ),
    );

    try {
      final lower = picked.name.toLowerCase();
      final mime = (picked.mimeType ?? '').trim().toLowerCase();
      final mediaType = (mime == 'image/jpeg' || mime == 'image/png' || mime == 'image/webp')
          ? DioMediaType.parse(mime)
          : lower.endsWith('.png')
              ? DioMediaType('image', 'png')
              : lower.endsWith('.webp')
                  ? DioMediaType('image', 'webp')
                  : DioMediaType('image', 'jpeg');
      final form = FormData.fromMap({
        'file': await MultipartFile.fromFile(
          picked.path,
          filename: picked.name,
          contentType: mediaType,
        ),
      });
      final resp = await api.dio.post<dynamic>('/api/image-search', data: form);
      if (mounted) Navigator.of(context).pop();
      final body = resp.data is Map ? Map<String, dynamic>.from(resp.data as Map) : const <String, dynamic>{};
      if (body['success'] != true) {
        _toast((body['message'] ?? body['error'] ?? strings.taskFailed).toString());
        return;
      }
      final candidates = ((body['candidates'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (!mounted) return;
      if (candidates.isEmpty) {
        _toast(strings.imageSearchNoMatch);
        return;
      }
      await showModalBottomSheet<void>(
        context: context,
        builder: (ctx) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                title: Text(strings.imageSearchCandidates, style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
              ...candidates.map((c) {
                final candidateNumber = (c['number'] ?? c['code'] ?? '').toString();
                final sim = ((c['similarity'] as num?)?.toDouble() ?? 0.0) * 100;
                final inLib = c['in_library'] == true;
                return ListTile(
                  title: Text(candidateNumber, style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text(strings.matchConfidence(sim.toStringAsFixed(1), inLib)),
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
      debugPrint('imageSearch error: $e');
      if (mounted) Navigator.of(context).pop();
      String msg = strings.requestFailed('$e');
      if (e is DioException && e.response?.data is Map) {
        final errBody = e.response!.data as Map;
        final serverMsg = (errBody['message'] ?? errBody['error'] ?? '').toString();
        if (serverMsg.isNotEmpty) msg = serverMsg;
      }
      _toast(msg);
    }
  }

  Future<bool?> _toggleWishlist(SearchResultItem item) async {
    final strings = ref.read(stringsProvider);
    final key = item.number.toUpperCase();
    final api = ref.read(apiClientProvider);
    try {
      if (_wishlisted.contains(key)) {
        final resp = await api.deleteJson('/api/wishlist/${Uri.encodeComponent(item.number)}');
        if (resp['success'] == true) {
          if (mounted) setState(() => _wishlisted = {..._wishlisted}..remove(key));
          return false;
        }
        return null;
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
        if (!mounted) return null;
        if (resp['success'] == true) {
          setState(() => _wishlisted = {..._wishlisted, key});
          return true;
        } else if (resp['already_owned'] == true) {
          _toast(strings.alreadyOwnedHint);
          return null;
        }
        return null;
      }
    } catch (e) {
      debugPrint('toggleWishlist error: $e');
      _toast(strings.requestFailed('$e'));
      return null;
    }
  }

  Future<void> _openWishlistSheet() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    try {
      final list = await api.getJsonList('/api/wishlist');
      if (!mounted) return;
      final items = list.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (ctx) => StatefulBuilder(
          builder: (sheetCtx, setSheetState) => DraggableScrollableSheet(
            expand: false,
            initialChildSize: 0.72,
            builder: (_, scrollCtrl) => Column(
              children: [
                ListTile(
                  title: Text(strings.wishlistCount(items.length), style: const TextStyle(fontWeight: FontWeight.w700)),
                  trailing: IconButton(
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.of(sheetCtx).pop(),
                  ),
                ),
                const Divider(height: 1),
                Expanded(
                  child: items.isEmpty
                      ? Center(child: Text(strings.emptyWishlist))
                      : ListView.builder(
                          controller: scrollCtrl,
                          itemCount: items.length,
                          itemBuilder: (_, idx) {
                            final w = items[idx];
                            final num = (w['number'] ?? '').toString();
                            final title = (w['title'] ?? '').toString();
                            final coverRaw = (w['cover'] ?? w['cover_url'] ?? '').toString();
                            final coverUrl = coverRaw.isNotEmpty
                                ? '/api/proxy-image?url=${Uri.encodeQueryComponent(coverRaw)}'
                                : (num.isNotEmpty
                                    ? '/api/wishlist/cover?number=${Uri.encodeQueryComponent(num)}'
                                    : '');
                            return ListTile(
                              leading: coverUrl.isNotEmpty
                                  ? ClipRRect(
                                      borderRadius: BorderRadius.circular(6),
                                      child: SizedBox(
                                        width: 56,
                                        height: 40,
                                        child: OpenAverNetworkImage(
                                          api: api,
                                          url: coverUrl,
                                          targetDecodeWidth: 160,
                                        ),
                                      ),
                                    )
                                  : null,
                              title: Text(num, style: const TextStyle(fontWeight: FontWeight.w700)),
                              subtitle: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
                              trailing: IconButton(
                                icon: const Icon(Icons.delete_outline_rounded),
                                onPressed: () async {
                                  await api.deleteJson('/api/wishlist/${Uri.encodeComponent(num)}');
                                  setSheetState(() {
                                    items.removeWhere((e) => (e['number'] ?? '').toString() == num);
                                  });
                                  _refreshWishlistMembership();
                                },
                              ),
                              onTap: () {
                                Navigator.of(sheetCtx).pop();
                                _startSearch(overrideQuery: num);
                              },
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      );
    } catch (e) {
      debugPrint('openWishlistSheet error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _scrapeFavoriteFile(FavoriteFileItem file) async {
    final strings = ref.read(stringsProvider);
    final ctrl = TextEditingController(text: file.number);
    final number = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(strings.scrapeOrganizeTitle),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(file.name, style: const TextStyle(fontSize: 12)),
            const SizedBox(height: 10),
            TextField(
              controller: ctrl,
              decoration: InputDecoration(labelText: strings.detectedNumberField),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: Text(strings.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(ctrl.text), child: Text(strings.startOrganize)),
        ],
      ),
    );
    ctrl.dispose();
    if (number == null || number.trim().isEmpty) return;
    _toast('${strings.startOrganize}: ${number.trim()}…');
    try {
      final resp = await ref.read(apiClientProvider).postJson('/api/scrape-single', data: {
        'file_path': file.path,
        'number': number.trim(),
      });
      if (!mounted) return;
      if (resp['success'] == true) {
        _toast(strings.organizeCompleted);
        _loadFavoriteFiles();
      } else {
        _toast((resp['error'] ?? strings.taskFailed).toString());
      }
    } catch (e) {
      debugPrint('scrapeFavoriteFile error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  void _openResultDetail(int index) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => SearchResultDetailPage(
          results: _results,
          initialIndex: index,
          localStatus: _localStatus,
          wishlistedNumbers: _wishlisted,
          onToggleWishlist: _toggleWishlist,
          onSearchActor: (actor) => _startSearch(overrideQuery: actor),
        ),
      ),
    );
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiClientProvider);
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);

    // Respond if parent PopScope cleared reset hook
    final resetHook = ref.watch(searchResetHookProvider);
    if (!resetHook.value && _inResultsMode && !_searching) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !resetHook.value && _inResultsMode) {
          _returnToHome();
        }
      });
    }

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
              child: Row(
                children: [
                  if (_inResultsMode) ...[
                    IconButton.filledTonal(
                      tooltip: strings.backToSearchHome,
                      onPressed: _returnToHome,
                      icon: const Icon(Icons.arrow_back_rounded),
                    ),
                    const SizedBox(width: 6),
                  ],
                  Expanded(
                    child: TextField(
                      controller: _queryCtrl,
                      textInputAction: TextInputAction.search,
                      decoration: InputDecoration(
                        hintText: strings.searchQueryHint,
                        prefixIcon: const Icon(Icons.search_rounded),
                        suffixIcon: _searching
                            ? IconButton(
                                icon: const Icon(Icons.stop_circle_outlined),
                                onPressed: () {
                                  _searchCancel?.cancel();
                                  setState(() => _searching = false);
                                },
                              )
                            : ((_queryCtrl.text.isEmpty && !_inResultsMode)
                                ? null
                                : IconButton(
                                    icon: const Icon(Icons.clear_rounded, size: 18),
                                    onPressed: _returnToHome,
                                  )),
                      ),
                      onChanged: (_) => setState(() {}),
                      onSubmitted: (_) => _startSearch(),
                    ),
                  ),
                  const SizedBox(width: 6),
                  IconButton.filledTonal(
                    tooltip: strings.batchSearch,
                    onPressed: _openBatchSearchDialog,
                    icon: const Icon(Icons.playlist_play_rounded),
                  ),
                  const SizedBox(width: 4),
                  IconButton.filledTonal(
                    tooltip: strings.imageSearch,
                    onPressed: _pickAndImageSearch,
                    icon: const Icon(Icons.image_search_rounded),
                  ),
                  const SizedBox(width: 4),
                  IconButton.filledTonal(
                    tooltip: strings.wishlistCount(_wishlisted.length),
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

            if (_inResultsMode)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
                child: Row(
                  children: [
                    ActionChip(
                      avatar: const Icon(Icons.home_outlined, size: 16),
                      label: Text(strings.backToSearchHome),
                      onPressed: _returnToHome,
                    ),
                    const SizedBox(width: 8),
                    if (_activeSearchLabel.isNotEmpty)
                      Expanded(
                        child: Text(
                          '$_activeSearchLabel (${_results.length})',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 12, color: palette.textMuted),
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
                        child: Chip(label: Text('${e.key}: ${e.value}')),
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
              child: _inResultsMode
                  ? (_results.isEmpty && !_searching
                      ? Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(strings.emptySearchResults, style: TextStyle(color: palette.textMuted)),
                              const SizedBox(height: 12),
                              OutlinedButton.icon(
                                onPressed: _returnToHome,
                                icon: const Icon(Icons.arrow_back_rounded),
                                label: Text(strings.backToSearchHome),
                              ),
                            ],
                          ),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                          itemCount: _results.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 10),
                          itemBuilder: (_, index) {
                            final r = _results[index];
                            final local = _localStatus[r.number.toUpperCase()];
                            final saved = _wishlisted.contains(r.number.toUpperCase());
                            final coverProxy = r.cover.isNotEmpty
                                ? '/api/proxy-image?url=${Uri.encodeQueryComponent(r.cover)}'
                                : '';

                            return InkWell(
                              borderRadius: BorderRadius.circular(12),
                              onTap: () => _openResultDetail(index),
                              child: Container(
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
                                        child: OpenAverNetworkImage(
                                          api: api,
                                          url: coverProxy,
                                          targetDecodeWidth: 280,
                                        ),
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
                                                    strings.inLibraryBadge,
                                                    style: TextStyle(
                                                      fontSize: 10,
                                                      color: palette.success,
                                                      fontWeight: FontWeight.w600,
                                                    ),
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
                                                  label: Text(strings.playLabel),
                                                )
                                              else
                                                TextButton.icon(
                                                  onPressed: () => _toggleWishlist(r),
                                                  icon: Icon(
                                                    saved ? Icons.bookmark_rounded : Icons.bookmark_add_outlined,
                                                    size: 16,
                                                  ),
                                                  label: Text(saved ? strings.wishlisted : strings.addWishlist),
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
                          },
                        ))
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                      children: [
                        if (_recentActressesAvailable || _makerCapsules.isNotEmpty) ...[
                          Text(strings.makerCapsulesTitle, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                          const SizedBox(height: 8),
                          Wrap(
                            spacing: 8,
                            runSpacing: 6,
                            children: [
                              if (_recentActressesAvailable && _recentActressesKey.isNotEmpty)
                                ActionChip(
                                  avatar: Icon(Icons.favorite_rounded, size: 15, color: palette.favoritePink),
                                  label: Text(strings.recentActressesLabel),
                                  onPressed: () => _startSearch(
                                    makerKey: _recentActressesKey,
                                    makerName: strings.recentActressesLabel,
                                  ),
                                ),
                              ..._makerCapsules.map((m) {
                                final name = (m['maker'] ?? '').toString();
                                final total = (m['total'] ?? 0).toString();
                                return ActionChip(
                                  label: Text('$name ($total)'),
                                  onPressed: () => _startSearch(makerKey: name, makerName: name),
                                );
                              }),
                            ],
                          ),
                          const SizedBox(height: 18),
                        ],
                        Row(
                          children: [
                            Text(
                              strings.favoriteFilesTitle(_favoriteFiles.length),
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
                            child: Text(strings.noFavoriteFiles, style: TextStyle(color: palette.textMuted, fontSize: 12.5)),
                          )
                        else
                          ..._favoriteFiles.map(
                            (f) => Card(
                              margin: const EdgeInsets.only(bottom: 8),
                              child: ListTile(
                                title: Text(f.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                                subtitle: Text(
                                  f.number.isNotEmpty ? strings.guessedNumber(f.number) : f.path,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                                trailing: FilledButton.tonal(
                                  onPressed: () => _scrapeFavoriteFile(f),
                                  child: Text(strings.organizeBtn),
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
