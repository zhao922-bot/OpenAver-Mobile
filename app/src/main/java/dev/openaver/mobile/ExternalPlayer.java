package dev.openaver.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ContentUris;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.MediaStore;
import android.webkit.MimeTypeMap;
import android.widget.Toast;

import java.util.Collections;
import java.util.List;
import java.util.Locale;

final class ExternalPlayer {
    private ExternalPlayer() {
    }

    interface BuiltInFallback {
        void open(String rawPath, int partNumber);
    }

    interface BuiltInMultipartFallback {
        void open(String rawPath, int partNumber, List<VideoPartParser.Part> parts);
    }

    static boolean open(Activity activity, String rawPath) {
        return open(activity, rawPath, null);
    }

    static boolean open(Activity activity, String rawPath, String rawParts) {
        return open(activity, rawPath, rawParts, null);
    }

    static boolean openExternalDirect(
            Activity activity,
            String rawPath,
            String rawParts,
            BuiltInMultipartFallback fallback
    ) {
        List<VideoPartParser.Part> parts = VideoPartParser.parse(rawPath, rawParts);
        if (parts.size() > 1) {
            showPartPicker(activity, parts, null, fallback);
            return true;
        }
        String selectedPath = parts.isEmpty() ? rawPath : parts.get(0).path;
        VideoPartParser.Part selectedPart = parts.isEmpty()
                ? new VideoPartParser.Part(selectedPath, "", 1)
                : parts.get(0);
        return openExternalOrFallback(activity, selectedPart, parts, fallback);
    }

    static boolean open(
            Activity activity,
            String rawPath,
            String rawParts,
            BuiltInFallback fallback
    ) {
        List<VideoPartParser.Part> parts = VideoPartParser.parse(rawPath, rawParts);
        if (parts.size() > 1) {
            showPartPicker(activity, parts, fallback, null);
            return true;
        }

        String selectedPath = parts.isEmpty() ? rawPath : parts.get(0).path;
        VideoPartParser.Part selectedPart = parts.isEmpty()
                ? new VideoPartParser.Part(selectedPath, "", 1)
                : parts.get(0);
        if (fallback != null) {
            showPlayerChoice(activity, selectedPart, fallback);
            return true;
        }
        return openExternalOrFallback(activity, selectedPart, parts, null);
    }

    private static BuiltInMultipartFallback wrapFallback(BuiltInFallback fallback) {
        if (fallback == null) {
            return null;
        }
        return (selectedPath, partNumber, parts) -> fallback.open(selectedPath, partNumber);
    }

    private static void showPartPicker(
            Activity activity,
            List<VideoPartParser.Part> parts,
            BuiltInFallback classicFallback,
            BuiltInMultipartFallback multipartFallback
    ) {
        String[] labels = buildPartLabels(activity, parts);
        BuiltInMultipartFallback effectiveFallback = multipartFallback != null
                ? multipartFallback
                : wrapFallback(classicFallback);
        AlertDialog.Builder builder = new AlertDialog.Builder(
                activity,
                NativeUiTheme.dialogStyle(activity)
        )
                .setTitle(R.string.choose_video_part)
                .setItems(labels, (dialog, which) ->
                        openExternalOrFallback(
                                activity,
                                parts.get(which),
                                parts,
                                effectiveFallback
                        ))
                .setNegativeButton(R.string.cancel, null);
        if (classicFallback != null) {
            builder.setNeutralButton(
                    R.string.play_in_builtin_player,
                    (dialog, which) ->
                            showBuiltInPartPicker(activity, parts, classicFallback)
            );
        }
        builder.show();
    }

