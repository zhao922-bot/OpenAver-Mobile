class SearchResultItem {
  const SearchResultItem({
    required this.number,
    required this.title,
    required this.originalTitle,
    required this.translatedTitle,
    required this.actors,
    required this.tags,
    required this.maker,
    required this.director,
    required this.series,
    required this.label,
    required this.date,
    required this.duration,
    required this.cover,
    required this.sampleImages,
    required this.source,
    required this.url,
    required this.raw,
  });

  final String number;
  final String title;
  final String originalTitle;
  final String translatedTitle;
  final List<String> actors;
  final List<String> tags;
  final String maker;
  final String director;
  final String series;
  final String label;
  final String date;
  final int? duration;
  final String cover;
  final List<String> sampleImages;
  final String source;
  final String url;
  final Map<String, dynamic> raw;

  factory SearchResultItem.fromJson(Map<String, dynamic> json) {
    List<String> parseList(dynamic v) {
      if (v is List) return v.map((e) => e.toString().trim()).where((e) => e.isNotEmpty).toList();
      if (v is String && v.trim().isNotEmpty) {
        return v.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
      }
      return const [];
    }

    String firstNonEmpty(List<dynamic> candidates) {
      for (final c in candidates) {
        if (c is String) {
          final trimmed = c.trim();
          if (trimmed.isNotEmpty) return trimmed;
        }
      }
      return '';
    }

    List<String> resolveSamples() {
      final rawSamples = json['sample_images'];
      final rawPreviews = json['preview_sample_images'];
      if (rawSamples is List) {
        final previewList = rawPreviews is List ? rawPreviews : const <dynamic>[];
        final resolved = <String>[];
        for (var i = 0; i < rawSamples.length; i++) {
          final preview = i < previewList.length ? previewList[i] : null;
          final url = firstNonEmpty([preview, rawSamples[i]]);
          if (url.isNotEmpty) resolved.add(url);
        }
        return resolved;
      }
      return parseList(rawSamples);
    }

    return SearchResultItem(
      number: (json['number'] as String?) ?? '',
      title: (json['title'] as String?) ?? '',
      originalTitle: (json['original_title'] as String?) ?? '',
      translatedTitle: (json['translated_title'] as String?) ?? '',
      actors: parseList(json['actors']),
      tags: parseList(json['tags']),
      maker: (json['maker'] as String?) ?? '',
      director: (json['director'] as String?) ?? '',
      series: (json['series'] as String?) ?? '',
      label: (json['label'] as String?) ?? '',
      date: (json['date'] as String?) ?? '',
      duration: (json['duration'] as num?)?.toInt(),
      cover: firstNonEmpty([json['preview_cover_url'], json['cover'], json['cover_url']]),
      sampleImages: resolveSamples(),
      source: (json['source'] as String?) ?? '',
      url: (json['url'] as String?) ?? '',
      raw: json,
    );
  }
}

class LocalStatusInfo {
  const LocalStatusInfo({
    required this.exists,
    required this.count,
    required this.primaryPath,
    required this.partPaths,
    required this.partTokens,
  });

  final bool exists;
  final int count;
  final String primaryPath;
  final List<String> partPaths;
  final List<String> partTokens;

  factory LocalStatusInfo.fromJson(Map<String, dynamic> json) {
    final playback = (json['playback'] as Map?)?.cast<String, dynamic>();
    final paths = (playback?['paths'] as List?)?.map((e) => e.toString()).toList() ??
        ((json['paths'] as List?)?.map((e) => e.toString()).toList() ?? const []);
    final tokens = (playback?['part_tokens'] as List?)?.map((e) => e.toString()).toList() ?? const [];
    return LocalStatusInfo(
      exists: json['exists'] == true,
      count: (json['count'] as num?)?.toInt() ?? paths.length,
      primaryPath: (playback?['path'] as String?) ?? (paths.isNotEmpty ? paths.first : ''),
      partPaths: paths,
      partTokens: tokens,
    );
  }
}

class FavoriteFileItem {
  const FavoriteFileItem({
    required this.path,
    required this.name,
    required this.number,
    required this.size,
  });

  final String path;
  final String name;
  final String number;
  final int size;

  factory FavoriteFileItem.fromJson(Map<String, dynamic> json) {
    return FavoriteFileItem(
      path: (json['path'] as String?) ?? '',
      name: (json['filename'] ?? json['name'] ?? '').toString(),
      number: (json['number'] as String?) ?? '',
      size: (json['size'] as num?)?.toInt() ?? 0,
    );
  }
}
