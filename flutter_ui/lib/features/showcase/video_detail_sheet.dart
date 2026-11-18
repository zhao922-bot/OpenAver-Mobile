import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/video_item.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';
import 'sample_gallery_viewer.dart';

class VideoDetailPage extends ConsumerStatefulWidget {
  const VideoDetailPage({
    super.key,
    required this.videos,
    required this.initialIndex,
    required this.onVideoUpdated,
    required this.onVideoDeleted,
    required this.onSelectActress,
  });

  final List<VideoItem> videos;
  final int initialIndex;
  final ValueChanged<VideoItem> onVideoUpdated;
  final ValueChanged<String> onVideoDeleted;
  final ValueChanged<String> onSelectActress;

  @override
  ConsumerState<VideoDetailPage> createState() => _VideoDetailPageState();
}

class _VideoDetailPageState extends ConsumerState<VideoDetailPage> {
  late final PageController _pageController;
  late List<VideoItem> _videos;
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _videos = List<VideoItem>.from(widget.videos);
    _currentIndex = widget.initialIndex.clamp(0, _videos.isEmpty ? 0 : _videos.length - 1);
    _pageController = PageController(initialPage: _currentIndex);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    if (_videos.isEmpty) {
      return Scaffold(
        appBar: AppBar(),
        body: const SizedBox.shrink(),
      );
    }

    final current = _videos[_currentIndex];
    return Scaffold(
      backgroundColor: palette.canvas,
      appBar: AppBar(
        title: Text(
          current.number.isNotEmpty ? current.number : current.title,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(
              child: Text(
                '${_currentIndex + 1} / ${_videos.length}',
                style: TextStyle(color: palette.textMuted, fontSize: 12),
              ),
            ),
          ),
        ],
      ),
      body: PageView.builder(
        controller: _pageController,
        itemCount: _videos.length,
        onPageChanged: (index) => setState(() => _currentIndex = index),
        itemBuilder: (_, index) {
          final item = _videos[index];
          return _VideoDetailBody(
            key: ValueKey(item.path),
            video: item,
            onUpdated: (updated) {
              setState(() => _videos[index] = updated);
              widget.onVideoUpdated(updated);
            },
            onDeleted: (deletedPath) {
              widget.onVideoDeleted(deletedPath);
              setState(() {
                _videos.removeWhere((v) => v.path == deletedPath);
                if (_currentIndex >= _videos.length && _videos.isNotEmpty) {
                  _currentIndex = _videos.length - 1;
                }
              });
              if (_videos.isEmpty && mounted) {
                Navigator.of(context).pop();
              }
            },
            onSelectActress: (name) {
              Navigator.of(context).pop();
              widget.onSelectActress(name);
            },
          );
        },
      ),
    );
  }
}

class _VideoDetailBody extends ConsumerStatefulWidget {
  const _VideoDetailBody({
    super.key,
    required this.video,
    required this.onUpdated,
    required this.onDeleted,
    required this.onSelectActress,
  });

  final VideoItem video;
  final ValueChanged<VideoItem> onUpdated;
  final ValueChanged<String> onDeleted;
  final ValueChanged<String> onSelectActress;

  @override
  ConsumerState<_VideoDetailBody> createState() => _VideoDetailBodyState();
}

class _VideoDetailBodyState extends ConsumerState<_VideoDetailBody> {
  // Dedicated ScrollController per video keeps sample scrolling reset to 0.0
  // on video transitions and prevents nested gesture leaks into the outer PageView.
  late final ScrollController _samplesScroll;

  bool _plotLoading = false;
  String? _plotText;
  String? _originalPlot;
  String? _plotError;
  bool _showOriginalPlot = false;
  bool _editingPlot = false;
  bool _savingPlot = false;
  bool _refetchingPlot = false;
  bool _translatingPlot = false;
  final TextEditingController _plotCtrl = TextEditingController();

  bool _editingTitle = false;
  bool _savingTitle = false;
  bool _translatingTitle = false;
  late final TextEditingController _titleCtrl;

  List<Map<String, dynamic>> _similar = const [];
  bool _similarLoading = false;

