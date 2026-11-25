import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/models/video_item.dart';
import '../../core/native_bridge.dart';
import '../player/builtin_player_page.dart';

typedef _ResumeTarget = ({LatestPlayback entry, VideoItem video, int index});

class ContinueWatchingTile extends ConsumerStatefulWidget {
  const ContinueWatchingTile({super.key, required this.api});

  final ApiClient api;

  @override
  ConsumerState<ContinueWatchingTile> createState() =>
      _ContinueWatchingTileState();
}

class _ContinueWatchingTileState extends ConsumerState<ContinueWatchingTile> {
  late Future<_ResumeTarget?> _target = _resolve();
  bool _busy = false;

  Future<_ResumeTarget?> _resolve() async {
    final entry = await NativeBridge.instance.readLatestPlayback();
    if (!mounted || entry == null) return null;
    // Only the current library can supply the playlist. Never fall back to a
    // title match or play paths solely because they were saved locally.
    final result = await widget.api.getJson(
      '/api/showcase/video/lookup',
      queryParameters: {'path': entry.path},
    );
    final raw = result['video'];
    if (result['success'] != true || raw is! Map<String, dynamic>) return null;
    final video = VideoItem.fromJson(raw);
    final index = video.isMultipart
        ? video.partPaths.indexOf(entry.path)
        : (video.path == entry.path ? 0 : -1);
    return index < 0 ? null : (entry: entry, video: video, index: index);
  }

  String _title(_ResumeTarget target) {
    if (target.video.title.isNotEmpty) return target.video.title;
    if (target.entry.title.isNotEmpty) return target.entry.title;
    if (target.video.number.isNotEmpty) return target.video.number;
    return Uri.tryParse(target.entry.path)?.pathSegments.lastOrNull ?? '';
  }

  Future<void> _open(_ResumeTarget shown) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final fresh = await _resolve();
      if (!mounted ||
          ModalRoute.isCurrentOf(context) != true ||
          ref.read(activeTabProvider) != 0) {
        return;
      }
      if (fresh == null ||
          fresh.entry.revision != shown.entry.revision ||
          fresh.entry.path != shown.entry.path) {
        _target = Future.value(fresh);
        return;
      }
      final video = fresh.video;
      final player = BuiltInPlayerPage(
        api: widget.api,
        title: _title(fresh),
        partPaths: video.isMultipart ? video.partPaths : [video.path],
        partTokens: video.partTokens,
        initialPartIndex: fresh.index,
      );
      final route = MaterialPageRoute<void>(builder: (_) => player);
      await Navigator.of(context).push(route);
      if (mounted) _target = _resolve();
    } catch (_) {
      if (mounted) {
        _target = Future.value(null);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(ref.read(stringsProvider).loadLibraryFailed)),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(LatestPlayback entry) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await NativeBridge.instance.removeLatestPlayback(entry);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(ref.read(stringsProvider).saveFailed)),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _target = _resolve();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final strings = ref.watch(stringsProvider);
    return FutureBuilder<_ResumeTarget?>(
      future: _target,
      builder: (context, snapshot) {
        final target = snapshot.data;
        if (snapshot.connectionState != ConnectionState.done ||
            target == null) {
          return const SizedBox.shrink();
        }
        final tokens = target.video.partTokens;
        final label =
            target.index < tokens.length && tokens[target.index].isNotEmpty
            ? tokens[target.index]
            : target.entry.partLabel;
        final partIndex = target.video.isMultipart
            ? target.index
            : target.entry.partIndex;
        final part = label.isEmpty
            ? strings.playbackPart(partIndex + 1)
            : label.toUpperCase();
        final position = target.entry.position;
        final seconds = (position.inSeconds % 60).toString().padLeft(2, '0');
        final minutes = position.inMinutes;
        final time = minutes < 60
            ? '$minutes:$seconds'
            : '${position.inHours}:${(minutes % 60).toString().padLeft(2, '0')}:$seconds';
        return ListTile(
          leading: const Icon(Icons.play_circle_outline_rounded),
          title: Text(strings.continueWatching),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _title(target),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              Text(
                '$part · $time',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
          trailing: IconButton(
            tooltip: strings.removeContinueWatching,
            icon: const Icon(Icons.close_rounded),
            onPressed: _busy ? null : () => _remove(target.entry),
          ),
          onTap: _busy ? null : () => _open(target),
        );
      },
    );
  }
}
