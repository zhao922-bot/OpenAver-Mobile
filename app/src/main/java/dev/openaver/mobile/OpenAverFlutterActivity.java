package dev.openaver.mobile;

import android.Manifest;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import io.flutter.embedding.android.FlutterActivity;
import io.flutter.embedding.engine.FlutterEngine;
import io.flutter.embedding.engine.FlutterEngineCache;
import io.flutter.plugin.common.MethodCall;
import io.flutter.plugin.common.MethodChannel;

/**
 * Primary Flutter UI host Activity backed by the in-process Chaquopy Python
 * FastAPI server started by MainActivity.
 */
public final class OpenAverFlutterActivity extends FlutterActivity {
    public static final String CHANNEL_NAME = "dev.openaver.mobile/bridge";
    public static final int RESULT_EXIT_APP = 1001;
    public static final int RESULT_SWITCH_CLASSIC_WEB = 1002;
    public static final String EXTRA_TARGET_PATH = "target_path";

    private static final int REQUEST_ALL_FILES_ACCESS = 5101;
    private static final int REQUEST_LEGACY_STORAGE = 5102;
    private static final int REQUEST_STORAGE_TREE = 5103;
    private static final int REQUEST_PICK_FILE = 5104;

    private static final String PREFS_NAME = "openaver_mobile";
    private static final String PREF_UI_LOCALE = "ui_locale";
    private static final String PREF_UI_MODE = "ui_mode";
    private static final String DEFAULT_UI_LOCALE = "zh-CN";

