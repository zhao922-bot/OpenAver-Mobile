package dev.openaver.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

final class VideoPartParser {
    private static final String[] VIDEO_EXTENSIONS = {
            ".mp4", ".mkv", ".avi", ".wmv", ".rmvb", ".flv", ".mov",
            ".m4v", ".ts", ".m2ts", ".webm", ".mpeg", ".mpg"
    };
    private static final int MAX_LABEL_LENGTH = 80;

    private VideoPartParser() {
    }

    static List<Part> parse(String rawPath, String rawParts) {
        List<Part> parts = new ArrayList<>();
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
                    if (!looksLikeVideoPath(path) || !seen.add(path)) {
                        continue;
                    }
                    String label = item.optString("label", "").trim();
                    if (label.length() > MAX_LABEL_LENGTH) {
                        label = label.substring(0, MAX_LABEL_LENGTH);
                    }
                    parts.add(new Part(path, label, parts.size() + 1));
                }
            } catch (Exception ignored) {
                // Invalid payloads fall back to the single path supplied by the page.
            }
        }
        if (parts.isEmpty()) {
            String path = rawPath == null ? "" : rawPath.trim();
            if (looksLikeVideoPath(path)) {
                parts.add(new Part(path, "", 1));
            }
        }
        return parts;
    }

    static boolean looksLikeVideoPath(String path) {
        if (path == null) {
            return false;
        }
        String lower = path.trim().toLowerCase(Locale.ROOT);
        for (String extension : VIDEO_EXTENSIONS) {
            if (lower.endsWith(extension)) {
                return true;
            }
        }
        return false;
    }

    static final class Part {
        final String path;
        final String label;
        final int number;

        Part(String path, String label, int number) {
            this.path = path;
            this.label = label;
            this.number = number;
        }
    }
}
