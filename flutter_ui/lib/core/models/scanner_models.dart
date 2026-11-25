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
