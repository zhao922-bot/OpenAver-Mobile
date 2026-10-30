package dev.openaver.mobile;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;

/**
 * Writes files below a user-granted Storage Access Framework tree.
 *
 * Android 10 grants legacy reads from a removable SD card but still rejects
 * arbitrary writes outside a SAF tree. Python uses this bridge only after a
 * direct filesystem write fails.
 */
public final class StorageBridge {
    private static final String PREFS = "openaver_storage";
    private static final String TREE_URI = "tree_uri";
    private static final Object LOCK = new Object();

    private static Context context;

    private StorageBridge() {
    }

    public static void initialize(Context source) {
        context = source.getApplicationContext();
    }

    public static boolean hasTreeAccess() {
        Uri tree = treeUri();
        return context != null && tree != null && hasPersistedWriteAccess(tree);
    }

    public static String treeDescription() {
        Uri tree = treeUri();
        if (tree == null) {
            return "";
        }
        try {
            return DocumentsContract.getTreeDocumentId(tree);
        } catch (Exception ignored) {
            return tree.toString();
        }
    }

    public static String setTreeUri(Activity activity, Uri tree) {
        if (activity == null || tree == null) {
            return "missing_tree_uri";
        }
        try {
            int flags = Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_GRANT_WRITE_URI_PERMISSION;
            activity.getContentResolver().takePersistableUriPermission(tree, flags);
            preferences().edit().putString(TREE_URI, tree.toString()).apply();
            return null;
        } catch (Exception error) {
            return error.getClass().getSimpleName() + ": " + error.getMessage();
        }
    }

    public static String clearTreeUri() {
        if (context == null) {
            return "bridge_not_initialized";
        }
        preferences().edit().remove(TREE_URI).apply();
        return null;
    }

    public static boolean hasAccessForPath(String path) {
        synchronized (LOCK) {
            try {
                Uri tree = treeUri();
                return tree != null
                        && hasPersistedWriteAccess(tree)
                        && relativePath(path) != null;
            } catch (Exception ignored) {
                return false;
            }
        }
    }

    public static boolean exists(String path) {
        synchronized (LOCK) {
            try {
                return findDocument(path) != null;
            } catch (Exception ignored) {
                return false;
            }
        }
    }

    public static Uri documentUriForPath(String path) {
        synchronized (LOCK) {
            try {
                if (!hasTreeAccess()) {
                    return null;
                }
                return findDocument(path);
            } catch (Exception ignored) {
                return null;
            }
        }
    }

    public static String mkdirs(String path) {
        synchronized (LOCK) {
            try {
                return resolveDirectory(path, true) == null ? "document_not_found" : null;
            } catch (Exception error) {
                return errorText(error);
            }
        }
    }

    public static String delete(String path) {
        synchronized (LOCK) {
            try {
                Uri document = findDocument(path);
                if (document == null) {
                    return null;
                }
                return DocumentsContract.deleteDocument(resolver(), document)
                        ? null : "delete_failed";
            } catch (Exception error) {
                return errorText(error);
            }
        }
    }

    public static String writeBytes(String path, byte[] data, boolean createParents) {
        synchronized (LOCK) {
            Uri existing = null;
            byte[] previous = null;
            boolean created = false;
            try {
                existing = findDocument(path);
                if (existing != null) {
                    previous = readAll(resolver().openInputStream(existing));
                } else {
                    if (!createParents) {
                        return "document_not_found";
                    }
                    existing = createDocument(path);
                    created = true;
                    if (existing == null) {
                        return "document_create_failed";
                    }
                }

                writeAll(existing, data);
                byte[] actual = readAll(resolver().openInputStream(existing));
                if (!Arrays.equals(data, actual)) {
                    if (created) {
                        DocumentsContract.deleteDocument(resolver(), existing);
                    } else if (previous != null) {
                        writeAll(existing, previous);
                    }
                    return "verify_failed";
                }
                return null;
            } catch (Exception error) {
                if (existing != null) {
                    try {
                        if (created) {
                            DocumentsContract.deleteDocument(resolver(), existing);
                        } else if (previous != null) {
                            writeAll(existing, previous);
                        }
                    } catch (Exception ignored) {
                        // The original write error is the useful diagnostic.
                    }
                }
                return errorText(error);
            }
        }
    }

