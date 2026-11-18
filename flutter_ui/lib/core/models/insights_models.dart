class InsightsRecord {
  const InsightsRecord({
    required this.year,
    required this.month,
    required this.date,
    required this.duration,
    required this.actresses,
    required this.maker,
    required this.director,
    required this.series,
    required this.tags,
  });

  final int? year;
  final String? month;
  final String? date;
  final int? duration;
  final List<String> actresses;
  final String? maker;
  final String? director;
  final String? series;
  final List<String> tags;

  factory InsightsRecord.fromJson(Map<String, dynamic> json) {
    List<String> listOf(dynamic v) =>
        v is List ? v.map((e) => e.toString()).where((e) => e.isNotEmpty).toList() : const [];
    return InsightsRecord(
      year: (json['year'] as num?)?.toInt(),
      month: json['month'] as String?,
      date: json['date'] as String?,
      duration: (json['duration'] as num?)?.toInt(),
      actresses: listOf(json['actresses']),
      maker: json['maker'] as String?,
      director: json['director'] as String?,
      series: json['series'] as String?,
      tags: listOf(json['tags']),
    );
  }
}

class ActressFavoriteInfo {
  const ActressFavoriteInfo({
    required this.birth,
    required this.photoName,
    required this.hasPhoto,
  });

  final String? birth;
  final String photoName;
  final bool hasPhoto;

  factory ActressFavoriteInfo.fromJson(Map<String, dynamic> json) {
    return ActressFavoriteInfo(
      birth: json['birth'] as String?,
      photoName: (json['photoName'] as String?) ?? '',
      hasPhoto: json['hasPhoto'] == true,
    );
  }
}

class InsightsSnapshot {
  const InsightsSnapshot({
    required this.logicalTitles,
    required this.physicalRows,
    required this.years,
    required this.records,
    required this.actressFavorites,
  });

  final int logicalTitles;
  final int physicalRows;
  final List<int> years;
  final List<InsightsRecord> records;
  final Map<String, ActressFavoriteInfo> actressFavorites;

  factory InsightsSnapshot.fromJson(Map<String, dynamic> json) {
    final rawRecords = (json['records'] as List?) ?? const [];
    final rawYears = (json['years'] as List?) ?? const [];
    final rawFavs = (json['actressFavorites'] as Map?) ?? const {};
    return InsightsSnapshot(
      logicalTitles: (json['logicalTitles'] as num?)?.toInt() ?? 0,
      physicalRows: (json['physicalRows'] as num?)?.toInt() ?? 0,
      years: rawYears.whereType<num>().map((e) => e.toInt()).toList(),
      records: rawRecords
          .whereType<Map>()
          .map((e) => InsightsRecord.fromJson(Map<String, dynamic>.from(e)))
          .toList(),
      actressFavorites: rawFavs.map(
        (key, value) => MapEntry(
          key.toString(),
          ActressFavoriteInfo.fromJson(
            value is Map ? Map<String, dynamic>.from(value) : const {},
          ),
        ),
      ),
    );
  }
}
