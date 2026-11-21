import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_ui/core/models/insights_models.dart';
import 'package:flutter_ui/features/insights/insights_chart_cache.dart';

void main() {
  test('chart aggregation is reused by filter and scoped to a snapshot', () {
    final snapshot = InsightsSnapshot.fromJson({
      'records': [
        {
          'year': 2024,
          'maker': ' Studio ',
          'actresses': ['A'],
          'tags': ['Tag'],
        },
        {
          'year': 2024,
          'maker': 'Other',
          'actresses': ['A'],
        },
        {
          'year': 2023,
          'maker': 'Studio',
          'tags': ['Tag'],
        },
      ],
    });
    final cache = InsightsChartCache(snapshot);
    final all = cache.forFilters();
    final year = cache.forFilters(year: 2024);
    final maker = cache.forFilters(maker: 'Studio');
    final both = cache.forFilters(year: 2024, maker: 'Studio');

    expect(all.videoCount, 3);
    expect(all.yearSpan, '2023-2024');
    expect(all.yearCounts, {2023: 1, 2024: 2});
    expect(all.topMakers.first.key, 'Studio');
    expect(all.topMakers.first.value, 2);
    expect(year.videoCount, 2);
    expect(year.topActresses.single.value, 2);
    expect(maker.videoCount, 2);
    expect(maker.topTags.single.value, 2);
    expect(both.videoCount, 1);
    expect(cache.forFilters(), same(all));
    expect(cache.forFilters(year: 2024, maker: 'Studio'), same(both));

    final next = InsightsChartCache(InsightsSnapshot.fromJson({}));
    expect(next.forFilters(), isNot(same(all)));
    expect(next.forFilters().videoCount, 0);
  });

  test('chart aggregation cache evicts older filter combinations', () {
    final cache = InsightsChartCache(InsightsSnapshot.fromJson({}));
    final oldest = cache.forFilters();
    for (var year = 2000; year < 2008; year++) {
      cache.forFilters(year: year);
    }
    expect(cache.forFilters(), isNot(same(oldest)));
  });
}
