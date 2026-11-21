import '../../core/models/insights_models.dart';

class InsightsChartCache {
  InsightsChartCache(this.snapshot);

  final InsightsSnapshot snapshot;
  static const _maxEntries = 8;
  final _aggregates = <(int?, String?), InsightsChartData>{};

  InsightsChartData forFilters({int? year, String? maker}) {
    final data = _aggregates.putIfAbsent((
      year,
      maker,
    ), () => InsightsChartData._aggregate(snapshot.records, year, maker));
    if (_aggregates.length > _maxEntries) {
      _aggregates.remove(_aggregates.keys.first);
    }
    return data;
  }
}

class InsightsChartData {
  InsightsChartData._({
    required this.videoCount,
    required this.yearCounts,
    required this.sortedYears,
    required this.yearSpan,
    required this.makerCount,
    required this.actressCount,
    required this.topMakers,
    required this.topActresses,
    required this.topTags,
  });

  final int videoCount;
  final Map<int, int> yearCounts;
  final List<int> sortedYears;
  final String yearSpan;
  final int makerCount;
  final int actressCount;
  final List<MapEntry<String, int>> topMakers;
  final List<MapEntry<String, int>> topActresses;
  final List<MapEntry<String, int>> topTags;

  factory InsightsChartData._aggregate(
    List<InsightsRecord> records,
    int? year,
    String? maker,
  ) {
    var videoCount = 0;
    final yearCounts = <int, int>{};
    final makerCounts = <String, int>{};
    final actressCounts = <String, int>{};
    final tagCounts = <String, int>{};

    for (final record in records) {
      final releaseYear = record.year;
      if (year != null && releaseYear != year) continue;
      final makerName = record.maker?.trim() ?? '';
      if (maker != null && makerName != maker) continue;

      videoCount++;
      if (releaseYear != null) {
        yearCounts[releaseYear] = (yearCounts[releaseYear] ?? 0) + 1;
      }
      if (makerName.isNotEmpty) {
        makerCounts[makerName] = (makerCounts[makerName] ?? 0) + 1;
      }
      for (final name in record.actresses) {
        actressCounts[name] = (actressCounts[name] ?? 0) + 1;
      }
      for (final tag in record.tags) {
        tagCounts[tag] = (tagCounts[tag] ?? 0) + 1;
      }
    }

    final sortedYears = yearCounts.keys.toList()..sort();
    final yearSpan = switch (sortedYears.length) {
      0 => '-',
      1 => '${sortedYears.first}',
      _ => '${sortedYears.first}-${sortedYears.last}',
    };
    List<MapEntry<String, int>> topEntries(Map<String, int> counts, int limit) {
      final sorted = counts.entries.toList()
        ..sort((a, b) => b.value.compareTo(a.value));
      return sorted.take(limit).toList();
    }

    return InsightsChartData._(
      videoCount: videoCount,
      yearCounts: yearCounts,
      sortedYears: sortedYears,
      yearSpan: yearSpan,
      makerCount: makerCounts.length,
      actressCount: actressCounts.length,
      topMakers: topEntries(makerCounts, 8),
      topActresses: topEntries(actressCounts, 25),
      topTags: topEntries(tagCounts, 24),
    );
  }
}
