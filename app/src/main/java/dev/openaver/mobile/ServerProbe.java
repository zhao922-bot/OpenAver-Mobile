package dev.openaver.mobile;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class ServerProbe {
    private static final int CONNECT_TIMEOUT_MS = 7000;
    private static final int READ_TIMEOUT_MS = 12000;
    private static final String USER_AGENT =
            "OpenAverMobile/" + BuildConfig.VERSION_NAME + " (Android)";

    private ServerProbe() {
    }

    static ProbeResult hello(String baseUrl, String cookie) {
        HttpURLConnection connection = null;
        try {
            connection = open(baseUrl + "/api/client/hello", "GET", cookie);
            int status = connection.getResponseCode();
            String body = readBody(status >= 400
                    ? connection.getErrorStream()
                    : connection.getInputStream());

            if (status == 403) {
                return ProbeResult.failure(ProbeFailure.SERVER_MODE_OFF, status);
            }
            if (status == 404) {
                return ProbeResult.failure(ProbeFailure.NOT_OPENAVER, status);
            }
            if (status != 200) {
                return ProbeResult.failure(ProbeFailure.HTTP_ERROR, status);
            }

            JSONObject json = new JSONObject(body);
            if (!"openaver".equals(json.optString("app"))) {
                return ProbeResult.failure(ProbeFailure.NOT_OPENAVER, status);
            }

            return ProbeResult.success(
                    json.optString("version", "unknown"),
                    json.optString("kind", "server"),
                    json.optBoolean("auth_required", false),
                    json.optBoolean("authed", false)
            );
        } catch (Exception ignored) {
            return ProbeResult.failure(ProbeFailure.UNREACHABLE, -1);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    static TokenResult requestToken(String baseUrl, String pin) {
        HttpURLConnection connection = null;
        try {
            connection = open(baseUrl + "/api/client/token", "POST", null);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");

            JSONObject request = new JSONObject();
            request.put("pin", pin);
            byte[] payload = request.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(payload.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(payload);
            }

            int status = connection.getResponseCode();
            String body = readBody(status >= 400
                    ? connection.getErrorStream()
                    : connection.getInputStream());

            if (status == 401) {
                return TokenResult.failure(TokenFailure.BAD_PIN, status);
            }
            if (status == 403) {
                return TokenResult.failure(TokenFailure.SERVER_MODE_OFF, status);
            }
            if (status != 200) {
                return TokenResult.failure(TokenFailure.HTTP_ERROR, status);
            }

            JSONObject json = new JSONObject(body);
            if (!json.optBoolean("success", false)) {
                return TokenResult.failure(TokenFailure.BAD_PIN, status);
            }
            return TokenResult.success(json.optString("token", ""));
        } catch (Exception ignored) {
            return TokenResult.failure(TokenFailure.UNREACHABLE, -1);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static HttpURLConnection open(String url, String method, String cookie)
            throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setInstanceFollowRedirects(false);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("User-Agent", USER_AGENT);
        connection.setRequestProperty("Connection", "close");
        if (cookie != null && !cookie.isEmpty()) {
            connection.setRequestProperty("Cookie", cookie);
        }
        return connection;
    }

    private static String readBody(InputStream stream) throws Exception {
        if (stream == null) {
            return "";
        }
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            char[] buffer = new char[4096];
            int read;
            while ((read = reader.read(buffer)) != -1) {
                result.append(buffer, 0, read);
            }
        }
        return result.toString();
    }

    enum ProbeFailure {
        NONE,
        UNREACHABLE,
        SERVER_MODE_OFF,
        NOT_OPENAVER,
        HTTP_ERROR
    }

    enum TokenFailure {
        NONE,
        BAD_PIN,
        SERVER_MODE_OFF,
        UNREACHABLE,
        HTTP_ERROR
    }

    static final class ProbeResult {
        final boolean success;
        final ProbeFailure failure;
        final int httpStatus;
        final String version;
        final String kind;
        final boolean authRequired;
        final boolean authed;

        private ProbeResult(
                boolean success,
                ProbeFailure failure,
                int httpStatus,
                String version,
                String kind,
                boolean authRequired,
                boolean authed
        ) {
            this.success = success;
            this.failure = failure;
            this.httpStatus = httpStatus;
            this.version = version;
            this.kind = kind;
            this.authRequired = authRequired;
            this.authed = authed;
        }

        static ProbeResult success(
                String version,
                String kind,
                boolean authRequired,
                boolean authed
        ) {
            return new ProbeResult(
                    true, ProbeFailure.NONE, 200,
                    version, kind, authRequired, authed
            );
        }

        static ProbeResult failure(ProbeFailure failure, int status) {
            return new ProbeResult(false, failure, status, "", "", false, false);
        }
    }

    static final class TokenResult {
        final boolean success;
        final TokenFailure failure;
        final int httpStatus;
        final String token;

        private TokenResult(
                boolean success,
                TokenFailure failure,
                int httpStatus,
                String token
        ) {
            this.success = success;
            this.failure = failure;
            this.httpStatus = httpStatus;
            this.token = token;
        }

        static TokenResult success(String token) {
            return new TokenResult(true, TokenFailure.NONE, 200, token);
        }

        static TokenResult failure(TokenFailure failure, int status) {
            return new TokenResult(false, failure, status, "");
        }
    }
}
