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

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.Locale;
import java.util.List;
import java.util.Set;

final class ExternalPlayer {
    private static final String[] VIDEO_EXTENSIONS = {
            ".mp4", ".mkv", ".avi", ".wmv", ".rmvb", ".flv", ".mov",
            ".m4v", ".ts", ".m2ts", ".webm", ".mpeg", ".mpg"
    };

    private ExternalPlayer() {
    }

    static boolean open(Activity activity, String rawPath) {
        return open(activity, rawPath, null);
    }

    static boolean open(Activity activity, String rawPath, String rawParts) {
        List<VideoPart> parts = parseParts(activity, rawPath, rawParts);
        if (parts.size() > 1) {
            String[] labels = new String[parts.size()];
            for (int index = 0; index < parts.size(); index++) {
                labels[index] = parts.get(index).label;
            }
            new AlertDialog.Builder(activity, android.R.style.Theme_Material_Dialog_Alert)
                    .setTitle(R.string.choose_video_part)
                    .setItems(labels, (dialog, which) ->
                            openSelected(activity, parts.get(which).path))
                    .setNegativeButton(R.string.cancel, null)
                    .show();
            return true;
        }

        String selectedPath = parts.isEmpty() ? rawPath : parts.get(0).path;
        return openSelected(activity, selectedPath);
    }

    private static boolean openSelected(Activity activity, String rawPath) {
        String path = normalizePath(rawPath);
        if (path.isEmpty() || !isVideoPath(path)) {
            toast(activity, R.string.video_file_unavailable);
            return false;
        }

        Uri uri = resolveUri(activity, rawPath, path);
        if (uri == null) {
            toast(activity, R.string.video_file_unavailable);
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
            toast(activity, R.string.video_player_missing);
            return false;
        }
    }

    private static List<VideoPart> parseParts(
            Activity activity,
            String rawPath,
            String rawParts
    ) {
        List<VideoPart> parts = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        if (rawParts != null && !rawParts.trim().isEmpty()) {
            try {
                JSONArray array = new JSONArray(rawParts);
                for (int index = 0; index < array.length(); index++) {
                    JSONObject item = array.optJSONObject(index);
                    if (item == null) {
                        continue;
                    }
                    String path = item.optString("path", "").trim();
                    if (path.isEmpty()
                            || !isVideoPath(normalizePath(path))
                            || !seen.add(path)) {
                        continue;
                    }
                    String label = item.optString("label", "").trim();
                    if (label.isEmpty()) {
                        label = activity.getString(
                                R.string.video_part_number,
                                parts.size() + 1
                        );
                    }
                    if (label.length() > 80) {
                        label = label.substring(0, 80);
                    }
                    parts.add(new VideoPart(path, label));
                }
            } catch (Exception ignored) {
                // Invalid payloads fall back to the single path supplied by the page.
            }
        }
        if (parts.isEmpty() && rawPath != null && !rawPath.trim().isEmpty()) {
            parts.add(new VideoPart(
                    rawPath,
                    activity.getString(R.string.video_part_number, 1)
            ));
        }
        return parts;
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

    private static boolean isVideoPath(String path) {
        String lower = path.toLowerCase(Locale.ROOT);
        for (String extension : VIDEO_EXTENSIONS) {
            if (lower.endsWith(extension)) {
                return true;
            }
        }
        return false;
    }

    private static void toast(Activity activity, int message) {
        Toast.makeText(activity, message, Toast.LENGTH_LONG).show();
    }

    private static final class VideoPart {
        final String path;
        final String label;

        VideoPart(String path, String label) {
            this.path = path;
            this.label = label;
        }
    }
}
