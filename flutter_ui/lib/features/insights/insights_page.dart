import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/models/insights_models.dart';

class InsightsPage extends ConsumerStatefulWidget {
  const InsightsPage({super.key});

  @override
  ConsumerState<InsightsPage> createState() => _InsightsPageState();
}

class _InsightsPageState extends ConsumerState<InsightsPage> {
  bool _loading = true;
  String? _error;
  InsightsSnapshot? _snapshot;

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
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await ref.read(apiClientProvider).getJson('/api/insights/snapshot');
      if (!mounted) return;
      if (resp['success'] != true) {
        setState(() {
          _loading = false;
          _error = (resp['error'] ?? '加载分析快照失败').toString();
        });
        return;
      }
      setState(() {
        _snapshot = InsightsSnapshot.fromJson(resp);
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final api = ref.watch(apiClientProvider);

    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, style: TextStyle(color: palette.danger)),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    final snap = _snapshot!;
    final filtered = snap.records.where((r) {
      if (_selectedYear != null && r.year != _selectedYear) return false;
      if (_selectedMaker != null && (r.maker ?? '') != _selectedMaker) return false;
      return true;
    }).toList();

    final yearCounts = <int, int>{};
    final makerCounts = <String, int>{};
    final actressCounts = <String, int>{};
    final tagCounts = <String, int>{};

    for (final r in filtered) {
      if (r.year != null) {
        yearCounts[r.year!] = (yearCounts[r.year!] ?? 0) + 1;
      }
      final mk = (r.maker ?? '').trim();
      if (mk.isNotEmpty) {
        makerCounts[mk] = (makerCounts[mk] ?? 0) + 1;
      }
      for (final a in r.actresses) {
        actressCounts[a] = (actressCounts[a] ?? 0) + 1;
      }
      for (final t in r.tags) {
        tagCounts[t] = (tagCounts[t] ?? 0) + 1;
      }
    }

    final sortedYears = yearCounts.keys.toList()..sort();
    final yearSpan = sortedYears.isEmpty
        ? '-'
        : (sortedYears.length == 1
            ? '${sortedYears.first}'
            : '${sortedYears.first}-${sortedYears.last}');

    final sortedMakers = makerCounts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final topMakers = sortedMakers.take(8).toList();
    final sortedActresses = actressCounts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final topActresses = sortedActresses.take(25).toList();
    final sortedTags = tagCounts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final topTags = sortedTags.take(24).toList();

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 28),
            children: [
              // 4-tile summary bar (mobile IA)
              GridView.count(
                crossAxisCount: 4,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisSpacing: 8,
                childAspectRatio: 1.25,
                children: [
                  _SummaryTile(label: '影片', value: '${filtered.length}', palette: palette),
                  _SummaryTile(label: '年份', value: yearSpan, palette: palette),
                  _SummaryTile(label: '女优', value: '${actressCounts.length}', palette: palette),
                  _SummaryTile(label: '片商', value: '${makerCounts.length}', palette: palette),
                ],
              ),

              if (_selectedYear != null || _selectedMaker != null) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  children: [
                    if (_selectedYear != null)
                      InputChip(
                        label: Text('年份: $_selectedYear'),
                        onDeleted: () => setState(() => _selectedYear = null),
                      ),
                    if (_selectedMaker != null)
                      InputChip(
                        label: Text('片商: $_selectedMaker'),
                        onDeleted: () => setState(() => _selectedMaker = null),
                      ),
                  ],
                ),
              ],

              // Year bar chart
              if (sortedYears.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: '发行年份分布',
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
                                  toY: yearCounts[sortedYears[i]]!.toDouble(),
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

              // Maker donut chart
              if (topMakers.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: '片商分布 Top 8',
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

              // Actress leaderboard
              if (topActresses.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: '女优作品榜 (点击跳转片库)',
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
                                backgroundImage: fav?.hasPhoto == true
                                    ? NetworkImage(
                                        api.resolveUrl('/api/actresses/photo/${Uri.encodeComponent(fav!.photoName)}'),
                                        headers: api.authHeaders,
                                      )
                                    : null,
                                child: fav?.hasPhoto == true
                                    ? null
                                    : Text('${i + 1}', style: const TextStyle(fontSize: 11)),
                              ),
                              title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
                              subtitle: fav?.birth != null ? Text('生日 ${fav!.birth}', style: const TextStyle(fontSize: 11)) : null,
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  if (fav != null)
                                    Padding(
                                      padding: const EdgeInsets.only(right: 6),
                                      child: Icon(Icons.favorite_rounded, size: 15, color: palette.favoritePink),
                                    ),
                                  Text('$count 部', style: TextStyle(color: palette.accent, fontWeight: FontWeight.w700)),
                                ],
                              ),
                              onTap: () {
                                ref.read(showcaseActressFilterProvider.notifier).state = name;
                                ref.read(activeTabProvider.notifier).state = 0;
                              },
                            );
                          },
                        ),
                    ],
                  ),
                ),
              ],

              // Tags cloud
              if (topTags.isNotEmpty) ...[
                const SizedBox(height: 14),
                _ChartCard(
                  title: '高频标签 Top ${topTags.length}',
                  palette: palette,
                  child: Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: topTags
                        .map((e) => Chip(label: Text('${e.key} (${e.value})')))
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
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: palette.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: palette.stroke),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: palette.textPrimary)),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}
