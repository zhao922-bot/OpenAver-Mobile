import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import '../../core/api_client.dart';
import '../../core/app_providers.dart';
import '../../core/native_bridge.dart';

class BuiltInPlayerPage extends ConsumerStatefulWidget {
  const BuiltInPlayerPage({
    super.key,
    required this.api,
    required this.title,
    required this.partPaths,
    this.partTokens = const [],
    this.initialPartIndex = 0,
  });

  final ApiClient api;
  final String title;
  final List<String> partPaths;
  final List<String> partTokens;
  final int initialPartIndex;

  @override
  ConsumerState<BuiltInPlayerPage> createState() => _BuiltInPlayerPageState();
}

class _BuiltInPlayerPageState extends ConsumerState<BuiltInPlayerPage> {
  late final Player _player;
  late final VideoController _controller;
  late final StreamSubscription<bool> _completedSub;
  late final StreamSubscription<String> _errorSub;
  late final AppLifecycleListener _lifecycleListener;
  late final Timer _saveTimer;
  late int _currentPart;
  double _rate = 1.0;
  bool _landscape = false;
  bool _playbackFailed = false;
  bool _acceptPlayerErrors = false;
  int _loadGeneration = 0;
  String? _loadedPath;
  Duration _lastSavedPosition = Duration.zero;
  Duration _resumeFloor = Duration.zero;

