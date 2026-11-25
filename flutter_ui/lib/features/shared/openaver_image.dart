import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import '../../core/api_client.dart';
import '../../core/app_theme.dart';

/// Cached network image widget with local auth header support and optional
/// sized decoding (`memCacheWidth`) for grid/list thumbnails.
class OpenAverNetworkImage extends StatelessWidget {
  const OpenAverNetworkImage({
    super.key,
    required this.api,
    required this.url,
    this.fit = BoxFit.cover,
    this.alignment = Alignment.center,
    this.width,
    this.height,
    this.fullResolution = false,
    this.targetDecodeWidth,
    this.errorIcon = Icons.broken_image_outlined,
  });

  final ApiClient api;
  final String url;
  final BoxFit fit;
  final Alignment alignment;
  final double? width;
  final double? height;
  final bool fullResolution;
  final int? targetDecodeWidth;
  final IconData errorIcon;

  static final _cacheKeys = Expando<Map<String, String>>();

  static Future<void> evictUrl(ApiClient api, String pathOrUrl) async {
    final resolved = api.resolveUrl(pathOrUrl);
    if (resolved.isEmpty) return;
    final keys = _cacheKeys[api] ??= {};
    final previous = keys[resolved] ?? resolved;
    // A new provider key refreshes all thumbnail decode sizes at the same URL.
    keys[resolved] = '$resolved#${DateTime.now().microsecondsSinceEpoch}';
    try {
      await CachedNetworkImage.evictFromCache(resolved, cacheKey: previous);
    } catch (error) {
      // The fresh provider key still bypasses the previous disk and memory entries.
      debugPrint('Image cache eviction failed: $error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final resolved = api.resolveUrl(url);
    if (resolved.isEmpty) {
      return Container(
        width: width,
        height: height,
        color: palette.surfaceHigh,
        child: Icon(errorIcon, color: palette.textMuted),
      );
    }

    int? memCacheWidth;
    if (!fullResolution) {
      if (targetDecodeWidth != null && targetDecodeWidth! > 0) {
        memCacheWidth = targetDecodeWidth;
      } else {
        final dpr = MediaQuery.maybeDevicePixelRatioOf(context) ?? 2.0;
        if (width != null && width!.isFinite && width! > 0) {
          memCacheWidth = (width! * dpr).round().clamp(160, 1200);
        } else {
          final screenW = MediaQuery.maybeSizeOf(context)?.width ?? 390.0;
          memCacheWidth = (screenW * dpr * 0.5).round().clamp(240, 1080);
        }
      }
    }

    final cacheKey = _cacheKeys[api]?[resolved];
    return CachedNetworkImage(
      key: ValueKey(cacheKey ?? resolved),
      cacheKey: cacheKey,
      imageUrl: resolved,
      httpHeaders: api.authHeaders,
      fit: fit,
      alignment: alignment,
      width: width,
      height: height,
      memCacheWidth: memCacheWidth,
      fadeInDuration: const Duration(milliseconds: 140),
      placeholder: (_, _) => Container(
        width: width,
        height: height,
        color: palette.surfaceHigh,
      ),
      errorWidget: (_, _, _) => Container(
        width: width,
        height: height,
        color: palette.surfaceHigh,
        child: Icon(errorIcon, color: palette.textMuted),
      ),
    );
  }
}
