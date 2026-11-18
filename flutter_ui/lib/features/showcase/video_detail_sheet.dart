import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/video_item.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';
import '../shared/openaver_image.dart';
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
  });

  final List<VideoItem> videos;
  final int initialIndex;
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

  @override
  void initState() {
    super.initState();
    _videos = List<VideoItem>.from(widget.videos);
    _currentIndex = widget.initialIndex.clamp(
      0,
      _videos.isEmpty ? 0 : _videos.length - 1,
    );
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
      return Scaffold(appBar: AppBar(), body: const SizedBox.shrink());
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
    required this.onUpdated,
    required this.onDeleted,
    required this.onSelectActress,
    required this.onSelectTag,
    required this.onSelectFilterText,
  });

  final VideoItem video;
  final ValueChanged<VideoItem> onUpdated;
  final ValueChanged<String> onDeleted;
  final ValueChanged<String> onSelectActress;
  final ValueChanged<String> onSelectTag;
  final ValueChanged<String> onSelectFilterText;

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

  bool _fetchingSamples = false;
  bool _detectingFocal = false;
  bool _autoTagging = false;

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
      debugPrint('loadPlot error: $e');
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
    final number = (sim['number'] ?? '').toString().trim();
    final title = (sim['title'] ?? '').toString().trim();

    try {
      final resp = await api.getJson(
        '/api/showcase/videos',
        queryParameters: {'paged': false},
      );
      if (!mounted) return;
      if (resp['success'] != true) {
        _showToast(strings.loadLibraryFailed);
        return;
      }
      final parsed = VideosPageResponse.fromJson(resp);
      var idx = -1;
      if (number.isNotEmpty) {
        idx = parsed.videos.indexWhere(
          (v) => v.number.toUpperCase() == number.toUpperCase(),
        );
      }
      if (idx == -1 && title.isNotEmpty) {
        idx = parsed.videos.indexWhere((v) => v.title == title);
      }
      if (idx == -1) {
        _showToast(strings.videoNotInLibrary);
        return;
      }
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => VideoDetailPage(
            videos: parsed.videos,
            initialIndex: idx,
            onVideoUpdated: widget.onUpdated,
            onVideoDeleted: widget.onDeleted,
            onSelectActress: widget.onSelectActress,
            onSelectTag: widget.onSelectTag,
            onSelectFilterText: widget.onSelectFilterText,
          ),
        ),
      );
    } catch (e) {
      debugPrint('openSimilarVideo error: $e');
      _showToast(strings.requestFailed('$e'));
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
      });
      if (!mounted) return;
      final translated = (resp['result'] as String?) ?? '';
      if (resp['success'] == true && translated.isNotEmpty) {
        await _saveTitle(translated);
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

  Future<void> _detectAndSaveFocal() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _detectingFocal = true);
    try {
      final resp = await api.postJson('/api/showcase/video/detect-focal', data: {
        'file_path': widget.video.path,
      });
      if (!mounted) return;
      final focal = (resp['auto_focal'] as String?) ?? '';
      if (resp['success'] == true && focal.isNotEmpty) {
        final save = await api.postJson('/api/showcase/video/save-focal', data: {
          'file_path': widget.video.path,
          'focal': focal,
        });
        if (!mounted) return;
        if (save['success'] == true) {
          widget.onUpdated(widget.video.copyWith(autoFocal: focal, cropMode: 'manual'));
          _showToast(strings.focalUpdated);
        }
      } else {
        _showToast(strings.focalNoFace);
      }
    } catch (e) {
      debugPrint('detectFocal error: $e');
      _showToast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _detectingFocal = false);
    }
  }

  Future<void> _autoTagVideo() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _autoTagging = true);
    try {
      final resp = await api.postJson('/api/tags/videos', data: {
        'paths': [widget.video.path],
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
        _showToast(strings.saved);
      } else {
        _showToast((resp['error'] ?? resp['detail'] ?? strings.saveFailed).toString());
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
    final ctrl = TextEditingController();
    final tag = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(strings.addUserTagTitle),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: InputDecoration(hintText: strings.tagNameHint),
          onSubmitted: (v) => Navigator.of(ctx).pop(v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: Text(strings.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(ctrl.text), child: Text(strings.confirm)),
        ],
      ),
    );
    ctrl.dispose();
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
    final strings = ref.read(stringsProvider);
    final numCtrl = TextEditingController(text: widget.video.number);
    var source = 'auto';
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
              try {
                final resp = await api.postJson('/api/rescrape/preview', data: {
                  'number': numCtrl.text.trim(),
                  'source': source,
                });
                setSheetState(() {
                  loading = false;
                  if (resp['success'] == true) {
                    preview = resp;
                  } else {
                    statusError = (resp['error'] ?? strings.rescrapeNotFound).toString();
                  }
                });
              } catch (e) {
                setSheetState(() {
                  loading = false;
                  statusError = e.toString();
                });
              }
            }

            Future<void> doApply() async {
              if (preview == null) return;
              setSheetState(() => loading = true);
              try {
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
                  _showToast(strings.rescrapeUpdated);
                } else {
                  setSheetState(() {
                    statusError = (resp['error'] ?? resp['reason'] ?? strings.saveFailed).toString();
                  });
                }
              } catch (e) {
                setSheetState(() {
                  loading = false;
                  statusError = e.toString();
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
                  Text(strings.rescrape, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: numCtrl,
                          decoration: InputDecoration(labelText: strings.numberLabel),
                        ),
                      ),
                      const SizedBox(width: 10),
                      DropdownButton<String>(
                        value: source,
                        items: [
                          DropdownMenuItem(value: 'auto', child: Text(strings.autoLabel)),
                          const DropdownMenuItem(value: 'javbus', child: Text('JavBus')),
                          const DropdownMenuItem(value: 'javdb', child: Text('JavDB')),
                          const DropdownMenuItem(value: 'dmm', child: Text('DMM')),
                          const DropdownMenuItem(value: 'jav321', child: Text('Jav321')),
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
                            '${strings.makerLabel}: ${preview!['maker'] ?? '-'} · ${strings.releaseLabel}: ${preview!['date'] ?? '-'}',
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
                          child: Text(loading ? strings.requesting : strings.previewRescrape),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: FilledButton(
                          onPressed: (loading || preview == null) ? null : doApply,
                          child: Text(strings.applyOverwrite),
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
              avatar: const Icon(Icons.auto_fix_high_rounded, size: 16),
              label: Text(strings.rescrape),
              onPressed: _openRescrapeDialog,
            ),
            ActionChip(
              avatar: _detectingFocal
                  ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.center_focus_strong_outlined, size: 16),
              label: Text(strings.detectFocal),
              onPressed: _detectingFocal ? null : _detectAndSaveFocal,
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
        Row(
          children: [
            Text(
              '${strings.sampleImages} (${v.sampleImages.length})',
              style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary),
            ),
            const Spacer(),
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