  @override
  void initState() {
    super.initState();
    _currentPart = widget.initialPartIndex.clamp(
      0,
      widget.partPaths.isEmpty ? 0 : widget.partPaths.length - 1,
    );
    _player = Player();
    _controller = VideoController(_player);
    _completedSub = _player.stream.completed.listen(_onCompleted);
    _errorSub = _player.stream.error.listen((_) {
      if (_acceptPlayerErrors) _showPlaybackFailure();
    });
    _lifecycleListener = AppLifecycleListener(onHide: _savePosition);
    _saveTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      _savePosition();
    });
    unawaited(_loadPart(_currentPart));
  }

  Future<void> _loadPart(int index) async {
    _savePosition();
    final generation = ++_loadGeneration;
    _loadedPath = null;
    _acceptPlayerErrors = false;
    setState(() {
      _currentPart = index;
      _playbackFailed = widget.partPaths.isEmpty;
    });
    if (widget.partPaths.isEmpty) return;

    final path = widget.partPaths[index];
    final savedPosition = await NativeBridge.instance.readPlaybackPosition(
      path,
    );
    if (!mounted || generation != _loadGeneration) return;

    final streamUrl = widget.api.resolveUrl(
      '/api/gallery/video?path=${Uri.encodeQueryComponent(path)}',
    );
    _acceptPlayerErrors = true;
    try {
      await _player.open(Media(streamUrl, httpHeaders: widget.api.authHeaders));
      if (!_ownsLoad(generation)) return;

      final restored =
          savedPosition == Duration.zero ||
          await _restorePosition(generation, savedPosition);
      if (!_ownsLoad(generation)) return;
      if (!restored) {
        debugPrint(
          'Could not restore bookmark at ${savedPosition.inMilliseconds}ms. '
          'Player is at ${_player.state.position.inMilliseconds}ms.',
        );
      }
      _loadedPath = path;
      _lastSavedPosition = savedPosition;
      _resumeFloor = restored ? Duration.zero : savedPosition;
      if (_rate != 1.0) await _player.setRate(_rate);
    } catch (_) {
      if (generation == _loadGeneration) _showPlaybackFailure();
    }
  }

  bool _ownsLoad(int generation) =>
      mounted && generation == _loadGeneration && !_playbackFailed;

  Future<bool> _restorePosition(int generation, Duration bookmark) async {
    final ready = await _waitForPlayerState(
      generation,
      const Duration(seconds: 6),
      (state) =>
          state.duration > Duration.zero && state.position > Duration.zero,
    );
    if (!ready) return false;
    // A previously saved position can outlast a shortened or replaced file.
    if (bookmark >= _player.state.duration) return true;

    // media_kit can accept a seek before the decoder can apply it.
    final earliest = bookmark - const Duration(milliseconds: 750);
    for (var attempt = 0; attempt < 2 && _ownsLoad(generation); attempt++) {
      await _player.seek(bookmark);
      if (await _waitForPlayerState(
        generation,
        const Duration(milliseconds: 1500),
        (state) => state.position >= earliest && state.position > Duration.zero,
      )) {
        return true;
      }
    }
    return false;
  }

  Future<bool> _waitForPlayerState(
    int generation,
    Duration timeout,
    bool Function(PlayerState) matches,
  ) async {
    final elapsed = Stopwatch()..start();
    while (_ownsLoad(generation)) {
      if (matches(_player.state)) return true;
      if (elapsed.elapsed >= timeout) break;
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    return false;
  }

  void _savePosition() {
    final path = _loadedPath;
    if (path == null || _player.state.completed || _playbackFailed) return;
    final position = _player.state.position;
    // Keep an unrestored bookmark until playback reaches it.
    if (position <= Duration.zero || position < _resumeFloor) return;
    _resumeFloor = Duration.zero;
    if (position == _lastSavedPosition) return;
    _lastSavedPosition = position;
    unawaited(NativeBridge.instance.savePlaybackPosition(path, position));
  }

  void _onCompleted(bool completed) {
    final path = _loadedPath;
    if (!mounted || !completed || path == null || _playbackFailed) return;
    _lastSavedPosition = Duration.zero;
    unawaited(NativeBridge.instance.savePlaybackPosition(path, Duration.zero));
    if (_currentPart + 1 < widget.partPaths.length) {
      unawaited(_loadPart(_currentPart + 1));
    }
  }

  void _showPlaybackFailure() {
    if (!mounted || _playbackFailed) return;
    _savePosition();
    setState(() => _playbackFailed = true);
  }

  Future<void> _toggleLandscape() async {
    _landscape = !_landscape;
    if (_landscape) {
      await SystemChrome.setPreferredOrientations([
        DeviceOrientation.landscapeLeft,
        DeviceOrientation.landscapeRight,
      ]);
      await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    } else {
      await SystemChrome.setPreferredOrientations([
        DeviceOrientation.portraitUp,
        DeviceOrientation.portraitDown,
        DeviceOrientation.landscapeLeft,
        DeviceOrientation.landscapeRight,
      ]);
      await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    }
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _savePosition();
    _saveTimer.cancel();
    _lifecycleListener.dispose();
    unawaited(_completedSub.cancel());
    unawaited(_errorSub.cancel());
    SystemChrome.setPreferredOrientations(const []);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final strings = ref.watch(stringsProvider);
    final isMultipart = widget.partPaths.length > 1;
    final controlsTheme = MaterialVideoControlsThemeData(
      displaySeekBar: true,
      volumeGesture: true,
      brightnessGesture: true,
      seekGesture: true,
      seekOnDoubleTap: true,
      speedUpOnLongPress: true,
      padding: EdgeInsets.only(bottom: _landscape ? 8.0 : 24.0),
      bottomButtonBarMargin: EdgeInsets.only(
        left: 16.0,
        right: 8.0,
        bottom: _landscape ? 8.0 : 12.0,
      ),
      seekBarMargin: EdgeInsets.only(
        left: 16.0,
        right: 16.0,
        bottom: _landscape ? 48.0 : 54.0,
      ),
      seekBarContainerHeight: 36.0,
    );

    return Scaffold(
      backgroundColor: Colors.black,
      appBar: _landscape
          ? null
          : AppBar(
              backgroundColor: Colors.black,
              foregroundColor: Colors.white,
              title: Text(
                widget.title.isEmpty ? 'OpenAver Player' : widget.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 15),
              ),
              actions: [
                PopupMenuButton<double>(
                  initialValue: _rate,
                  icon: Text(
                    '${_rate}x',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                  onSelected: (value) {
                    setState(() => _rate = value);
                    _player.setRate(value);
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 0.75, child: Text('0.75x')),
                    PopupMenuItem(value: 1.0, child: Text('1.0x')),
                    PopupMenuItem(value: 1.25, child: Text('1.25x')),
                    PopupMenuItem(value: 1.5, child: Text('1.5x')),
                    PopupMenuItem(value: 2.0, child: Text('2.0x')),
                  ],
                ),
                IconButton(
                  icon: const Icon(Icons.screen_rotation_rounded),
                  onPressed: _toggleLandscape,
                ),
                IconButton(
                  icon: const Icon(Icons.open_in_new_rounded),
                  onPressed: () {
                    if (widget.partPaths.isNotEmpty) {
                      _player.pause();
                      NativeBridge.instance.openExternalPlayer(
                        path: widget.partPaths[_currentPart],
                      );
                    }
                  },
                ),
              ],
            ),
      body: SafeArea(
        top: _landscape,
        bottom: true,
        child: Column(
          children: [
            Expanded(
              child: Stack(
                children: [
                  Center(
                    child: MaterialVideoControlsTheme(
                      normal: controlsTheme,
                      fullscreen: controlsTheme,
                      child: Video(controller: _controller),
                    ),
                  ),
                  if (_playbackFailed)
                    Center(
                      child: Card(
                        color: Colors.grey.shade900,
                        margin: const EdgeInsets.all(24),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                strings.playbackFailed,
                                textAlign: TextAlign.center,
                                style: const TextStyle(color: Colors.white),
                              ),
                              if (widget.partPaths.isNotEmpty) ...[
                                const SizedBox(height: 8),
                                FilledButton.icon(
                                  onPressed: () => _loadPart(_currentPart),
                                  icon: const Icon(Icons.refresh_rounded),
                                  label: Text(strings.retry),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                  if (_landscape)
                    Positioned(
                      top: 8,
                      right: 12,
                      child: IconButton.filled(
                        style: IconButton.styleFrom(
                          backgroundColor: Colors.black54,
                          foregroundColor: Colors.white,
                        ),
                        icon: const Icon(Icons.fullscreen_exit_rounded),
                        onPressed: _toggleLandscape,
                      ),
                    ),
                ],
              ),
            ),
            if (isMultipart)
              SizedBox(
                height: 54,
                child: ListView.separated(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 8,
                  ),
                  scrollDirection: Axis.horizontal,
                  itemCount: widget.partPaths.length,
                  separatorBuilder: (_, _) => const SizedBox(width: 8),
                  itemBuilder: (_, index) {
                    final active = index == _currentPart;
                    final label =
                        index < widget.partTokens.length &&
                            widget.partTokens[index].isNotEmpty
                        ? widget.partTokens[index].toUpperCase()
                        : 'Part ${index + 1}';
                    return ChoiceChip(
                      label: Text(label),
                      selected: active,
                      onSelected: (selected) {
                        if (selected) unawaited(_loadPart(index));
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
}
