import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/app_providers.dart';
import '../../core/app_theme.dart';
import '../../core/l10n.dart';
import 'task_center.dart';

class TaskCenterPage extends ConsumerWidget {
  const TaskCenterPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final strings = ref.watch(stringsProvider);
    final center = TaskCenter.forApi(ref.watch(apiClientProvider));

    return Scaffold(
      appBar: AppBar(title: Text(strings.taskCenterTitle)),
      body: SafeArea(
        top: false,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListenableBuilder(
              key: ObjectKey(center),
              listenable: center,
              builder: (context, _) {
                final jobs = center.jobs;
                if (jobs.isEmpty) return _EmptyTasks(strings: strings);

                final active = jobs.where((job) => job.isActive).toList();
                final recent = jobs.where((job) => !job.isActive).toList();
                return ListView(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                  children: [
                    if (active.isNotEmpty) ...[
                      _SectionHeading(title: strings.taskCenterCurrent),
                      for (final job in active) _taskCard(job, strings),
                    ],
                    if (recent.isNotEmpty) ...[
                      if (active.isNotEmpty) const SizedBox(height: 12),
                      _SectionHeading(title: strings.taskCenterRecent),
                      for (final job in recent) _taskCard(job, strings),
                    ],
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  _TaskCard _taskCard(TaskJob job, AppStrings strings) =>
      _TaskCard(key: ObjectKey(job), job: job, strings: strings);
}

class _EmptyTasks extends StatelessWidget {
  const _EmptyTasks({required this.strings});

  final AppStrings strings;

  @override
  Widget build(BuildContext context) {
    final palette = OpenAverPalette.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.task_alt_rounded,
              size: 36,
              color: palette.textSecondary,
            ),
            const SizedBox(height: 12),
            Text(strings.taskCenterEmpty, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
      child: Semantics(
        header: true,
        child: Text(title, style: Theme.of(context).textTheme.titleMedium),
      ),
    );
  }
}

class _TaskCard extends StatefulWidget {
  const _TaskCard({super.key, required this.job, required this.strings});

  final TaskJob job;
  final AppStrings strings;

  @override
  State<_TaskCard> createState() => _TaskCardState();
}

class _TaskCardState extends State<_TaskCard> {
  bool _acting = false;
  bool _actionFailed = false;

  Future<void> _runAction(Future<void> Function() action) async {
    if (_acting) return;
    setState(() {
      _acting = true;
      _actionFailed = false;
    });
    try {
      await action();
    } catch (_) {
      if (mounted) setState(() => _actionFailed = true);
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final job = widget.job;
    final strings = widget.strings;
    final theme = Theme.of(context);
    final palette = OpenAverPalette.of(context);
    final secondaryText = theme.textTheme.bodyMedium?.copyWith(
      color: palette.textSecondary,
    );
    final (title, icon) = switch (job.kind) {
      TaskKind.scan => (strings.taskCenterScan, Icons.radar_rounded),
      TaskKind.metadataBackfill => (strings.metadataBackfill, Icons.library_books_outlined),
      TaskKind.batchTag => (strings.taskCenterBatchTag, Icons.sell_outlined),
      TaskKind.batchTagPreview => (
        strings.taskCenterBatchTagPreview,
        Icons.preview_outlined,
      ),
      TaskKind.similar => (
        strings.taskCenterSimilar,
        Icons.photo_library_outlined,
      ),
      TaskKind.faces => (strings.taskCenterFaces, Icons.face_outlined),
      TaskKind.aiTags => (
        strings.taskCenterAiTags,
        Icons.auto_awesome_outlined,
      ),
    };
    final status = switch (job.status) {
      TaskStatus.running => strings.taskCenterRunning,
      TaskStatus.starting => strings.starting,
      TaskStatus.cancelling => strings.taskCenterCancelling,
      TaskStatus.succeeded when job.failureCount > 0 =>
        strings.taskCenterCompletedWithFailures,
      TaskStatus.succeeded => strings.taskDone,
      TaskStatus.failed => strings.taskFailed,
      TaskStatus.cancelled => strings.taskCenterCancelled,
      TaskStatus.stopped => strings.taskCenterStopped,
      TaskStatus.interrupted => strings.taskCenterInterrupted,
    };
    final statusColor = switch (job.status) {
      TaskStatus.running || TaskStatus.starting => palette.accent,
      TaskStatus.succeeded when job.failureCount > 0 => palette.warning,
      TaskStatus.succeeded => palette.success,
      TaskStatus.failed => palette.danger,
      TaskStatus.cancelling ||
      TaskStatus.stopped ||
      TaskStatus.interrupted => palette.warning,
      TaskStatus.cancelled => palette.textSecondary,
    };
    final source = job.subject?.trim();
    final reason = job.reason?.trim();
    final reasonText = reason == null || reason.isEmpty
        ? null
        : strings.taskCenterReason(reason);
    final message = job.message?.trim();
    final hasMessage =
        message != null &&
        message.isNotEmpty &&
        message != reason &&
        message != reasonText;
    final current = job.current;
    final total = job.total;
    final progress = job.progress;
    final progressText = switch ((current, total)) {
      (final int done, final int count) => strings.taskCenterProgress(
        done,
        count,
      ),
      (final int done, _) => strings.taskCenterProcessed(done),
      _ => job.isActive ? strings.taskCenterProgressUnknown : null,
    };
    final cancelLabel = switch (job.kind) {
      TaskKind.similar ||
      TaskKind.faces ||
      TaskKind.aiTags => strings.backfillStopBtn,
      _ => strings.cancel,
    };
    final finishedAt = job.finishedAt;

    return Card.outlined(
      margin: const EdgeInsets.only(bottom: 10),
      color: palette.surface,
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(icon, size: 22, color: palette.textSecondary),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(title, style: theme.textTheme.titleMedium),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 12,
                  runSpacing: 6,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    DecoratedBox(
                      decoration: BoxDecoration(
                        color: palette.surfaceHigh,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 3,
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.circle, size: 8, color: statusColor),
                            const SizedBox(width: 6),
                            Flexible(
                              child: Text(
                                status,
                                style: theme.textTheme.labelMedium,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    if (source != null && source.isNotEmpty)
                      Text(
                        strings.taskCenterSource(source),
                        style: secondaryText,
                      ),
                  ],
                ),
                if (progressText != null) ...[
                  const SizedBox(height: 10),
                  Text(progressText, style: secondaryText),
                ],
                if (job.isActive || progress != null) ...[
                  const SizedBox(height: 6),
                  ExcludeSemantics(
                    child: LinearProgressIndicator(
                      value: progress,
                      minHeight: 4,
                    ),
                  ),
                ],
                if (job.failureCount > 0 ||
                    job.warningCount > 0 ||
                    reasonText != null ||
                    hasMessage) ...[
                  const SizedBox(height: 10),
                  if (job.failureCount > 0)
                    Text(
                      strings.taskCenterFailureCount(job.failureCount),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  if (job.warningCount > 0)
                    Text(
                      strings.taskCenterWarningCount(job.warningCount),
                      style: secondaryText,
                    ),
                  if (reasonText != null)
                    Text(reasonText, style: secondaryText),
                  if (hasMessage) Text(message, style: secondaryText),
                ],
                if (_acting) ...[
                  const SizedBox(height: 8),
                  Text(strings.requesting, style: secondaryText),
                ] else if (job.canCancel || job.canRetry) ...[
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 8,
                    children: [
                      if (job.canCancel)
                        OutlinedButton(
                          onPressed: () => _runAction(job.cancel),
                          child: Text(cancelLabel),
                        ),
                      if (job.canRetry)
                        FilledButton.tonal(
                          onPressed: () => _runAction(job.retry),
                          child: Text(strings.retry),
                        ),
                    ],
                  ),
                ],
                if (_actionFailed) ...[
                  const SizedBox(height: 8),
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      strings.taskCenterActionFailed,
                      style: secondaryText,
                    ),
                  ),
                ],
              ],
            ),
          ),
          ExpansionTile(
            key: PageStorageKey((job.kind, job.startedAt)),
            title: Text(
              strings.taskCenterDetails,
              style: theme.textTheme.bodyMedium,
            ),
            tilePadding: const EdgeInsets.symmetric(horizontal: 16),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
            shape: const Border(),
            collapsedShape: const Border(),
            children: [
              Text(
                strings.taskCenterStarted(_formatTime(job.startedAt)),
                style: secondaryText,
              ),
              if (finishedAt != null)
                Text(
                  strings.taskCenterFinished(_formatTime(finishedAt)),
                  style: secondaryText,
                ),
              for (final (heading, examples) in [
                (strings.taskCenterFailureExamples, job.failureExamples),
                (strings.taskCenterWarningExamples, job.warningExamples),
              ])
                if (examples.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(heading, style: theme.textTheme.titleSmall),
                  SelectionArea(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final example in examples)
                          Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(example, style: secondaryText),
                          ),
                      ],
                    ),
                  ),
                ],
            ],
          ),
        ],
      ),
    );
  }

  String _formatTime(DateTime timestamp) {
    final local = timestamp.toLocal();
    final dateTime = local.toIso8601String();
    return dateTime
        .substring(0, dateTime.indexOf('T') + 6)
        .replaceFirst('T', ' ');
  }
}
