package dev.openaver.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Android counterpart of windows/cf_shell.py.
 *
 * <p>The server owns the job broker.  This agent long-polls the same loopback
 * endpoint as the desktop shell, executes jobs on the WebView transport, and
 * posts the result back.  It is intentionally started only after the embedded
 * Python server is healthy.</p>
 */
public final class CfShellAgent {
    private static final String POLL_PATH = "/api/cf/shell/poll";
    private static final String RESULT_PATH = "/api/cf/shell/result";
    private static final int HOLD_SECONDS = 20;
    private static final int POLL_TIMEOUT_MS = 35_000;
    private static final int RESULT_TIMEOUT_MS = 10_000;

    private final String baseUrl;
    private final String authToken;
    private final AndroidCfTransport transport;
    private volatile boolean stopped;
    private Thread thread;

    public CfShellAgent(String baseUrl, String authToken, AndroidCfTransport transport) {
        this.baseUrl = baseUrl;
        this.authToken = authToken;
        this.transport = transport;
    }

    public synchronized void start() {
        if (thread != null && thread.isAlive()) {
            return;
        }
        stopped = false;
        thread = new Thread(this::runLoop, "openaver-cf-shell");
        thread.setDaemon(true);
        thread.start();
    }

    public synchronized void stop() {
        stopped = true;
        if (thread != null) {
            thread.interrupt();
            thread = null;
        }
    }

    private void runLoop() {
        int failures = 0;
        while (!stopped) {
            try {
                JSONObject body = pollBody();
                JSONObject response = postJson(POLL_PATH, body, POLL_TIMEOUT_MS);
                failures = 0;
                JSONObject job = response.optJSONObject("job");
                if (job != null) {
                    executeJob(job);
                }
            } catch (Exception exc) {
                if (stopped) {
                    return;
                }
                failures++;
                sleepBackoff(failures);
            }
        }
    }

    private JSONObject pollBody() throws Exception {
        JSONObject body = new JSONObject();
        body.put("shell", "windows");
        JSONArray sites = new JSONArray();
        sites.put(AndroidCfTransport.SITE_JAVLIBRARY);
        sites.put("fc-javten");
        body.put("sites", sites);
        body.put("applied_proxy", JSONObject.NULL);
        body.put("server_remote", false);
        body.put("preparing", new JSONArray());
        body.put("hold", HOLD_SECONDS);
        return body;
    }

    private void executeJob(JSONObject job) {
        String id = job.optString("id", "");
        String kind = job.optString("kind", "");
        JSONObject args = job.optJSONObject("args");
        String site = args == null ? "" : args.optString("cache_key", "");

        JSONObject result = new JSONObject();
        try {
            result.put("id", id);
            Object value;
            switch (kind) {
                case "is_ready":
                    value = transport.isReady(site);
                    break;
                case "begin_solve":
                    transport.beginSolve(args.optString("origin_url", ""), site);
                    value = true;
                    break;
                case "fetch":
                    value = transport.fetch(args.optString("url", ""), site);
                    break;
                case "navigate_and_settle":
                    value = transport.navigateAndSettle(args.optString("url", ""), site);
                    break;
                default:
                    throw new AndroidCfTransport.TransportException("unknown job kind");
            }
            result.put("ok", true);
            result.put("value", value);
        } catch (AndroidCfTransport.ChallengeRequiredException exc) {
            result = errorResult(id, "challenge", exc);
        } catch (AndroidCfTransport.TransportTimeoutException exc) {
            result = errorResult(id, "timeout", exc);
        } catch (AndroidCfTransport.TransportException exc) {
            result = errorResult(id, "unavailable", exc);
        } catch (Exception exc) {
            result = errorResult(id, "error", exc);
        }

        try {
            postJson(RESULT_PATH, result, RESULT_TIMEOUT_MS);
        } catch (Exception ignored) {
            // The server has its own execution timeout and will retry the source.
        }
    }

    private JSONObject errorResult(String id, String error, Exception exc) {
        JSONObject result = new JSONObject();
        try {
            result.put("id", id);
            result.put("ok", false);
            result.put("error", error);
            String message = exc == null ? "" : String.valueOf(exc.getMessage());
            if (message.length() > 500) {
                message = message.substring(0, 500);
            }
            result.put("message", message);
        } catch (Exception ignored) {
            // JSONObject never rejects the primitive values used here.
        }
        return result;
    }

    private JSONObject postJson(String path, JSONObject body, int readTimeoutMs)
            throws IOException, org.json.JSONException {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(baseUrl + path);
            connection = (HttpURLConnection) url.openConnection(Proxy.NO_PROXY);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(5_000);
            connection.setReadTimeout(readTimeoutMs);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Authorization", "Bearer " + authToken);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }

            int status = connection.getResponseCode();
            InputStream stream = status >= 400
                    ? connection.getErrorStream()
                    : connection.getInputStream();
            String text = readAll(stream);
            if (status != HttpURLConnection.HTTP_OK) {
                throw new IOException("CF shell HTTP " + status + ": " + text);
            }
            return new JSONObject(text);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String readAll(InputStream stream) throws IOException {
        if (stream == null) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            char[] buffer = new char[4096];
            int count;
            while ((count = reader.read(buffer)) != -1) {
                builder.append(buffer, 0, count);
            }
        }
        return builder.toString();
    }

    private void sleepBackoff(int failures) {
        int[] delays = {1_000, 2_000, 4_000, 8_000, 10_000};
        long delay = delays[Math.min(failures - 1, delays.length - 1)];
        try {
            Thread.sleep(delay);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
        }
    }
}
