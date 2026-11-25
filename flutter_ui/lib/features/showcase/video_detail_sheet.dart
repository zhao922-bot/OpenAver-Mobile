import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import '../../core/models/video_item.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';
import '../scanner/metadata_source_sheet.dart';
import '../shared/openaver_image.dart';
import '../shared/prompt_dialog.dart';
import 'sample_gallery_viewer.dart';

class VideoDetailPage extends ConsumerStatefulWidget {
  const VideoDetailPage({
    super.key,
    required this.videos,
    required this.initialIndex,
    required this.onVideoUpdated,
    required this.onVideoDeleted,
    required this.onSelectActress,
    this.onSelectTag,
    this.onSelectFilterText,
    this.totalVideos,
    this.loadMoreVideos,
  });

  final List<VideoItem> videos;
  final int initialIndex;
  final int? totalVideos;
  final Future<({List<VideoItem> videos, bool hasMore})?> Function()? loadMoreVideos;
  final ValueChanged<VideoItem> onVideoUpdated;
  final ValueChanged<String> onVideoDeleted;
  final ValueChanged<String> onSelectActress;
  final ValueChanged<String>? onSelectTag;
  final ValueChanged<String>? onSelectFilterText;

  @override
  ConsumerState<VideoDetailPage> createState() => _VideoDetailPageState();
}

class _VideoDetailPageState extends ConsumerState<VideoDetailPage> {
  late final PageController _pageController;
  late List<VideoItem> _videos;
  late int _currentIndex;
  late int _totalVideos;
  late bool _hasMoreVideos;
  bool _loadingMoreVideos = false;

