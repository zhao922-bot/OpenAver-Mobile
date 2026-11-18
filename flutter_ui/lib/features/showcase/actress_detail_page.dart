import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import '../../core/models/actress_models.dart';
import '../../core/native_bridge.dart';
import '../shared/openaver_image.dart';

class ActressDetailPage extends ConsumerStatefulWidget {
  const ActressDetailPage({
    super.key,
    required this.actresses,
    required this.initialIndex,
    required this.onActressUpdated,
    required this.onViewVideos,
  });

  final List<ActressProfile> actresses;
  final int initialIndex;
  final ValueChanged<ActressProfile> onActressUpdated;
  final ValueChanged<String> onViewVideos;

  @override
  ConsumerState<ActressDetailPage> createState() => _ActressDetailPageState();
}

class _ActressDetailPageState extends ConsumerState<ActressDetailPage> {
  late final PageController _pageController;
  late List<ActressProfile> _actresses;
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _actresses = List<ActressProfile>.from(widget.actresses);
    _currentIndex = widget.initialIndex.clamp(
      0,
      _actresses.isEmpty ? 0 : _actresses.length - 1,
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
    final strings = ref.watch(stringsProvider);

    if (_actresses.isEmpty) {
      return Scaffold(
        appBar: AppBar(title: Text(strings.actressDetail)),
        body: const SizedBox.shrink(),
      );
    }

    final current = _actresses[_currentIndex];
    return Scaffold(
      backgroundColor: palette.canvas,
      appBar: AppBar(
        title: Text(current.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(
              child: Text(
                '${_currentIndex + 1} / ${_actresses.length}',
                style: TextStyle(color: palette.textMuted, fontSize: 12),
              ),
            ),
          ),
        ],
      ),
      body: PageView.builder(
        controller: _pageController,
        itemCount: _actresses.length,
        onPageChanged: (idx) => setState(() => _currentIndex = idx),
        itemBuilder: (_, idx) {
          final item = _actresses[idx];
          return _ActressDetailBody(
            key: ValueKey(item.name),
            initialProfile: item,
            onUpdated: (updated) {
              setState(() => _actresses[idx] = updated);
              widget.onActressUpdated(updated);
            },
            onViewVideos: (name) {
              Navigator.of(context).pop();
              widget.onViewVideos(name);
            },
          );
        },
      ),
    );
  }
}

class _ActressDetailBody extends ConsumerStatefulWidget {
  const _ActressDetailBody({
    super.key,
    required this.initialProfile,
    required this.onUpdated,
    required this.onViewVideos,
  });

  final ActressProfile initialProfile;
  final ValueChanged<ActressProfile> onUpdated;
  final ValueChanged<String> onViewVideos;

  @override
  ConsumerState<_ActressDetailBody> createState() => _ActressDetailBodyState();
}

class _ActressDetailBodyState extends ConsumerState<_ActressDetailBody> {
  late ActressProfile _profile;
  bool _loadingDetail = false;
  bool _togglingFavorite = false;
  bool _detectingFocal = false;

  @override
  void initState() {
    super.initState();
    _profile = widget.initialProfile;
    _fetchDetailIfNeeded();
  }

  Future<void> _fetchDetailIfNeeded() async {
    setState(() => _loadingDetail = true);
    try {
      final resp = await ref.read(apiClientProvider).getJson(
        '/api/actresses/${Uri.encodeComponent(_profile.name)}',
      );
      if (!mounted) return;
      if (resp['actress'] is Map) {
        final merged = ActressProfile.fromJson(
          Map<String, dynamic>.from(resp['actress'] as Map),
          fallbackVideoCount: _profile.videoCount,
        ).copyWith(isFavorite: true);
        setState(() {
          _profile = merged;
          _loadingDetail = false;
        });
        widget.onUpdated(merged);
        return;
      }
    } catch (e) {
      debugPrint('Failed to fetch actress detail ${_profile.name}: $e');
    }
    if (mounted) setState(() => _loadingDetail = false);
  }