    private static SharedPreferences preferences() {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static ContentResolver resolver() {
        if (context == null) {
            throw new IllegalStateException("bridge_not_initialized");
        }
        return context.getContentResolver();
    }

    private static Uri treeUri() {
        if (context == null) {
            return null;
        }
        String value = preferences().getString(TREE_URI, "");
        return value == null || value.isEmpty() ? null : Uri.parse(value);
    }

    private static boolean hasPersistedWriteAccess(Uri tree) {
        if (context == null) {
            return false;
        }
        for (UriPermission permission :
                context.getContentResolver().getPersistedUriPermissions()) {
            if (permission.getUri().equals(tree)
                    && permission.isReadPermission()
                    && permission.isWritePermission()) {
                return true;
            }
        }
        return false;
    }

    private static String relativePath(String absolutePath) {
        Uri tree = treeUri();
        if (tree == null || absolutePath == null || absolutePath.isEmpty()) {
            return null;
        }

        String treeId = DocumentsContract.getTreeDocumentId(tree);
        int colon = treeId.indexOf(':');
        if (colon < 0) {
            return null;
        }
        String treeVolume = treeId.substring(0, colon);
        String treePath = trimSlashes(treeId.substring(colon + 1));

        String normalized = new File(absolutePath).getAbsolutePath().replace('\\', '/');
        String volume;
        String relative;
        if (normalized.equals("/storage/emulated/0")
                || normalized.startsWith("/storage/emulated/0/")) {
            volume = "primary";
            relative = normalized.substring("/storage/emulated/0".length());
        } else if (normalized.equals("/storage/self/primary")
                || normalized.startsWith("/storage/self/primary/")) {
            volume = "primary";
            relative = normalized.substring("/storage/self/primary".length());
        } else if (normalized.startsWith("/storage/")) {
            String rest = normalized.substring("/storage/".length());
            int slash = rest.indexOf('/');
            volume = slash < 0 ? rest : rest.substring(0, slash);
            relative = slash < 0 ? "" : rest.substring(slash);
        } else if (normalized.startsWith("/mnt/media_rw/")) {
            String rest = normalized.substring("/mnt/media_rw/".length());
            int slash = rest.indexOf('/');
            volume = slash < 0 ? rest : rest.substring(0, slash);
            relative = slash < 0 ? "" : rest.substring(slash);
        } else {
            return null;
        }

        if (!treeVolume.equals(volume)) {
            return null;
        }
        relative = trimSlashes(relative);
        if (!treePath.isEmpty()) {
            if (relative.equals(treePath)) {
                return "";
            }
            if (!relative.startsWith(treePath + "/")) {
                return null;
            }
            relative = relative.substring(treePath.length() + 1);
        }
        return relative;
    }

    private static Uri findDocument(String path) {
        Uri tree = treeUri();
        String relative = relativePath(path);
        if (tree == null || relative == null || relative.isEmpty()) {
            return null;
        }
        String treeId = DocumentsContract.getTreeDocumentId(tree);
        Uri candidate = DocumentsContract.buildDocumentUriUsingTree(
                tree, treeId + "/" + relative
        );
        return documentExists(candidate) ? candidate : null;
    }

    private static Uri resolveDirectory(String path, boolean create) throws IOException {
        Uri tree = treeUri();
        String relative = relativePath(path);
        if (tree == null || relative == null) {
            throw new IOException("path_outside_tree");
        }
        String treeId = DocumentsContract.getTreeDocumentId(tree);
        Uri current = DocumentsContract.buildDocumentUriUsingTree(tree, treeId);
        if (relative.isEmpty()) {
            return current;
        }
        String[] segments = relative.split("/");
        for (String segment : segments) {
            if (segment.isEmpty()) {
                continue;
            }
            String childId = documentId(current) + "/" + segment;
            Uri child = DocumentsContract.buildDocumentUriUsingTree(tree, childId);
            if (documentExists(child)) {
                current = child;
            } else if (create) {
                current = DocumentsContract.createDocument(
                        resolver(), current,
                        DocumentsContract.Document.MIME_TYPE_DIR,
                        segment
                );
                if (current == null) {
                    throw new IOException("directory_create_failed: " + segment);
                }
            } else {
                return null;
            }
        }
        return current;
    }

    private static Uri createDocument(String path) throws IOException {
        String relative = relativePath(path);
        if (relative == null || relative.isEmpty()) {
            return null;
        }
        int slash = relative.lastIndexOf('/');
        String parentPath = slash < 0 ? "" : relative.substring(0, slash);
        String name = slash < 0 ? relative : relative.substring(slash + 1);
        Uri tree = treeUri();
        String parentId = DocumentsContract.getTreeDocumentId(tree);
        if (!parentPath.isEmpty()) {
            parentId += "/" + parentPath;
        }
        Uri parent = resolveDirectoryById(tree, parentId, true);
        return DocumentsContract.createDocument(
                resolver(), parent, mimeType(name), name
        );
    }

    private static Uri resolveDirectoryById(Uri tree, String documentId, boolean create)
            throws IOException {
        String rootId = DocumentsContract.getTreeDocumentId(tree);
        Uri current = DocumentsContract.buildDocumentUriUsingTree(tree, rootId);
        if (documentId.equals(rootId)) {
            return current;
        }
        String suffix = documentId.substring(rootId.length());
        for (String segment : suffix.split("/")) {
            if (segment.isEmpty()) {
                continue;
            }
            String childId = DocumentsContract.getDocumentId(current) + "/" + segment;
            Uri child = DocumentsContract.buildDocumentUriUsingTree(tree, childId);
            if (documentExists(child)) {
                current = child;
            } else if (create) {
                current = DocumentsContract.createDocument(
                        resolver(), current,
                        DocumentsContract.Document.MIME_TYPE_DIR,
                        segment
                );
                if (current == null) {
                    throw new IOException("directory_create_failed: " + segment);
                }
            } else {
                throw new IOException("directory_not_found: " + segment);
            }
        }
        return current;
    }

    private static boolean documentExists(Uri document) {
        try (Cursor cursor = resolver().query(
                document,
                new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID},
                null, null, null
        )) {
            return cursor != null && cursor.moveToFirst();
        } catch (Exception ignored) {
            return false;
        }
    }