  @override
  void initState() {
    super.initState();
    _videos = List<VideoItem>.from(widget.videos);
    _currentIndex = widget.initialIndex.clamp(
      0,
      _videos.isEmpty ? 0 : _videos.length - 1,
    );
    _pageController = PageController(initialPage: _currentIndex);
    _totalVideos = widget.totalVideos ?? _videos.length;
    _hasMoreVideos = widget.loadMoreVideos != null;
    if (_hasMoreVideos) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _prefetchVideos());
    }
  }

  Future<void> _prefetchVideos() async {
    if (!mounted || !_hasMoreVideos || _loadingMoreVideos ||
        _currentIndex < _videos.length - 3) {
      return;
    }
    _loadingMoreVideos = true;
    try {
      final result = await widget.loadMoreVideos!();
      if (!mounted) return;
      if (result == null) {
        _hasMoreVideos = false;
        return;
      }
      setState(() {
        final seen = _videos.map((video) => video.path).toSet();
        _videos.addAll(result.videos.where((video) => seen.add(video.path)));
        _hasMoreVideos = result.hasMore;
      });
    } finally {
      _loadingMoreVideos = false;
    }
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
      return Scaffold(appBar: AppBar(), body: const SizedBox.shrink());
    }

    final current = _videos[_currentIndex];
    final notifyUpdated = widget.onVideoUpdated;
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
                '${_currentIndex + 1} / $_totalVideos',
                style: TextStyle(color: palette.textMuted, fontSize: 12),
              ),
            ),
          ),
        ],
      ),
      body: PageView.builder(
        controller: _pageController,
        itemCount: _videos.length,
        onPageChanged: (index) {
          setState(() => _currentIndex = index);
          _prefetchVideos();
        },
        itemBuilder: (_, index) {
          final item = _videos[index];
          return _VideoDetailBody(
            key: ValueKey(item.path),
            video: item,
            isCurrentVideo: () => mounted && _videos.isNotEmpty &&
                _videos[_currentIndex].path == item.path,
            onUpdated: (updated) {
              if (mounted) {
                final index = _videos.indexWhere((video) => video.path == updated.path);
                if (index != -1) setState(() => _videos[index] = updated);
              }
              notifyUpdated(updated);
            },
            onDeleted: (deletedPath) {
              widget.onVideoDeleted(deletedPath);
              if (!mounted || !_videos.any((v) => v.path == deletedPath)) return;
              setState(() {
                _videos.removeWhere((v) => v.path == deletedPath);
                _totalVideos--;
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
            onSelectTag: (tag) {
              Navigator.of(context).pop();
              widget.onSelectTag?.call(tag);
            },
            onSelectFilterText: (term) {
              Navigator.of(context).pop();
              widget.onSelectFilterText?.call(term);
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
    required this.isCurrentVideo,
    required this.onUpdated,
    required this.onDeleted,
    required this.onSelectActress,
    required this.onSelectTag,
    required this.onSelectFilterText,
  });

  final VideoItem video;
  final bool Function() isCurrentVideo;
  final ValueChanged<VideoItem> onUpdated;
  final ValueChanged<String> onDeleted;
  final ValueChanged<String> onSelectActress;
  final ValueChanged<String> onSelectTag;
  final ValueChanged<String> onSelectFilterText;

  @override
  ConsumerState<_VideoDetailBody> createState() => _VideoDetailBodyState();
}

class _VideoDetailBodyState extends ConsumerState<_VideoDetailBody>
    with AutomaticKeepAliveClientMixin {
  bool _rescraping = false;
  bool _pickerOpen = false;
  String? _rescrapeStatus;
  int _plotRequest = 0;

  @override
  bool get wantKeepAlive => _rescraping;

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

  bool _fetchingSamples = false;
  bool _autoTagging = false;

  List<Map<String, dynamic>> _similar = const [];
  bool _similarLoading = false;
  CancelToken? _similarLookup;

  @override
  void initState() {
    super.initState();
    _samplesScroll = ScrollController();
    _titleCtrl = TextEditingController(text: widget.video.title);
    _loadPlot();
    _loadSimilar();
  }

  @override
  void didUpdateWidget(covariant _VideoDetailBody oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_editingTitle && widget.video.title != oldWidget.video.title) {
      _titleCtrl.text = widget.video.title;
    }
  }

  @override
  void dispose() {
    _similarLookup?.cancel();
    _samplesScroll.dispose();
    _plotCtrl.dispose();
    _titleCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadPlot() async {
    final request = ++_plotRequest;
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
      if (!mounted || request != _plotRequest) return;
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
      debugPrint('loadPlot error: $e');
      if (!mounted || request != _plotRequest) return;
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
        queryParameters: {'limit': 12},
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
    } catch (e) {
      debugPrint('loadSimilar error: $e');
      if (!mounted) return;
      setState(() => _similarLoading = false);
    }
  }

  Future<void> _openSimilarVideo(Map<String, dynamic> sim) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final path = (sim['path'] ?? '').toString();
    final number = (sim['number'] ?? '').toString().trim();
    final title = (sim['title'] ?? '').toString().trim();
    if (path.isEmpty && number.isEmpty && title.isEmpty) {
      _showToast(strings.videoNotInLibrary);
      return;
    }
    _similarLookup?.cancel();
    final cancel = CancelToken();
    _similarLookup = cancel;

    bool ownsLookup() => mounted && _similarLookup == cancel &&
        widget.isCurrentVideo() && ModalRoute.of(context)?.isCurrent == true;

    try {
      final resp = await api.dio.get<Map<String, dynamic>>(
        '/api/showcase/video/lookup',
        queryParameters: {
          if (path.isNotEmpty) 'path': path,
          if (number.isNotEmpty) 'number': number,
          if (title.isNotEmpty) 'title': title,
        },
        cancelToken: cancel,
      );
      if (!mounted || !ownsLookup()) return;
      if (resp.statusCode == 404) {
        _showToast(strings.videoNotInLibrary);
        return;
      }
      final video = resp.data?['video'];
      if (resp.data?['success'] != true || video is! Map<String, dynamic>) {
        _showToast(strings.loadLibraryFailed);
        return;
      }
      final item = VideoItem.fromJson(video);
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => VideoDetailPage(
            videos: [item],
            initialIndex: 0,
            onVideoUpdated: widget.onUpdated,
            onVideoDeleted: widget.onDeleted,
            onSelectActress: widget.onSelectActress,
            onSelectTag: widget.onSelectTag,
            onSelectFilterText: widget.onSelectFilterText,
          ),
        ),
      );
    } catch (e) {
      if (!ownsLookup()) return;
      debugPrint('openSimilarVideo error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (_similarLookup == cancel) _similarLookup = null;
    }
  }

  Future<void> _toggleFavorite() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final nextPicked = !widget.video.isFavorite;
    try {
      final resp = await api.postJson('/api/user-rating', data: {
        'file_path': widget.video.path,
        'picked': nextPicked,
      });
      if (resp['success'] == true) {
        widget.onUpdated(widget.video.copyWith(userRating: nextPicked ? 1 : 0));
      } else {
        _showToast((resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('toggleFavorite error: $e');
      _showToast(strings.requestFailed('$e'));
    }
  }

  Future<void> _savePlot({String? customPlot, bool allowEmpty = true}) async {
    final strings = ref.read(stringsProvider);
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
        _showToast((resp['message'] ?? resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('savePlot error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _savingPlot = false);
    }
  }

  Future<void> _refetchPlot() async {
    final strings = ref.read(stringsProvider);
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
        _showToast(strings.refetchPlotSuccess(sourceLabel));
      } else {
        _showToast((resp['message'] ?? resp['error'] ?? strings.refetchPlotEmpty).toString());
      }
    } catch (e) {
      debugPrint('refetchPlot error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _refetchingPlot = false);
    }
  }

  Future<void> _translatePlot() async {
    final strings = ref.read(stringsProvider);
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
        _showToast((resp['error'] ?? strings.translateFailed).toString());
      }
    } catch (e) {
      debugPrint('translatePlot error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _translatingPlot = false);
    }
  }

  Future<void> _saveTitle(String newTitle) async {
    final strings = ref.read(stringsProvider);
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
        _showToast((resp['message'] ?? resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('saveTitle error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _savingTitle = false);
    }
  }

  Future<void> _translateTitle() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _translatingTitle = true);
    try {
      final resp = await api.postJson('/api/translate', data: {
        'text': widget.video.title,
        'mode': 'translate',
        'actors': widget.video.actresses,
        'number': widget.video.number,
        'force': true,
      });
      if (!mounted) return;
      final translated = (resp['result'] as String?) ?? '';
      if (resp['success'] == true && translated.isNotEmpty) {
        await _saveTitle(translated);
      } else if (resp['skipped'] == true) {
        _showToast(strings.alreadyTargetLanguage);
      } else {
        _showToast((resp['error'] ?? strings.translateFailed).toString());
      }
    } catch (e) {
      debugPrint('translateTitle error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _translatingTitle = false);
    }
  }

  Future<void> _fetchSamples() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _fetchingSamples = true);
    try {
      final resp = await api.postJson('/api/scraper/fetch-samples', data: {
        'file_path': widget.video.path,
        'number': widget.video.number,
      });
      if (!mounted) return;
      if (resp['success'] == true) {
        final fresh = await api.getJson(
          '/api/showcase/video',
          queryParameters: {'path': widget.video.path},
        );
        if (fresh['success'] == true && fresh['video'] is Map) {
          widget.onUpdated(VideoItem.fromJson(Map<String, dynamic>.from(fresh['video'])));
        }
        _showToast(strings.samplesFetched);
      } else {
        _showToast((resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('fetchSamples error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _fetchingSamples = false);
    }
  }

  Future<void> _openFocalEditor() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    final savedFocal = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _FocalCropSheet(
        api: api,
        strings: strings,
        video: widget.video,
      ),
    );
    if (savedFocal != null && savedFocal.isNotEmpty && mounted) {
      widget.onUpdated(widget.video.copyWith(autoFocal: savedFocal, cropMode: 'manual'));
      _showToast(strings.focalSavedMsg);
    }
  }

  Future<void> _autoTagVideo() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _autoTagging = true);
    try {
      final resp = await api.postJson('/api/ai/tags/videos', data: {
        'file_path': widget.video.path,
      });
      if (!mounted) return;
      if (resp['success'] == true) {
        final fresh = await api.getJson(
          '/api/showcase/video',
          queryParameters: {'path': widget.video.path},
        );
        if (fresh['success'] == true && fresh['video'] is Map) {
          widget.onUpdated(VideoItem.fromJson(Map<String, dynamic>.from(fresh['video'])));
        }
        final added = (resp['added'] as List?)?.map((e) => e.toString()).where((e) => e.isNotEmpty).toList() ?? const [];
        _showToast(added.isNotEmpty ? '${strings.saved}: ${added.join(', ')}' : strings.saved);
      } else {
        _showToast((resp['detail'] ?? resp['reason'] ?? resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('autoTagVideo error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _autoTagging = false);
    }
  }

  Future<void> _addUserTag() async {
    final strings = ref.read(stringsProvider);
    final tag = await showPromptTextDialog(
      context: context,
      title: strings.addUserTagTitle,
      hintText: strings.tagNameHint,
      cancelLabel: strings.cancel,
      confirmLabel: strings.confirm,
    );
    if (tag == null || tag.trim().isEmpty) return;
    final api = ref.read(apiClientProvider);
    try {
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
    } catch (e) {
      debugPrint('addUserTag error: $e');
      _showToast(strings.requestFailed('$e'));
    }
  }

  Future<void> _removeUserTag(String tag) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    try {
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
    } catch (e) {
      debugPrint('removeUserTag error: $e');
      _showToast(strings.requestFailed('$e'));
    }
  }

  Future<void> _openRescrapeDialog() async {
    if (_rescraping || _pickerOpen) return;
    final api = ref.read(apiClientProvider);
    final strings = ref.read(stringsProvider);
    final video = widget.video;
    final notifyUpdated = widget.onUpdated;
    _pickerOpen = true;
    SourceSelection? selected;
    try {
      selected = await showModalBottomSheet<SourceSelection>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (_) => MetadataSourceSheet(
          api: api,
          strings: strings,
          videoLabel: video.number.isNotEmpty
              ? video.number
              : video.title.isNotEmpty ? video.title : video.path,
        ),
      );
    } finally {
      _pickerOpen = false;
    }
    if (selected == null || selected.isEmpty || !mounted ||
        !widget.isCurrentVideo() || ref.read(apiClientProvider) != api) {
      return;
    }
    final sources = selected;
    setState(() {
      _rescraping = true;
      _rescrapeStatus = strings.requesting;
    });
    updateKeepAlive();
    final changed = <MetadataField>{};
    final failures = <String>{};
    String? summaryText;
    bool finished = false;
    bool streamError = false;
    void recordFailure(Map item) {
      final reason = item['error']?.toString();
      if (reason == null || reason.isEmpty) return;
      final field = MetadataField.values.asNameMap()[item['element']];
      final source = sources[field]?.label ?? item['source'];
      failures.add([field?.label(strings), source, reason].whereType<String>().join(' · '));
    }
    try {
      await for (final event in api.streamSse(
        '/api/gallery/rescrape-elements',
        method: 'POST',
        data: {'file_path': video.path, 'sources': {
          for (final entry in sources.entries) entry.key.name: entry.value.id,
        }},
      )) {
        if (finished || streamError) continue;
        final data = event.data;
        final field = MetadataField.values.asNameMap()[data['element']];
        if (event.type == 'result-item') {
          if (field != null && sources.containsKey(field) &&
              (data['success'] == true || data['partial'] == true)) {
            changed.add(field);
          }
          recordFailure(data);
        } else if (event.type == 'progress' && mounted && field != null) {
          setState(() => _rescrapeStatus = '${field.label(strings)} · ${sources[field]?.label ?? ''}');
        } else if (event.type == 'error') {
          streamError = true;
          failures.add((data['error'] ?? data['message'] ?? strings.taskStreamInterrupted).toString());
          if (data['rejected'] == true) finished = true;
        } else if (event.type == 'done' && data['summary'] is Map) {
          final summary = data['summary'] as Map;
          final counts = summary['fields_filled'];
          if (counts is Map) {
            for (final field in sources.keys) {
              final count = counts[field.name];
              if (count is num && count > 0) changed.add(field);
            }
          }
          if (summary['failed_items'] case final List items) {
            for (final item in items.whereType<Map>()) {
              recordFailure(item);
            }
          }
          summaryText = strings.rescrapeSummary(changed.length,
              (summary['failed'] as num?)?.toInt() ?? failures.length,
              (summary['skipped'] as num?)?.toInt() ?? 0);
          if (data['cancelled'] == true) failures.add(strings.taskCancelled);
          finished = true;
        }
      }
      if (!finished && !streamError) failures.add(strings.taskStreamInterrupted);
    } catch (e) {
      failures.add(strings.requestFailed('$e'));
    }
    // Confirmed writes stay attached to the original path even if its page closes.
    // A lost stream may have committed a field before its result reached us.
    if (changed.isNotEmpty || !finished) {
      try {
        await _refreshRescrapedVideo(
          api: api,
          strings: strings,
          video: video,
          fields: finished ? changed : sources.keys.toSet(),
          notifyUpdated: notifyUpdated,
        );
      } catch (e) {
        failures.add(strings.requestFailed('$e'));
      }
    }
    if (!mounted) return;
    setState(() {
      _rescraping = false;
      _rescrapeStatus = [?summaryText, ...failures].join('\n');
    });
    updateKeepAlive();
  }

  Future<void> _refreshRescrapedVideo({
    required ApiClient api,
    required AppStrings strings,
    required VideoItem video,
    required Set<MetadataField> fields,
    required ValueChanged<VideoItem> notifyUpdated,
  }) async {
    final response = await api.getJson(
      '/api/showcase/video',
      queryParameters: {'path': video.path},
    );
    final row = response['video'];
    if (response['success'] != true || row is! Map<String, dynamic> || row['path'] != video.path) {
      throw StateError((response['error'] ?? strings.loadLibraryFailed).toString());
    }
    final updated = VideoItem.fromJson(row);
    final images = <String>{
      if (fields.contains(MetadataField.cover)) ...[
        video.coverUrl, video.coverFullUrl, updated.coverUrl, updated.coverFullUrl,
      ],
      if (fields.contains(MetadataField.samples)) ...[
        ...video.sampleImages, ...updated.sampleImages,
      ],
    };
    await Future.wait(images.map((url) => OpenAverNetworkImage.evictUrl(api, url)));
    if (mounted && ref.read(apiClientProvider) != api) return;
    notifyUpdated(updated);
    if (mounted && fields.contains(MetadataField.plot)) await _loadPlot();
  }

  Future<void> _confirmDelete() async {
    final strings = ref.read(stringsProvider);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(strings.removeFromDb),
        content: Text(strings.removeFromDbConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(strings.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(strings.confirmRemove)),
        ],
      ),
    );
    if (ok != true) return;
    final api = ref.read(apiClientProvider);
    try {
      await api.deleteJson('/api/showcase/video', queryParameters: {'path': widget.video.path});
      widget.onDeleted(widget.video.path);
    } catch (e) {
      debugPrint('deleteVideo error: $e');
      _showToast(strings.requestFailed('$e'));
    }
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
    super.build(context);
    final api = ref.watch(apiClientProvider);
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);
    final v = widget.video;
    final hasPlot = (_plotText ?? '').trim().isNotEmpty;
    final displayedPlot = _showOriginalPlot && (_originalPlot ?? '').isNotEmpty
        ? _originalPlot!
        : (_plotText ?? '');

    final mediaPane = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
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
                  OpenAverNetworkImage(
                    api: api,
                    url: v.coverFullUrl.isNotEmpty ? v.coverFullUrl : v.coverUrl,
                    alignment: v.focalAlignment,
                    errorIcon: Icons.movie_outlined,
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
        const SizedBox(height: 12),
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
        if (v.isMultipart) ...[
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: List.generate(v.partPaths.length, (idx) {
              final token = idx < v.partTokens.length && v.partTokens[idx].isNotEmpty
                  ? v.partTokens[idx].toUpperCase()
                  : 'CD${idx + 1}';
              return ActionChip(
                avatar: const Icon(Icons.play_circle_outline_rounded, size: 16),
                label: Text(token),
                onPressed: () => _openBuiltInPlayer(api, partIndex: idx),
              );
            }),
          ),
        ],
      ],
    );

    final detailsPane = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_editingTitle)
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: _titleCtrl,
                maxLines: 3,
                minLines: 1,
                decoration: InputDecoration(labelText: strings.editTitleLabel),
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
                    child: Text(_savingTitle ? strings.saving : strings.save),
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
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ActionChip(
              avatar: Icon(_rescraping ? Icons.hourglass_top : Icons.auto_fix_high_rounded, size: 16),
              label: Text(strings.rescrape),
              onPressed: _rescraping ? null : _openRescrapeDialog,
            ),
            ActionChip(
              avatar: const Icon(Icons.crop_rounded, size: 16),
              label: Text(strings.detectFocal),
              onPressed: _openFocalEditor,
            ),
            ActionChip(
              avatar: _autoTagging
                  ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.auto_awesome_outlined, size: 16),
              label: Text(strings.aiAutoTag),
              onPressed: _autoTagging ? null : _autoTagVideo,
            ),
            ActionChip(
              avatar: const Icon(Icons.delete_outline_rounded, size: 16),
              label: Text(strings.removeFromDb),
              onPressed: _confirmDelete,
            ),
          ],
        ),
        if (_rescrapeStatus != null)
          Semantics(liveRegion: true, child: Text(_rescrapeStatus!)),
        const SizedBox(height: 14),

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
              if (v.number.isNotEmpty) _MetaPill(label: strings.numberLabel, value: v.number),
              if (v.releaseDate.isNotEmpty) _MetaPill(label: strings.releaseLabel, value: v.releaseDate),
              if (v.duration != null) _MetaPill(label: strings.durationLabel, value: '${v.duration} min'),
              if (v.maker.isNotEmpty)
                _MetaPill(
                  label: strings.makerLabel,
                  value: v.maker,
                  onTap: () => widget.onSelectFilterText(v.maker),
                ),
              if (v.director.isNotEmpty)
                _MetaPill(
                  label: strings.directorLabel,
                  value: v.director,
                  onTap: () => widget.onSelectFilterText(v.director),
                ),
              if (v.series.isNotEmpty)
                _MetaPill(
                  label: strings.seriesLabel,
                  value: v.series,
                  onTap: () => widget.onSelectFilterText(v.series),
                ),
              if (v.label.isNotEmpty)
                _MetaPill(
                  label: strings.labelLabel,
                  value: v.label,
                  onTap: () => widget.onSelectFilterText(v.label),
                ),
              if (v.formattedSize.isNotEmpty) _MetaPill(label: strings.sizeLabel, value: v.formattedSize),
              if (v.partTokens.isNotEmpty) _MetaPill(label: strings.partsLabel, value: v.partTokens.join(', ')),
            ],
          ),
        ),

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

        const SizedBox(height: 14),
        Row(
          children: [
            Text(strings.tagsLabel, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
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
                onPressed: () => widget.onSelectTag(ut),
                onDeleted: () => _removeUserTag(ut),
              ),
            ),
            ...v.tags.map(
              (t) => ActionChip(
                label: Text(t),
                onPressed: () => widget.onSelectTag(t),
              ),
            ),
          ],
        ),

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
                      decoration: InputDecoration(hintText: strings.plotInputHint),
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
                          child: Text(_savingPlot ? strings.saving : strings.save),
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
                      (_plotError != null && _plotError!.isNotEmpty) ? _plotError! : strings.emptyPlot,
                      style: TextStyle(color: palette.textMuted, fontSize: 13),
                    ),
                    const SizedBox(height: 8),
                    ActionChip(
                      avatar: const Icon(Icons.edit_outlined, size: 15),
                      label: Text(strings.addPlotManually),
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

        const SizedBox(height: 16),
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          children: [
            Text(
              '${strings.sampleImages} (${v.sampleImages.length})',
              style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary),
            ),
            TextButton.icon(
              onPressed: _fetchingSamples ? null : _fetchSamples,
              icon: _fetchingSamples
                  ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.collections_outlined, size: 16),
              label: Text(strings.fetchSamples),
            ),
          ],
        ),
        if (v.sampleImages.isNotEmpty) ...[
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
                      child: OpenAverNetworkImage(
                        api: api,
                        url: v.sampleImages[idx],
                        targetDecodeWidth: 420,
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],

        if (_similarLoading || _similar.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text(strings.similarVideos, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
          const SizedBox(height: 8),
          if (_similarLoading)
            const LinearProgressIndicator(minHeight: 2)
          else
            SizedBox(
              height: 170,
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
                    child: InkWell(
                      borderRadius: BorderRadius.circular(10),
                      onTap: () => _openSimilarVideo(sim),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(10),
                              child: SizedBox(
                                width: double.infinity,
                                child: OpenAverNetworkImage(
                                  api: api,
                                  url: cover,
                                  targetDecodeWidth: 280,
                                ),
                              ),
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
                    ),
                  );
                },
              ),
            ),
        ],
      ],
    );

    return LayoutBuilder(
      builder: (_, constraints) {
        final wide = constraints.maxWidth >= 720;
        if (wide) {
          return Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 360,
                  child: SingleChildScrollView(child: mediaPane),
                ),
                const SizedBox(width: 20),
                Expanded(
                  child: SingleChildScrollView(child: detailsPane),
                ),
              ],
            ),
          );
        }
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            mediaPane,
            const SizedBox(height: 14),
            detailsPane,
          ],
        );
      },
    );
  }
}

