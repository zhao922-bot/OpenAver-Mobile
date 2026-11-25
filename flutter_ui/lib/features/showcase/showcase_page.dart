import 'dart:async';
import 'dart:math';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import '../../core/models/actress_models.dart';
import '../../core/models/video_item.dart';
import '../shared/openaver_image.dart';
import '../shared/prompt_dialog.dart';
import 'actress_detail_page.dart';
import 'continue_watching_tile.dart';
import 'video_detail_sheet.dart';

class ShowcasePage extends ConsumerStatefulWidget {
  const ShowcasePage({super.key});

  @override
  ConsumerState<ShowcasePage> createState() => _ShowcasePageState();
}

class _ShowcasePageState extends ConsumerState<ShowcasePage> {
  final TextEditingController _searchCtrl = TextEditingController();
  final ScrollController _gridScroll = ScrollController();

  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  List<VideoItem> _videos = const [];
  List<ActressProfile> _actresses = const [];

  bool _actressMode = false;
  bool _favoritesOnly = false;
  bool _listView = false;
  String _sort = 'date';
  String _order = 'desc';
  int? _randomSeed;
  int? _columnOverride; // null = responsive Auto
  int _page = 1;
  int _totalPages = 1;
  int _total = 0;
  static const int _perPage = 45;
  Timer? _reloadTimer;
  CancelToken? _loadCancel;
  Future<void>? _pendingMore;

  @override
  void initState() {
    super.initState();
    _gridScroll.addListener(_onScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadData());
  }

  @override
  void dispose() {
    _reloadTimer?.cancel();
    _cancelLoad();
    _searchCtrl.dispose();
    _gridScroll.removeListener(_onScroll);
    _gridScroll.dispose();
    super.dispose();
  }

  void _cancelLoad() {
    final cancel = _loadCancel;
    _loadCancel = null;
    _pendingMore = null;
    cancel?.cancel();
  }

  bool _ownsLoad(CancelToken cancel) => mounted && _loadCancel == cancel;

  void _resetLoadingState() {
    _loading = true;
    _loadingMore = false;
    _error = null;
    _page = 1;
    _totalPages = 1;
    _total = 0;
  }

  void _scheduleLoad(Duration delay) {
    _reloadTimer?.cancel();
    _cancelLoad();
    setState(_resetLoadingState);
    _reloadTimer = Timer(delay, _loadData);
  }

  void _onFilterChanged(String? previous, String? next) {
    _actressMode = false;
    // Clearing both filters is a single user action.
    _scheduleLoad(Duration.zero);
  }

  void _onScroll() {
    if (_actressMode || _loading || _loadingMore || _page >= _totalPages) return;
    if (!_gridScroll.hasClients) return;
    final pos = _gridScroll.position;
    if (pos.pixels >= pos.maxScrollExtent - 320) {
      _loadMore();
    }
  }

  int _effectiveColumns(double width) {
    if (_columnOverride != null) return _columnOverride!;
    if (width >= 1000) return 5;
    if (width >= 720) return 4;
    if (width >= 520) return 3;
    return 3;
  }

  Future<Map<String, dynamic>> _fetchVideoPage(int page, CancelToken cancel) {
    final query = _searchCtrl.text.trim();
    final actress = ref.read(showcaseActressFilterProvider);
    final tag = ref.read(showcaseTagFilterProvider);
    return ref.read(apiClientProvider).getJson(
      '/api/showcase/videos',
      queryParameters: {
        'paged': true,
        'page': page,
        'per_page': _perPage,
        'sort': _sort,
        'order': _order,
        if (query.isNotEmpty) 'q': query,
        if (actress != null && actress.isNotEmpty) 'actress': actress,
        if (tag != null && tag.isNotEmpty) 'tag': tag,
        if (_favoritesOnly) 'favorites_only': true,
        if (_sort == 'random') 'random_seed': _randomSeed,
      },
      cancelToken: cancel,
    );
  }