    private static String documentId(Uri document) {
        try (Cursor cursor = resolver().query(
                document,
                new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID},
                null, null, null
        )) {
            if (cursor != null && cursor.moveToFirst()) {
                return cursor.getString(0);
            }
        } catch (Exception ignored) {
            // Fall through to DocumentsContract's URI identity.
        }
        return DocumentsContract.getDocumentId(document);
    }

    private static void writeAll(Uri document, byte[] data) throws IOException {
        try (ParcelFileDescriptor descriptor =
                     resolver().openFileDescriptor(document, "wt")) {
            if (descriptor == null) {
                throw new IOException("document_open_failed");
            }
            try (FileOutputStream output =
                         new FileOutputStream(descriptor.getFileDescriptor())) {
                output.write(data);
                output.flush();
                descriptor.getFileDescriptor().sync();
            }
        }
    }

    private static byte[] readAll(InputStream input) throws IOException {
        if (input == null) {
            throw new IOException("document_read_failed");
        }
        try (InputStream source = input;
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = source.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }

    private static String mimeType(String name) {
        String lower = name.toLowerCase();
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
            return "image/jpeg";
        }
        if (lower.endsWith(".png")) {
            return "image/png";
        }
        if (lower.endsWith(".webp")) {
            return "image/webp";
        }
        if (lower.endsWith(".nfo") || lower.endsWith(".xml")) {
            return "application/xml";
        }
        return "application/octet-stream";
    }

    private static String trimSlashes(String value) {
        String result = value == null ? "" : value;
        while (result.startsWith("/")) {
            result = result.substring(1);
        }
        while (result.endsWith("/")) {
            result = result.substring(0, result.length() - 1);
        }
        return result;
    }

    private static String errorText(Exception error) {
        String message = error.getMessage();
        return error.getClass().getSimpleName()
                + (message == null || message.isEmpty() ? "" : ": " + message);
    }
}
