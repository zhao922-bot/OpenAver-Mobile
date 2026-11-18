class MissingCheckSummary {
  const MissingCheckSummary({
    required this.missingBoth,
    required this.missingNfo,
    required this.missingCover,
    required this.totalMissing,
    required this.untranslatedTitles,
    required this.missingSamples,
    required this.missingPlots,
    this.pendingTranslationBatchIds = const [],
  });

  final int missingBoth;
  final int missingNfo;
  final int missingCover;
  final int totalMissing;
  final int untranslatedTitles;
  final int missingSamples;
  final int missingPlots;
  final List<String> pendingTranslationBatchIds;

  factory MissingCheckSummary.fromJson(Map<String, dynamic> json) {
    final data = (json['data'] as Map<String, dynamic>?) ?? json;
    final rawBatches = (data['pending_plot_translations'] as List?) ?? const [];
    final batches = <String>[];
    for (final b in rawBatches) {
      if (b is Map && b['batch_id'] != null) {
        batches.add(b['batch_id'].toString());
      } else if (b is String && b.isNotEmpty) {
        batches.add(b);
      }
    }
    return MissingCheckSummary(
      missingBoth: (data['missing_both'] as num?)?.toInt() ?? 0,
      missingNfo: (data['missing_nfo'] as num?)?.toInt() ?? 0,
      missingCover: (data['missing_cover'] as num?)?.toInt() ?? 0,
      totalMissing: (data['total_missing'] as num?)?.toInt() ?? 0,
      untranslatedTitles: (data['untranslated_titles'] as num?)?.toInt() ?? 0,
      missingSamples: (data['missing_samples'] as num?)?.toInt() ?? 0,
      missingPlots: (data['missing_plots'] as num?)?.toInt() ?? 0,
      pendingTranslationBatchIds: batches,
    );
  }
}

class BrowseDirEntry {
  const BrowseDirEntry({
    required this.name,
    required this.path,
  });

  final String name;
  final String path;

  factory BrowseDirEntry.fromJson(Map<String, dynamic> json) {
    return BrowseDirEntry(
      name: (json['name'] as String?) ?? '',
      path: (json['path'] as String?) ?? '',
    );
  }
}

class BrowseDirResponse {
  const BrowseDirResponse({
    required this.currentPath,
    required this.parentPath,
    required this.entries,
    required this.files,
  });

  final String currentPath;
  final String? parentPath;
  final List<BrowseDirEntry> entries;
  final List<String> files;

  factory BrowseDirResponse.fromJson(Map<String, dynamic> json) {
    final rawEntries = (json['entries'] as List?) ?? const [];
    final rawFiles = (json['files'] as List?) ?? const [];
    return BrowseDirResponse(
      currentPath: (json['current_path'] as String?) ?? '',
      parentPath: json['parent_path'] as String?,
      entries: rawEntries
          .whereType<Map>()
          .map((e) => BrowseDirEntry.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
      files: rawFiles.map((e) => e.toString()).toList(),
    );
  }
}