class _MetaPill extends StatelessWidget {
  const _MetaPill({
    required this.label,
    required this.value,
    this.onTap,
  });

  final String label;
  final String value;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final child = RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12, color: palette.textSecondary),
        children: [
          TextSpan(
            text: '$label: ',
            style: TextStyle(color: palette.textMuted),
          ),
          TextSpan(
            text: value,
            style: TextStyle(
              color: onTap != null ? palette.accent : palette.textPrimary,
              fontWeight: FontWeight.w500,
              decoration: onTap != null ? TextDecoration.underline : null,
            ),
          ),
        ],
      ),
    );
    if (onTap == null) return child;
    return InkWell(
      borderRadius: BorderRadius.circular(4),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 1, horizontal: 2),
        child: child,
      ),
    );
  }
}

class _FocalCropSheet extends StatefulWidget {
  const _FocalCropSheet({
    required this.api,
    required this.strings,
    required this.video,
  });

  final ApiClient api;
  final AppStrings strings;
  final VideoItem video;

  @override
  State<_FocalCropSheet> createState() => _FocalCropSheetState();
}

class _FocalCropSheetState extends State<_FocalCropSheet> {
  static const double _cropRatio = 0.71;

  late double _x;
  late double _y;
  String? _expectedCoverPath;
  bool _detecting = false;
  bool _saving = false;
  String? _statusText;
  bool _statusIsError = false;

