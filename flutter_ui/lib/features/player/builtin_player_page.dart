import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';
import '../../core/api_client.dart';
import '../../core/native_bridge.dart';

class BuiltInPlayerPage extends StatefulWidget {
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
  State<BuiltInPlayerPage> createState() => _BuiltInPlayerPageState();
}

class _BuiltInPlayerPageState extends State<BuiltInPlayerPage> {
  late final Player _player;
  late final VideoController _controller;
  late int _currentPart;
  double _rate = 1.0;
  bool _landscape = false;
  StreamSubscription<bool>? _completedSub;

  @override
  void initState() {
    super.initState();
    _currentPart = widget.initialPartIndex.clamp(
      0,
      widget.partPaths.isEmpty ? 0 : widget.partPaths.length - 1,
    );
    _player = Player();
    _controller = VideoController(_player);
    _loadCurrentPart();

    _completedSub = _player.stream.completed.listen((completed) {
      if (completed && _currentPart + 1 < widget.partPaths.length) {
        if (!mounted) return;
        setState(() => _currentPart += 1);
        _loadCurrentPart();
      }
    });
  }

  void _loadCurrentPart() {
    if (widget.partPaths.isEmpty) return;
    final rawPath = widget.partPaths[_currentPart];
    final streamUrl = widget.api.resolveUrl(
      '/api/gallery/video?path=${Uri.encodeQueryComponent(rawPath)}',
    );
    _player.open(
      Media(streamUrl, httpHeaders: widget.api.authHeaders),
      play: true,
    );
    if (_rate != 1.0) {
      _player.setRate(_rate);
    }
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
    _completedSub?.cancel();
    SystemChrome.setPreferredOrientations(const []);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  scrollDirection: Axis.horizontal,
                  itemCount: widget.partPaths.length,
                  separatorBuilder: (_, _) => const SizedBox(width: 8),
                  itemBuilder: (_, index) {
                    final active = index == _currentPart;
                    final label = index < widget.partTokens.length &&
                            widget.partTokens[index].isNotEmpty
                        ? widget.partTokens[index].toUpperCase()
                        : 'Part ${index + 1}';
                    return ChoiceChip(
                      label: Text(label),
                      selected: active,
                      onSelected: (_) {
                        setState(() => _currentPart = index);
                        _loadCurrentPart();
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
