import 'package:flutter/material.dart';
import '../../core/api_client.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';

class AiBackfillBar extends StatefulWidget {
  const AiBackfillBar({
    super.key,
    required this.api,
    required this.strings,
    required this.statusEndpoint,
    required this.startEndpoint,
    required this.stopEndpoint,
    required this.rebuildEndpoint,
  });

  final ApiClient api;
  final AppStrings strings;
  final String statusEndpoint;
  final String startEndpoint;
  final String stopEndpoint;
  final String rebuildEndpoint;

  @override
  State<AiBackfillBar> createState() => _AiBackfillBarState();
}

class _AiBackfillBarState extends State<AiBackfillBar> {
  Map<String, dynamic>? _status;
  bool _busy = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final resp = await widget.api.getJson(widget.statusEndpoint);
      if (!mounted) return;
      setState(() => _status = resp);
    } catch (e) {
      debugPrint('AiBackfillBar refresh ${widget.statusEndpoint} error: $e');
    }
  }

  Future<void> _runAction(String endpoint, {bool confirmRebuild = false}) async {
    if (_busy) return;
    if (confirmRebuild) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(widget.strings.backfillRebuildBtn),
          content: Text(widget.strings.backfillRebuildConfirm),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(widget.strings.cancel)),
            FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(widget.strings.confirm)),
          ],
        ),
      );
      if (ok != true) return;
    }

    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      final resp = await widget.api.postJson(endpoint);
      if (!mounted) return;
      final detail = (resp['status'] ?? resp['reason'] ?? resp['error'] ?? '').toString();
      if (detail.isNotEmpty) {
        setState(() => _message = detail);
      }
      await _refresh();
    } catch (e) {
      debugPrint('AiBackfillBar action $endpoint error: $e');
      if (mounted) {
        setState(() => _message = widget.strings.requestFailed('$e'));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    final running = _status?['running'] == true;
    final processed = (_status?['processed'] as num?)?.toInt() ?? 0;
    final total = (_status?['total'] as num?)?.toInt() ?? 0;
    final pending = (_status?['pending'] as num?)?.toInt() ?? 0;
    final stoppedReason = (_status?['stopped_reason'] ?? '').toString();

    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: palette.surfaceHigh,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: palette.stroke),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_status != null)
            Text(
              running
                  ? widget.strings.backfillRunningLabel(processed, total)
                  : '${widget.strings.backfillPendingLabel(pending)}${stoppedReason.isNotEmpty ? ' ($stoppedReason)' : ''}',
              style: TextStyle(fontSize: 12, color: palette.textSecondary),
            ),
          if (_message != null && _message!.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(_message!, style: TextStyle(fontSize: 11.5, color: palette.textMuted)),
          ],
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              if (!running)
                FilledButton.tonalIcon(
                  onPressed: _busy ? null : () => _runAction(widget.startEndpoint),
                  icon: const Icon(Icons.play_arrow_rounded, size: 16),
                  label: Text(widget.strings.backfillStartBtn),
                )
              else
                FilledButton.tonalIcon(
                  onPressed: _busy ? null : () => _runAction(widget.stopEndpoint),
                  icon: const Icon(Icons.stop_rounded, size: 16),
                  label: Text(widget.strings.backfillStopBtn),
                ),
              if (!running)
                OutlinedButton.icon(
                  onPressed: _busy ? null : () => _runAction(widget.rebuildEndpoint, confirmRebuild: true),
                  icon: const Icon(Icons.refresh_rounded, size: 16),
                  label: Text(widget.strings.backfillRebuildBtn),
                ),
              TextButton.icon(
                onPressed: _busy ? null : _refresh,
                icon: const Icon(Icons.sync_rounded, size: 15),
                label: Text(widget.strings.backfillRefreshBtn),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