  @override
  void initState() {
    super.initState();
    _initInitialFocal();
    _runFaceDetect(silentIfEmpty: true);
  }

  void _initInitialFocal() {
    final v = widget.video;
    if (v.cropMode != 'default' && v.autoFocal.isNotEmpty) {
      final parts = v.autoFocal.split(',');
      if (parts.length == 2) {
        final px = double.tryParse(parts[0].trim());
        final py = double.tryParse(parts[1].trim());
        if (px != null && py != null) {
          _x = px.clamp(0.0, 1.0);
          _y = py.clamp(0.0, 1.0);
          return;
        }
      }
    }
    _x = 1.0;
    _y = 0.5;
  }

  Future<void> _runFaceDetect({required bool silentIfEmpty}) async {
    setState(() {
      _detecting = true;
      if (!silentIfEmpty) {
        _statusText = null;
        _statusIsError = false;
      }
    });
    try {
      final resp = await widget.api.postJson(
        '/api/showcase/video/detect-focal',
        data: {'path': widget.video.path},
      );
      if (!mounted) return;
      final coverPath = resp['cover_path'] as String?;
      if (coverPath != null) {
        _expectedCoverPath = coverPath;
      }
      final focal = (resp['auto_focal'] as String?) ?? '';
      final reason = (resp['reason'] as String?) ?? '';
      if (resp['success'] == true && focal.isNotEmpty) {
        final parts = focal.split(',');
        if (parts.length == 2) {
          final px = double.tryParse(parts[0].trim());
          final py = double.tryParse(parts[1].trim());
          if (px != null && py != null) {
            final shouldApply = !silentIfEmpty || widget.video.autoFocal.isEmpty;
            setState(() {
              if (shouldApply) {
                _x = px.clamp(0.0, 1.0);
                _y = py.clamp(0.0, 1.0);
              }
              if (!silentIfEmpty) {
                _statusText = widget.strings.focalUpdated;
                _statusIsError = false;
              }
            });
            return;
          }
        }
      }
      if (!silentIfEmpty) {
        String msg = widget.strings.focalNoFace;
        if (reason == 'device_disabled' || reason == 'too_slow_auto_disabled') {
          msg = widget.strings.focalDisabledHint;
        } else if (reason == 'still_detecting') {
          msg = widget.strings.focalStillDetectingHint;
        }
        setState(() {
          _statusText = msg;
          _statusIsError = false;
        });
      }
    } catch (e) {
      debugPrint('focal detect error: $e');
      if (mounted && !silentIfEmpty) {
        setState(() {
          _statusText = widget.strings.requestFailed('$e');
          _statusIsError = true;
        });
      }
    } finally {
      if (mounted) setState(() => _detecting = false);
    }
  }