  Future<bool> _favoriteActress() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _togglingFavorite = true);
    try {
      final resp = await api.dio.post<dynamic>(
        '/api/actresses/favorite',
        data: {'name': _profile.name},
      );
      final body = resp.data is Map
          ? Map<String, dynamic>.from(resp.data as Map)
          : const <String, dynamic>{};
      if (!mounted) return false;

      if ((resp.statusCode == 200 || resp.statusCode == 409) &&
          body['actress'] is Map) {
        final updated = ActressProfile.fromJson(
          Map<String, dynamic>.from(body['actress'] as Map),
          fallbackVideoCount: _profile.videoCount,
        ).copyWith(isFavorite: true);
        setState(() => _profile = updated);
        widget.onUpdated(updated);
        _toast(resp.statusCode == 409 ? strings.actressAlreadyExists : strings.actressAdded);
        return true;
      }

      if (body['success'] == true) {
        final updated = _profile.copyWith(isFavorite: true);
        setState(() => _profile = updated);
        widget.onUpdated(updated);
        _toast(strings.actressAdded);
        return true;
      }
      _toast((body['message'] ?? body['error'] ?? strings.saveFailed).toString());
      return false;
    } catch (e) {
      debugPrint('favorite actress error: $e');
      _toast(strings.requestFailed('$e'));
      return false;
    } finally {
      if (mounted) setState(() => _togglingFavorite = false);
    }
  }

  Future<void> _toggleFavorite() async {
    final strings = ref.read(stringsProvider);
    if (!_profile.isFavorite) {
      await _favoriteActress();
      return;
    }
    final confirm = await showDialog<bool>(
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
    if (confirm != true) return;

    setState(() => _togglingFavorite = true);
    try {
      final resp = await ref.read(apiClientProvider).deleteJson(
        '/api/actresses/${Uri.encodeComponent(_profile.name)}',
      );
      if (!mounted) return;
      if (resp['success'] == true) {
        final updated = _profile.copyWith(isFavorite: false);
        setState(() => _profile = updated);
        widget.onUpdated(updated);
        _toast(strings.actressRemoved);
      } else {
        _toast((resp['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('unfavorite actress error: $e');
      _toast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _togglingFavorite = false);
    }
  }

  Future<void> _openPhotoPicker() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);

    if (!_profile.isFavorite) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(strings.changeCoverPhoto),
          content: Text(strings.favoriteFirstHint),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(strings.cancel)),
            FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(strings.confirm)),
          ],
        ),
      );
      if (ok != true) return;
      final added = await _favoriteActress();
      if (!added || !mounted) return;
    }

    final result = await showModalBottomSheet<ActressProfile>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _ActressPhotoPickerSheet(
        api: api,
        strings: strings,
        profile: _profile,
      ),
    );

    if (result != null && mounted) {
      await OpenAverNetworkImage.evictUrl(api, _profile.photoUrl);
      await OpenAverNetworkImage.evictUrl(api, result.photoUrl);
      setState(() => _profile = result);
      widget.onUpdated(result);
    }
  }

  Future<void> _detectAndSaveFocal() async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    if (!_profile.isFavorite) {
      final added = await _favoriteActress();
      if (!added || !mounted) return;
    }
    setState(() => _detectingFocal = true);
    try {
      final det = await api.postJson(
        '/api/actresses/${Uri.encodeComponent(_profile.name)}/detect-focal',
      );
      if (!mounted) return;
      final focal = (det['auto_focal'] as String?) ?? '';
      if (focal.isEmpty) {
        _toast(strings.focalNoFace);
        return;
      }
      final save = await api.postJson(
        '/api/actresses/${Uri.encodeComponent(_profile.name)}/focal',
        data: {'focal': focal},
      );
      if (!mounted) return;
      if (save['success'] == true) {
        final updated = _profile.copyWith(autoFocal: focal, cropMode: 'manual');
        setState(() => _profile = updated);
        widget.onUpdated(updated);
        _toast(strings.focalUpdated);
      } else {
        _toast((save['error'] ?? strings.saveFailed).toString());
      }
    } catch (e) {
      debugPrint('detect actress focal error: $e');
      _toast(strings.requestFailed('$e'));
    } finally {
      if (mounted) setState(() => _detectingFocal = false);
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), duration: const Duration(seconds: 2)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiClientProvider);
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);
    final photoUrl = _profile.photoUrl.isNotEmpty
        ? _profile.photoUrl
        : '/api/actresses/photo/${Uri.encodeComponent(_profile.name)}';

    final portraitCard = ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: AspectRatio(
        aspectRatio: 0.75,
        child: Stack(
          fit: StackFit.expand,
          children: [
            OpenAverNetworkImage(
              api: api,
              url: photoUrl,
              alignment: _profile.focalAlignment,
              errorIcon: Icons.person_rounded,
            ),
            Positioned(
              right: 10,
              top: 10,
              child: IconButton.filled(
                style: IconButton.styleFrom(
                  backgroundColor: Colors.black54,
                  foregroundColor: _profile.isFavorite ? palette.favoritePink : Colors.white,
                ),
                icon: _togglingFavorite
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : Icon(_profile.isFavorite ? Icons.favorite_rounded : Icons.favorite_border_rounded),
                onPressed: _togglingFavorite ? null : _toggleFavorite,
              ),
            ),
            if (_profile.photoSource.isNotEmpty)
              Positioned(
                left: 10,
                bottom: 10,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: Color(0xA6000000),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    _profile.photoSource,
                    style: const TextStyle(color: Colors.white, fontSize: 11),
                  ),
                ),
              ),
          ],
        ),
      ),
    );

    final infoColumn = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                _profile.name,
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                  color: palette.textPrimary,
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: palette.surface,
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: palette.stroke),
              ),
              child: Text(
                strings.videosUnit(_profile.videoCount),
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: palette.accent,
                  fontSize: 12.5,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: () => widget.onViewVideos(_profile.name),
          icon: const Icon(Icons.video_library_outlined),
          label: Text('${strings.viewActressVideos} (${_profile.videoCount})'),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _openPhotoPicker,
                icon: const Icon(Icons.photo_library_outlined, size: 18),
                label: Text(strings.changeCoverPhoto),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton.tonalIcon(
                onPressed: _togglingFavorite ? null : _toggleFavorite,
                icon: Icon(
                  _profile.isFavorite ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                  size: 18,
                  color: _profile.isFavorite ? palette.favoritePink : null,
                ),
                label: Text(_profile.isFavorite ? strings.unfavoriteActress : strings.favoriteActress),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: ActionChip(
            avatar: _detectingFocal
                ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.center_focus_strong_outlined, size: 16),
            label: Text(strings.detectFocal),
            onPressed: _detectingFocal ? null : _detectAndSaveFocal,
          ),
        ),
        if (_loadingDetail)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: LinearProgressIndicator(minHeight: 2),
          ),
        const SizedBox(height: 12),
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
              Wrap(
                spacing: 14,
                runSpacing: 8,
                children: [
                  if (_profile.birth.isNotEmpty)
                    _ActressInfoRow(
                      label: strings.birthLabel,
                      value: _profile.age != null
                          ? '${_profile.birth} (${_profile.age})'
                          : _profile.birth,
                    ),
                  if (_profile.height.isNotEmpty)
                    _ActressInfoRow(label: strings.heightLabel, value: '${_profile.height} cm'),
                  if (_profile.cup.isNotEmpty)
                    _ActressInfoRow(label: strings.cupLabel, value: _profile.cup),
                  if (_profile.measurementsText.isNotEmpty)
                    _ActressInfoRow(label: strings.measurementsLabel, value: _profile.measurementsText),
                  if (_profile.hometown.isNotEmpty)
                    _ActressInfoRow(label: strings.hometownLabel, value: _profile.hometown),
                  if (_profile.hobby.isNotEmpty)
                    _ActressInfoRow(label: strings.hobbyLabel, value: _profile.hobby),
                ],
              ),
              if (_profile.aliases.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(strings.aliases, style: TextStyle(fontSize: 12, color: palette.textMuted)),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: _profile.aliases.map((a) => Chip(label: Text(a))).toList(),
                ),
              ],
            ],
          ),
        ),
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
                  width: 300,
                  child: SingleChildScrollView(child: portraitCard),
                ),
                const SizedBox(width: 20),
                Expanded(
                  child: SingleChildScrollView(child: infoColumn),
                ),
              ],
            ),
          );
        }
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 380),
              child: Center(child: portraitCard),
            ),
            const SizedBox(height: 14),
            infoColumn,
          ],
        );
      },
    );
  }
}

