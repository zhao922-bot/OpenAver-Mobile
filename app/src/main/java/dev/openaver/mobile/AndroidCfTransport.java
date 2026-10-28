package dev.openaver.mobile;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;
import org.json.JSONTokener;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Android WebView-backed implementation of the desktop CF transport.
 *
 * <p>The Python server already exposes the same CF handoff protocol used by
 * the desktop shell.  This class is the Android shell side: it keeps a
 * cookie-bearing WebView per site, lets the user solve a challenge in a
 * visible overlay, and executes same-origin fetches for the Python scraper.</p>
 */
public final class AndroidCfTransport {
    public static final String SITE_JAVLIBRARY = "javlibrary";
    public static final String SITE_FC2_JAVTEN = "fc-javten";

    private static final long PAGE_TIMEOUT_MS = 45_000L;
    private static final long FETCH_TIMEOUT_MS = 60_000L;
    private static final long READY_TIMEOUT_MS = 10_000L;

    private final Activity activity;
    private final FrameLayout root;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Map<String, SiteView> sites = new HashMap<>();
    private final Map<String, CompletableFuture<String>> pendingFetches =
            new ConcurrentHashMap<>();

    private FrameLayout overlay;
    private FrameLayout webHost;
    private TextView statusText;
    private String activeSite;

    public AndroidCfTransport(Activity activity, FrameLayout root) {
        this.activity = activity;
        this.root = root;
        createOverlay();
        sites.put(SITE_JAVLIBRARY, createSiteView(SITE_JAVLIBRARY));
        // Keep the historical source id spelling used by OpenAver.
        sites.put("fc-javten", createSiteView("fc-javten"));
    }

    public boolean isOverlayVisible() {
        return overlay != null && overlay.getVisibility() == View.VISIBLE;
    }

    public void hideOverlay() {
        mainHandler.post(() -> {
            if (overlay != null) {
                overlay.setVisibility(View.GONE);
            }
        });
    }

    public void onPause() {
        for (SiteView site : sites.values()) {
            site.webView.onPause();
        }
    }

    public void onResume() {
        for (SiteView site : sites.values()) {
            site.webView.onResume();
        }
    }

    public void destroy() {
        hideOverlay();
        for (SiteView site : sites.values()) {
            site.webView.stopLoading();
            site.webView.setWebChromeClient(null);
            site.webView.setWebViewClient(null);
            site.webView.destroy();
        }
        sites.clear();
        pendingFetches.clear();
        if (overlay != null && overlay.getParent() instanceof ViewGroup) {
            ((ViewGroup) overlay.getParent()).removeView(overlay);
        }
    }

    public void beginSolve(String originUrl, String cacheKey) throws TransportException {
        SiteView site = requireSite(cacheKey);
        mainHandler.post(() -> {
            showSite(site);
            statusText.setText("请在下方完成 Cloudflare 验证");
            site.load(originUrl);
        });
    }

    public boolean isReady(String cacheKey) {
        SiteView site = sites.get(cacheKey);
        if (site == null) {
            return false;
        }
        boolean ready = evaluateReady(site);
        if (ready) {
            mainHandler.post(this::hideOverlayNow);
        }
        return ready;
    }

    public String fetch(String url, String cacheKey) throws TransportException {
        SiteView site = requireSite(cacheKey);
        ensurePageForUrl(site, url);
        if (!evaluateReady(site)) {
            throw new ChallengeRequiredException("Cloudflare verification is not complete");
        }
        if (SITE_JAVLIBRARY.equals(cacheKey)) {
            setJavLibraryCookie(site);
        }
        return fetchHtml(site, url);
    }

    public String navigateAndSettle(String url, String cacheKey) throws TransportException {
        SiteView site = requireSite(cacheKey);
        long generation = site.load(url);
        site.awaitPage(generation, PAGE_TIMEOUT_MS);

        long deadline = System.currentTimeMillis() + READY_TIMEOUT_MS;
        while (System.currentTimeMillis() < deadline) {
            if (evaluateReady(site)) {
                return site.evaluateString("location.href", 5_000L);
            }
            sleepQuietly(100L);
        }
        throw new ChallengeRequiredException("page did not become ready");
    }

    private SiteView requireSite(String key) throws TransportException {
        SiteView site = sites.get(key);
        if (site == null) {
            throw new TransportException("unknown CF site: " + key);
        }
        return site;
    }

    private void ensurePageForUrl(SiteView site, String url) throws TransportException {
        String current = site.currentUrl();
        if (!sameOrigin(current, url)) {
            long generation = site.load(url);
            site.awaitPage(generation, PAGE_TIMEOUT_MS);
        }
    }

    private void setJavLibraryCookie(SiteView site) {
        mainHandler.post(() -> {
            String origin = "https://www.javlibrary.com/";
            CookieManager.getInstance().setCookie(origin, "over18=18; path=/");
            site.webView.evaluateJavascript(
                    "document.cookie='over18=18; path=/';", null);
        });
    }

