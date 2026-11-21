import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/insights_models.dart';
import '../shared/openaver_image.dart';
import 'insights_chart_cache.dart';

class InsightsPage extends ConsumerStatefulWidget {
  const InsightsPage({super.key});

  @override
  ConsumerState<InsightsPage> createState() => _InsightsPageState();
}

class _InsightsPageState extends ConsumerState<InsightsPage> {
  bool _loading = true;
  String? _error;
  InsightsChartCache? _charts;
  int _loadGeneration = 0;

  int? _selectedYear;
  String? _selectedMaker;

  static const List<Color> _makerColors = [
    Color(0xFFFF8A4C),
    Color(0xFF60A5FA),
    Color(0xFF34D399),
    Color(0xFFA78BFA),
    Color(0xFFF472B6),
    Color(0xFFFBBF24),
    Color(0xFF2DD4BF),
    Color(0xFF94A3B8),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    if (!mounted) return;
    final generation = ++_loadGeneration;
    final strings = ref.read(stringsProvider);
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/insights/snapshot');
      if (!mounted || generation != _loadGeneration) return;
      if (resp['success'] != true) {
        setState(() {
          _loading = false;
          _error = (resp['error'] ?? strings.loadLibraryFailed).toString();
        });
        return;
      }
      final snapshot = InsightsSnapshot.fromJson(resp);
      setState(() {
        if (_selectedYear != null &&
            !snapshot.records.any((record) => record.year == _selectedYear)) {
          _selectedYear = null;
        }
        if (_selectedMaker != null &&
            !snapshot.records.any((record) => record.maker?.trim() == _selectedMaker)) {
          _selectedMaker = null;
        }
        _charts = InsightsChartCache(snapshot);
        _loading = false;
      });
    } catch (e) {
      if (!mounted || generation != _loadGeneration) return;
      debugPrint('Insights _load error: $e');
      setState(() {
        _loading = false;
        _error = strings.loadLibraryFailed;
      });
    }
  }

  Widget _buildRefreshBody(Widget child) {
    final strings = ref.watch(stringsProvider);
    final error = _error;
    return Column(
      children: [
        if (_loading) LinearProgressIndicator(semanticsLabel: strings.loading),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: Row(
              children: [
                Expanded(
                  child: Semantics(
                    liveRegion: true,
                    child: Text(
                      error,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: OpenAverPalette.of(context).danger),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                TextButton(onPressed: _load, child: Text(strings.retry)),
              ],
            ),
          ),
        Expanded(child: RefreshIndicator(onRefresh: _load, child: child)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final strings = ref.watch(stringsProvider);
    final api = ref.watch(apiClientProvider);

    ref.listen<int>(libraryRevisionProvider, (prev, next) {
      if (prev != next) {
        _load();
      }
    });

    final charts = _charts;
    if (charts == null) {
      final error = _error;
      if (error == null) {
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      }
      return Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(error, style: TextStyle(color: palette.danger)),
                const SizedBox(height: 12),
                FilledButton(onPressed: _load, child: Text(strings.retry)),
              ],
            ),
          ),
        ),
      );
    }

    final snap = charts.snapshot;
    if (snap.records.isEmpty) {
      return Scaffold(
        body: SafeArea(
          child: _buildRefreshBody(
            ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 96, horizontal: 24),
                  child: Column(
                    children: [
                      Icon(Icons.pie_chart_outline_rounded, size: 48, color: palette.textMuted),
                      const SizedBox(height: 12),
                      Text(strings.insightsEmpty, style: TextStyle(color: palette.textMuted)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final data = charts.forFilters(year: _selectedYear, maker: _selectedMaker);
    final sortedYears = data.sortedYears;
    final topMakers = data.topMakers;
    final topActresses = data.topActresses;
    final topTags = data.topTags;

    return Scaffold(
      body: SafeArea(
        child: _buildRefreshBody(
          ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 28),
            children: [
              GridView.count(
                crossAxisCount: 4,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 8,
                childAspectRatio: 1.25,
                children: [
                  _SummaryTile(label: strings.insightsVideos, value: '${data.videoCount}', palette: palette),
                  _SummaryTile(label: strings.insightsYears, value: data.yearSpan, palette: palette),
                  _SummaryTile(label: strings.insightsActresses, value: '${data.actressCount}', palette: palette),
                  _SummaryTile(label: strings.insightsMakers, value: '${data.makerCount}', palette: palette),
                ],
              ),

              if (_selectedYear != null || _selectedMaker != null) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  children: [
                    if (_selectedYear != null)
                      InputChip(
                        label: Text('${strings.insightsYears}: $_selectedYear'),
                        onDeleted: () => setState(() => _selectedYear = null),
                      ),
                    if (_selectedMaker != null)
                      InputChip(
                        label: Text('${strings.makerLabel}: $_selectedMaker'),
                        onDeleted: () => setState(() => _selectedMaker = null),
                      ),
                  ],
                ),
              ],

              if (sortedYears.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: strings.insightsYearDistribution,
                  palette: palette,
                  child: SizedBox(
                    height: 190,
                    child: BarChart(
                      BarChartData(
                        gridData: const FlGridData(show: false),
                        borderData: FlBorderData(show: false),
                        titlesData: FlTitlesData(
                          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          bottomTitles: AxisTitles(
                            sideTitles: SideTitles(
                              showTitles: true,
                              getTitlesWidget: (val, _) {
                                final idx = val.toInt();
                                if (idx < 0 || idx >= sortedYears.length) {
                                  return const SizedBox.shrink();
                                }
                                final step = (sortedYears.length / 6).ceil().clamp(1, 10);
                                if (idx % step != 0 && idx != sortedYears.length - 1) {
                                  return const SizedBox.shrink();
                                }
                                return Padding(
                                  padding: const EdgeInsets.only(top: 4),
                                  child: Text(
                                    '${sortedYears[idx] % 100}'.padLeft(2, '0'),
                                    style: TextStyle(fontSize: 10, color: palette.textMuted),
                                  ),
                                );
                              },
                            ),
                          ),
                        ),
                        barTouchData: BarTouchData(
                          touchCallback: (event, resp) {
                            if (event is FlTapUpEvent && resp?.spot != null) {
                              final idx = resp!.spot!.touchedBarGroupIndex;
                              if (idx >= 0 && idx < sortedYears.length) {
                                final year = sortedYears[idx];
                                setState(() {
                                  _selectedYear = _selectedYear == year ? null : year;
                                });
                              }
                            }
                          },
                        ),
                        barGroups: [
                          for (var i = 0; i < sortedYears.length; i++)
                            BarChartGroupData(
                              x: i,
                              barRods: [
                                BarChartRodData(
                                  toY: data.yearCounts[sortedYears[i]]!.toDouble(),
                                  width: sortedYears.length > 16 ? 8 : 14,
                                  borderRadius: BorderRadius.circular(4),
                                  color: _selectedYear == sortedYears[i]
                                      ? palette.blue
                                      : palette.accent,
                                ),
                              ],
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],

              if (topMakers.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: strings.insightsMakerTop,
                  palette: palette,
                  child: Row(
                    children: [
                      SizedBox(
                        width: 140,
                        height: 140,
                        child: PieChart(
                          PieChartData(
                            centerSpaceRadius: 34,
                            sectionsSpace: 2,
                            sections: [
                              for (var i = 0; i < topMakers.length; i++)
                                PieChartSectionData(
                                  value: topMakers[i].value.toDouble(),
                                  title: '',
                                  radius: _selectedMaker == topMakers[i].key ? 36 : 28,
                                  color: _makerColors[i % _makerColors.length],
                                ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            for (var i = 0; i < topMakers.length; i++)
                              InkWell(
                                onTap: () {
                                  final mk = topMakers[i].key;
                                  setState(() => _selectedMaker = _selectedMaker == mk ? null : mk);
                                },
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(vertical: 3),
                                  child: Row(
                                    children: [
                                      Container(
                                        width: 10,
                                        height: 10,
                                        decoration: BoxDecoration(
                                          color: _makerColors[i % _makerColors.length],
                                          shape: BoxShape.circle,
                                        ),
                                      ),
                                      const SizedBox(width: 6),
                                      Expanded(
                                        child: Text(
                                          topMakers[i].key,
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(fontSize: 12, color: palette.textPrimary),
                                        ),
                                      ),
                                      Text(
                                        '${topMakers[i].value}',
                                        style: TextStyle(fontSize: 11.5, color: palette.textMuted),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],

              if (topActresses.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: strings.insightsActressBoard,
                  palette: palette,
                  child: Column(
                    children: [
                      for (var i = 0; i < topActresses.length; i++)
                        Builder(
                          builder: (_) {
                            final name = topActresses[i].key;
                            final count = topActresses[i].value;
                            final fav = snap.actressFavorites[name];
                            return ListTile(
                              dense: true,
                              contentPadding: EdgeInsets.zero,
                              leading: CircleAvatar(
                                radius: 18,
                                backgroundColor: palette.surfaceHigh,
                                child: fav?.hasPhoto == true
                                    ? ClipOval(
                                        child: OpenAverNetworkImage(
                                          api: api,
                                          url: '/api/actresses/photo/${Uri.encodeComponent(fav!.photoName)}',
                                          width: 36,
                                          height: 36,
                                          targetDecodeWidth: 120,
                                          errorIcon: Icons.person_rounded,
                                        ),
                                      )
                                    : Text('${i + 1}', style: const TextStyle(fontSize: 11)),
                              ),
                              title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
                              subtitle: fav?.birth != null
                                  ? Text('${strings.birthLabel} ${fav!.birth}', style: const TextStyle(fontSize: 11))
                                  : null,
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  if (fav != null)
                                    Padding(
                                      padding: const EdgeInsets.only(right: 6),
                                      child: Icon(Icons.favorite_rounded, size: 15, color: palette.favoritePink),
                                    ),
                                  Text(
                                    strings.videosUnit(count),
                                    style: TextStyle(color: palette.accent, fontWeight: FontWeight.w700),
                                  ),
                                ],
                              ),
                              onTap: () {
                                ref.read(showcaseActressFilterProvider.notifier).setActress(name);
                                ref.read(activeTabProvider.notifier).setTab(0);
                              },
                            );
                          },
                        ),
                    ],
                  ),
                ),
              ],

              if (topTags.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: strings.insightsTagsTop(topTags.length),
                  palette: palette,
                  child: Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: topTags
                        .map(
                          (e) => ActionChip(
                            label: Text('${e.key} (${e.value})'),
                            onPressed: () {
                              ref.read(showcaseTagFilterProvider.notifier).setTag(e.key);
                              ref.read(activeTabProvider.notifier).setTab(0);
                            },
                          ),
                        )
                        .toList(),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _SummaryTile extends StatelessWidget {
  const _SummaryTile({
    required this.label,
    required this.value,
    required this.palette,
  });

  final String label;
  final String value;
  final OpenAverPalette palette;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: palette.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: palette.stroke),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              value,
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: palette.textPrimary),
            ),
          ),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: 11, color: palette.textMuted)),
        ],
      ),
    );
  }
}

class _ChartCard extends StatelessWidget {
  const _ChartCard({
    required this.title,
    required this.palette,
    required this.child,
  });

  final String title;
  final OpenAverPalette palette;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: palette.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: palette.stroke),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
            const SizedBox(height: 10),
            child,
          ],
        ),
      ),
    );
  }
}