    private MethodChannel bridgeChannel;
    private MethodChannel.Result pendingTreeResult;
    private MethodChannel.Result pendingPickFileResult;
    private MethodChannel.Result pendingPermissionResult;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (!MobileRuntimeSession.isReady()) {
            Intent intent = new Intent(this, MainActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            startActivity(intent);
            finish();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        AndroidCfTransport cfTransport = MobileRuntimeSession.getCfTransport();
        FrameLayout contentRoot = findViewById(android.R.id.content);
        if (cfTransport != null && contentRoot != null) {
            cfTransport.setHost(this, contentRoot);
        }
    }

    @Override
    public void onBackPressed() {
        AndroidCfTransport cfTransport = MobileRuntimeSession.getCfTransport();
        if (cfTransport != null && cfTransport.isOverlayVisible()) {
            cfTransport.hideOverlay();
            return;
        }
        super.onBackPressed();
    }

    @Nullable
    @Override
    public FlutterEngine provideFlutterEngine(@NonNull Context context) {
        FlutterEngine cached = FlutterEngineCache.getInstance().get(MobileRuntimeSession.FLUTTER_ENGINE_ID);
        return cached != null ? cached : super.provideFlutterEngine(context);
    }

    @Override
    public boolean shouldDestroyEngineWithHost() {
        return FlutterEngineCache.getInstance().get(MobileRuntimeSession.FLUTTER_ENGINE_ID) == null;
    }

    @Override
    public void configureFlutterEngine(@NonNull FlutterEngine flutterEngine) {
        FlutterEngine cached = FlutterEngineCache.getInstance().get(MobileRuntimeSession.FLUTTER_ENGINE_ID);
        if (cached != flutterEngine) {
            super.configureFlutterEngine(flutterEngine);
        }
        bridgeChannel = new MethodChannel(
                flutterEngine.getDartExecutor().getBinaryMessenger(),
                CHANNEL_NAME
        );
        bridgeChannel.setMethodCallHandler(this::handleMethodCall);
    }

    private void handleMethodCall(MethodCall call, MethodChannel.Result result) {
        switch (call.method) {
            case "getBootstrapInfo": {
                result.success(FlutterEngineManager.buildBootstrapPayload(this));
                break;
            }
            case "openExternalPlayer": {
                String path = call.argument("path");
                String parts = call.argument("parts");
                boolean handled = ExternalPlayer.openExternalDirect(
                        this,
                        path,
                        parts,
                        (selectedPath, partNumber, parsedParts) -> runOnUiThread(() -> {
                            if (bridgeChannel != null) {
                                List<Map<String, String>> serializedParts = new ArrayList<>();
                                for (VideoPartParser.Part item : parsedParts) {
                                    Map<String, String> entry = new HashMap<>();
                                    entry.put("path", item.path);
                                    entry.put("label", item.label);
                                    serializedParts.add(entry);
                                }
                                Map<String, Object> payload = new HashMap<>();
                                payload.put("path", selectedPath);
                                payload.put("part", partNumber);
                                payload.put("parts", serializedParts);
                                bridgeChannel.invokeMethod("openBuiltInPlayer", payload);
                            }
                        })
                );
                result.success(handled);
                break;
            }
            case "setTaskKeepAlive": {
                Boolean active = call.argument("active");
                if (Boolean.TRUE.equals(active)) {
                    TaskKeepAliveService.start(this);
                } else {
                    TaskKeepAliveService.stop(this);
                }
                result.success(null);
                break;
            }
            case "hasStorageAccess": {
                result.success(hasStorageAccess());
                break;
            }
            case "getStorageTreeInfo": {
                Map<String, Object> info = new HashMap<>();
                info.put("granted", StorageBridge.hasTreeAccess());
                info.put("description", StorageBridge.treeDescription());
                result.success(info);
                break;
            }
            case "openStoragePermission": {
                openStoragePermission(result);
                break;
            }
            case "openStorageTreePicker": {
                openStorageTreePicker(result);
                break;
            }
            case "clearStorageTree": {
                StorageBridge.clearTreeUri();
                result.success(null);
                break;
            }
            case "pickFile": {
                List<String> mimeTypes = call.argument("mimeTypes");
                openFilePicker(mimeTypes, result);
                break;
            }
            case "saveTempFileToDownloads": {
                String tempPath = call.argument("tempPath");
                String filename = call.argument("filename");
                String mimeType = call.argument("mimeType");
                result.success(saveToDownloads(tempPath, filename, mimeType));
                break;
            }
            case "syncNativeTheme": {
                String theme = call.argument("theme");
                if (theme != null) {
                    String mapped = "dark".equals(theme) ? "dim" : theme;
                    NativeUiTheme.apply(this, mapped);
                }
                result.success(null);
                break;
            }
            case "syncUiLocale": {
                String locale = call.argument("locale");
                if (locale != null && !locale.isEmpty()) {
                    getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                            .edit()
                            .putString(PREF_UI_LOCALE, locale)
                            .apply();
                }
                result.success(null);
                break;
            }
            case "openExternalUrl": {
                String url = call.argument("url");
                if (url != null && !url.isEmpty()) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                        result.success(true);
                    } catch (Exception ignored) {
                        Toast.makeText(this, R.string.external_browser_missing, Toast.LENGTH_SHORT).show();
                        result.success(false);
                    }
                } else {
                    result.success(false);
                }
                break;
            }
            case "switchToClassicWeb": {
                String path = call.argument("path");
                getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                        .edit()
                        .putString(PREF_UI_MODE, "web")
                        .apply();
                Intent data = new Intent();
                data.putExtra(EXTRA_TARGET_PATH, path == null || path.isEmpty() ? "/showcase" : path);
                setResult(RESULT_SWITCH_CLASSIC_WEB, data);
                result.success(true);
                finish();
                break;
            }
            case "exitApp": {
                setResult(RESULT_EXIT_APP);
                result.success(true);
                finish();
                break;
            }
            default:
                result.notImplemented();
                break;
        }
    }

    static boolean hasStorageAccess(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return context.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED
                    && context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED;
        }
        return Environment.isExternalStorageManager();
    }

    private boolean hasStorageAccess() {
        return hasStorageAccess(this);
    }

    private void openStoragePermission(MethodChannel.Result result) {
        if (pendingPermissionResult != null) {
            pendingPermissionResult.success(hasStorageAccess());
            pendingPermissionResult = null;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            if (hasStorageAccess()) {
                Intent appSettings = new Intent(
                        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())
                );
                startActivity(appSettings);
                result.success(true);
                return;
            }
            pendingPermissionResult = result;
            requestPermissions(
                    new String[]{
                            Manifest.permission.READ_EXTERNAL_STORAGE,
                            Manifest.permission.WRITE_EXTERNAL_STORAGE
                    },
                    REQUEST_LEGACY_STORAGE
            );
            return;
        }
        pendingPermissionResult = result;
        try {
            Intent intent = new Intent(
                    Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:" + getPackageName())
            );
            startActivityForResult(intent, REQUEST_ALL_FILES_ACCESS);
        } catch (Exception first) {
            try {
                Intent fallback = new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION);
                startActivityForResult(fallback, REQUEST_ALL_FILES_ACCESS);
            } catch (Exception second) {
                pendingPermissionResult = null;
                result.success(false);
            }
        }
    }

    private void openStorageTreePicker(MethodChannel.Result result) {
        if (pendingTreeResult != null) {
            pendingTreeResult.success(null);
            pendingTreeResult = null;
        }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        );
        try {
            pendingTreeResult = result;
            startActivityForResult(intent, REQUEST_STORAGE_TREE);
        } catch (Exception error) {
            pendingTreeResult = null;
            Toast.makeText(this, R.string.storage_tree_open_failed, Toast.LENGTH_LONG).show();
            result.success(null);
        }
    }

    private void openFilePicker(List<String> mimeTypes, MethodChannel.Result result) {
        if (pendingPickFileResult != null) {
            pendingPickFileResult.success(null);
            pendingPickFileResult = null;
        }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        if (mimeTypes != null && !mimeTypes.isEmpty()) {
            intent.putExtra(Intent.EXTRA_MIME_TYPES, mimeTypes.toArray(new String[0]));
        }
        try {
            pendingPickFileResult = result;
            startActivityForResult(
                    Intent.createChooser(intent, getString(R.string.file_chooser_title)),
                    REQUEST_PICK_FILE
            );
        } catch (Exception error) {
            pendingPickFileResult = null;
            result.success(null);
        }
    }

    private Map<String, Object> copyPickedUriToCache(Uri uri) {
        if (uri == null) {
            return null;
        }
        ContentResolver resolver = getContentResolver();
        String name = "upload.bin";
        long size = 0L;
        try (Cursor cursor = resolver.query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int nameIdx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                int sizeIdx = cursor.getColumnIndex(OpenableColumns.SIZE);
                if (nameIdx >= 0) {
                    String candidate = cursor.getString(nameIdx);
                    if (candidate != null && !candidate.trim().isEmpty()) {
                        name = candidate.replace('/', '_').replace('\\', '_');
                    }
                }
                if (sizeIdx >= 0) {
                    size = cursor.getLong(sizeIdx);
                }
            }
        } catch (Exception ignored) {
        }

        File pickedDir = new File(getCacheDir(), "picked");
        if (!pickedDir.exists()) {
            pickedDir.mkdirs();
        }
        File target = new File(pickedDir, System.currentTimeMillis() + "_" + name);
        try (InputStream in = resolver.openInputStream(uri);
             OutputStream out = new FileOutputStream(target)) {
            if (in == null) {
                return null;
            }
            byte[] buffer = new byte[65536];
            int read;
            long total = 0L;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
                total += read;
            }
            out.flush();
            if (size <= 0L) {
                size = total;
            }
            Map<String, Object> payload = new HashMap<>();
            payload.put("path", target.getAbsolutePath());
            payload.put("name", name);
            payload.put("size", size);
            return payload;
        } catch (Exception error) {
            target.delete();
            return null;
        }
    }

    private String saveToDownloads(String tempPath, String filename, String mimeType) {
        if (tempPath == null || filename == null || filename.isEmpty()) {
            return null;
        }
        File source = new File(tempPath);
        if (!source.isFile()) {
            return null;
        }
        String resolvedMime = (mimeType == null || mimeType.isEmpty())
                ? "application/octet-stream"
                : mimeType;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentResolver resolver = getContentResolver();
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, filename);
            values.put(MediaStore.Downloads.MIME_TYPE, resolvedMime);
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/OpenAver");
            values.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri item = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (item == null) {
                return null;
            }
            try (InputStream in = new FileInputStream(source);
                 OutputStream out = resolver.openOutputStream(item)) {
                if (out == null) {
                    return null;
                }
                byte[] buf = new byte[65536];
                int read;
                while ((read = in.read(buf)) != -1) {
                    out.write(buf, 0, read);
                }
                out.flush();
            } catch (Exception error) {
                resolver.delete(item, null, null);
                return null;
            }
            ContentValues done = new ContentValues();
            done.put(MediaStore.Downloads.IS_PENDING, 0);
            resolver.update(item, done, null, null);
            return "Download/OpenAver/" + filename;
        }
        File downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        File targetDir = new File(downloads, "OpenAver");
        if (!targetDir.exists()) {
            targetDir.mkdirs();
        }
        File target = new File(targetDir, filename);
        try (InputStream in = new FileInputStream(source);
             OutputStream out = new FileOutputStream(target)) {
            byte[] buf = new byte[65536];
            int read;
            while ((read = in.read(buf)) != -1) {
                out.write(buf, 0, read);
            }
            out.flush();
            return target.getAbsolutePath();
        } catch (Exception error) {
            return null;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQUEST_ALL_FILES_ACCESS) {
            if (pendingPermissionResult != null) {
                pendingPermissionResult.success(hasStorageAccess());
                pendingPermissionResult = null;
            }
            return;
        }
        if (requestCode == REQUEST_STORAGE_TREE) {
            MethodChannel.Result callback = pendingTreeResult;
            pendingTreeResult = null;
            if (callback != null) {
                if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                    String error = StorageBridge.setTreeUri(this, data.getData());
                    Map<String, Object> resp = new HashMap<>();
                    resp.put("granted", error == null);
                    resp.put("description", StorageBridge.treeDescription());
                    if (error != null) {
                        resp.put("error", error);
                    }
                    callback.success(resp);
                } else {
                    callback.success(null);
                }
            }
            return;
        }
        if (requestCode == REQUEST_PICK_FILE) {
            MethodChannel.Result callback = pendingPickFileResult;
            pendingPickFileResult = null;
            if (callback != null) {
                if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                    callback.success(copyPickedUriToCache(data.getData()));
                } else {
                    callback.success(null);
                }
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            @NonNull String[] permissions,
            @NonNull int[] grantResults
    ) {
        if (requestCode == REQUEST_LEGACY_STORAGE) {
            if (pendingPermissionResult != null) {
                pendingPermissionResult.success(hasStorageAccess());
                pendingPermissionResult = null;
            }
            return;
        }
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
    }
}