  Future<void> _loadData() async {
    if (!mounted) return;
    _reloadTimer?.cancel();
    _reloadTimer = null;
    _cancelLoad();
    final cancel = CancelToken();
    _loadCancel = cancel;
    setState(_resetLoadingState);

    if (_actressMode) {
      await _loadActresses(cancel);
      return;
    }
    final strings = ref.read(stringsProvider);

    try {
      final resp = await _fetchVideoPage(1, cancel);
      if (!_ownsLoad(cancel)) return;
      if (resp['success'] != true) {
        setState(() {
          _loading = false;
          _error = (resp['error'] ?? strings.loadLibraryFailed).toString();
        });
        return;
      }
      final parsed = VideosPageResponse.fromJson(resp);
      setState(() {
        _videos = parsed.videos;
        _total = parsed.total;
        _page = parsed.page;
        _totalPages = parsed.totalPages;
        _loading = false;
      });
    } catch (e) {
      if (!_ownsLoad(cancel)) return;
      debugPrint('Showcase _loadData error: $e');
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _loadMore() {
    final pending = _pendingMore;
    if (pending != null) return pending;
    final cancel = _loadCancel;
    if (cancel == null || _loading || _actressMode || _page >= _totalPages) {
      return Future.value();
    }
    return _pendingMore = _requestMore(_page + 1, cancel);
  }

  Future<void> _requestMore(int page, CancelToken cancel) async {
    setState(() => _loadingMore = true);
    try {
      final resp = await _fetchVideoPage(page, cancel);
      if (!_ownsLoad(cancel)) return;
      if (resp['success'] == true) {
        final parsed = VideosPageResponse.fromJson(resp);
        final seen = _videos.map((e) => e.path).toSet();
        final appended = parsed.videos.where((v) => seen.add(v.path)).toList();
        setState(() {
          _videos = [..._videos, ...appended];
          _page = parsed.page;
          _totalPages = parsed.totalPages;
          _total = parsed.total;
        });
      }
    } catch (e) {
      if (!_ownsLoad(cancel)) return;
      debugPrint('Showcase _loadMore error: $e');
      _toast(ref.read(stringsProvider).requestFailed('$e'));
    } finally {
      if (_ownsLoad(cancel)) {
        _pendingMore = null;
        setState(() => _loadingMore = false);
      }
    }
  }

  Future<void> _loadActresses(CancelToken cancel) async {
    final api = ref.read(apiClientProvider);
    try {
      final libFuture = api.getJson('/api/actresses/library', cancelToken: cancel);
      final favFuture = api.getJson('/api/actresses', cancelToken: cancel).catchError((Object e) {
        if (_ownsLoad(cancel)) debugPrint('fetch /api/actresses error: $e');
        return <String, dynamic>{};
      });
      final libResp = await libFuture;
      final favResp = await favFuture;
      if (!_ownsLoad(cancel)) return;

      final favByName = <String, ActressProfile>{};
      final favList = (favResp['actresses'] as List?) ?? const [];
      for (final raw in favList.whereType<Map>()) {
        final p = ActressProfile.fromJson(Map<String, dynamic>.from(raw)).copyWith(isFavorite: true);
        if (p.name.isNotEmpty) {
          favByName[p.name] = p;
        }
      }

      final libList = (libResp['actresses'] as List?) ?? const [];
      final merged = <ActressProfile>[];
      final seenNames = <String>{};
      for (final raw in libList.whereType<Map>()) {
        final g = LibraryActressGroup.fromJson(Map<String, dynamic>.from(raw));
        final rich = favByName[g.primaryName];
        seenNames.add(g.primaryName);
        if (rich != null) {
          merged.add(rich.copyWith(
            videoCount: g.videoCount,
            aliases: g.aliases.isNotEmpty ? g.aliases : rich.aliases,
            photoUrl: g.photoUrl.isNotEmpty ? g.photoUrl : rich.photoUrl,
            isFavorite: true,
          ));
        } else {
          merged.add(ActressProfile(
            name: g.primaryName,
            aliases: g.aliases,
            birth: '',
            age: null,
            height: '',
            cup: '',
            bust: '',
            waist: '',
            hip: '',
            hometown: '',
            hobby: '',
            photoUrl: g.photoUrl,
            photoSource: '',
            autoFocal: '',
            cropMode: 'auto',
            isFavorite: g.isFavorite,
            videoCount: g.videoCount,
          ));
        }
      }

      // Include favorited actresses that currently have 0 library videos too
      for (final fav in favByName.values) {
        if (!seenNames.contains(fav.name)) {
          merged.add(fav);
        }
      }

      final query = _searchCtrl.text.trim().toLowerCase();
      var filtered = merged;
      if (_favoritesOnly) {
        filtered = filtered.where((a) => a.isFavorite).toList();
      }
      if (query.isNotEmpty) {
        filtered = filtered
            .where((a) =>
                a.name.toLowerCase().contains(query) ||
                a.aliases.any((al) => al.toLowerCase().contains(query)))
            .toList();
      }

      setState(() {
        _actresses = filtered;
        _total = filtered.length;
        _loading = false;
      });
    } catch (e) {
      if (!_ownsLoad(cancel)) return;
      debugPrint('Showcase _loadActresses error: $e');
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _toggleActressFavoriteInline(ActressProfile actress) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    try {
      if (actress.isFavorite) {
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: Text(strings.unfavoriteActress),
            content: Text(strings.confirmUnfavoriteActress),
            actions: [
              TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(strings.cancel)),
              FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(strings.confirm)),
            ],
          ),
        );
        if (ok != true) return;
        final resp = await api.deleteJson('/api/actresses/${Uri.encodeComponent(actress.name)}');
        if (!mounted) return;
        if (resp['success'] == true) {
          _updateActressItem(actress.copyWith(isFavorite: false));
          _toast(strings.actressRemoved);
        }
      } else {
        final resp = await api.dio.post<dynamic>(
          '/api/actresses/favorite',
          data: {'name': actress.name},
        );
        final body = resp.data is Map
            ? Map<String, dynamic>.from(resp.data as Map)
            : const <String, dynamic>{};
        if (!mounted) return;
        if ((resp.statusCode == 200 || resp.statusCode == 409) && body['actress'] is Map) {
          final updated = ActressProfile.fromJson(
            Map<String, dynamic>.from(body['actress'] as Map),
            fallbackVideoCount: actress.videoCount,
          ).copyWith(isFavorite: true);
          _updateActressItem(updated);
          _toast(resp.statusCode == 409 ? strings.actressAlreadyExists : strings.actressAdded);
        } else if (body['success'] == true) {
          _updateActressItem(actress.copyWith(isFavorite: true));
          _toast(strings.actressAdded);
        } else {
          _toast((body['message'] ?? body['error'] ?? strings.saveFailed).toString());
        }
      }
    } catch (e) {
      debugPrint('toggleActressFavoriteInline error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  Future<void> _showAddActressDialog() async {
    final strings = ref.read(stringsProvider);
    final name = await showPromptTextDialog(
      context: context,
      title: strings.addFavoriteActress,
      hintText: strings.actressNameHint,
      cancelLabel: strings.cancel,
      confirmLabel: strings.add,
    );
    if (!mounted || name == null || name.trim().isEmpty) return;
    final api = ref.read(apiClientProvider);
    try {
      final resp = await api.dio.post<dynamic>(
        '/api/actresses/favorite',
        data: {'name': name.trim()},
      );
      final body = resp.data is Map
          ? Map<String, dynamic>.from(resp.data as Map)
          : const <String, dynamic>{};
      if (!mounted) return;
      if (resp.statusCode == 200 || resp.statusCode == 409) {
        _toast(resp.statusCode == 409 ? strings.actressAlreadyExists : strings.actressAdded);
        if (_actressMode) _loadData();
      } else {
        _toast((body['message'] ?? body['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('addActress error: $e');
      _toast(strings.requestFailed('$e'));
    }
  }

  void _updateActressItem(ActressProfile updated) {
    if (!mounted) return;
    setState(() {
      final idx = _actresses.indexWhere((a) => a.name == updated.name);
      if (idx != -1) {
        final copy = List<ActressProfile>.from(_actresses);
        copy[idx] = updated;
        _actresses = copy;
      }
    });
  }

  void _openActressDetail(int index) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ActressDetailPage(
          actresses: _actresses,
          initialIndex: index,
          onActressUpdated: _updateActressItem,
          onViewVideos: _showActressVideos,
        ),
      ),
    );
  }

  void _showActressVideos(String name) {
    if (ref.read(showcaseActressFilterProvider) == name) {
      if (_actressMode) {
        setState(() => _actressMode = false);
        _loadData();
      }
      return;
    }
    ref.read(showcaseActressFilterProvider.notifier).setActress(name);
  }

  Future<void> _openDetail(int index) async {
    final cancel = _loadCancel;
    final videos = _videos;
    final total = _total;
    final hasMore = _page < _totalPages;
    var browseChanged = false;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => VideoDetailPage(
          videos: videos,
          initialIndex: index,
          totalVideos: total,
          loadMoreVideos: cancel == null || !hasMore
              ? null
              : () async {
                  if (browseChanged || !_ownsLoad(cancel)) return null;
                  await _loadMore();
                  if (browseChanged || !_ownsLoad(cancel)) return null;
                  return (videos: _videos, hasMore: _page < _totalPages);
                },
          onVideoUpdated: (updated) {
            if (!mounted || (cancel != null && !_ownsLoad(cancel))) return;
            final idx = _videos.indexWhere((v) => v.path == updated.path);
            final previous = idx == -1 ? null : _videos[idx];
            if (_searchCtrl.text.trim().isNotEmpty ||
                ref.read(showcaseTagFilterProvider) != null ||
                (_favoritesOnly && previous?.isFavorite != updated.isFavorite) ||
                (_sort == 'title' && previous?.title != updated.title)) {
              browseChanged = true;
            }
            if (idx != -1) {
              setState(() {
                final copy = List<VideoItem>.from(_videos);
                copy[idx] = updated;
                _videos = copy;
              });
            }
          },
          onVideoDeleted: (deletedPath) {
            if (!mounted || (cancel != null && !_ownsLoad(cancel))) return;
            browseChanged = true;
            if (_videos.any((v) => v.path == deletedPath)) {
              setState(() {
                _videos = _videos.where((v) => v.path != deletedPath).toList();
                _total = (_total - 1).clamp(0, _total);
              });
            }
          },
          onSelectActress: _showActressVideos,
          onSelectTag: (tag) {
            ref.read(showcaseTagFilterProvider.notifier).setTag(tag);
          },
          onSelectFilterText: (term) {
            _searchCtrl.text = term;
            setState(() => _actressMode = false);
            _loadData();
          },
        ),
      ),
    );
    if (browseChanged && mounted && (cancel == null || _ownsLoad(cancel))) {
      _loadData();
    }
  }

