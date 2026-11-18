import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/video_item.dart';
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
  String? _error;
  List<VideoItem> _videos = const [];
  List<LibraryActressGroup> _actresses = const [];

  bool _actressMode = false;
  bool _favoritesOnly = false;
  String _sort = 'date';
  String _order = 'desc';
  int _columns = 3;
  int _page = 1;
  int _totalPages = 1;
  int _total = 0;
  static const int _perPage = 45;
  Timer? _searchDebounce;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadData());
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchCtrl.dispose();
    _gridScroll.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    if (_actressMode) {
      await _loadActresses();
      return;
    }
    final api = ref.read(apiClientProvider);
    final actressFilter = ref.read(showcaseActressFilterProvider);
    final query = _searchCtrl.text.trim().toLowerCase();
    final useClientFilter = query.isNotEmpty || _favoritesOnly || _sort == 'random';

    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await api.getJson(
        '/api/showcase/videos',
        queryParameters: {
          'paged': useClientFilter ? false : true,
          'page': useClientFilter ? 1 : _page,
          'per_page': useClientFilter ? 0 : _perPage,
          'sort': _sort,
          'order': _order,
          if (actressFilter != null && actressFilter.isNotEmpty) 'actress': actressFilter,
        },
      );
      if (!mounted) return;
      if (resp['success'] != true) {
        setState(() {
          _loading = false;
          _error = (resp['error'] ?? '加载片库失败').toString();
        });
        return;
      }
      final parsed = VideosPageResponse.fromJson(resp);
      var items = parsed.videos;
      if (useClientFilter) {
        if (_favoritesOnly) {
          items = items.where((v) => v.isFavorite).toList();
        }
        if (query.isNotEmpty) {
          items = items.where((v) {
            return v.number.toLowerCase().contains(query) ||
                v.title.toLowerCase().contains(query) ||
                v.maker.toLowerCase().contains(query) ||
                v.actresses.any((a) => a.toLowerCase().contains(query)) ||
                v.tags.any((t) => t.toLowerCase().contains(query)) ||
                v.userTags.any((t) => t.toLowerCase().contains(query));
          }).toList();
        }
        if (_sort == 'random') {
          items = List<VideoItem>.from(items)..shuffle();
        }
      }
      setState(() {
        _videos = items;
        _total = useClientFilter ? items.length : parsed.total;
        _page = useClientFilter ? 1 : parsed.page;
        _totalPages = useClientFilter ? 1 : parsed.totalPages;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _loadActresses() async {
    final api = ref.read(apiClientProvider);
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await api.getJson('/api/actresses/library');
      if (!mounted) return;
      final list = (resp['actresses'] as List?) ?? const [];
      final query = _searchCtrl.text.trim().toLowerCase();
      var groups = list
          .whereType<Map>()
          .map((e) => LibraryActressGroup.fromJson(Map<String, dynamic>.from(e)))
          .toList();
      if (_favoritesOnly) {
        groups = groups.where((g) => g.isFavorite).toList();
      }
      if (query.isNotEmpty) {
        groups = groups
            .where((g) =>
                g.primaryName.toLowerCase().contains(query) ||
                g.aliases.any((a) => a.toLowerCase().contains(query)))
            .toList();
      }
      setState(() {
        _actresses = groups;
        _total = groups.length;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  void _openDetail(int index) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => VideoDetailPage(
          videos: _videos,
          initialIndex: index,
          onVideoUpdated: (updated) {
            if (!mounted) return;
            setState(() {
              final idx = _videos.indexWhere((v) => v.path == updated.path);
              if (idx != -1) {
                final copy = List<VideoItem>.from(_videos);
                copy[idx] = updated;
                _videos = copy;
              }
            });
          },
          onVideoDeleted: (deletedPath) {
            if (!mounted) return;
            setState(() {
              _videos = _videos.where((v) => v.path != deletedPath).toList();
              _total = (_total - 1).clamp(0, _total);
            });
          },
          onSelectActress: (name) {
            ref.read(showcaseActressFilterProvider.notifier).state = name;
            setState(() {
              _actressMode = false;
              _page = 1;
            });
            _loadData();
          },
        ),
      ),
    );
  }

  void _showSortSheet() {
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) {
        final sorts = const [
          ('date', '发行日期'),
          ('mdate', '入库时间'),
          ('num', '番号'),
          ('title', '标题'),
          ('actor', '女优'),
          ('maker', '片商'),
          ('size', '文件大小'),
          ('random', '随机顺序'),
        ];
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Text('排序与显示', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                    const Spacer(),
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(value: 'desc', label: Text('降序')),
                        ButtonSegment(value: 'asc', label: Text('升序')),
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
                          _page = 1;
                        });
                        Navigator.of(ctx).pop();
                        _loadData();
                      },
                    );
                  }).toList(),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    const Text('每行列数', style: TextStyle(fontWeight: FontWeight.w600)),
                    const Spacer(),
                    SegmentedButton<int>(
                      segments: const [
                        ButtonSegment(value: 2, label: Text('2 列')),
                        ButtonSegment(value: 3, label: Text('3 列')),
                        ButtonSegment(value: 4, label: Text('4 列')),
                      ],
                      selected: {_columns},
                      onSelectionChanged: (values) {
                        setState(() => _columns = values.first);
                        Navigator.of(ctx).pop();
                      },
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiClientProvider);
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);
    final actressFilter = ref.watch(showcaseActressFilterProvider);

    ref.listen<String?>(showcaseActressFilterProvider, (prev, next) {
      if (prev != next) {
        _page = 1;
        _actressMode = false;
        _loadData();
      }
    });

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // Search + quick filters
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
                      onChanged: (_) {
                        setState(() {});
                        _searchDebounce?.cancel();
                        _searchDebounce = Timer(const Duration(milliseconds: 280), _loadData);
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filledTonal(
                    tooltip: '排序/列数',
                    onPressed: _showSortSheet,
                    icon: const Icon(Icons.tune_rounded),
                  ),
                ],
              ),
            ),

            // Mode & filter pills
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Row(
                children: [
                  FilterChip(
                    label: Text('${strings.allVideos} ($_total)'),
                    selected: !_actressMode && !_favoritesOnly && (actressFilter == null),
                    onSelected: (_) {
                      ref.read(showcaseActressFilterProvider.notifier).state = null;
                      setState(() {
                        _actressMode = false;
                        _favoritesOnly = false;
                        _page = 1;
                      });
                      _loadData();
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
                        ref.read(showcaseActressFilterProvider.notifier).state = null;
                        setState(() => _page = 1);
                        _loadData();
                      },
                    ),
                  ],
                ],
              ),
            ),

            Expanded(
              child: RefreshIndicator(
                onRefresh: _loadData,
                child: _loading
                    ? const Center(child: CircularProgressIndicator())
                    : _error != null
                        ? ListView(
                            children: [
                              Padding(
                                padding: const EdgeInsets.all(24),
                                child: Column(
                                  children: [
                                    Icon(Icons.error_outline_rounded, size: 42, color: palette.danger),
                                    const SizedBox(height: 10),
                                    Text(_error!, style: TextStyle(color: palette.textSecondary)),
                                    const SizedBox(height: 12),
                                    FilledButton(onPressed: _loadData, child: Text(strings.retry)),
                                  ],
                                ),
                              ),
                            ],
                          )
                        : _actressMode
                            ? _buildActressGrid(api, palette)
                            : _buildVideoGrid(api, palette),
              ),
            ),

            if (!_actressMode && _totalPages > 1)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                decoration: BoxDecoration(
                  color: palette.surface,
                  border: Border(top: BorderSide(color: palette.stroke)),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    TextButton.icon(
                      onPressed: _page <= 1 || _loading
                          ? null
                          : () {
                              setState(() => _page -= 1);
                              _loadData();
                              if (_gridScroll.hasClients) _gridScroll.jumpTo(0);
                            },
                      icon: const Icon(Icons.chevron_left_rounded),
                      label: const Text('上一页'),
                    ),
                    Text(
                      '$_page / $_totalPages',
                      style: TextStyle(fontWeight: FontWeight.w600, color: palette.textPrimary),
                    ),
                    TextButton.icon(
                      onPressed: _page >= _totalPages || _loading
                          ? null
                          : () {
                              setState(() => _page += 1);
                              _loadData();
                              if (_gridScroll.hasClients) _gridScroll.jumpTo(0);
                            },
                      icon: const Icon(Icons.chevron_right_rounded),
                      label: const Text('下一页'),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildVideoGrid(ApiClient api, OpenAverPalette palette) {
    if (_videos.isEmpty) {
      return ListView(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 72, horizontal: 24),
            child: Column(
              children: [
                Icon(Icons.video_library_outlined, size: 48, color: palette.textMuted),
                const SizedBox(height: 12),
                Text('暂无匹配的影片记录', style: TextStyle(color: palette.textMuted)),
              ],
            ),
          ),
        ],
      );
    }

    return GridView.builder(
      controller: _gridScroll,
      padding: const EdgeInsets.fromLTRB(10, 6, 10, 16),
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: _columns,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        childAspectRatio: _columns >= 4 ? 0.68 : 0.72,
      ),
      itemCount: _videos.length,
      itemBuilder: (_, index) {
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
                      if (v.coverUrl.isNotEmpty)
                        Image.network(
                          api.resolveUrl(v.coverUrl),
                          headers: api.authHeaders,
                          fit: BoxFit.cover,
                          alignment: v.focalAlignment,
                          errorBuilder: (_, _, _) => Container(
                            color: palette.surfaceHigh,
                            child: Icon(Icons.broken_image_outlined, color: palette.textMuted),
                          ),
                        )
                      else
                        Container(
                          color: palette.surfaceHigh,
                          child: Icon(Icons.movie_outlined, color: palette.textMuted),
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
    );
  }

  Widget _buildActressGrid(ApiClient api, OpenAverPalette palette) {
    if (_actresses.isEmpty) {
      return ListView(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 72, horizontal: 24),
            child: Center(
              child: Text('暂无女优数据', style: TextStyle(color: palette.textMuted)),
            ),
          ),
        ],
      );
    }

    return GridView.builder(
      padding: const EdgeInsets.fromLTRB(10, 6, 10, 16),
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: _columns,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        childAspectRatio: 0.78,
      ),
      itemCount: _actresses.length,
      itemBuilder: (_, index) {
        final a = _actresses[index];
        final photoUrl = a.photoUrl.isNotEmpty
            ? a.photoUrl
            : '/api/actresses/photo/${Uri.encodeComponent(a.primaryName)}';
        return GestureDetector(
          onTap: () {
            ref.read(showcaseActressFilterProvider.notifier).state = a.primaryName;
            setState(() {
              _actressMode = false;
              _page = 1;
            });
            _loadData();
          },
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
                      Image.network(
                        api.resolveUrl(photoUrl),
                        headers: api.authHeaders,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) => Container(
                          color: palette.surfaceHigh,
                          child: Icon(Icons.person_rounded, size: 36, color: palette.textMuted),
                        ),
                      ),
                      if (a.isFavorite)
                        Positioned(
                          top: 5,
                          right: 5,
                          child: Icon(Icons.favorite_rounded, size: 15, color: palette.favoritePink),
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
                        a.primaryName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: palette.textPrimary),
                      ),
                      Text(
                        '${a.videoCount} 部',
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
