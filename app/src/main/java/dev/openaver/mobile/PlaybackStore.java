package dev.openaver.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;

import java.util.HashMap;
import java.util.Map;

import io.flutter.plugin.common.MethodCall;
import io.flutter.plugin.common.MethodChannel;

final class PlaybackStore {
    // Uri.encode(path) escapes '#', so these keys cannot collide with existing bookmarks.
    private static final String PATH = "#latest.path";
    private static final String TITLE = "#latest.title";
    private static final String PART_LABEL = "#latest.partLabel";
    private static final String PART_INDEX = "#latest.partIndex";
    private static final String REVISION = "#latest.revision";

    private PlaybackStore() {
    }

    static synchronized void handle(Context context, MethodCall call, MethodChannel.Result result) {
        SharedPreferences prefs = context.getSharedPreferences("playback_positions", Context.MODE_PRIVATE);
        switch (call.method) {
            case "readPlaybackPosition": {
                String path = call.argument("path");
                result.success(path == null ? 0L : prefs.getLong(Uri.encode(path), 0L));
                break;
            }
            case "savePlaybackPosition":
                save(prefs, call);
                result.success(null);
                break;
            case "readLatestPlayback":
                result.success(readLatest(prefs));
                break;
            case "removeLatestPlayback": {
                String path = call.argument("path");
                Number revision = call.argument("revision");
                boolean matches = path != null && path.equals(prefs.getString(PATH, null))
                        && revision != null && revision.longValue() == prefs.getLong(REVISION, 0L);
                if (matches) {
                    clearLatest(prefs.edit()).apply();
                }
                result.success(matches);
                break;
            }
            default:
                result.notImplemented();
        }
    }

    private static void save(SharedPreferences prefs, MethodCall call) {
        String path = call.argument("path");
        Number milliseconds = call.argument("milliseconds");
        if (path == null || path.isEmpty() || milliseconds == null) {
            return;
        }
        String key = Uri.encode(path);
        boolean samePath = path.equals(prefs.getString(PATH, null));
        SharedPreferences.Editor editor = prefs.edit();
        if (milliseconds.longValue() <= 0L) {
            editor.remove(key);
            if (samePath) {
                clearLatest(editor);
            }
        } else {
            String title = call.argument("title");
            String label = call.argument("partLabel");
            Number index = call.argument("partIndex");
            editor.putLong(key, milliseconds.longValue());
            editor.putString(PATH, path);
            editor.putLong(REVISION, prefs.getLong(REVISION, 0L) + 1L);
            if (!samePath || title != null) {
                editor.putString(TITLE, title);
            }
            if (!samePath || label != null) {
                editor.putString(PART_LABEL, label);
            }
            if (!samePath || index != null) {
                editor.putInt(PART_INDEX, index == null ? 0 : index.intValue());
            }
        }
        editor.apply();
    }

    private static Map<String, Object> readLatest(SharedPreferences prefs) {
        String path = prefs.getString(PATH, null);
        if (path == null) {
            return null;
        }
        long milliseconds = prefs.getLong(Uri.encode(path), 0L);
        if (milliseconds <= 0L) {
            return null;
        }
        Map<String, Object> entry = new HashMap<>();
        entry.put("path", path);
        entry.put("milliseconds", milliseconds);
        entry.put("title", prefs.getString(TITLE, ""));
        entry.put("partLabel", prefs.getString(PART_LABEL, ""));
        entry.put("partIndex", prefs.getInt(PART_INDEX, 0));
        entry.put("revision", prefs.getLong(REVISION, 0L));
        return entry;
    }

    private static SharedPreferences.Editor clearLatest(SharedPreferences.Editor editor) {
        // Keep the counter so a later save of the same path gets a distinct revision.
        return editor.remove(PATH).remove(TITLE).remove(PART_LABEL).remove(PART_INDEX);
    }
}
