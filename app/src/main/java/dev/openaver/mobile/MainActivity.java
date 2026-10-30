package dev.openaver.mobile;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewConfiguration;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;
import android.system.Os;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String TAG = "OpenAverStartup";
    private static final String LOCAL_HOST = "127.0.0.1";
    private static final int LOCAL_PORT = 8765;
    private static final int REQUEST_FILE_CHOOSER = 4101;
    private static final int REQUEST_ALL_FILES_ACCESS = 4102;
    private static final int REQUEST_LEGACY_STORAGE = 4103;
    private static final int REQUEST_STORAGE_TREE = 4104;
    private static final long EXIT_BACK_WINDOW_MS = 2000L;
    private static final long PAGE_LOAD_TIMEOUT_MS = 30000L;
    private static final long LOCAL_START_TIMEOUT_MS = 300_000L;
    private static final boolean NATIVE_LOADED;
    private static final String PREFS_NAME = "openaver_mobile";
    private static final String PREF_UI_LOCALE = "ui_locale";
    private static final String PREF_MENU_HANDLE_X = "menu_handle_x";
    private static final String PREF_MENU_HANDLE_Y = "menu_handle_y";
    private static final String DEFAULT_UI_LOCALE = "zh-CN";

    static {
        boolean loaded = false;
        try {
            System.loadLibrary("openaver_mobile");
            loaded = true;
        } catch (UnsatisfiedLinkError ignored) {
            // ABI reporting is informational; the embedded Python runtime is separate.
        }
        NATIVE_LOADED = loaded;
    }

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService runtimeExecutor = Executors.newSingleThreadExecutor();

    private FrameLayout root;
    private ScrollView setupScroll;
    private TextView permissionLabel;
    private TextView permissionTitle;
    private TextView permissionBody;
    private TextView localStep1Title;
    private TextView localStep1Body;
    private TextView permissionStatus;
    private TextView storagePathText;
    private Button permissionButton;
    private FrameLayout webContainer;
    private WebView webView;
    private ProgressBar pageProgress;
    private LinearLayout webError;
    private ImageButton menuHandle;
    private FrameLayout loadingOverlay;
    private TextView loadingText;
    private FrameLayout fullscreenContainer;
    private AndroidCfTransport cfTransport;
    private CfShellAgent cfShell;

    private Runnable pageLoadTimeout;
    private ValueCallback<Uri[]> filePathCallback;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;
    private boolean webPageLoading;
    private boolean webBackDispatchPending;
    private boolean runtimeStarting;
    private boolean runtimeReady;
    private boolean runtimeFailed;
    private volatile int localPort = LOCAL_PORT;
    private volatile String localAuthToken = "";
    private volatile String localAuthCookieName = "";
    private long lastBackPressMs;
    private SharedPreferences preferences;
    private float menuTouchDownRawX;
    private float menuTouchDownRawY;
    private int menuDragStartLeft;
    private int menuDragStartTop;
    private int menuTouchSlop;
    private boolean menuTouchMoved;
    private boolean menuHandleTouching;

    private static native String nativeAbi();

    @Override
    protected void attachBaseContext(Context newBase) {
        SharedPreferences preferences =
                newBase.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String localeTag = preferences.getString(PREF_UI_LOCALE, DEFAULT_UI_LOCALE);
        Locale locale = Locale.forLanguageTag(localeTag);
        Locale.setDefault(locale);
        Configuration configuration = new Configuration(
                newBase.getResources().getConfiguration()
        );
        configuration.setLocale(locale);
        super.attachBaseContext(newBase.createConfigurationContext(configuration));
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        StorageBridge.initialize(this);
        preferences = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);

        pageLoadTimeout = () -> {
            if (webPageLoading) {
                showPageError();
            }
        };

        bindViews();
        configureSystemBars();
        configureMenuHandle();
        configureSetupUi();
        configureErrorUi();
        configureWebView();
        updatePermissionUi();

        if (hasStorageAccess()) {
            mainHandler.postDelayed(this::startEmbeddedRuntime, 250L);
        }
    }

    private void bindViews() {
        root = findViewById(R.id.root);
        setupScroll = findViewById(R.id.setupScroll);
        permissionLabel = findViewById(R.id.permissionLabel);
        permissionTitle = findViewById(R.id.permissionTitle);
        permissionBody = findViewById(R.id.permissionBody);
        localStep1Title = findViewById(R.id.localStep1Title);
        localStep1Body = findViewById(R.id.localStep1Body);
        permissionStatus = findViewById(R.id.permissionStatus);
        permissionStatus.setTextIsSelectable(true);
        storagePathText = findViewById(R.id.storagePathText);
        permissionButton = findViewById(R.id.permissionButton);
        webContainer = findViewById(R.id.webContainer);
        webView = findViewById(R.id.webView);
        pageProgress = findViewById(R.id.pageProgress);
        webError = findViewById(R.id.webError);
        menuHandle = findViewById(R.id.menuHandle);
        loadingOverlay = findViewById(R.id.loadingOverlay);
        loadingText = findViewById(R.id.loadingText);
        fullscreenContainer = findViewById(R.id.fullscreenContainer);
    }

    @SuppressLint("ClickableViewAccessibility")
    private void configureMenuHandle() {
        menuTouchSlop = Math.max(
                ViewConfiguration.get(this).getScaledTouchSlop(),
                Math.round(8f * getResources().getDisplayMetrics().density)
        );
        menuHandle.setOnClickListener(view -> showWebMenu());
        menuHandle.setOnTouchListener((view, event) -> {
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    menuHandleTouching = true;
                    menuTouchMoved = false;
                    menuTouchDownRawX = event.getRawX();
                    menuTouchDownRawY = event.getRawY();
                    menuDragStartLeft = view.getLeft();
                    menuDragStartTop = view.getTop();
                    view.getParent().requestDisallowInterceptTouchEvent(true);
                    return true;
                case MotionEvent.ACTION_MOVE:
                    if (!menuTouchMoved) {
                        float dx = event.getRawX() - menuTouchDownRawX;
                        float dy = event.getRawY() - menuTouchDownRawY;
                        menuTouchMoved = Math.hypot(dx, dy) >= menuTouchSlop;
                    }
                    if (menuTouchMoved) {
                        moveMenuHandle(
                                menuDragStartLeft + Math.round(event.getRawX() - menuTouchDownRawX),
                                menuDragStartTop + Math.round(event.getRawY() - menuTouchDownRawY)
                        );
                    }
                    return true;
                case MotionEvent.ACTION_UP:
                    menuHandleTouching = false;
                    view.getParent().requestDisallowInterceptTouchEvent(false);
                    if (menuTouchMoved) {
                        view.post(this::saveMenuHandlePosition);
                    } else {
                        view.performClick();
                    }
                    return true;
                case MotionEvent.ACTION_CANCEL:
                    menuHandleTouching = false;
                    view.getParent().requestDisallowInterceptTouchEvent(false);
                    if (menuTouchMoved) {
                        view.post(this::saveMenuHandlePosition);
                    }
                    return true;
                default:
                    return false;
            }
        });
        root.addOnLayoutChangeListener((view, left, top, right, bottom,
                                        oldLeft, oldTop, oldRight, oldBottom) -> {
            int width = right - left;
            int height = bottom - top;
            int oldWidth = oldRight - oldLeft;
            int oldHeight = oldBottom - oldTop;
            if (width != oldWidth || height != oldHeight) {
                view.post(this::applySavedMenuHandlePosition);
            }
        });
        root.post(this::applySavedMenuHandlePosition);
    }

    private void moveMenuHandle(int requestedLeft, int requestedTop) {
        if (root == null || menuHandle == null) {
            return;
        }
        int availableWidth = root.getWidth() - root.getPaddingLeft()
                - root.getPaddingRight() - menuHandle.getWidth();
        int availableHeight = root.getHeight() - root.getPaddingTop()
                - root.getPaddingBottom() - menuHandle.getHeight();
        int left = clamp(requestedLeft, root.getPaddingLeft(),
                root.getPaddingLeft() + Math.max(0, availableWidth));
        int top = clamp(requestedTop, root.getPaddingTop(),
                root.getPaddingTop() + Math.max(0, availableHeight));

        FrameLayout.LayoutParams params =
                (FrameLayout.LayoutParams) menuHandle.getLayoutParams();
        params.gravity = Gravity.TOP | Gravity.START;
        params.leftMargin = left - root.getPaddingLeft();
        params.topMargin = top - root.getPaddingTop();
        menuHandle.setLayoutParams(params);
    }

    private void saveMenuHandlePosition() {
        if (root == null || menuHandle == null) {
            return;
        }
        int availableWidth = root.getWidth() - root.getPaddingLeft()
                - root.getPaddingRight() - menuHandle.getWidth();
        int availableHeight = root.getHeight() - root.getPaddingTop()
                - root.getPaddingBottom() - menuHandle.getHeight();
        int rootLeft = webContainer.getLeft() + menuHandle.getLeft();
        int rootTop = webContainer.getTop() + menuHandle.getTop();
        float x = availableWidth > 0
                ? (rootLeft - root.getPaddingLeft()) / (float) availableWidth
                : 0f;
        float y = availableHeight > 0
                ? (rootTop - root.getPaddingTop()) / (float) availableHeight
                : 0.5f;
        preferences.edit()
                .putFloat(PREF_MENU_HANDLE_X, clamp(x, 0f, 1f))
                .putFloat(PREF_MENU_HANDLE_Y, clamp(y, 0f, 1f))
                .apply();
    }

    private void applySavedMenuHandlePosition() {
        if (root == null || menuHandle == null || root.getWidth() == 0
                || menuHandle.getWidth() == 0 || menuHandleTouching) {
            return;
        }
        float savedX = preferences.getFloat(PREF_MENU_HANDLE_X, Float.NaN);
        float savedY = preferences.getFloat(PREF_MENU_HANDLE_Y, Float.NaN);
        if (Float.isNaN(savedX) || Float.isNaN(savedY)) {
            FrameLayout.LayoutParams params =
                    (FrameLayout.LayoutParams) menuHandle.getLayoutParams();
            params.gravity = Gravity.END | Gravity.CENTER_VERTICAL;
            params.leftMargin = 0;
            params.topMargin = 0;
            menuHandle.setLayoutParams(params);
            return;
        }

        int availableWidth = root.getWidth() - root.getPaddingLeft()
                - root.getPaddingRight() - menuHandle.getWidth();
        int availableHeight = root.getHeight() - root.getPaddingTop()
                - root.getPaddingBottom() - menuHandle.getHeight();
        int left = root.getPaddingLeft()
                + Math.round(clamp(savedX, 0f, 1f) * Math.max(0, availableWidth));
        int top = root.getPaddingTop()
                + Math.round(clamp(savedY, 0f, 1f) * Math.max(0, availableHeight));
        moveMenuHandle(left, top);
    }

    private static int clamp(int value, int minimum, int maximum) {
        return Math.max(minimum, Math.min(value, maximum));
    }

    private static float clamp(float value, float minimum, float maximum) {
        return Math.max(minimum, Math.min(value, maximum));
    }

    private void configureSystemBars() {
        Window window = getWindow();
        window.setStatusBarColor(getColor(R.color.bg));
        window.setNavigationBarColor(getColor(R.color.bg));
        window.setNavigationBarContrastEnforced(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets bars = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout()
                );
                view.setPadding(0, bars.top, 0, bars.bottom);
                view.post(this::applySavedMenuHandlePosition);
                return insets;
            });
            root.requestApplyInsets();
        } else {
            root.setFitsSystemWindows(true);
        }
    }

    private void configureSetupUi() {
        boolean legacyStorage = usesLegacyStorage();
        TextView releasePill = findViewById(R.id.releasePill);
        releasePill.setText(getString(R.string.release_badge, BuildConfig.OPENAVER_RELEASE));
        permissionLabel.setText(legacyStorage
                ? R.string.permission_label_legacy
                : R.string.permission_label);
        permissionTitle.setText(legacyStorage
                ? R.string.permission_title_legacy
                : R.string.permission_title);
        permissionBody.setText(legacyStorage
                ? R.string.permission_body_legacy
                : R.string.permission_body);
        localStep1Title.setText(legacyStorage
                ? R.string.local_step1_title_legacy
                : R.string.local_step1_title);
        localStep1Body.setText(legacyStorage
                ? R.string.local_step1_body_legacy
                : R.string.local_step1_body);
        storagePathText.setText(getString(
                R.string.storage_root,
                Environment.getExternalStorageDirectory().getAbsolutePath()
        ));
        permissionButton.setOnClickListener(view -> {
            if (runtimeFailed && hasStorageAccess() && !runtimeStarting) {
                startEmbeddedRuntime();
            } else {
                openStoragePermission();
            }
        });
    }

    private void configureErrorUi() {
        Button retryButton = findViewById(R.id.errorRetryButton);
        Button storageButton = findViewById(R.id.errorServerButton);
        retryButton.setOnClickListener(view -> {
            if (!hasStorageAccess()) {
                showPermissionUi();
                openStoragePermission();
                return;
            }
            webError.setVisibility(View.GONE);
            if (runtimeReady) {
                refreshWeb();
            } else {
                startEmbeddedRuntime();
            }
        });
        storageButton.setText(storagePermissionButtonText());
        storageButton.setOnClickListener(view -> openStoragePermission());
    }

    private void updatePermissionUi() {
        boolean granted = hasStorageAccess();
        boolean legacyStorage = usesLegacyStorage();
        permissionButton.setText(runtimeFailed && granted
                ? R.string.retry_start_local
                : (granted
                    ? R.string.menu_storage_settings
                    : storagePermissionButtonText()));
        permissionStatus.setText(granted
                ? (legacyStorage
                    ? R.string.permission_granted_legacy
                    : R.string.permission_granted)
                : (legacyStorage
                    ? R.string.permission_required_legacy
                    : R.string.permission_required));
        permissionStatus.setTextColor(getColor(granted ? R.color.accent_mint : R.color.warm));
        permissionStatus.setVisibility(View.VISIBLE);
    }

    private void showPermissionUi() {
        webContainer.setVisibility(View.GONE);
        setupScroll.setVisibility(View.VISIBLE);
        hideLoading();
        updatePermissionUi();
    }

    private boolean hasStorageAccess() {
        if (usesLegacyStorage()) {
            return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED
                    && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED;
        }
        return Environment.isExternalStorageManager();
    }

    private boolean usesLegacyStorage() {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.R;
    }

    private int storagePermissionButtonText() {
        return usesLegacyStorage()
                ? R.string.open_permission_settings_legacy
                : R.string.open_permission_settings;
    }

    private void openStoragePermission() {
        if (usesLegacyStorage()) {
            if (hasStorageAccess()) {
                openAppPermissionSettings();
                return;
            }
            requestPermissions(
                    new String[]{
                            Manifest.permission.READ_EXTERNAL_STORAGE,
                            Manifest.permission.WRITE_EXTERNAL_STORAGE
                    },
                    REQUEST_LEGACY_STORAGE
            );
            return;
        }
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
                permissionStatus.setText(R.string.permission_open_failed);
                permissionStatus.setTextColor(getColor(R.color.danger));
                permissionStatus.setVisibility(View.VISIBLE);
            }
        }
    }

    private void openStorageTreePicker() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
        );
        try {
            startActivityForResult(intent, REQUEST_STORAGE_TREE);
        } catch (Exception error) {
            Toast.makeText(
                    this,
                    R.string.storage_tree_open_failed,
                    Toast.LENGTH_LONG
            ).show();
        }
    }

    private void openAppPermissionSettings() {
        try {
            Intent intent = new Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getPackageName())
            );
            startActivity(intent);
        } catch (Exception ignored) {
            permissionStatus.setText(usesLegacyStorage()
                    ? R.string.permission_open_failed_legacy
                    : R.string.permission_open_failed);
            permissionStatus.setTextColor(getColor(R.color.danger));
            permissionStatus.setVisibility(View.VISIBLE);
        }
    }

    private void startEmbeddedRuntime() {
        if (runtimeStarting || runtimeReady) {
            return;
        }
        if (!hasStorageAccess()) {
            showPermissionUi();
            return;
        }

        runtimeStarting = true;
        runtimeFailed = false;
        showLoading(getString(R.string.starting_local));
        runtimeExecutor.execute(() -> {
            String stage = getString(R.string.starting_python);
            try {
                updateLoadingText(stage);
                Python py = Python.getInstance();
                stage = getString(R.string.loading_openaver_service);
                updateLoadingText(stage);
                PyObject boot = py.getModule("openaver_boot");
                String dataDir = new File(getFilesDir(), "openaver_data").getAbsolutePath();
                String cascadePath = new File(
                        getFilesDir(),
                        "chaquopy/AssetFinder/app/core/focal/facefinder"
                ).getAbsolutePath();
                Os.setenv("OPENAVER_NATIVE_LIB", getApplicationInfo().nativeLibraryDir
                        + "/libopenaver_mobile.so", true);
                Os.setenv("OPENAVER_CASCADE_PATH", cascadePath, true);
                Os.setenv("OPENAVER_FOCAL_NATIVE", "1", true);
                stage = getString(R.string.starting_local_server);
                updateLoadingText(stage);
                int serverPort = boot.callAttr(
                        "start_server", LOCAL_HOST, LOCAL_PORT, dataDir,
                        getApplicationInfo().nativeLibraryDir + "/libopenaver_mobile.so",
                        cascadePath
                ).toInt();
                localPort = serverPort;
                localAuthToken = boot.callAttr("server_token").toString();
                localAuthCookieName = boot.callAttr("auth_cookie_name").toString();
                if (localAuthToken == null || localAuthToken.isEmpty()
                        || localAuthCookieName == null || localAuthCookieName.isEmpty()) {
                    throw new IllegalStateException("local authentication token unavailable");
                }
                stage = getString(R.string.waiting_local_server);
                updateLoadingText(stage);
                if (!waitForHealth(LOCAL_START_TIMEOUT_MS, boot, serverPort)) {
                    String serverError = serverErrorMessage(boot);
                    if (serverError.isEmpty()) {
                        serverError = "local health check timed out after "
                                + (LOCAL_START_TIMEOUT_MS / 1000L) + " seconds";
                    }
                    String startupPhase = startupStatus(boot);
                    String serverStack = serverStackSummary(boot);
                    throw new IllegalStateException(
                            serverError + "\nphase=" + startupPhase + "\n" + serverStack
                    );
                }
                mainHandler.post(() -> {
                    runtimeStarting = false;
                    runtimeReady = true;
                    runtimeFailed = false;
                    hideLoading();
                    setupScroll.setVisibility(View.GONE);
                    webContainer.setVisibility(View.VISIBLE);
                    applyLocalAuthCookie(() -> {
                        startCfShell();
                        openLocalPath("/scanner");
                    });
                });
            } catch (Throwable error) {
                final String failureStage = stage;
                Log.e(TAG, failureStage, error);
                mainHandler.post(() -> {
                    runtimeStarting = false;
                    runtimeReady = false;
                    runtimeFailed = true;
                    hideLoading();
                    showPermissionUi();
                    permissionStatus.setText(getString(
                            R.string.local_runtime_failed_detail,
                            failureStage + "\n" + error
                    ));
                    permissionStatus.setTextColor(getColor(R.color.danger));
                    permissionStatus.setVisibility(View.VISIBLE);
                });
            }
        });
    }

    private boolean waitForHealth(long timeoutMs, PyObject boot, int port) {
        long startedAt = SystemClock.elapsedRealtime();
        long deadline = startedAt + timeoutMs;
        long lastElapsedSecond = -1L;
        String lastPhase = "";
        while (SystemClock.elapsedRealtime() < deadline) {
            String phase = startupStatus(boot);
            if (!phase.equals(lastPhase)) {
                lastPhase = phase;
                int phaseText = startupPhaseText(phase);
                if (phaseText != 0) {
                    updateLoadingText(getString(phaseText));
                }
            }
            long elapsedMs = SystemClock.elapsedRealtime() - startedAt;
            long elapsedSecond = elapsedMs / 1000L;
            if (elapsedSecond >= 5L && elapsedSecond / 5L != lastElapsedSecond / 5L) {
                lastElapsedSecond = elapsedSecond;
                final long statusSecond = elapsedSecond;
                mainHandler.post(() -> loadingText.setText(getString(
                        R.string.waiting_local_server_elapsed,
                        statusSecond
                )));
            }
            HttpURLConnection connection = null;
            try {
                URL url = new URL(localBaseUrl(port) + "/api/mobile/health");
                connection = (HttpURLConnection) url.openConnection();
                connection.setConnectTimeout(1200);
                connection.setReadTimeout(1500);
                connection.setUseCaches(false);
                if (connection.getResponseCode() == HttpURLConnection.HTTP_OK) {
                    try (InputStream input = connection.getInputStream()) {
                        byte[] buffer = new byte[128];
                        int count = input.read(buffer);
                        if (count > 0) {
                            String body = new String(buffer, 0, count);
                            if (body.contains("\"status\":\"ok\"")) {
                                return true;
                            }
                        }
                    }
                }
            } catch (Exception ignored) {
                // Server is still importing OpenAver or initializing SQLite.
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
            if (!isServerAlive(boot)) {
                return false;
            }
            SystemClock.sleep(700L);
        }
        return false;
    }

    private boolean isServerAlive(PyObject boot) {
        try {
            return boot.callAttr("is_server_alive").toBoolean();
        } catch (Throwable error) {
            Log.w(TAG, "server liveness probe failed", error);
            return true;
        }
    }

    private String serverErrorMessage(PyObject boot) {
        try {
            String value = boot.callAttr("server_error").toString();
            return value == null ? "" : value;
        } catch (Throwable error) {
            Log.w(TAG, "server error probe failed", error);
            return "";
        }
    }

    private String startupStatus(PyObject boot) {
        try {
            String value = boot.callAttr("startup_status").toString();
            return value == null ? "unknown" : value;
        } catch (Throwable error) {
            Log.w(TAG, "startup status probe failed", error);
            return "unknown";
        }
    }

    private String serverStackSummary(PyObject boot) {
        try {
            String value = boot.callAttr("server_stack").toString();
            return value == null ? "" : value;
        } catch (Throwable error) {
            Log.w(TAG, "server stack probe failed", error);
            return "";
        }
    }

    private int startupPhaseText(String phase) {
        switch (phase) {
            case "uvicorn_running":
            case "app_imported":
                return R.string.starting_local_server;
            case "data_layout":
                return R.string.startup_phase_data_layout;
            case "database":
                return R.string.startup_phase_database;
            case "notifications":
                return R.string.startup_phase_notifications;
            case "access_auth":
                return R.string.startup_phase_access_auth;
            case "background_tasks":
                return R.string.startup_phase_background_tasks;
            default:
                return 0;
        }
    }

    private void updateLoadingText(String text) {
        mainHandler.post(() -> loadingText.setText(text));
    }

    private void openLocalPath(String path) {
        webError.setVisibility(View.GONE);
        webPageLoading = true;
        pageProgress.setVisibility(View.VISIBLE);
        webView.loadUrl(localBaseUrl() + path);
        mainHandler.removeCallbacks(pageLoadTimeout);
        mainHandler.postDelayed(pageLoadTimeout, PAGE_LOAD_TIMEOUT_MS);
    }

    private void applyLocalAuthCookie(Runnable afterCookieSet) {
        String cookie = localAuthCookieName + "=" + localAuthToken
                + "; Path=/; HttpOnly; SameSite=Strict";
        CookieManager.getInstance().setCookie(
                localBaseUrl(),
                cookie,
                accepted -> {
                    if (!accepted) {
                        Log.w(TAG, "WebView rejected loopback authentication cookie");
                    }
                    mainHandler.post(afterCookieSet);
                }
        );
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUserAgentString(
                settings.getUserAgentString() + " OpenAverMobile/" + BuildConfig.VERSION_NAME
        );

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, false);

        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true);
        }

        webView.setBackgroundColor(getColor(R.color.bg));
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        webView.setWebViewClient(new OpenAverWebViewClient());
        webView.setWebChromeClient(new OpenAverChromeClient());
        webView.setDownloadListener(new OpenAverDownloadListener());
    }

    private void refreshWeb() {
        webError.setVisibility(View.GONE);
        webPageLoading = true;
        pageProgress.setVisibility(View.VISIBLE);
        webView.reload();
        mainHandler.removeCallbacks(pageLoadTimeout);
        mainHandler.postDelayed(pageLoadTimeout, PAGE_LOAD_TIMEOUT_MS);
    }

    private void startCfShell() {
        if (cfShell != null) {
            return;
        }
        cfTransport = new AndroidCfTransport(this, root);
        cfShell = new CfShellAgent(localBaseUrl(), localAuthToken, cfTransport);
        cfShell.start();
    }

    private void showPageError() {
        webPageLoading = false;
        mainHandler.removeCallbacks(pageLoadTimeout);
        pageProgress.setVisibility(View.GONE);
        webError.setVisibility(View.VISIBLE);
        webError.bringToFront();
    }

    private void showWebMenu() {
        Dialog dialog = new Dialog(this, android.R.style.Theme_Material_Dialog_NoActionBar);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setContentView(R.layout.dialog_web_menu);
        dialog.setCanceledOnTouchOutside(true);

        TextView serverText = dialog.findViewById(R.id.menuServer);
        serverText.setText(getString(
                R.string.menu_connected_to,
                LOCAL_HOST + ":" + localPort
        ));

        dialog.findViewById(R.id.menuRefresh).setOnClickListener(view -> {
            dialog.dismiss();
            refreshWeb();
        });
        dialog.findViewById(R.id.menuScanner).setOnClickListener(view -> {
            dialog.dismiss();
            openLocalPath("/scanner");
        });
        dialog.findViewById(R.id.menuStorageSettings).setOnClickListener(view -> {
            dialog.dismiss();
            openStoragePermission();
        });
        dialog.findViewById(R.id.menuStorageTree).setOnClickListener(view -> {
            dialog.dismiss();
            openStorageTreePicker();
        });
        dialog.findViewById(R.id.menuAbout).setOnClickListener(view -> {
            dialog.dismiss();
            showAbout();
        });
        dialog.findViewById(R.id.menuExit).setOnClickListener(view -> {
            dialog.dismiss();
            finish();
        });
        dialog.findViewById(R.id.menuCancel).setOnClickListener(view -> dialog.dismiss());

        Window window = dialog.getWindow();
        if (window != null) {
            window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
            WindowManager.LayoutParams params = window.getAttributes();
            params.dimAmount = 0.72f;
            window.setAttributes(params);
        }
        dialog.show();
        if (window != null) {
            window.setGravity(Gravity.BOTTOM);
            window.setLayout(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
            );
        }
    }

    private void showAbout() {
        String dataDir = new File(getFilesDir(), "openaver_data").getAbsolutePath();
        String message = getString(
                R.string.about_message,
                BuildConfig.VERSION_NAME,
                BuildConfig.OPENAVER_RELEASE,
                BuildConfig.OPENAVER_COMMIT,
                dataDir
        );
        message += "\n\n" + getString(R.string.native_abi, nativeAbiSafe());

        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(R.string.about_title)
                .setMessage(message)
                .setPositiveButton(R.string.ok, null)
                .show();
    }

    private void openExternal(Uri uri) {
        Intent intent = new Intent(Intent.ACTION_VIEW, uri);
        try {
            startActivity(intent);
        } catch (Exception ignored) {
            toast(R.string.external_browser_missing);
        }
    }

    private boolean handleNavigation(Uri uri) {
        if (uri == null) {
            return false;
        }
        if (isLocalServer(uri)) {
            return false;
        }

        String scheme = uri.getScheme();
        if (scheme == null) {
            return false;
        }
        scheme = scheme.toLowerCase(Locale.ROOT);

        if ("http".equals(scheme) || "https".equals(scheme)
                || "mailto".equals(scheme) || "tel".equals(scheme)) {
            openExternal(uri);
            return true;
        }
        if ("intent".equals(scheme)) {
            try {
                Intent intent = Intent.parseUri(uri.toString(), Intent.URI_INTENT_SCHEME);
                startActivity(intent);
            } catch (Exception ignored) {
                toast(R.string.external_browser_missing);
            }
            return true;
        }
        return !("blob".equals(scheme) || "data".equals(scheme) || "javascript".equals(scheme));
    }

    private boolean isLocalServer(Uri target) {
        String host = target.getHost();
        if (host == null || !LOCAL_HOST.equalsIgnoreCase(host)) {
            return false;
        }
        int port = target.getPort();
        return port == -1 || port == localPort;
    }

    private String localBaseUrl() {
        return localBaseUrl(localPort);
    }

    private String localBaseUrl(int port) {
        return "http://" + LOCAL_HOST + ":" + port;
    }

    private void download(String url, String userAgent, String contentDisposition,
                          String mimeType) {
        if (url == null || !(url.startsWith("http://") || url.startsWith("https://"))) {
            toast(R.string.download_failed);
            return;
        }
        try {
            String fileName = URLUtil.guessFileName(url, contentDisposition, mimeType);
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
            request.setTitle(fileName);
            request.setDescription(getString(R.string.app_name));
            if (mimeType != null && !mimeType.isEmpty()) {
                request.setMimeType(mimeType);
            }
            if (userAgent != null && !userAgent.isEmpty()) {
                request.addRequestHeader("User-Agent", userAgent);
            }
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null && !cookie.isEmpty()) {
                request.addRequestHeader("Cookie", cookie);
            }
            request.setAllowedOverMetered(true);
            request.setAllowedOverRoaming(false);
            request.setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
            );
            request.setDestinationInExternalPublicDir(
                    Environment.DIRECTORY_DOWNLOADS,
                    fileName
            );

            DownloadManager manager =
                    (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (manager == null) {
                throw new IllegalStateException("download manager unavailable");
            }
            manager.enqueue(request);
            toast(R.string.download_started);
        } catch (Exception ignored) {
            toast(R.string.download_failed);
        }
    }

    private void showFullscreen(View view, WebChromeClient.CustomViewCallback callback) {
        if (customView != null && customViewCallback != null) {
            customViewCallback.onCustomViewHidden();
        }
        customView = view;
        customViewCallback = callback;
        fullscreenContainer.removeAllViews();
        fullscreenContainer.addView(view, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        fullscreenContainer.setVisibility(View.VISIBLE);
        fullscreenContainer.bringToFront();
        root.setPadding(0, 0, 0, 0);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hideSystemBars();
    }

    private void hideFullscreen() {
        if (customView == null) {
            return;
        }
        fullscreenContainer.removeAllViews();
        fullscreenContainer.setVisibility(View.GONE);
        customView = null;
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        showSystemBars();
        root.requestApplyInsets();
        if (customViewCallback != null) {
            customViewCallback.onCustomViewHidden();
            customViewCallback = null;
        }
    }

    private void hideSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.systemBars());
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                );
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            );
        }
    }

    private void showSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.show(WindowInsets.Type.systemBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
        }
    }

    private void showLoading(String text) {
        loadingText.setText(text);
        loadingOverlay.setVisibility(View.VISIBLE);
        loadingOverlay.bringToFront();
    }

    private void hideLoading() {
        loadingOverlay.setVisibility(View.GONE);
    }

    private String nativeAbiSafe() {
        if (NATIVE_LOADED) {
            try {
                String abi = nativeAbi();
                if (abi != null && !abi.isEmpty()) {
                    return abi;
                }
            } catch (Throwable ignored) {
                // Fall through to the platform's ABI list.
            }
        }
        if (Build.SUPPORTED_ABIS.length > 0) {
            return Build.SUPPORTED_ABIS[0];
        }
        return "unknown";
    }

    private void toast(int stringResource) {
        Toast.makeText(this, stringResource, Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onBackPressed() {
        if (customView != null) {
            hideFullscreen();
            return;
        }
        if (cfTransport != null && cfTransport.isOverlayVisible()) {
            cfTransport.hideOverlay();
            return;
        }
        if (webContainer.getVisibility() == View.VISIBLE) {
            dispatchWebBack();
            return;
        }
        super.onBackPressed();
    }

    private void dispatchWebBack() {
        if (webBackDispatchPending) {
            return;
        }
        webBackDispatchPending = true;
        try {
            webView.evaluateJavascript(
                    "(function(){try{return !!(window.OpenAverMobileBack"
                            + "&&window.OpenAverMobileBack());}catch(e){return false;}})()",
                    result -> {
                        webBackDispatchPending = false;
                        if (!"true".equals(result)) {
                            performWebHistoryBackOrExit();
                        }
                    }
            );
        } catch (Throwable error) {
            webBackDispatchPending = false;
            performWebHistoryBackOrExit();
        }
    }

    private void performWebHistoryBackOrExit() {
        if (webView.canGoBack()) {
            webView.goBack();
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastBackPressMs <= EXIT_BACK_WINDOW_MS) {
            super.onBackPressed();
        } else {
            lastBackPressMs = now;
            toast(R.string.exit_hint);
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        if (root != null) {
            root.post(this::applySavedMenuHandlePosition);
        }
    }

    @Override
    protected void onPause() {
        if (cfTransport != null) {
            cfTransport.onPause();
        }
        if (webView != null) {
            webView.onPause();
        }
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (cfTransport != null) {
            cfTransport.onResume();
        }
        if (webView != null && webContainer.getVisibility() == View.VISIBLE) {
            webView.onResume();
        }
        updatePermissionUi();
        if (hasStorageAccess() && !runtimeReady && !runtimeStarting) {
            mainHandler.postDelayed(this::startEmbeddedRuntime, 250L);
        }
    }

    @Override
    protected void onDestroy() {
        mainHandler.removeCallbacksAndMessages(null);
        runtimeExecutor.shutdownNow();
        if (localAuthCookieName != null && !localAuthCookieName.isEmpty()) {
            CookieManager.getInstance().setCookie(
                    localBaseUrl(),
                    localAuthCookieName + "=; Max-Age=0; Path=/"
            );
        }
        if (cfShell != null) {
            cfShell.stop();
            cfShell = null;
        }
        if (cfTransport != null) {
            cfTransport.destroy();
            cfTransport = null;
        }
        if (webView != null) {
            webView.stopLoading();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
        }
        super.onDestroy();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_FILE_CHOOSER) {
            if (filePathCallback == null) {
                return;
            }
            Uri[] result = null;
            if (resultCode == RESULT_OK) {
                result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            }
            filePathCallback.onReceiveValue(result);
            filePathCallback = null;
            return;
        }
        if (requestCode == REQUEST_ALL_FILES_ACCESS) {
            updatePermissionUi();
            if (hasStorageAccess()) {
                startEmbeddedRuntime();
            } else {
                showPermissionUi();
            }
            return;
        }
        if (requestCode == REQUEST_STORAGE_TREE) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                String error = StorageBridge.setTreeUri(this, data.getData());
                Toast.makeText(
                        this,
                        error == null
                                ? R.string.storage_tree_authorized
                                : R.string.storage_tree_authorize_failed,
                        Toast.LENGTH_LONG
                ).show();
            }
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_LEGACY_STORAGE) {
            return;
        }
        updatePermissionUi();
        if (hasStorageAccess()) {
            startEmbeddedRuntime();
        } else {
            showPermissionUi();
        }
    }

    private final class OpenAverWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return handleNavigation(request.getUrl());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return handleNavigation(Uri.parse(url));
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            super.onPageStarted(view, url, favicon);
            webBackDispatchPending = false;
            webError.setVisibility(View.GONE);
            pageProgress.setVisibility(View.VISIBLE);
            pageProgress.setProgress(0);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            webPageLoading = false;
            mainHandler.removeCallbacks(pageLoadTimeout);
            pageProgress.setVisibility(View.GONE);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request,
                                    WebResourceError error) {
            super.onReceivedError(view, request, error);
            if (request.isForMainFrame()) {
                showPageError();
            }
        }

        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                        WebResourceResponse errorResponse) {
            super.onReceivedHttpError(view, request, errorResponse);
            if (request.isForMainFrame() && errorResponse.getStatusCode() >= 400) {
                showPageError();
            }
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler,
                                       android.net.http.SslError error) {
            handler.cancel();
            showPageError();
        }
    }

    private final class OpenAverChromeClient extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            super.onProgressChanged(view, newProgress);
            if (newProgress >= 100) {
                pageProgress.setVisibility(View.GONE);
            } else {
                pageProgress.setVisibility(View.VISIBLE);
                pageProgress.setProgress(newProgress);
            }
        }

        @Override
        public boolean onShowFileChooser(WebView webView,
                                         ValueCallback<Uri[]> callback,
                                         FileChooserParams fileChooserParams) {
            if (filePathCallback != null) {
                filePathCallback.onReceiveValue(null);
            }
            filePathCallback = callback;
            Intent intent = fileChooserParams.createIntent();
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            try {
                startActivityForResult(
                        Intent.createChooser(intent, getString(R.string.file_chooser_title)),
                        REQUEST_FILE_CHOOSER
                );
                return true;
            } catch (Exception ignored) {
                filePathCallback = null;
                return false;
            }
        }

        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            showFullscreen(view, callback);
        }

        @Override
        public void onHideCustomView() {
            hideFullscreen();
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            request.deny();
        }
    }

    private final class OpenAverDownloadListener implements DownloadListener {
        @Override
        public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                    String mimetype, long contentLength) {
            download(url, userAgent, contentDisposition, mimetype);
        }
    }
}

