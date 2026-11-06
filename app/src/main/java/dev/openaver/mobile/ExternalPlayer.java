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

import java.util.Locale;
import java.util.List;

final class ExternalPlayer {
    private ExternalPlayer() {
    }

    interface BuiltInFallback {
        void open(String rawPath, int partNumber);
    }

    static boolean open(Activity activity, String rawPath) {
        return open(activity, rawPath, null);
    }

    static boolean open(Activity activity, String rawPath, String rawParts) {
        return open(activity, rawPath, rawParts, null);
    }

    static boolean open(
            Activity activity,
            String rawPath,
            String rawParts,
            BuiltInFallback fallback
    ) {
        List<VideoPartParser.Part> parts = VideoPartParser.parse(rawPath, rawParts);
        if (parts.size() > 1) {
            String[] labels = new String[parts.size()];
            for (int index = 0; index < parts.size(); index++) {
                VideoPartParser.Part part = parts.get(index);
                labels[index] = part.label.isEmpty()
                        ? activity.getString(R.string.video_part_number, part.number)
                        : part.label;
            }
            AlertDialog.Builder builder = new AlertDialog.Builder(
                    activity,
                    android.R.style.Theme_Material_Dialog_Alert
            )
                    .setTitle(R.string.choose_video_part)
                    .setItems(labels, (dialog, which) ->
                            openExternalOrFallback(
                                    activity,
                                    parts.get(which),
                                    fallback
                            ))
                    .setNegativeButton(R.string.cancel, null);
            if (fallback != null) {
                builder.setNeutralButton(
                        R.string.play_in_builtin_player,
                        (dialog, which) ->
                                showBuiltInPartPicker(activity, parts, fallback)
                );
            }
            builder.show();
            return true;
        }

        String selectedPath = parts.isEmpty() ? rawPath : parts.get(0).path;
        VideoPartParser.Part selectedPart = parts.isEmpty()
                ? new VideoPartParser.Part(selectedPath, "", 1)
                : parts.get(0);
        return openExternalOrFallback(activity, selectedPart, fallback);
    }

    private static boolean openExternalOrFallback(
            Activity activity,
            VideoPartParser.Part part,
            BuiltInFallback fallback
    ) {
        boolean opened = openSelected(activity, part.path, fallback == null);
        if (opened || fallback == null) {
            return opened;
        }
        toast(activity, R.string.opened_with_builtin_player);
        fallback.open(part.path, part.number);
        return true;
    }

    private static void showBuiltInPartPicker(
            Activity activity,
            List<VideoPartParser.Part> parts,
            BuiltInFallback fallback
    ) {
        String[] labels = new String[parts.size()];
        for (int index = 0; index < parts.size(); index++) {
            VideoPartParser.Part part = parts.get(index);
            labels[index] = part.label.isEmpty()
                    ? activity.getString(R.string.video_part_number, part.number)
                    : part.label;
        }
        new AlertDialog.Builder(activity, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(R.string.choose_video_part)
                .setItems(labels, (dialog, which) -> {
                    VideoPartParser.Part part = parts.get(which);
                    fallback.open(part.path, part.number);
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
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