    private static void showPlayerChoice(
            Activity activity,
            VideoPartParser.Part part,
            BuiltInFallback fallback
    ) {
        String[] choices = {
                activity.getString(R.string.play_with_external_player),
                activity.getString(R.string.play_in_builtin_player),
        };
        new AlertDialog.Builder(activity, NativeUiTheme.dialogStyle(activity))
                .setTitle(R.string.choose_video_player)
                .setItems(choices, (dialog, which) -> {
                    if (which == 0) {
                        openExternalOrFallback(
                                activity,
                                part,
                                Collections.singletonList(part),
                                wrapFallback(fallback)
                        );
                    } else {
                        fallback.open(part.path, part.number);
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private static boolean openExternalOrFallback(
            Activity activity,
            VideoPartParser.Part part,
            List<VideoPartParser.Part> parts,
            BuiltInMultipartFallback fallback
    ) {
        boolean opened = openSelected(activity, part.path, fallback == null);
        if (opened || fallback == null) {
            return opened;
        }
        toast(activity, R.string.opened_with_builtin_player);
        fallback.open(part.path, part.number, parts);
        return true;
    }

    private static void showBuiltInPartPicker(
            Activity activity,
            List<VideoPartParser.Part> parts,
            BuiltInFallback fallback
    ) {
        String[] labels = buildPartLabels(activity, parts);
        new AlertDialog.Builder(activity, NativeUiTheme.dialogStyle(activity))
                .setTitle(R.string.choose_video_part)
                .setItems(labels, (dialog, which) -> {
                    VideoPartParser.Part part = parts.get(which);
                    fallback.open(part.path, part.number);
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private static String[] buildPartLabels(Activity activity, List<VideoPartParser.Part> parts) {
        String[] labels = new String[parts.size()];
        for (int index = 0; index < parts.size(); index++) {
            VideoPartParser.Part part = parts.get(index);
            labels[index] = part.label.isEmpty()
                    ? activity.getString(R.string.video_part_number, part.number)
                    : part.label;
        }
        return labels;
    }

    private static boolean openSelected(
            Activity activity,
            String rawPath,
            boolean notifyFailure
    ) {
        String path = normalizePath(rawPath);
        if (path.isEmpty() || !VideoPartParser.looksLikeVideoPath(path)) {
            if (notifyFailure) {
                toast(activity, R.string.video_file_unavailable);
            }
            return false;
        }

        Uri uri = resolveUri(activity, rawPath, path);
        if (uri == null) {
            if (notifyFailure) {
                toast(activity, R.string.video_file_unavailable);
            }
            return false;
        }

        String mimeType = activity.getContentResolver().getType(uri);
        if (mimeType == null || !mimeType.startsWith("video/")) {
            String extension = MimeTypeMap.getFileExtensionFromUrl(path);
            mimeType = MimeTypeMap.getSingleton()
                    .getMimeTypeFromExtension(extension.toLowerCase(Locale.ROOT));
        }
        if (mimeType == null || !mimeType.startsWith("video/")) {
            mimeType = "video/*";
        }

        Intent target = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, mimeType)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        target.setClipData(ClipData.newRawUri("video", uri));
        Intent chooser = Intent.createChooser(
                target,
                activity.getString(R.string.choose_video_player)
        );
        chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

        try {
            activity.startActivity(chooser);
            return true;
        } catch (ActivityNotFoundException | SecurityException error) {
            if (notifyFailure) {
                toast(activity, R.string.video_player_missing);
            }
            return false;
        }
    }

    private static Uri resolveUri(Activity activity, String rawPath, String path) {
        if (rawPath != null) {
            Uri parsed = Uri.parse(rawPath);
            if ("content".equals(parsed.getScheme())) {
                return parsed;
            }
        }

        Uri safUri = StorageBridge.documentUriForPath(path);
        if (safUri != null) {
            return safUri;
        }

        return queryMediaStore(activity, path);
    }

    private static Uri queryMediaStore(Activity activity, String path) {
        String[] projection = {MediaStore.Video.Media._ID};
        String selection = MediaStore.Video.Media.DATA + "=?";
        try (Cursor cursor = activity.getContentResolver().query(
                MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                new String[]{path},
                null
        )) {
            if (cursor != null && cursor.moveToFirst()) {
                long id = cursor.getLong(0);
                return ContentUris.withAppendedId(
                        MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                        id
                );
            }
        } catch (Exception ignored) {
            // SAF is the primary path on removable storage; MediaStore is a fallback.
        }
        return null;
    }

    private static String normalizePath(String rawPath) {
        if (rawPath == null) {
            return "";
        }
        String value = rawPath.trim();
        Uri parsed = Uri.parse(value);
        if ("file".equals(parsed.getScheme())) {
            value = parsed.getPath() == null ? "" : parsed.getPath();
        }
        while (value.startsWith("//")) {
            value = value.substring(1);
        }
        return value;
    }

    private static void toast(Activity activity, int message) {
        Toast.makeText(activity, message, Toast.LENGTH_LONG).show();
    }
}