    private String fetchHtml(SiteView site, String url) throws TransportException {
        String requestId = UUID.randomUUID().toString();
        CompletableFuture<String> future = new CompletableFuture<>();
        pendingFetches.put(requestId, future);

        String id = JSONObject.quote(requestId);
        String target = JSONObject.quote(url);
        String script =
                "(function(){var id=" + id + ";var u=" + target + ";" +
                "(async function(){try{" +
                "var r=await fetch(u,{credentials:'include',cache:'no-store'});" +
                "var h=await r.text();" +
                "window.OpenAverNative.onFetchResult(id,JSON.stringify(" +
                "{finalUrl:r.url,status:r.status,html:h}));" +
                "}catch(e){" +
                "window.OpenAverNative.onFetchResult(id,JSON.stringify(" +
                "{finalUrl:u,status:0,html:'',error:String(e)}));" +
                "}})();return true;})()";

        mainHandler.post(() -> site.webView.evaluateJavascript(script, null));

        String raw;
        try {
            raw = future.get(FETCH_TIMEOUT_MS, TimeUnit.MILLISECONDS);
        } catch (Exception exc) {
            throw new TransportTimeoutException("WebView fetch timed out");
        } finally {
            pendingFetches.remove(requestId);
        }

        JSONObject result;
        try {
            result = new JSONObject(raw);
        } catch (Exception exc) {
            throw new TransportException("invalid WebView fetch result");
        }

        String error = result.optString("error", "");
        if (!error.isEmpty()) {
            throw new TransportException("WebView fetch failed: " + error);
        }
        int status = result.optInt("status", 0);
        String html = result.optString("html", "");
        if (isChallengeHtml(html)) {
            throw new ChallengeRequiredException("Cloudflare challenge returned");
        }
        if (status == 0) {
            throw new TransportException("WebView fetch returned status 0");
        }
        if (status >= 400) {
            throw new TransportException("WebView fetch returned HTTP " + status);
        }
        return html;
    }

    @SuppressLint("SetJavaScriptEnabled")
    private SiteView createSiteView(String key) {
        WebView webView = new WebView(activity);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setUserAgentString(settings.getUserAgentString());

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, true);

