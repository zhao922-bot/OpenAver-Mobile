import 'package:flutter/painting.dart';

class VideoItem {
  const VideoItem({
    required this.path,
    required this.title,
    required this.originalTitle,
    required this.actresses,
    required this.number,
    required this.maker,
    required this.releaseDate,
    required this.tags,
    required this.size,
    required this.coverUrl,
    required this.coverFullUrl,
    required this.mtime,
    required this.director,
    required this.duration,
    required this.series,
    required this.label,
    required this.sampleImages,
    required this.userTags,
    required this.userRating,
    required this.hasCover,
    required this.hasNfo,
    required this.needsTranslate,
    required this.canTranslate,
    required this.autoFocal,
    required this.cropMode,
    required this.partTokens,
    required this.partPaths,
  });

  final String path;
  final String title;
  final String originalTitle;
  final List<String> actresses;
  final String number;
  final String maker;
  final String releaseDate;
  final List<String> tags;
  final int size;
  final String coverUrl;
  final String coverFullUrl;
  final int mtime;
  final String director;
  final int? duration;
  final String series;
  final String label;
  final List<String> sampleImages;
  final List<String> userTags;
  final int userRating;
  final bool hasCover;
  final bool hasNfo;
  final bool needsTranslate;
  final bool canTranslate;
  final String autoFocal;
  final String cropMode;
  final List<String> partTokens;
  final List<String> partPaths;

  bool get isFavorite => userRating > 0;
  bool get isMultipart => partPaths.length > 1;

  Alignment get focalAlignment {
    if (cropMode == 'default' || autoFocal.isEmpty) {
      return Alignment.centerRight;
    }
    final parts = autoFocal.split(',');
    if (parts.length != 2) return Alignment.centerRight;
    final x = double.tryParse(parts[0].trim());
    final y = double.tryParse(parts[1].trim());
    if (x == null || y == null) return Alignment.centerRight;
    return Alignment(
      (x.clamp(0.0, 1.0) * 2.0) - 1.0,
      (y.clamp(0.0, 1.0) * 2.0) - 1.0,
    );
  }

  String get formattedSize {
    if (size <= 0) return '';
    const gb = 1024 * 1024 * 1024;
    if (size >= gb) {
      return '${(size / gb).toStringAsFixed(2)} GB';
    }
    return '${(size / (1024 * 1024)).toStringAsFixed(0)} MB';
  }

  VideoItem copyWith({
    String? title,
    String? originalTitle,
    List<String>? userTags,
    int? userRating,
    bool? hasNfo,
    bool? needsTranslate,
    bool? canTranslate,
    String? autoFocal,
    String? cropMode,
  }) {
    return VideoItem(
      path: path,
      title: title ?? this.title,
      originalTitle: originalTitle ?? this.originalTitle,
      actresses: actresses,
      number: number,
      maker: maker,
      releaseDate: releaseDate,
      tags: tags,
      size: size,
      coverUrl: coverUrl,
      coverFullUrl: coverFullUrl,
      mtime: mtime,
      director: director,
      duration: duration,
      series: series,
      label: label,
      sampleImages: sampleImages,
      userTags: userTags ?? this.userTags,
      userRating: userRating ?? this.userRating,
      hasCover: hasCover,
      hasNfo: hasNfo ?? this.hasNfo,
      needsTranslate: needsTranslate ?? this.needsTranslate,
      canTranslate: canTranslate ?? this.canTranslate,
      autoFocal: autoFocal ?? this.autoFocal,
      cropMode: cropMode ?? this.cropMode,
      partTokens: partTokens,
      partPaths: partPaths,
    );
  }

  factory VideoItem.fromJson(Map<String, dynamic> json) {
    List<String> splitCsv(dynamic raw) {
      if (raw is List) {
        return raw.map((e) => e.toString().trim()).where((e) => e.isNotEmpty).toList();
      }
      final text = (raw ?? '').toString();
      if (text.trim().isEmpty) return const [];
      return text.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
    }

    List<String> stringList(dynamic raw) {
      if (raw is! List) return const [];
      return raw.map((e) => e.toString()).where((e) => e.isNotEmpty).toList();
    }

    return VideoItem(
      path: (json['path'] as String?) ?? '',
      title: (json['title'] as String?) ?? '',
      originalTitle: (json['original_title'] as String?) ?? '',
      actresses: splitCsv(json['actresses']),
      number: (json['number'] as String?) ?? '',
      maker: (json['maker'] as String?) ?? '',
      releaseDate: (json['release_date'] as String?) ?? '',
      tags: splitCsv(json['tags']),
      size: (json['size'] as num?)?.toInt() ?? 0,
      coverUrl: (json['cover_url'] as String?) ?? '',
      coverFullUrl: (json['cover_full_url'] as String?) ?? '',
      mtime: (json['mtime'] as num?)?.toInt() ?? 0,
      director: (json['director'] as String?) ?? '',
      duration: (json['duration'] as num?)?.toInt(),
      series: (json['series'] as String?) ?? '',
      label: (json['label'] as String?) ?? '',
      sampleImages: stringList(json['sample_images']),
      userTags: stringList(json['user_tags']),
      userRating: (json['user_rating'] as num?)?.toInt() ?? 0,
      hasCover: json['has_cover'] == true,
      hasNfo: json['has_nfo'] == true,
      needsTranslate: json['needs_translate'] == true,
      canTranslate: json['can_translate'] == true,
      autoFocal: (json['auto_focal'] as String?) ?? '',
      cropMode: (json['crop_mode'] as String?) ?? 'auto',
      partTokens: stringList(json['part_tokens']),
      partPaths: stringList(json['part_paths']),
    );
  }
}

class VideosPageResponse {
  const VideosPageResponse({
    required this.videos,
    required this.total,
    required this.page,
    required this.perPage,
    required this.totalPages,
    required this.paged,
  });

  final List<VideoItem> videos;
  final int total;
  final int page;
  final int perPage;
  final int totalPages;
  final bool paged;

  factory VideosPageResponse.fromJson(Map<String, dynamic> json) {
    final rawList = (json['videos'] as List?) ?? const [];
    return VideosPageResponse(
      videos: rawList
          .whereType<Map>()
          .map((e) => VideoItem.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
      total: (json['total'] as num?)?.toInt() ?? rawList.length,
      page: (json['page'] as num?)?.toInt() ?? 1,
      perPage: (json['per_page'] as num?)?.toInt() ?? 0,
      totalPages: (json['total_pages'] as num?)?.toInt() ?? 1,
      paged: json['paged'] == true,
    );
  }
}

class LibraryActressGroup {
  const LibraryActressGroup({
    required this.primaryName,
    required this.aliases,
    required this.videoCount,
    required this.isFavorite,
    required this.photoUrl,
  });

  final String primaryName;
  final List<String> aliases;
  final int videoCount;
  final bool isFavorite;
  final String photoUrl;

  factory LibraryActressGroup.fromJson(Map<String, dynamic> json) {
    final name = (json['primary_name'] as String?) ??
        (json['name'] as String?) ??
        '';
    final rawAliases = (json['aliases'] as List?) ?? (json['names'] as List?) ?? const [];
    final aliases = rawAliases
        .map((e) => e.toString().trim())
        .where((e) => e.isNotEmpty && e != name)
        .toList();
    return LibraryActressGroup(
      primaryName: name,
      aliases: aliases,
      videoCount: (json['video_count'] as num?)?.toInt() ?? 0,
      isFavorite: json['is_favorite'] == true,
      photoUrl: (json['photo_url'] as String?) ?? '',
    );
  }
}
