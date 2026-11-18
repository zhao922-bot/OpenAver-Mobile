package dev.openaver.mobile;

/**
 * Process-local holder for the embedded Python server session shared between
 * MainActivity (bootstrap / classic WebView fallback) and OpenAverFlutterActivity.
 */
final class MobileRuntimeSession {
    private static volatile boolean ready = false;
    private static volatile int port = 8765;
    private static volatile String authToken = "";
    private static volatile String authCookieName = "";
    private static volatile String dataDir = "";
    private static volatile String abi = "";
    private static volatile AndroidCfTransport cfTransport;
    private static volatile CfMobileAgent cfMobile;

    private MobileRuntimeSession() {
    }

    static void markReady(
            int serverPort,
            String token,
            String cookieName,
            String runtimeDataDir,
            String runtimeAbi,
            AndroidCfTransport transport,
            CfMobileAgent mobileAgent
    ) {
        port = serverPort;
        authToken = token == null ? "" : token;
        authCookieName = cookieName == null ? "" : cookieName;
        dataDir = runtimeDataDir == null ? "" : runtimeDataDir;
        abi = runtimeAbi == null ? "" : runtimeAbi;
        cfTransport = transport;
        cfMobile = mobileAgent;
        ready = true;
    }

    static void clear() {
        ready = false;
        authToken = "";
        authCookieName = "";
        cfTransport = null;
        cfMobile = null;
    }

    static void setCfAgent(AndroidCfTransport transport, CfMobileAgent mobileAgent) {
        cfTransport = transport;
        cfMobile = mobileAgent;
    }

    static boolean isReady() {
        return ready && authToken != null && !authToken.isEmpty();
    }

    static int getPort() {
        return port;
    }

    static String getAuthToken() {
        return authToken;
    }

    static String getAuthCookieName() {
        return authCookieName;
    }

    static String getDataDir() {
        return dataDir;
    }

    static String getAbi() {
        return abi;
    }

    static AndroidCfTransport getCfTransport() {
        return cfTransport;
    }

    static CfMobileAgent getCfMobile() {
        return cfMobile;
    }
}
