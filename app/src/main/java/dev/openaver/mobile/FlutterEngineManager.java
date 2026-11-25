package dev.openaver.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import java.util.HashMap;
import java.util.Map;

import io.flutter.embedding.engine.FlutterEngine;
import io.flutter.embedding.engine.FlutterEngineCache;
import io.flutter.embedding.engine.dart.DartExecutor;
import io.flutter.plugin.common.MethodCall;
import io.flutter.plugin.common.MethodChannel;

/**
 * Manages the pre-warmed cached FlutterEngine so MainActivity can overlap
 * Flutter/Impeller initialization with background Chaquopy Python startup.
 */
final class FlutterEngineManager {
    private static final String TAG = "OpenAverFlutter";
    private static final String PREFS_NAME = "openaver_mobile";
    private static final String PREF_UI_LOCALE = "ui_locale";
    private static final String DEFAULT_UI_LOCALE = "zh-CN";

    private FlutterEngineManager() {
    }

    static FlutterEngine prewarm(Context appContext) {
        FlutterEngineCache cache = FlutterEngineCache.getInstance();
        FlutterEngine existing = cache.get(MobileRuntimeSession.FLUTTER_ENGINE_ID);
        if (existing != null) {
            return existing;
        }
        try {
            FlutterEngine engine = new FlutterEngine(appContext.getApplicationContext());
            MethodChannel channel = new MethodChannel(
                    engine.getDartExecutor().getBinaryMessenger(),
                    OpenAverFlutterActivity.CHANNEL_NAME
            );
            installBackgroundBridge(channel, appContext);
            engine.getDartExecutor().executeDartEntrypoint(
                    DartExecutor.DartEntrypoint.createDefault()
            );
            cache.put(MobileRuntimeSession.FLUTTER_ENGINE_ID, engine);
            return engine;
        } catch (Throwable error) {
            Log.w(TAG, "FlutterEngine prewarm skipped; falling back to on-demand engine", error);
            return null;
        }
    }

    static void installBackgroundBridge(MethodChannel channel, Context context) {
        Context appContext = context.getApplicationContext();
        channel.setMethodCallHandler((call, result) -> {
            switch (call.method) {
                case "getBootstrapInfo":
                    result.success(buildBootstrapPayload(appContext));
                    break;
                case "syncNativeTheme":
                case "syncUiLocale":
                    result.success(null);
                    break;
                case "consumeTaskCenterRequest":
                    result.success(false);
                    break;
                case "setTaskKeepAlive":
                    TaskKeepAliveService.setFlutterActive(
                            appContext, Boolean.TRUE.equals(call.argument("active")));
                    result.success(null);
                    break;
                case "updateTaskNotification":
                    updateTaskNotification(call);
                    result.success(null);
                    break;
                default:
                    PlaybackStore.handle(appContext, call, result);
                    break;
            }
        });
    }

    static void updateTaskNotification(MethodCall call) {
        Number taskCount = call.argument("taskCount");
        Number progressCurrent = call.argument("progressCurrent");
        Number progressTotal = call.argument("progressTotal");
        TaskKeepAliveService.updateFlutterNotification(
                taskCount == null ? 0 : taskCount.intValue(),
                progressCurrent == null ? 0 : progressCurrent.intValue(),
                progressCurrent == null || progressTotal == null ? 0 : progressTotal.intValue(),
                call.argument("taskSummary")
        );
    }

    static void notifyRuntimeReady(Context context) {
        FlutterEngine engine = FlutterEngineCache.getInstance().get(MobileRuntimeSession.FLUTTER_ENGINE_ID);
        if (engine == null) {
            return;
        }
        try {
            MethodChannel channel = new MethodChannel(
                    engine.getDartExecutor().getBinaryMessenger(),
                    OpenAverFlutterActivity.CHANNEL_NAME
            );
            channel.invokeMethod("onRuntimeReady", buildBootstrapPayload(context));
        } catch (Throwable error) {
            Log.w(TAG, "Failed to notify prewarmed engine of runtime readiness", error);
        }
    }

    static Map<String, Object> buildBootstrapPayload(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        SharedPreferences themePrefs = context.getSharedPreferences("native_appearance", Context.MODE_PRIVATE);
        Map<String, Object> info = new HashMap<>();
        info.put("ready", MobileRuntimeSession.isReady());
        info.put("port", MobileRuntimeSession.getPort());
        info.put("token", MobileRuntimeSession.getAuthToken());
        info.put("cookieName", MobileRuntimeSession.getAuthCookieName());
        info.put("dataDir", MobileRuntimeSession.getDataDir());
        info.put("version", BuildConfig.VERSION_NAME);
        info.put("openaverRelease", BuildConfig.OPENAVER_RELEASE);
        info.put("openaverCommit", BuildConfig.OPENAVER_COMMIT);
        info.put("abi", MobileRuntimeSession.getAbi());
        info.put("uiLocale", prefs.getString(PREF_UI_LOCALE, DEFAULT_UI_LOCALE));
        info.put("theme", themePrefs.getString("theme", "dim"));
        info.put("hasStorageAccess", OpenAverFlutterActivity.hasStorageAccess(context));
        info.put("hasTreeAccess", StorageBridge.hasTreeAccess());
        info.put("treeDescription", StorageBridge.treeDescription());
        return info;
    }

    static void destroy() {
        FlutterEngineCache cache = FlutterEngineCache.getInstance();
        FlutterEngine engine = cache.get(MobileRuntimeSession.FLUTTER_ENGINE_ID);
        if (engine != null) {
            cache.remove(MobileRuntimeSession.FLUTTER_ENGINE_ID);
            try {
                engine.destroy();
            } catch (Throwable error) {
                Log.w(TAG, "Error destroying cached FlutterEngine", error);
            }
        }
    }
}
