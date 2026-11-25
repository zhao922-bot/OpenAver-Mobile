import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/search_models.dart';
import '../../core/models/video_item.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';
import '../shared/openaver_image.dart';
import '../showcase/sample_gallery_viewer.dart';
import '../showcase/video_detail_sheet.dart';

class SearchResultDetailPage extends ConsumerStatefulWidget {
  const SearchResultDetailPage({
    super.key,
    required this.results,
    required this.initialIndex,
    required this.localStatus,
    required this.wishlistedNumbers,
    required this.onToggleWishlist,
    required this.onSearchActor,
  });

  final List<SearchResultItem> results;
  final int initialIndex;
  final Map<String, LocalStatusInfo> localStatus;
  final Set<String> wishlistedNumbers;
  final Future<bool?> Function(SearchResultItem item) onToggleWishlist;
  final ValueChanged<String> onSearchActor;

  @override
  ConsumerState<SearchResultDetailPage> createState() => _SearchResultDetailPageState();
}

class _SearchResultDetailPageState extends ConsumerState<SearchResultDetailPage> {
  late final PageController _pageController;
  late int _index;
  late Set<String> _wishlisted;
  final Map<String, String> _translatedTitles = {};
  bool _translating = false;

  @override
  void initState() {
    super.initState();
    _index = widget.initialIndex.clamp(
      0,
      widget.results.isEmpty ? 0 : widget.results.length - 1,
    );
    _pageController = PageController(initialPage: _index);
    _wishlisted = Set<String>.from(widget.wishlistedNumbers);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  Future<void> _toggleBookmark(SearchResultItem item) async {
    final nextState = await widget.onToggleWishlist(item);
    if (nextState == null || !mounted) return;
    final key = item.number.toUpperCase();
    setState(() {
      if (nextState) {
        _wishlisted.add(key);
      } else {
        _wishlisted.remove(key);
      }
    });
  }

  Future<void> _translateTitle(SearchResultItem item) async {
    final strings = ref.read(stringsProvider);
    final api = ref.read(apiClientProvider);
    setState(() => _translating = true);
    try {
      final resp = await api.postJson('/api/translate', data: {
        'text': item.title,
        'mode': 'translate',
        'actors': item.actors,
        'number': item.number,
        'force': true,
      });
      if (!mounted) return;
      final res = (resp['result'] as String?) ?? '';
      if (resp['success'] == true && res.isNotEmpty) {
        setState(() => _translatedTitles[item.number] = res);
      } else if (resp['skipped'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(strings.alreadyTargetLanguage)),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text((resp['error'] ?? strings.translateFailed).toString())),
        );
      }
    } catch (e) {
      debugPrint('search detail translateTitle error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(strings.requestFailed('$e'))),
        );
      }
    } finally {
      if (mounted) setState(() => _translating = false);
    }
  }

  Future<void> _openInLibrary(ApiClient api, LocalStatusInfo local) async {
    final strings = ref.read(stringsProvider);
    try {
      final resp = await api.getJson(
        '/api/showcase/video',
        queryParameters: {'path': local.primaryPath},
      );
      if (!mounted) return;
      if (resp['success'] == true && resp['video'] is Map) {
        final video = VideoItem.fromJson(Map<String, dynamic>.from(resp['video'] as Map));
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => VideoDetailPage(
              videos: [video],
              initialIndex: 0,
              onVideoUpdated: (_) {
                if (mounted) ref.read(libraryRevisionProvider.notifier).bump();
              },
              onVideoDeleted: (_) {},
              onSelectActress: (name) {
                Navigator.of(context).pop();
                widget.onSearchActor(name);
              },
            ),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(strings.videoNotInLibrary)),
        );
      }
    } catch (e) {
      debugPrint('openInLibrary error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(strings.requestFailed('$e'))),
        );
      }
    }
  }

  String _proxyImage(String raw) {
    if (raw.isEmpty) return '';
    if (raw.startsWith('/api/')) return raw;
    return '/api/proxy-image?url=${Uri.encodeQueryComponent(raw)}';
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiClientProvider);
    final strings = ref.watch(stringsProvider);
    final palette = OpenAverPalette.of(context);

    if (widget.results.isEmpty) {
      return Scaffold(appBar: AppBar(), body: const SizedBox.shrink());
    }

    return Scaffold(
      backgroundColor: palette.canvas,
      appBar: AppBar(
        title: Text(
          strings.searchResultDetailTitle(_index + 1, widget.results.length),
          style: const TextStyle(fontSize: 16),
        ),
      ),
      body: PageView.builder(
        controller: _pageController,
        itemCount: widget.results.length,
        onPageChanged: (idx) => setState(() => _index = idx),
        itemBuilder: (_, idx) {
          final item = widget.results[idx];
          final local = widget.localStatus[item.number.toUpperCase()];
          final saved = _wishlisted.contains(item.number.toUpperCase());
          final translated = _translatedTitles[item.number] ?? item.translatedTitle;
          final coverUrl = _proxyImage(item.cover);
          final sampleProxies = item.sampleImages.map(_proxyImage).where((u) => u.isNotEmpty).toList();
          final gallery = [if (coverUrl.isNotEmpty) coverUrl, ...sampleProxies];

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              GestureDetector(
                onTap: gallery.isEmpty
                    ? null
                    : () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => SampleGalleryViewer(
                              api: api,
                              imageUrls: gallery,
                              initialIndex: 0,
                              title: item.title,
                            ),
                          ),
                        ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(14),
                  child: AspectRatio(
                    aspectRatio: 16 / 10,
                    child: OpenAverNetworkImage(
                      api: api,
                      url: coverUrl,
                      errorIcon: Icons.movie_outlined,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  if (item.number.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: palette.accent.withValues(alpha: 0.16),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        item.number,
                        style: TextStyle(fontWeight: FontWeight.w700, color: palette.accent),
                      ),
                    ),
                  if (item.source.isNotEmpty) ...[
                    const SizedBox(width: 8),
                    Chip(label: Text(item.source)),
                  ],
                  const Spacer(),
                  if (local?.exists == true)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: palette.success.withValues(alpha: 0.16),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        strings.inLibraryBadge,
                        style: TextStyle(color: palette.success, fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              SelectableText(
                translated.isNotEmpty ? translated : item.title,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: palette.textPrimary,
                  height: 1.35,
                ),
              ),
              if (translated.isNotEmpty && translated != item.title) ...[
                const SizedBox(height: 4),
                Text(item.title, style: TextStyle(fontSize: 12.5, color: palette.textMuted)),
              ],
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (local?.exists == true) ...[
                    FilledButton.icon(
                      onPressed: () {
                        Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => BuiltInPlayerPage(
                              api: api,
                              title: item.title,
                              partPaths: local!.partPaths,
                              partTokens: local.partTokens,
                            ),
                          ),
                        );
                      },
                      icon: const Icon(Icons.play_arrow_rounded),
                      label: Text(strings.builtinPlayer),
                    ),
                    OutlinedButton.icon(
                      onPressed: () {
                        String? partsJson;
                        if (local!.partPaths.length > 1) {
                          partsJson = jsonEncode([
                            for (var i = 0; i < local.partPaths.length; i++)
                              {
                                'path': local.partPaths[i],
                                'label': i < local.partTokens.length ? local.partTokens[i] : 'Part ${i + 1}',
                              },
                          ]);
                        }
                        NativeBridge.instance.openExternalPlayer(
                          path: local.primaryPath,
                          partsJson: partsJson,
                        );
                      },
                      icon: const Icon(Icons.open_in_new_rounded, size: 18),
                      label: Text(strings.externalPlayer),
                    ),
                    FilledButton.tonalIcon(
                      onPressed: () => _openInLibrary(api, local!),
                      icon: const Icon(Icons.library_books_outlined, size: 18),
                      label: Text(strings.viewInLibrary),
                    ),
                  ] else
                    FilledButton.icon(
                      onPressed: () => _toggleBookmark(item),
                      icon: Icon(saved ? Icons.bookmark_rounded : Icons.bookmark_add_outlined),
                      label: Text(saved ? strings.wishlisted : strings.addWishlist),
                    ),
                  ActionChip(
                    avatar: _translating
                        ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.translate_rounded, size: 16),
                    label: Text(strings.translateAi),
                    onPressed: _translating ? null : () => _translateTitle(item),
                  ),
                  if (item.url.isNotEmpty)
                    ActionChip(
                      avatar: const Icon(Icons.public_rounded, size: 16),
                      label: Text(strings.openOriginalUrl),
                      onPressed: () => NativeBridge.instance.openExternalUrl(item.url),
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
                    if (item.date.isNotEmpty) _InfoPair(label: strings.releaseLabel, value: item.date),
                    if (item.duration != null) _InfoPair(label: strings.durationLabel, value: '${item.duration} min'),
                    if (item.maker.isNotEmpty) _InfoPair(label: strings.makerLabel, value: item.maker),
                    if (item.director.isNotEmpty) _InfoPair(label: strings.directorLabel, value: item.director),
                    if (item.series.isNotEmpty) _InfoPair(label: strings.seriesLabel, value: item.series),
                    if (item.label.isNotEmpty) _InfoPair(label: strings.labelLabel, value: item.label),
                  ],
                ),
              ),
              if (item.actors.isNotEmpty) ...[
                const SizedBox(height: 14),
                Text(strings.actresses, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: item.actors
                      .map(
                        (actor) => ActionChip(
                          avatar: const Icon(Icons.person_rounded, size: 15),
                          label: Text(actor),
                          onPressed: () {
                            Navigator.of(context).pop();
                            widget.onSearchActor(actor);
                          },
                        ),
                      )
                      .toList(),
                ),
              ],
              if (item.tags.isNotEmpty) ...[
                const SizedBox(height: 14),
                Text(strings.tagsLabel, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: item.tags.map((t) => Chip(label: Text(t))).toList(),
                ),
              ],
              if (sampleProxies.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(
                  '${strings.sampleImages} (${sampleProxies.length})',
                  style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  height: 120,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: sampleProxies.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 8),
                    itemBuilder: (_, sIdx) {
                      return GestureDetector(
                        onTap: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => SampleGalleryViewer(
                              api: api,
                              imageUrls: sampleProxies,
                              initialIndex: sIdx,
                              title: item.title,
                            ),
                          ),
                        ),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(10),
                          child: AspectRatio(
                            aspectRatio: 16 / 10,
                            child: OpenAverNetworkImage(
                              api: api,
                              url: sampleProxies[sIdx],
                              targetDecodeWidth: 420,
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _InfoPair extends StatelessWidget {
  const _InfoPair({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    return RichText(
      text: TextSpan(
        style: TextStyle(fontSize: 12, color: palette.textSecondary),
        children: [
          TextSpan(text: '$label: ', style: TextStyle(color: palette.textMuted)),
          TextSpan(text: value, style: TextStyle(color: palette.textPrimary, fontWeight: FontWeight.w500)),
        ],
      ),
    );
  }
}