  void _showSortSheet(AppStrings strings) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) {
        final sorts = [
          ('date', strings.sortDate),
          ('mdate', strings.sortAdded),
          ('num', strings.sortNumber),
          ('title', strings.sortTitle),
          ('actor', strings.sortActor),
          ('maker', strings.sortMaker),
          ('size', strings.sortSize),
          ('random', strings.sortRandom),
        ];
        final maxSheetHeight = MediaQuery.sizeOf(ctx).height * 0.85;
        return ConstrainedBox(
          constraints: BoxConstraints(maxHeight: maxSheetHeight),
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        strings.sortAndDisplay,
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                      ),
                    ),
                    const SizedBox(width: 12),
                    SegmentedButton<String>(
                      segments: [
                        ButtonSegment(value: 'desc', label: Text(strings.sortDesc)),
                        ButtonSegment(value: 'asc', label: Text(strings.sortAsc)),
                      ],
                      selected: {_order},
                      onSelectionChanged: (values) {
                        setState(() {
                          _order = values.first;
                          _page = 1;
                        });
                        Navigator.of(ctx).pop();
                        _loadData();
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: sorts.map((s) {
                    return ChoiceChip(
                      label: Text(s.$2),
                      selected: _sort == s.$1,
                      onSelected: (_) {
                        setState(() {
                          _sort = s.$1;
                          _randomSeed = _sort == 'random' ? Random().nextInt(1 << 31) : null;
                          _page = 1;
                        });
                        Navigator.of(ctx).pop();
                        _loadData();
                      },
                    );
                  }).toList(),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        strings.viewMode,
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ),
                    const SizedBox(width: 12),
                    SegmentedButton<bool>(
                      segments: [
                        ButtonSegment(value: false, label: Text(strings.viewGrid)),
                        ButtonSegment(value: true, label: Text(strings.viewList)),
                      ],
                      selected: {_listView},
                      onSelectionChanged: (values) {
                        setState(() => _listView = values.first);
                        Navigator.of(ctx).pop();
                      },
                    ),
                  ],
                ),
                if (!_listView) ...[
                  const SizedBox(height: 16),
                  Text(
                    strings.columnsPerRow,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: SegmentedButton<int?>(
                      showSelectedIcon: false,
                      segments: [
                        ButtonSegment(value: null, label: Text(strings.autoLabel)),
                        ButtonSegment(value: 2, label: Text(strings.columnsCount(2))),
                        ButtonSegment(value: 3, label: Text(strings.columnsCount(3))),
                        ButtonSegment(value: 4, label: Text(strings.columnsCount(4))),
                      ],
                      selected: {_columnOverride},
                      onSelectionChanged: (values) {
                        setState(() => _columnOverride = values.first);
                        Navigator.of(ctx).pop();
                      },
                    ),
                  ),
                ],
              ],
            ),
          ),
        );
      },
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
    final actressFilter = ref.watch(showcaseActressFilterProvider);
    final tagFilter = ref.watch(showcaseTagFilterProvider);

    ref.listen<String?>(showcaseActressFilterProvider, _onFilterChanged);
    ref.listen<String?>(showcaseTagFilterProvider, _onFilterChanged);
    ref.listen(libraryRevisionProvider, (_, _) => _loadData());

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
                      controller: _searchCtrl,
                      decoration: InputDecoration(
                        hintText: strings.searchLibraryHint,
                        prefixIcon: const Icon(Icons.search_rounded, size: 20),
                        suffixIcon: _searchCtrl.text.isEmpty
                            ? null
                            : IconButton(
                                icon: const Icon(Icons.clear_rounded, size: 18),
                                onPressed: () {
                                  _searchCtrl.clear();
                                  _loadData();
                                },
                              ),
                      ),
                      onChanged: (_) => _scheduleLoad(const Duration(milliseconds: 280)),
                    ),
                  ),
                  const SizedBox(width: 8),
                  if (_actressMode)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: IconButton.filledTonal(
                        tooltip: strings.addFavoriteActress,
                        onPressed: _showAddActressDialog,
                        icon: const Icon(Icons.person_add_alt_1_rounded),
                      ),
                    ),
                  IconButton.filledTonal(
                    tooltip: strings.sortAndDisplay,
                    onPressed: () => _showSortSheet(strings),
                    icon: const Icon(Icons.tune_rounded),
                  ),
                ],
              ),
            ),

            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Row(
                children: [
                  FilterChip(
                    label: Text('${strings.allVideos} ($_total)'),
                    selected: !_actressMode && !_favoritesOnly && actressFilter == null && tagFilter == null,
                    onSelected: (_) {
                      final hasFilters = ref.read(showcaseActressFilterProvider) != null ||
                          ref.read(showcaseTagFilterProvider) != null;
                      setState(() {
                        _actressMode = false;
                        _favoritesOnly = false;
                      });
                      ref.read(showcaseActressFilterProvider.notifier).setActress(null);
                      ref.read(showcaseTagFilterProvider.notifier).setTag(null);
                      if (!hasFilters) _loadData();
                    },
                  ),
                  const SizedBox(width: 8),
                  FilterChip(
                    avatar: Icon(
                      Icons.favorite_rounded,
                      size: 16,
                      color: _favoritesOnly ? palette.favoritePink : palette.textMuted,
                    ),
                    label: Text(strings.favoritesOnly),
                    selected: _favoritesOnly,
                    onSelected: (v) {
                      setState(() {
                        _favoritesOnly = v;
                        _page = 1;
                      });
                      _loadData();
                    },
                  ),
                  const SizedBox(width: 8),
                  FilterChip(
                    avatar: const Icon(Icons.people_alt_outlined, size: 16),
                    label: Text(strings.actresses),
                    selected: _actressMode,
                    onSelected: (v) {
                      setState(() => _actressMode = v);
                      _loadData();
                    },
                  ),
                  if (actressFilter != null && actressFilter.isNotEmpty) ...[
                    const SizedBox(width: 8),
                    InputChip(
                      label: Text(actressFilter),
                      selected: true,
                      onDeleted: () {
                        ref.read(showcaseActressFilterProvider.notifier).setActress(null);
                      },
                    ),
                  ],
                  if (tagFilter != null && tagFilter.isNotEmpty) ...[
                    const SizedBox(width: 8),
                    InputChip(
                      avatar: const Icon(Icons.label_outline_rounded, size: 15),
                      label: Text(tagFilter),
                      selected: true,
                      onDeleted: () {
                        ref.read(showcaseTagFilterProvider.notifier).setTag(null);
                      },
                    ),
                  ],
                ],
              ),
            ),

            if (!_loading && !_actressMode && !_favoritesOnly &&
                actressFilter == null && tagFilter == null &&
                _searchCtrl.text.trim().isEmpty && ref.watch(activeTabProvider) == 0 &&
                ModalRoute.isCurrentOf(context) == true)
              ContinueWatchingTile(key: ValueKey((api, _loadCancel)), api: api),
            Expanded(
              child: LayoutBuilder(
                builder: (_, constraints) {
                  final columns = _effectiveColumns(constraints.maxWidth);
                  final itemWidthPx = ((constraints.maxWidth / columns) * MediaQuery.devicePixelRatioOf(context))
                      .round()
                      .clamp(200, 900);
                  return RefreshIndicator(
                    onRefresh: _loadData,
                    child: _loading
                        ? const Center(child: CircularProgressIndicator())
                        : _error != null
                            ? ListView(
                                children: [
                                  Padding(
                                    padding: const EdgeInsets.all(32),
                                    child: Column(
                                      children: [
                                        Text(_error!, style: TextStyle(color: palette.danger)),
                                        const SizedBox(height: 12),
                                        FilledButton(onPressed: _loadData, child: Text(strings.retry)),
                                      ],
                                    ),
                                  ),
                                ],
                              )
                            : (_actressMode
                                ? _buildActressGrid(api, palette, strings, columns, itemWidthPx)
                                : _buildVideoView(api, palette, strings, columns, itemWidthPx)),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildVideoView(
    ApiClient api,
    OpenAverPalette palette,
    AppStrings strings,
    int columns,
    int decodeWidth,
  ) {
    if (_videos.isEmpty) {
      return ListView(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 72, horizontal: 24),
            child: Column(
              children: [
                Icon(Icons.video_library_outlined, size: 48, color: palette.textMuted),
                const SizedBox(height: 12),
                Text(strings.emptyVideos, style: TextStyle(color: palette.textMuted)),
              ],
            ),
          ),
        ],
      );
    }

    if (_listView) {
      return ListView.separated(
        controller: _gridScroll,
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 24),
        itemCount: _videos.length + (_loadingMore || _page < _totalPages ? 1 : 0),
        separatorBuilder: (_, _) => const SizedBox(height: 8),
        itemBuilder: (_, index) {
          if (index >= _videos.length) {
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Center(
                child: _loadingMore
                    ? const CircularProgressIndicator(strokeWidth: 2)
                    : Text(strings.loadingMore, style: TextStyle(color: palette.textMuted, fontSize: 12)),
              ),
            );
          }
          final v = _videos[index];
          return Card(
            child: ListTile(
              contentPadding: const EdgeInsets.all(8),
              leading: ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: SizedBox(
                  width: 96,
                  height: 64,
                  child: OpenAverNetworkImage(
                    api: api,
                    url: v.coverUrl,
                    alignment: v.focalAlignment,
                    targetDecodeWidth: 260,
                    errorIcon: Icons.movie_outlined,
                  ),
                ),
              ),
              title: Text(
                v.title.isNotEmpty ? v.title : v.number,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
              ),
              subtitle: Text(
                [
                  if (v.number.isNotEmpty) v.number,
                  if (v.actresses.isNotEmpty) v.actresses.take(2).join(', '),
                  if (v.releaseDate.isNotEmpty) v.releaseDate,
                ].join(' · '),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11.5, color: palette.textMuted),
              ),
              trailing: v.isFavorite
                  ? Icon(Icons.favorite_rounded, color: palette.favoritePink, size: 18)
                  : null,
              onTap: () => _openDetail(index),
            ),
          );
        },
      );
    }

    return CustomScrollView(
      controller: _gridScroll,
      slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(10, 6, 10, 10),
          sliver: SliverGrid(
            gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: columns,
              mainAxisSpacing: 8,
              crossAxisSpacing: 8,
              childAspectRatio: columns >= 4 ? 0.68 : 0.72,
            ),
            delegate: SliverChildBuilderDelegate(
              (_, index) {
                final v = _videos[index];
                return GestureDetector(
                  onTap: () => _openDetail(index),
                  child: Container(
                    decoration: BoxDecoration(
                      color: palette.surface,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: palette.stroke),
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              OpenAverNetworkImage(
                                api: api,
                                url: v.coverUrl,
                                alignment: v.focalAlignment,
                                targetDecodeWidth: decodeWidth,
                                errorIcon: Icons.movie_outlined,
                              ),
                              if (v.isFavorite)
                                Positioned(
                                  top: 5,
                                  right: 5,
                                  child: Container(
                                    padding: const EdgeInsets.all(3),
                                    decoration: const BoxDecoration(
                                      color: Colors.black54,
                                      shape: BoxShape.circle,
                                    ),
                                    child: Icon(Icons.favorite_rounded, size: 13, color: palette.favoritePink),
                                  ),
                                ),
                              if (v.isMultipart)
                                Positioned(
                                  left: 5,
                                  bottom: 5,
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: Colors.black87,
                                      borderRadius: BorderRadius.circular(5),
                                    ),
                                    child: Text(
                                      '${v.partPaths.length}P',
                                      style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(6, 5, 6, 6),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (v.number.isNotEmpty)
                                Text(
                                  v.number,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    fontSize: 11,
                                    fontWeight: FontWeight.w700,
                                    color: palette.accent,
                                  ),
                                ),
                              Text(
                                v.title.isNotEmpty ? v.title : v.number,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(fontSize: 11, color: palette.textPrimary),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              },
              childCount: _videos.length,
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
            child: Center(
              child: _loadingMore
                  ? const Padding(
                      padding: EdgeInsets.all(8),
                      child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2)),
                    )
                  : (_page < _totalPages
                      ? OutlinedButton(onPressed: _loadMore, child: Text(strings.loadingMore))
                      : Text(
                          '${_videos.length} / $_total · ${strings.allLoaded}',
                          style: TextStyle(color: palette.textMuted, fontSize: 11.5),
                        )),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildActressGrid(
    ApiClient api,
    OpenAverPalette palette,
    AppStrings strings,
    int columns,
    int decodeWidth,
  ) {
    if (_actresses.isEmpty) {
      return ListView(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 72, horizontal: 24),
            child: Center(
              child: Text(strings.emptyActresses, style: TextStyle(color: palette.textMuted)),
            ),
          ),
        ],
      );
    }

    return GridView.builder(
      padding: const EdgeInsets.fromLTRB(10, 6, 10, 20),
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: columns,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        childAspectRatio: 0.78,
      ),
      itemCount: _actresses.length,
      itemBuilder: (_, index) {
        final a = _actresses[index];
        final photoUrl = a.photoUrl.isNotEmpty
            ? a.photoUrl
            : '/api/actresses/photo/${Uri.encodeComponent(a.name)}';
        return GestureDetector(
          onTap: () => _openActressDetail(index),
          child: Container(
            decoration: BoxDecoration(
              color: palette.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: palette.stroke),
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      OpenAverNetworkImage(
                        api: api,
                        url: photoUrl,
                        alignment: a.focalAlignment,
                        targetDecodeWidth: decodeWidth,
                        errorIcon: Icons.person_rounded,
                      ),
                      Positioned(
                        top: 4,
                        right: 4,
                        child: GestureDetector(
                          onTap: () => _toggleActressFavoriteInline(a),
                          child: Container(
                            padding: const EdgeInsets.all(4),
                            decoration: const BoxDecoration(
                              color: Colors.black54,
                              shape: BoxShape.circle,
                            ),
                            child: Icon(
                              a.isFavorite ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                              size: 15,
                              color: a.isFavorite ? palette.favoritePink : Colors.white70,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        a.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: palette.textPrimary),
                      ),
                      Text(
                        strings.videosUnit(a.videoCount),
                        style: TextStyle(fontSize: 10.5, color: palette.textMuted),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
