import 'package:flutter/material.dart';

/// Displays an AlertDialog with a TextField whose TextEditingController is
/// owned and disposed by a dedicated StatefulWidget so exit animations never
/// reference a disposed controller.
Future<String?> showPromptTextDialog({
  required BuildContext context,
  required String title,
  required String cancelLabel,
  required String confirmLabel,
  String? subtitle,
  String initialValue = '',
  String? hintText,
  String? labelText,
  int minLines = 1,
  int maxLines = 1,
}) {
  return showDialog<String>(
    context: context,
    builder: (_) => _PromptTextDialog(
      title: title,
      subtitle: subtitle,
      initialValue: initialValue,
      hintText: hintText,
      labelText: labelText,
      minLines: minLines,
      maxLines: maxLines,
      cancelLabel: cancelLabel,
      confirmLabel: confirmLabel,
    ),
  );
}

class _PromptTextDialog extends StatefulWidget {
  const _PromptTextDialog({
    required this.title,
    required this.cancelLabel,
    required this.confirmLabel,
    this.subtitle,
    this.initialValue = '',
    this.hintText,
    this.labelText,
    this.minLines = 1,
    this.maxLines = 1,
  });

  final String title;
  final String? subtitle;
  final String initialValue;
  final String? hintText;
  final String? labelText;
  final int minLines;
  final int maxLines;
  final String cancelLabel;
  final String confirmLabel;

  @override
  State<_PromptTextDialog> createState() => _PromptTextDialogState();
}

class _PromptTextDialogState extends State<_PromptTextDialog> {
  late final TextEditingController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.initialValue);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isSingleLine = widget.maxLines == 1;
    final field = TextField(
      controller: _ctrl,
      autofocus: true,
      minLines: widget.minLines,
      maxLines: widget.maxLines,
      decoration: InputDecoration(
        hintText: widget.hintText,
        labelText: widget.labelText,
      ),
      onSubmitted: isSingleLine ? (v) => Navigator.of(context).pop(v) : null,
    );

    return AlertDialog(
      title: Text(widget.title),
      content: widget.subtitle != null && widget.subtitle!.isNotEmpty
          ? Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.subtitle!, style: const TextStyle(fontSize: 12)),
                const SizedBox(height: 10),
                field,
              ],
            )
          : field,
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(widget.cancelLabel),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_ctrl.text),
          child: Text(widget.confirmLabel),
        ),
      ],
    );
  }
}
