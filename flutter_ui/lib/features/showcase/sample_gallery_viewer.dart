import 'package:flutter/material.dart';
import '../../core/api_client.dart';
import '../shared/openaver_image.dart';

class SampleGalleryViewer extends StatefulWidget {
  const SampleGalleryViewer({
    super.key,
    required this.api,
    required this.imageUrls,
    this.initialIndex = 0,
    this.title = '',
  });

  final ApiClient api;
  final List<String> imageUrls;
  final int initialIndex;
  final String title;

  @override
  State<SampleGalleryViewer> createState() => _SampleGalleryViewerState();
}

class _SampleGalleryViewerState extends State<SampleGalleryViewer> {
  late final PageController _pageController;
  late int _index;

  @override
  void initState() {
    super.initState();
    _index = widget.initialIndex.clamp(
      0,
      widget.imageUrls.isEmpty ? 0 : widget.imageUrls.length - 1,
    );
    _pageController = PageController(initialPage: _index);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          PageView.builder(
            controller: _pageController,
            itemCount: widget.imageUrls.length,
            onPageChanged: (value) => setState(() => _index = value),
            itemBuilder: (_, idx) {
              return _ZoomableImage(
                api: widget.api,
                url: widget.imageUrls[idx],
              );
            },
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      '${_index + 1} / ${widget.imageUrls.length}',
                      style: const TextStyle(color: Colors.white, fontSize: 13),
                    ),
                  ),
                  const Spacer(),
                  IconButton.filled(
                    style: IconButton.styleFrom(
                      backgroundColor: Colors.black54,
                      foregroundColor: Colors.white,
                    ),
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ZoomableImage extends StatefulWidget {
  const _ZoomableImage({required this.api, required this.url});

  final ApiClient api;
  final String url;

  @override
  State<_ZoomableImage> createState() => _ZoomableImageState();
}

class _ZoomableImageState extends State<_ZoomableImage> {
  final TransformationController _transform = TransformationController();

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  void _toggleZoom() {
    if (_transform.value != Matrix4.identity()) {
      _transform.value = Matrix4.identity();
    } else {
      _transform.value = Matrix4.diagonal3Values(2.2, 2.2, 1.0);
    }
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onDoubleTap: _toggleZoom,
      child: InteractiveViewer(
        transformationController: _transform,
        minScale: 1.0,
        maxScale: 4.5,
        child: Center(
          child: OpenAverNetworkImage(
            api: widget.api,
            url: widget.url,
            fit: BoxFit.contain,
            fullResolution: true,
          ),
        ),
      ),
    );
  }
}