        SiteView site = new SiteView(key, webView);
        webView.setBackgroundColor(Color.WHITE);
        webView.setWebViewClient(site);
        webView.setWebChromeClient(new WebChromeClient());
        webView.addJavascriptInterface(new NativeBridge(), "OpenAverNative");
        webHost.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        webView.setVisibility(View.GONE);
        return site;
    }

    private void createOverlay() {
        overlay = new FrameLayout(activity);
        overlay.setBackgroundColor(Color.WHITE);
        overlay.setVisibility(View.GONE);

        LinearLayout panel = new LinearLayout(activity);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setBackgroundColor(Color.WHITE);

        LinearLayout toolbar = new LinearLayout(activity);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setPadding(dp(16), dp(8), dp(8), dp(8));

        TextView title = new TextView(activity);
        title.setText("Cloudflare 验证");
        title.setTextSize(16);
        title.setTextColor(Color.rgb(32, 32, 32));
        title.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.addView(title, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        Button close = new Button(activity);
        close.setText("关闭");
        close.setAllCaps(false);
        close.setOnClickListener(view -> hideOverlayNow());
        toolbar.addView(close, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        statusText = new TextView(activity);
        statusText.setText("请完成验证后返回 OpenAver");
        statusText.setTextSize(12);
        statusText.setTextColor(Color.rgb(90, 90, 90));
        statusText.setPadding(dp(16), 0, dp(16), dp(8));

        webHost = new FrameLayout(activity);
        panel.addView(toolbar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        panel.addView(statusText, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        panel.addView(webHost, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
        ));

        overlay.addView(panel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        root.addView(overlay, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
    }

    private void showSite(SiteView site) {
        activeSite = site.key;
        for (SiteView candidate : sites.values()) {
            candidate.webView.setVisibility(candidate == site ? View.VISIBLE : View.GONE);
        }
        overlay.setVisibility(View.VISIBLE);
        overlay.bringToFront();
    }

    private void hideOverlayNow() {
        if (overlay != null) {
            overlay.setVisibility(View.GONE);
        }
    }

    private boolean evaluateReady(SiteView site) {
        try {
            JSONObject data = site.evaluateJson(
                    "(function(){return {title:(document.title||'')," +
                    "html:(document.documentElement?document.documentElement.outerHTML:'').slice(0,300000)};})()",
                    5_000L
            );
            if (data == null) {
                return false;
            }
            String title = data.optString("title", "").trim();
            String html = data.optString("html", "");
            if (title.isEmpty()) {
                return false;
            }
            String lowerTitle = title.toLowerCase(Locale.ROOT);
            if (lowerTitle.contains("just a moment")
                    || title.contains("請稍候")
                    || title.contains("请稍候")
                    || isChallengeHtml(html)) {
                return false;
            }
            return !SITE_JAVLIBRARY.equals(site.key) || !html.contains("agreeBtn");
        } catch (Exception ignored) {
            return false;
        }
    }

    private static boolean isChallengeHtml(String html) {
        if (html == null || html.isEmpty()) {
            return false;
        }
        String lower = html.toLowerCase(Locale.ROOT);
        return lower.contains("just a moment")
                || lower.contains("challenge-form")
                || lower.contains("cf-turnstile-response");
    }

    private static boolean sameOrigin(String left, String right) {
        try {
            Uri a = Uri.parse(left);
            Uri b = Uri.parse(right);
            return a.getScheme() != null
                    && a.getScheme().equalsIgnoreCase(b.getScheme())
                    && a.getHost() != null
                    && a.getHost().equalsIgnoreCase(b.getHost())
                    && effectivePort(a) == effectivePort(b);
        } catch (Exception ignored) {
            return false;
        }
    }

    private static int effectivePort(Uri uri) {
        int port = uri.getPort();
        if (port != -1) {
            return port;
        }
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
        }
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private final class NativeBridge {
        @JavascriptInterface
        public void onFetchResult(String requestId, String json) {
            CompletableFuture<String> future = pendingFetches.get(requestId);
            if (future != null) {
                future.complete(json);
            }
        }
    }

    private final class SiteView extends WebViewClient {
        final String key;
        final WebView webView;
        final Object lock = new Object();

        long generation;
        boolean started;
        boolean finished;
        String error;
        String currentUrl = "";

        SiteView(String key, WebView webView) {
            this.key = key;
            this.webView = webView;
        }

        String currentUrl() {
            synchronized (lock) {
                return currentUrl;
            }
        }

        long load(String url) {
            long generation;
            synchronized (lock) {
                generation = ++this.generation;
                started = false;
                finished = false;
                error = null;
                currentUrl = url;
            }
            mainHandler.post(() -> webView.loadUrl(url));
            return generation;
        }

        void awaitPage(long generation, long timeoutMs) throws TransportException {
            long deadline = System.currentTimeMillis() + timeoutMs;
            synchronized (lock) {
                while (this.generation == generation && !finished) {
                    long remaining = deadline - System.currentTimeMillis();
                    if (remaining <= 0) {
                        throw new TransportTimeoutException("page load timed out");
                    }
                    try {
                        lock.wait(Math.min(remaining, 500L));
                    } catch (InterruptedException exc) {
                        Thread.currentThread().interrupt();
                        throw new TransportException("page load interrupted");
                    }
                }
                if (this.generation != generation) {
                    return;
                }
                if (error != null && !error.isEmpty()) {
                    throw new TransportException("page load failed: " + error);
                }
            }
        }

        JSONObject evaluateJson(String script, long timeoutMs) throws TransportException {
            String raw = evaluateRaw(script, timeoutMs);
            if (raw == null || "null".equals(raw)) {
                return null;
            }
            try {
                return new JSONObject(raw);
            } catch (Exception exc) {
                return null;
            }
        }

        String evaluateString(String script, long timeoutMs) throws TransportException {
            String raw = evaluateRaw(script, timeoutMs);
            if (raw == null || "null".equals(raw)) {
                return "";
            }
            try {
                Object value = new JSONTokener(raw).nextValue();
                return value == null ? "" : String.valueOf(value);
            } catch (Exception exc) {
                return "";
            }
        }

        private String evaluateRaw(String script, long timeoutMs) throws TransportException {
            CountDownLatch latch = new CountDownLatch(1);
            AtomicReference<String> value = new AtomicReference<>();
            mainHandler.post(() -> webView.evaluateJavascript(script, result -> {
                value.set(result);
                latch.countDown();
            }));
            try {
                if (!latch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                    throw new TransportTimeoutException("JavaScript evaluation timed out");
                }
            } catch (InterruptedException exc) {
                Thread.currentThread().interrupt();
                throw new TransportException("JavaScript evaluation interrupted");
            }
            return value.get();
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String scheme = request.getUrl().getScheme();
            return scheme == null || (!"http".equalsIgnoreCase(scheme)
                    && !"https".equalsIgnoreCase(scheme));
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return false;
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            synchronized (lock) {
                started = true;
                currentUrl = url;
            }
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            synchronized (lock) {
                if (started) {
                    currentUrl = url;
                    finished = true;
                    lock.notifyAll();
                }
            }
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request,
                                    WebResourceError errorInfo) {
            if (request.isForMainFrame()) {
                synchronized (lock) {
                    error = errorInfo.getDescription() == null
                            ? "WebView error"
                            : errorInfo.getDescription().toString();
                    finished = true;
                    lock.notifyAll();
                }
            }
        }

        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                        WebResourceResponse errorResponse) {
            // A 403 can be a Cloudflare page that still needs to be displayed.
        }
    }

    public static class TransportException extends Exception {
        TransportException(String message) {
            super(message);
        }
    }

    public static final class ChallengeRequiredException extends TransportException {
        ChallengeRequiredException(String message) {
            super(message);
        }
    }

    public static final class TransportTimeoutException extends TransportException {
        TransportTimeoutException(String message) {
            super(message);
        }
    }
}