class _ActressInfoRow extends StatelessWidget {
  const _ActressInfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    return RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12.5, color: palette.textSecondary),
        children: [
          TextSpan(text: '$label: ', style: TextStyle(color: palette.textMuted)),
          TextSpan(
            text: value,
            style: TextStyle(color: palette.textPrimary, fontWeight: FontWeight.w500),
          ),
        ],
      ),
    );
  }
}

class _ActressPhotoPickerSheet extends StatefulWidget {
  const _ActressPhotoPickerSheet({
    required this.api,
    required this.strings,
    required this.profile,
  });

  final ApiClient api;
  final AppStrings strings;
  final ActressProfile profile;

  @override
  State<_ActressPhotoPickerSheet> createState() => _ActressPhotoPickerSheetState();
}

class _ActressPhotoPickerSheetState extends State<_ActressPhotoPickerSheet> {
  final List<PhotoCandidate> _candidates = [];
  final Set<String> _seenIds = {};
  CancelToken? _cancel;
  int _attempt = 0;
  bool _loading = true;
  bool _applying = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchCandidates();
  }

  @override
  void dispose() {
    _cancel?.cancel();
    super.dispose();
  }

  Future<void> _fetchCandidates({bool nextBatch = false}) async {
    _cancel?.cancel();
    final cancel = CancelToken();
    _cancel = cancel;
    if (nextBatch) _attempt += 1;

    setState(() {
      _loading = true;
      _error = null;
      _candidates.clear();
    });

    try {
      await for (final event in widget.api.streamSse(
        '/api/actresses/${Uri.encodeComponent(widget.profile.name)}/photo-candidates',
        queryParameters: {
          if (_attempt > 0) 'attempt': _attempt,
          if (_seenIds.isNotEmpty) 'exclude': _seenIds.join(','),
        },
        cancelToken: cancel,
      )) {
        if (!mounted) break;
        if (event.data.containsKey('full_url')) {
          final cand = PhotoCandidate.fromJson(event.data);
          if (cand.id.isNotEmpty) _seenIds.add(cand.id);
          setState(() => _candidates.add(cand));
        } else if (event.data['error'] != null) {
          setState(() => _error = event.data['error'].toString());
        }
      }
    } catch (e) {
      if (!cancel.isCancelled && mounted) {
        debugPrint('photo candidates SSE error: $e');
        setState(() => _error = e.toString());
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _selectCandidate(PhotoCandidate cand) async {
    if (_applying) return;
    setState(() => _applying = true);
    try {
      final resp = await widget.api.postJson(
        '/api/actresses/${Uri.encodeComponent(widget.profile.name)}/photo',
        data: {
          'source': cand.source,
          'url': cand.fullUrl,
          'video_path': cand.videoPath,
          'crop_spec': 'v1',
        },
      );
      if (!mounted) return;
      if (resp['photo_url'] != null) {
        final updated = widget.profile.copyWith(
          photoUrl: resp['photo_url'].toString(),
          photoSource: (resp['photo_source'] as String?) ?? cand.source,
          autoFocal: (resp['auto_focal'] as String?) ?? '',
          cropMode: (resp['crop_mode'] as String?) ?? 'auto',
        );
        Navigator.of(context).pop(updated);
      } else {
        setState(() {
          _applying = false;
          _error = (resp['error'] ?? widget.strings.saveFailed).toString();
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _applying = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _uploadLocal() async {
    if (_applying) return;
    final picked = await NativeBridge.instance.pickFile(
      mimeTypes: const ['image/jpeg', 'image/png', 'image/webp'],
    );
    if (picked == null || picked.path.isEmpty) return;
    setState(() {
      _applying = true;
      _error = null;
    });
    try {
      final form = FormData.fromMap({
        'file': await MultipartFile.fromFile(picked.path, filename: picked.name),
      });
      final resp = await widget.api.dio.post<dynamic>(
        '/api/actresses/${Uri.encodeComponent(widget.profile.name)}/photo/upload',
        data: form,
      );
      final body = resp.data is Map
          ? Map<String, dynamic>.from(resp.data as Map)
          : const <String, dynamic>{};
      if (!mounted) return;
      if (resp.statusCode == 200 && body['photo_url'] != null) {
        final updated = widget.profile.copyWith(
          photoUrl: body['photo_url'].toString(),
          photoSource: (body['photo_source'] as String?) ?? 'upload',
          autoFocal: (body['auto_focal'] as String?) ?? '',
          cropMode: (body['crop_mode'] as String?) ?? 'auto',
        );
        Navigator.of(context).pop(updated);
      } else {
        setState(() {
          _applying = false;
          _error = (body['error'] ?? widget.strings.saveFailed).toString();
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _applying = false;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.78,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    widget.strings.photoCandidatesTitle,
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                ),
                TextButton.icon(
                  onPressed: (_loading || _applying) ? null : () => _fetchCandidates(nextBatch: true),
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: Text(widget.strings.nextPhotoBatch),
                ),
                IconButton(
                  icon: const Icon(Icons.close_rounded),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
          ),
          if (_loading || _applying) const LinearProgressIndicator(minHeight: 2),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              child: Text(_error!, style: TextStyle(color: palette.danger, fontSize: 12.5)),
            ),
          Expanded(
            child: _candidates.isEmpty && !_loading
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        widget.strings.photoCandidatesEmpty,
                        textAlign: TextAlign.center,
                        style: TextStyle(color: palette.textMuted),
                      ),
                    ),
                  )
                : GridView.builder(
                    padding: const EdgeInsets.all(12),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 3,
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 0.75,
                    ),
                    itemCount: _candidates.length,
                    itemBuilder: (_, idx) {
                      final c = _candidates[idx];
                      final url = c.source == 'local_crop'
                          ? c.thumbUrl
                          : '/api/proxy-image?url=${Uri.encodeQueryComponent(c.thumbUrl)}';
                      return GestureDetector(
                        onTap: _applying ? null : () => _selectCandidate(c),
                        child: Container(
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: palette.stroke),
                          ),
                          clipBehavior: Clip.antiAlias,
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              OpenAverNetworkImage(
                                api: widget.api,
                                url: url,
                                fit: BoxFit.cover,
                              ),
                              Positioned(
                                left: 5,
                                bottom: 5,
                                child: Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: Color(0xA6000000),
                                    borderRadius: BorderRadius.circular(5),
                                  ),
                                  child: Text(
                                    c.source,
                                    style: const TextStyle(color: Colors.white, fontSize: 10),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
              child: SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _applying ? null : _uploadLocal,
                  icon: const Icon(Icons.upload_rounded),
                  label: Text(widget.strings.uploadLocalPhoto),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