  Future<void> _saveFocal() async {
    setState(() {
      _saving = true;
      _statusText = null;
      _statusIsError = false;
    });
    try {
      final focalStr = '${_x.toStringAsFixed(4)},${_y.toStringAsFixed(4)}';
      final resp = await widget.api.postJson(
        '/api/showcase/video/save-focal',
        data: {
          'path': widget.video.path,
          'focal': focalStr,
          'expected_cover_path': _expectedCoverPath ?? '',
        },
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        Navigator.of(context).pop((resp['auto_focal'] as String?) ?? focalStr);
      } else {
        setState(() {
          _saving = false;
          _statusText = (resp['error'] ?? widget.strings.saveFailed).toString();
          _statusIsError = true;
        });
      }
    } catch (e) {
      debugPrint('focal save error: $e');
      if (mounted) {
        setState(() {
          _saving = false;
          _statusText = widget.strings.requestFailed('$e');
          _statusIsError = true;
        });
      }
    }
  }

  void _updateFromLocalPosition(Offset pos, Size boxSize) {
    if (boxSize.width <= 0 || boxSize.height <= 0) return;
    setState(() {
      _x = (pos.dx / boxSize.width).clamp(0.0, 1.0);
      _y = (pos.dy / boxSize.height).clamp(0.0, 1.0);
    });
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final coverUrl = widget.video.coverFullUrl.isNotEmpty
        ? widget.video.coverFullUrl
        : widget.video.coverUrl;

    return Padding(
      padding: EdgeInsets.fromLTRB(
        16,
        14,
        16,
        MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  widget.strings.focalCropTitle,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close_rounded),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
          Text(
            widget.strings.focalDragHint,
            style: TextStyle(fontSize: 12, color: palette.textMuted),
          ),
          const SizedBox(height: 10),
          AspectRatio(
            aspectRatio: 1.48,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: LayoutBuilder(
                builder: (_, constraints) {
                  final boxW = constraints.maxWidth;
                  final boxH = constraints.maxHeight;
                  final winW = (boxH * _cropRatio).clamp(24.0, boxW);
                  final left = ((boxW - winW) * _x).clamp(0.0, boxW - winW);

                  return GestureDetector(
                    onTapDown: (d) => _updateFromLocalPosition(d.localPosition, Size(boxW, boxH)),
                    onPanUpdate: (d) => _updateFromLocalPosition(d.localPosition, Size(boxW, boxH)),
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        OpenAverNetworkImage(
                          api: widget.api,
                          url: coverUrl,
                          fit: BoxFit.cover,
                          errorIcon: Icons.movie_outlined,
                        ),
                        // Dim regions outside the 0.71 portrait crop window
                        if (left > 0)
                          Positioned(
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: left,
                            child: const ColoredBox(color: Color(0x88000000)),
                          ),
                        if (left + winW < boxW)
                          Positioned(
                            left: left + winW,
                            top: 0,
                            bottom: 0,
                            right: 0,
                            child: const ColoredBox(color: Color(0x88000000)),
                          ),
                        Positioned(
                          left: left,
                          top: 0,
                          bottom: 0,
                          width: winW,
                          child: Container(
                            decoration: BoxDecoration(
                              border: Border.all(color: palette.accent, width: 2),
                            ),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Text(
                'X: ${(_x * 100).round()}%',
                style: TextStyle(fontSize: 12, color: palette.textSecondary),
              ),
              Expanded(
                child: Slider(
                  value: _x,
                  min: 0.0,
                  max: 1.0,
                  onChanged: (v) => setState(() => _x = v),
                ),
              ),
            ],
          ),
          if (_statusText != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                _statusText!,
                style: TextStyle(
                  fontSize: 12,
                  color: _statusIsError ? palette.danger : palette.textSecondary,
                ),
              ),
            ),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.spaceBetween,
            children: [
              OutlinedButton.icon(
                onPressed: (_detecting || _saving) ? null : () => _runFaceDetect(silentIfEmpty: false),
                icon: _detecting
                    ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.face_retouching_natural_outlined, size: 17),
                label: Text(widget.strings.focalDetectLocalBtn),
              ),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextButton(
                    onPressed: (_detecting || _saving)
                        ? null
                        : () => setState(() {
                              _x = 1.0;
                              _y = 0.5;
                            }),
                    child: Text(widget.strings.focalResetBtn),
                  ),
                  const SizedBox(width: 6),
                  FilledButton(
                    onPressed: (_detecting || _saving) ? null : _saveFocal,
                    child: Text(_saving ? widget.strings.saving : widget.strings.focalSaveBtn),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}