  @override
  void initState() {
    super.initState();
    _samplesScroll = ScrollController();
    _titleCtrl = TextEditingController(text: widget.video.title);
    _loadPlot();
    _loadSimilar();
  }

  @override
  void dispose() {
    _samplesScroll.dispose();
    _plotCtrl.dispose();
    _titleCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadPlot() async {
    final api = ref.read(apiClientProvider);
    setState(() {
      _plotLoading = true;
      _plotError = null;
    });
    try {
      final resp = await api.getJson(
        '/api/showcase/video/plot',
        queryParameters: {'file_path': widget.video.path},
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        setState(() {
          _plotText = (resp['plot'] as String?) ?? '';
          _originalPlot = (resp['original_plot'] as String?) ?? '';
          _plotCtrl.text = _plotText ?? '';
          _plotLoading = false;
        });
      } else {
        setState(() {
          _plotText = '';
          _plotError = (resp['message'] ?? resp['error'] ?? '').toString();
          _plotLoading = false;
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _plotError = e.toString();
        _plotLoading = false;
      });
    }
  }

  Future<void> _loadSimilar() async {
    if (widget.video.number.isEmpty) return;
    final api = ref.read(apiClientProvider);
    setState(() => _similarLoading = true);
    try {
      final resp = await api.getJson(
        '/api/similar-covers/by-number/${Uri.encodeComponent(widget.video.number)}',
        queryParameters: {'limit': 10},
      );
      if (!mounted) return;
      final list = (resp['results'] as List?) ?? const [];
      setState(() {
        _similar = list
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
        _similarLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _similarLoading = false);
    }
  }

  Future<void> _toggleFavorite() async {
    final api = ref.read(apiClientProvider);
    final nextPicked = !widget.video.isFavorite;
    final resp = await api.postJson('/api/user-rating', data: {
      'file_path': widget.video.path,
      'picked': nextPicked,
    });
    if (resp['success'] == true) {
      widget.onUpdated(widget.video.copyWith(userRating: nextPicked ? 1 : 0));
    }
  }

  Future<void> _savePlot({String? customPlot, bool allowEmpty = true}) async {
    final text = (customPlot ?? _plotCtrl.text).trim();
    if (text.isEmpty) return;
    final api = ref.read(apiClientProvider);
    setState(() => _savingPlot = true);
    try {
      final resp = await api.postJson('/api/showcase/video/plot', data: {
        'file_path': widget.video.path,
        'plot': text,
        'allow_empty_existing': allowEmpty,
      });
      if (!mounted) return;
      if (resp['success'] == true) {
        setState(() {
          _plotText = (resp['plot'] as String?) ?? text;
          _originalPlot = (resp['original_plot'] as String?) ?? (_originalPlot ?? '');
          _plotError = null;
          _editingPlot = false;
          _showOriginalPlot = false;
        });
      } else {
        _showToast((resp['message'] ?? resp['error'] ?? '保存失败').toString());
      }
    } finally {
      if (mounted) setState(() => _savingPlot = false);
    }
  }

  Future<void> _refetchPlot() async {
    final api = ref.read(apiClientProvider);
    setState(() => _refetchingPlot = true);
    try {
      final resp = await api.postJson('/api/showcase/video/plot/refetch', data: {
        'file_path': widget.video.path,
        'source': 'auto',
      });
      if (!mounted) return;
      if (resp['success'] == true) {
        final fetched = (resp['plot'] as String?) ?? '';
        setState(() {
          _plotText = fetched;
          _originalPlot = '';
          _plotCtrl.text = fetched;
          _plotError = null;
          _showOriginalPlot = false;
          _editingPlot = false;
        });
        final sourceLabel = (resp['source_label'] ?? resp['source'] ?? '').toString();
        _showToast(sourceLabel.isNotEmpty ? '已从 $sourceLabel 重新获取简介' : '已重新获取简介');
      } else {
        _showToast((resp['message'] ?? resp['error'] ?? '未获取到简介').toString());
      }
    } finally {
      if (mounted) setState(() => _refetchingPlot = false);
    }
  }

  Future<void> _translatePlot() async {
    final source = (_plotText ?? '').trim();
    if (source.isEmpty) return;
    final api = ref.read(apiClientProvider);
    setState(() => _translatingPlot = true);
    try {
      final resp = await api.postJson('/api/translate', data: {
        'text': source,
        'mode': 'translate',
        'actors': widget.video.actresses,
        'number': widget.video.number,
        'force': true,
      });
      if (!mounted) return;
      final translated = (resp['result'] as String?) ?? '';
      if (resp['success'] == true && translated.isNotEmpty) {
        final saveResp = await api.postJson('/api/showcase/video/plot', data: {
          'file_path': widget.video.path,
          'plot': translated,
          'original_plot': (_originalPlot ?? '').isNotEmpty ? _originalPlot : source,
          'allow_empty_existing': true,
        });
        if (!mounted) return;
        if (saveResp['success'] == true) {
          setState(() {
            _plotText = (saveResp['plot'] as String?) ?? translated;
            _originalPlot = (saveResp['original_plot'] as String?) ?? source;
            _plotCtrl.text = _plotText ?? '';
            _showOriginalPlot = false;
          });
        }
      } else {
        _showToast((resp['error'] ?? '翻译失败').toString());
      }
    } finally {
      if (mounted) setState(() => _translatingPlot = false);
    }
  }

  Future<void> _saveTitle(String newTitle) async {
    final trimmed = newTitle.trim();
    if (trimmed.isEmpty) return;
    final api = ref.read(apiClientProvider);
    setState(() => _savingTitle = true);
    try {
      final resp = await api.postJson('/api/showcase/video/title', data: {
        'file_path': widget.video.path,
        'title': trimmed,
      });
      if (!mounted) return;
      if (resp['success'] == true) {
        final updated = widget.video.copyWith(
          title: (resp['title'] as String?) ?? trimmed,
          originalTitle: (resp['original_title'] as String?) ?? widget.video.originalTitle,
          needsTranslate: resp['needs_translate'] == true,
          canTranslate: resp['can_translate'] == true,
          hasNfo: true,
        );
        widget.onUpdated(updated);
        setState(() {
          _titleCtrl.text = updated.title;
          _editingTitle = false;
        });
      } else {
        _showToast((resp['message'] ?? resp['error'] ?? '标题保存失败').toString());
      }
    } finally {
      if (mounted) setState(() => _savingTitle = false);
    }
  }

  Future<void> _translateTitle() async {
    final api = ref.read(apiClientProvider);
    setState(() => _translatingTitle = true);
    try {
      final resp = await api.postJson('/api/translate', data: {
        'text': widget.video.title,
        'mode': 'translate',
        'actors': widget.video.actresses,
        'number': widget.video.number,
      });
      if (!mounted) return;
      final translated = (resp['result'] as String?) ?? '';
      if (resp['success'] == true && translated.isNotEmpty) {
        await _saveTitle(translated);
      } else {
        _showToast((resp['error'] ?? '标题翻译失败').toString());
      }
    } finally {
      if (mounted) setState(() => _translatingTitle = false);
    }
  }

  Future<void> _addUserTag() async {
    final ctrl = TextEditingController();
    final tag = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('添加个人标签'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(hintText: '输入标签名称'),
          onSubmitted: (v) => Navigator.of(ctx).pop(v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(ctrl.text), child: const Text('确定')),
        ],
      ),
    );
    ctrl.dispose();
    if (tag == null || tag.trim().isEmpty) return;
    final api = ref.read(apiClientProvider);
    final resp = await api.postJson('/api/user-tags', data: {
      'file_path': widget.video.path,
      'add': [tag.trim()],
      'remove': const [],
    });
    if (resp['success'] == true && resp['user_tags'] is List) {
      widget.onUpdated(
        widget.video.copyWith(
          userTags: (resp['user_tags'] as List).map((e) => e.toString()).toList(),
        ),
      );
    }
  }

  Future<void> _removeUserTag(String tag) async {
    final api = ref.read(apiClientProvider);
    final resp = await api.postJson('/api/user-tags', data: {
      'file_path': widget.video.path,
      'add': const [],
      'remove': [tag],
    });
    if (resp['success'] == true && resp['user_tags'] is List) {
      widget.onUpdated(
        widget.video.copyWith(
          userTags: (resp['user_tags'] as List).map((e) => e.toString()).toList(),
        ),
      );
    }
  }

  Future<void> _openRescrapeDialog() async {
    final numCtrl = TextEditingController(text: widget.video.number);
    String source = 'auto';
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (sheetCtx) {
        var loading = false;
        Map<String, dynamic>? preview;
        String? statusError;
        return StatefulBuilder(
          builder: (ctx, setSheetState) {
            final api = ref.read(apiClientProvider);
            Future<void> doPreview() async {
              setSheetState(() {
                loading = true;
                statusError = null;
              });
              final resp = await api.postJson('/api/rescrape/preview', data: {
                'number': numCtrl.text.trim(),
                'source': source,
              });
              setSheetState(() {
                loading = false;
                if (resp['success'] == true) {
                  preview = resp;
                } else {
                  statusError = (resp['error'] ?? '未找到匹配元数据').toString();
                }
              });
            }

            Future<void> doApply() async {
              if (preview == null) return;
              setSheetState(() => loading = true);
              final resp = await api.postJson('/api/enrich-single', data: {
                'file_path': widget.video.path,
                'number': numCtrl.text.trim(),
                'source': source,
                'mode': 'fill_missing',
                'metadata': preview,
                'overwrite_existing': true,
              });
              setSheetState(() => loading = false);
              if (resp['success'] == true) {
                final fresh = await api.getJson(
                  '/api/showcase/video',
                  queryParameters: {'path': widget.video.path},
                );
                if (fresh['success'] == true && fresh['video'] is Map) {
                  widget.onUpdated(VideoItem.fromJson(Map<String, dynamic>.from(fresh['video'])));
                }
                if (ctx.mounted) Navigator.of(ctx).pop();
                _showToast('重刮并更新成功');
              } else {
                setSheetState(() {
                  statusError = (resp['error'] ?? resp['reason'] ?? '应用失败').toString();
                });
              }
            }

            return Padding(
              padding: EdgeInsets.fromLTRB(
                16,
                16,
                16,
                MediaQuery.of(ctx).viewInsets.bottom + 16,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('重刮元数据', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: numCtrl,
                          decoration: const InputDecoration(labelText: '番号'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      DropdownButton<String>(
                        value: source,
                        items: const [
                          DropdownMenuItem(value: 'auto', child: Text('自动')),
                          DropdownMenuItem(value: 'javbus', child: Text('JavBus')),
                          DropdownMenuItem(value: 'javdb', child: Text('JavDB')),
                          DropdownMenuItem(value: 'dmm', child: Text('DMM')),
                          DropdownMenuItem(value: 'jav321', child: Text('Jav321')),
                        ],
                        onChanged: (v) {
                          if (v != null) setSheetState(() => source = v);
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  if (statusError != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(statusError!, style: const TextStyle(color: Colors.redAccent)),
                    ),
                  if (preview != null)
                    Container(
                      padding: const EdgeInsets.all(10),
                      margin: const EdgeInsets.only(bottom: 12),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: Colors.white24),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            (preview!['title'] ?? '').toString(),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '片商: ${preview!['maker'] ?? '-'} · 发行: ${preview!['date'] ?? '-'}',
                            style: const TextStyle(fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: loading ? null : doPreview,
                          child: Text(loading ? '请求中…' : '预览刮削结果'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: FilledButton(
                          onPressed: (loading || preview == null) ? null : doApply,
                          child: const Text('覆盖更新'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
    numCtrl.dispose();
  }

  Future<void> _confirmDelete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('移出片库索引'),
        content: const Text('仅从本地索引数据库中移除此记录，不会删除视频和封面文件。'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('确认移出')),
        ],
      ),
    );
    if (ok != true) return;
    final api = ref.read(apiClientProvider);
    await api.deleteJson('/api/showcase/video', queryParameters: {'path': widget.video.path});
    widget.onDeleted(widget.video.path);
  }

  void _openBuiltInPlayer(ApiClient api, {int partIndex = 0}) {
    final paths = widget.video.isMultipart ? widget.video.partPaths : [widget.video.path];
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => BuiltInPlayerPage(
          api: api,
          title: widget.video.title,
          partPaths: paths,
          partTokens: widget.video.partTokens,
          initialPartIndex: partIndex,
        ),
      ),
    );
  }

  void _openExternalPlayer() {
    String? partsJson;
    if (widget.video.isMultipart) {
      final list = <Map<String, String>>[];
      for (var i = 0; i < widget.video.partPaths.length; i++) {
        final label = i < widget.video.partTokens.length ? widget.video.partTokens[i] : 'Part ${i + 1}';
        list.add({'path': widget.video.partPaths[i], 'label': label});
      }
      partsJson = jsonEncode(list);
    }
    NativeBridge.instance.openExternalPlayer(
      path: widget.video.path,
      partsJson: partsJson,
    );
  }

  void _showToast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiClientProvider);
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);
    final v = widget.video;
    final hasPlot = (_plotText ?? '').trim().isNotEmpty;
    final displayedPlot = _showOriginalPlot && (_originalPlot ?? '').isNotEmpty
        ? _originalPlot!
        : (_plotText ?? '');

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      children: [
        // Cover banner with hero tap to open full-screen viewer
        GestureDetector(
          onTap: v.coverFullUrl.isEmpty
              ? null
              : () {
                  final gallery = [v.coverFullUrl, ...v.sampleImages];
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => SampleGalleryViewer(
                        api: api,
                        imageUrls: gallery,
                        initialIndex: 0,
                        title: v.title,
                      ),
                    ),
                  );
                },
          child: ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: AspectRatio(
              aspectRatio: 16 / 10,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (v.coverFullUrl.isNotEmpty || v.coverUrl.isNotEmpty)
                    Image.network(
                      api.resolveUrl(v.coverFullUrl.isNotEmpty ? v.coverFullUrl : v.coverUrl),
                      headers: api.authHeaders,
                      fit: BoxFit.cover,
                      alignment: v.focalAlignment,
                      errorBuilder: (_, _, _) => Container(
                        color: palette.surfaceHigh,
                        child: Icon(Icons.broken_image_outlined, color: palette.textMuted, size: 42),
                      ),
                    )
                  else
                    Container(
                      color: palette.surfaceHigh,
                      child: Icon(Icons.movie_outlined, color: palette.textMuted, size: 48),
                    ),
                  Positioned(
                    right: 10,
                    top: 10,
                    child: IconButton.filled(
                      style: IconButton.styleFrom(
                        backgroundColor: Colors.black54,
                        foregroundColor: v.isFavorite ? palette.favoritePink : Colors.white,
                      ),
                      icon: Icon(v.isFavorite ? Icons.favorite_rounded : Icons.favorite_border_rounded),
                      onPressed: _toggleFavorite,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 14),

        // Title + inline editor + AI translate
        if (_editingTitle)
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: _titleCtrl,
                maxLines: 3,
                minLines: 1,
                decoration: const InputDecoration(labelText: '编辑标题'),
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: _savingTitle ? null : () => setState(() => _editingTitle = false),
                    child: Text(strings.cancel),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: _savingTitle ? null : () => _saveTitle(_titleCtrl.text),
                    child: Text(_savingTitle ? '保存中…' : strings.save),
                  ),
                ],
              ),
            ],
          )
        else
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                v.title.isNotEmpty ? v.title : v.number,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: palette.textPrimary,
                  height: 1.35,
                ),
              ),
              if (v.originalTitle.isNotEmpty && v.originalTitle != v.title) ...[
                const SizedBox(height: 4),
                Text(
                  v.originalTitle,
                  style: TextStyle(fontSize: 12, color: palette.textMuted),
                ),
              ],
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  ActionChip(
                    avatar: const Icon(Icons.edit_outlined, size: 16),
                    label: Text(strings.edit),
                    onPressed: () {
                      _titleCtrl.text = v.title;
                      setState(() => _editingTitle = true);
                    },
                  ),
                  if (v.canTranslate)
                    ActionChip(
                      avatar: _translatingTitle
                          ? const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.translate_rounded, size: 16),
                      label: Text(strings.translateAi),
                      onPressed: _translatingTitle ? null : _translateTitle,
                    ),
                ],
              ),
            ],
          ),

        const SizedBox(height: 12),

        // Play buttons
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: () => _openBuiltInPlayer(api),
                icon: const Icon(Icons.play_arrow_rounded),
                label: Text(strings.builtinPlayer),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _openExternalPlayer,
                icon: const Icon(Icons.open_in_new_rounded, size: 18),
                label: Text(strings.externalPlayer),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),

        // Quick action row
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ActionChip(
              avatar: const Icon(Icons.auto_fix_high_rounded, size: 16),
              label: Text(strings.rescrape),
              onPressed: _openRescrapeDialog,
            ),
            ActionChip(
              avatar: const Icon(Icons.delete_outline_rounded, size: 16),
              label: Text(strings.removeFromDb),
              onPressed: _confirmDelete,
            ),
          ],
        ),
        const SizedBox(height: 14),

        // Metadata info card
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: palette.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: palette.stroke),
          ),
          child: Wrap(
            spacing: 14,
            runSpacing: 6,
            children: [
              if (v.number.isNotEmpty) _MetaPill(label: '番号', value: v.number),
              if (v.releaseDate.isNotEmpty) _MetaPill(label: '发行', value: v.releaseDate),
              if (v.duration != null) _MetaPill(label: '时长', value: '${v.duration} min'),
              if (v.maker.isNotEmpty) _MetaPill(label: '片商', value: v.maker),
              if (v.director.isNotEmpty) _MetaPill(label: '导演', value: v.director),
              if (v.series.isNotEmpty) _MetaPill(label: '系列', value: v.series),
              if (v.formattedSize.isNotEmpty) _MetaPill(label: '大小', value: v.formattedSize),
              if (v.partTokens.isNotEmpty) _MetaPill(label: '分段', value: v.partTokens.join(', ')),
            ],
          ),
        ),

        // Actresses
        if (v.actresses.isNotEmpty) ...[
          const SizedBox(height: 14),
          Text(strings.actresses, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: v.actresses
                .map(
                  (name) => ActionChip(
                    avatar: CircleAvatar(
                      backgroundColor: palette.favoritePink.withValues(alpha: 0.2),
                      child: Icon(Icons.person_rounded, size: 14, color: palette.favoritePink),
                    ),
                    label: Text(name),
                    onPressed: () => widget.onSelectActress(name),
                  ),
                )
                .toList(),
          ),
        ],

        // User Tags & Genre Tags
        const SizedBox(height: 14),
        Row(
          children: [
            Text('标签', style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
            const Spacer(),
            TextButton.icon(
              onPressed: _addUserTag,
              icon: const Icon(Icons.add_rounded, size: 16),
              label: Text(strings.addTag),
            ),
          ],
        ),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            ...v.userTags.map(
              (ut) => InputChip(
                label: Text(ut),
                backgroundColor: palette.accent.withValues(alpha: 0.16),
                onDeleted: () => _removeUserTag(ut),
              ),
            ),
            ...v.tags.map((t) => Chip(label: Text(t))),
          ],
        ),

        // Plot section (inline edit + AI translate + refetch)
        const SizedBox(height: 16),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: palette.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: palette.stroke),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(strings.plot, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                  const Spacer(),
                  if ((_originalPlot ?? '').isNotEmpty)
                    TextButton(
                      onPressed: () => setState(() => _showOriginalPlot = !_showOriginalPlot),
                      child: Text(_showOriginalPlot ? strings.showTranslated : strings.showOriginal),
                    ),
                  TextButton.icon(
                    onPressed: _refetchingPlot ? null : _refetchPlot,
                    icon: _refetchingPlot
                        ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.refresh_rounded, size: 16),
                    label: Text(strings.refetchPlot),
                  ),
                ],
              ),
              if (_plotLoading)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
                )
              else if (_editingPlot)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextField(
                      controller: _plotCtrl,
                      maxLines: 6,
                      minLines: 3,
                      decoration: const InputDecoration(hintText: '输入简介内容…'),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton(
                          onPressed: _savingPlot ? null : () => setState(() => _editingPlot = false),
                          child: Text(strings.cancel),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(
                          onPressed: _savingPlot ? null : () => _savePlot(),
                          child: Text(_savingPlot ? '保存中…' : strings.save),
                        ),
                      ],
                    ),
                  ],
                )
              else if (hasPlot)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SelectableText(
                      displayedPlot,
                      style: TextStyle(color: palette.textSecondary, height: 1.55, fontSize: 13.5),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      children: [
                        ActionChip(
                          avatar: const Icon(Icons.edit_outlined, size: 15),
                          label: Text(strings.edit),
                          onPressed: () {
                            _plotCtrl.text = _plotText ?? '';
                            setState(() => _editingPlot = true);
                          },
                        ),
                        ActionChip(
                          avatar: _translatingPlot
                              ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                              : const Icon(Icons.translate_rounded, size: 15),
                          label: Text(strings.translateAi),
                          onPressed: _translatingPlot ? null : _translatePlot,
                        ),
                      ],
                    ),
                  ],
                )
              else
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      (_plotError != null && _plotError!.isNotEmpty) ? _plotError! : '暂无简介',
                      style: TextStyle(color: palette.textMuted, fontSize: 13),
                    ),
                    const SizedBox(height: 8),
                    ActionChip(
                      avatar: const Icon(Icons.edit_outlined, size: 15),
                      label: const Text('手动添加简介'),
                      onPressed: () {
                        _plotCtrl.text = '';
                        setState(() => _editingPlot = true);
                      },
                    ),
                  ],
                ),
            ],
          ),
        ),

        // Sample images horizontal gallery with isolated ScrollController
        if (v.sampleImages.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(
            '${strings.sampleImages} (${v.sampleImages.length})',
            style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary),
          ),
          const SizedBox(height: 8),
          SizedBox(
            height: 120,
            child: ListView.separated(
              controller: _samplesScroll,
              scrollDirection: Axis.horizontal,
              physics: const ClampingScrollPhysics(),
              itemCount: v.sampleImages.length,
              separatorBuilder: (_, _) => const SizedBox(width: 8),
              itemBuilder: (_, idx) {
                return GestureDetector(
                  onTap: () {
                    Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => SampleGalleryViewer(
                          api: api,
                          imageUrls: v.sampleImages,
                          initialIndex: idx,
                          title: v.title,
                        ),
                      ),
                    );
                  },
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: AspectRatio(
                      aspectRatio: 16 / 10,
                      child: Image.network(
                        api.resolveUrl(v.sampleImages[idx]),
                        headers: api.authHeaders,
                        fit: BoxFit.cover,
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],

        // Similar recommendations
        if (_similarLoading || _similar.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(strings.similarVideos, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
          const SizedBox(height: 8),
          if (_similarLoading)
            const LinearProgressIndicator(minHeight: 2)
          else
            SizedBox(
              height: 165,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: _similar.length,
                separatorBuilder: (_, _) => const SizedBox(width: 10),
                itemBuilder: (_, idx) {
                  final sim = _similar[idx];
                  final cover = ((sim['cover_url'] ?? sim['cover_full_url']) ?? '').toString();
                  final num = (sim['number'] ?? '').toString();
                  final title = (sim['title'] ?? '').toString();
                  return SizedBox(
                    width: 112,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(10),
                            child: cover.isNotEmpty
                                ? Image.network(
                                    api.resolveUrl(cover),
                                    headers: api.authHeaders,
                                    fit: BoxFit.cover,
                                    width: double.infinity,
                                  )
                                : Container(color: palette.surfaceHigh),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          num.isNotEmpty ? num : title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: palette.textPrimary,
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
        ],
      ],
    );
  }
}

class _MetaPill extends StatelessWidget {
  const _MetaPill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    return RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12, color: palette.textSecondary),
        children: [
          TextSpan(
            text: '$label: ',
            style: TextStyle(color: palette.textMuted),
          ),
          TextSpan(
            text: value,
            style: TextStyle(color: palette.textPrimary, fontWeight: FontWeight.w500),
          ),
        ],
      ),
    );
  }
}
