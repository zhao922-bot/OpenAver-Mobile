import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/l10n.dart';

const metadataBackfillPath = '/api/gallery/backfill-elements';

enum MetadataField {
  cover,
  plot,
  samples,
  tags;

  String label(AppStrings strings) => switch (this) {
    cover => strings.coverLabel,
    plot => strings.plot,
    samples => strings.sampleImages,
    tags => strings.tagsLabel,
  };
}

typedef SourceSelection = Map<MetadataField, ({String id, String label})>;

class MetadataSourceSheet extends StatefulWidget {
  const MetadataSourceSheet({
    super.key,
    required this.api,
    required this.strings,
    this.videoLabel,
  });

  final ApiClient api;
  final AppStrings strings;
  final String? videoLabel;

  @override
  State<MetadataSourceSheet> createState() => _MetadataSourceSheetState();
}

class _MetadataSourceSheetState extends State<MetadataSourceSheet> {
  final _selected = SourceSelection();
  Map<MetadataField, Map<String, String>>? _options;
  String? _error;
  bool _submitted = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final response = await widget.api.getJson(
        '$metadataBackfillPath/sources',
      );
      final sources = response['sources'];
      if (response['success'] != true || sources is! Map) {
        throw FormatException(
          response['error']?.toString() ?? widget.strings.invalidSourceList,
        );
      }
      final options = <MetadataField, Map<String, String>>{};
      for (final field in MetadataField.values) {
        final rows = sources[field.name];
        if (rows is! List) {
          throw FormatException(widget.strings.invalidSourceList);
        }
        options[field] = {
          for (final row in rows)
            if (row case {'id': final String id, 'label': final String label}
                when id.trim().isNotEmpty &&
                    id == id.trim() &&
                    id.toLowerCase() != 'auto' &&
                    label.trim().isNotEmpty)
              id: label,
        };
      }
      if (mounted) setState(() => _options = options);
    } catch (e) {
      if (mounted) setState(() => _error = widget.strings.requestFailed('$e'));
    }
  }

  void _confirm() {
    if (_submitted || _selected.isEmpty) return;
    _submitted = true;
    Navigator.pop(context, SourceSelection.unmodifiable(_selected));
  }

  @override
  Widget build(BuildContext context) {
    final strings = widget.strings;
    final options = _options;
    final videoLabel = widget.videoLabel;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Semantics(
                    header: true,
                    child: Text(
                      videoLabel == null ? strings.metadataBackfill : strings.rescrape,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                ),
                CloseButton(onPressed: () => Navigator.pop(context)),
              ],
            ),
            if (_error != null) ...[
              Semantics(liveRegion: true, child: Text(_error!)),
              TextButton(onPressed: _load, child: Text(strings.retry)),
            ] else if (options == null)
              const LinearProgressIndicator()
            else ...[
              Text(videoLabel == null
                  ? strings.metadataBackfillHint
                  : strings.rescrapeFieldsHint(videoLabel)),
              for (final field in MetadataField.values) ...[
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  key: ValueKey(field.name),
                  decoration: InputDecoration(labelText: field.label(strings)),
                  initialValue: '',
                  isExpanded: true,
                  items: [
                    DropdownMenuItem(value: '', child: Text(strings.skipField)),
                    for (final option in options[field]!.entries)
                      DropdownMenuItem(
                        value: option.key,
                        child: Text(option.value),
                      ),
                  ],
                  onChanged: options[field]!.isEmpty
                      ? null
                      : (id) {
                          final label = options[field]![id];
                          setState(() {
                            if (id == null || label == null) {
                              _selected.remove(field);
                            } else {
                              _selected[field] = (id: id, label: label);
                            }
                          });
                        },
                ),
              ],
              if (options.values.every((list) => list.isEmpty))
                Text(strings.noMetadataSources),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: _selected.isEmpty ? null : _confirm,
                child: Text(videoLabel == null
                    ? strings.runMetadataBackfill
                    : strings.replaceSelectedFields),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
