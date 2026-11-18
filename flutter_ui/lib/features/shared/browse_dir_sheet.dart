import 'package:flutter/material.dart';
import '../../core/api_client.dart';
import '../../core/app_theme.dart';
import '../../core/models/scanner_models.dart';

class BrowseDirSheet extends StatefulWidget {
  const BrowseDirSheet({
    super.key,
    required this.api,
    this.initialPath,
    this.expandVideos = false,
  });

  final ApiClient api;
  final String? initialPath;
  final bool expandVideos;

  static Future<String?> pickFolder(
    BuildContext context,
    ApiClient api, {
    String? initialPath,
  }) {
    return showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => SizedBox(
        height: MediaQuery.of(context).size.height * 0.78,
        child: BrowseDirSheet(api: api, initialPath: initialPath),
      ),
    );
  }

  @override
  State<BrowseDirSheet> createState() => _BrowseDirSheetState();
}

class _BrowseDirSheetState extends State<BrowseDirSheet> {
  bool _loading = true;
  String? _error;
  BrowseDirResponse? _data;

  @override
  void initState() {
    super.initState();
    _loadPath(widget.initialPath);
  }

  Future<void> _loadPath(String? path) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await widget.api.getJson(
        '/api/gallery/browse-dir',
        queryParameters: {
          'path': ?path,
          if (widget.expandVideos) 'expand': 'videos',
        },
      );
      if (resp['success'] == false) {
        setState(() {
          _loading = false;
          _error = (resp['error'] ?? 'Unable to browse directory').toString();
        });
        return;
      }
      setState(() {
        _data = BrowseDirResponse.fromJson(resp);
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
    final current = _data?.currentPath ?? '';

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
          child: Row(
            children: [
              const Icon(Icons.folder_open_rounded, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  current.isEmpty ? '选择目录' : current,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: palette.textPrimary,
                  ),
                ),
              ),
              if (_data?.parentPath != null)
                IconButton(
                  tooltip: '上一层',
                  icon: const Icon(Icons.arrow_upward_rounded),
                  onPressed: _loading ? null : () => _loadPath(_data!.parentPath),
                ),
              IconButton(
                icon: const Icon(Icons.close_rounded),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(_error!, style: TextStyle(color: palette.danger)),
                            const SizedBox(height: 12),
                            FilledButton(
                              onPressed: () => _loadPath(null),
                              child: const Text('返回根目录'),
                            ),
                          ],
                        ),
                      ),
                    )
                  : ListView.builder(
                      itemCount: _data?.entries.length ?? 0,
                      itemBuilder: (_, index) {
                        final entry = _data!.entries[index];
                        return ListTile(
                          leading: Icon(Icons.folder_rounded, color: palette.accent),
                          title: Text(entry.name),
                          trailing: const Icon(Icons.chevron_right_rounded, size: 18),
                          onTap: () => _loadPath(entry.path),
                        );
                      },
                    ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: current.isEmpty ? null : () => Navigator.of(context).pop(current),
                icon: const Icon(Icons.check_rounded),
                label: const Text('选择当前目录'),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
