package dev.openaver.mobile.smoke;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.Activity;
import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.Environment;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Exercises the installed Android host, Flutter UI, and local Python runtime. */
public final class EmulatorSmoke extends Instrumentation {
    private static final long UI_TIMEOUT_MS = 20_000;
    private static final String MOVIE = "TST-12400";
    private static final String LIBRARY = "OpenAverSmoke";
    private static final Pattern PLAYER_TIME = Pattern.compile("(\\d{2}):(\\d{2}) / 02:00");

    private UiAutomation automation;
    private boolean launcherRecovered;

    @Override
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }

    @Override
    public void onStart() {
        Bundle result = new Bundle();
        try {
            automation = getUiAutomation();
            AccessibilityServiceInfo info = automation.getServiceInfo();
            info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
            automation.setServiceInfo(info);
            startHost();
            installFixture();
            configureLibrary();
            scanAndPlay();
            cancelScan();
            result.putString("stream", "\nOpenAver emulator smoke passed\n");
            finish(Activity.RESULT_OK, result);
        } catch (Exception | AssertionError error) {
            result.putString("stream", "\n" + android.util.Log.getStackTraceString(error)
                    + "\nVisible controls: " + visibleLabels() + "\n");
            finish(Activity.RESULT_CANCELED, result);
        }
    }

    private void startHost() {
        String target = getTargetContext().getPackageName();
        Intent intent = new Intent(Intent.ACTION_MAIN)
                .setClassName(target, "dev.openaver.mobile.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getTargetContext().startActivity(intent);

        if (!Environment.isExternalStorageManager()) {
            tap(awaitNode("storage permission button", node -> {
                String id = node.getViewIdResourceName();
                return id != null && id.endsWith(":id/permissionButton");
            }, 75_000, intent));
            tap(awaitNode("Android all-files access switch", node ->
                    "com.android.settings".equals(String.valueOf(node.getPackageName()))
                            && node.isCheckable() && !node.isChecked(), UI_TIMEOUT_MS));
            back();
        }

        awaitNode("Flutter settings tab", node -> labelled(node, "Settings", "设置"),
                90_000, intent);
        stage("Host and Flutter UI launched");
    }

    private File fixtureDirectory() {
        return new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES),
                LIBRARY);
    }

    private void installFixture() throws IOException {
        File folder = fixtureDirectory();
        Files.createDirectories(folder.toPath());
        for (int part = 1; part <= 2; part++) {
            File target = new File(folder, MOVIE + "-CD" + part + ".mp4");
            try (InputStream clip = getContext().getAssets().open("smoke.mp4")) {
                Files.copy(clip, target.toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
        }
    }

    private void configureLibrary() {
        click("Settings", "设置");
        if (find(node -> labelled(node, "Save Settings", "Appearance & General")) == null) {
            click("en");
        }
        tap(awaitNode("Library & Display section", node -> node.isClickable()
                && labelled(node, "Library & Display", "片库目录与展示"), UI_TIMEOUT_MS));
        scrollTo("Add Library Folder", "添加扫描目录");
        click("Add Library Folder", "添加扫描目录");
        File folder = fixtureDirectory();
        openFolder(folder.getParentFile());
        openFolder(folder);
        click("Select Current Folder", "选择当前目录");
        click("Save Settings", "保存设置");
        awaitNode("save confirmed", node -> labelled(node, "Saved", "已保存"), UI_TIMEOUT_MS);
        stage("Library folder saved through Settings");
    }

    private void openFolder(File folder) {
        clickAccessible(folder.getName(), node -> labelled(node, folder.getName()));
        awaitNode("folder path " + folder, node -> labelled(node, folder.getPath()), UI_TIMEOUT_MS);
    }

    private void scanAndPlay() {
        click("Scanner", "片库");
        click("Scan Library", "扫描片库");
        awaitNode("successful scan completion", node -> label(node).contains("100%"), 45_000);
        click("Showcase", "浏览");
        clickAccessible("indexed video", node -> label(node).contains(MOVIE));
        awaitNode("video details", node -> labelled(node, "Built-in Player", "内置播放器"),
                UI_TIMEOUT_MS);
        openPart("CD1");
        awaitPlaybackTime(18, 45_000);
        leavePlayer();
        openPart("CD2");
        int secondPart = awaitPlaybackTime(0, 9_000);
        if (secondPart > 8) {
            throw new AssertionError("CD2 inherited CD1's position: " + secondPart);
        }
        leavePlayer();
        int bookmark = savedFirstPartSeconds();
        if (bookmark < 15) {
            throw new AssertionError("CD1 bookmark was " + bookmark + " seconds after exit");
        }
        stage("CD1 saved at " + bookmark + "s");
        openPart("CD1");
        int resumed = awaitPlaybackTime(bookmark - 2, 10_000);
        leavePlayer();
        back();
        stage("Media scanned, segments stayed independent, and CD1 resumed at " + resumed + "s");
    }

    private int savedFirstPartSeconds() {
        SharedPreferences storage = getTargetContext().getSharedPreferences(
                "playback_positions", Context.MODE_PRIVATE);
        String filename = MOVIE + "-CD1.mp4";
        for (var entry : storage.getAll().entrySet()) {
            if (Uri.decode(entry.getKey()).endsWith("/" + filename)
                    && entry.getValue() instanceof Long milliseconds) {
                return (int) (milliseconds / 1000);
            }
        }
        return 0;
    }

    private void openPart(String part) {
        click(part);
        awaitNode("player controls", node -> labelled(node, "1.0x"), UI_TIMEOUT_MS);
    }

    private void leavePlayer() {
        click("Back");
        awaitNode("video details", node -> labelled(node, "Built-in Player", "内置播放器"),
                UI_TIMEOUT_MS);
    }

    private void cancelScan() throws Exception {
        // Enough local entries to keep the real scanner busy while the test presses Stop.
        File folder = new File(fixtureDirectory(), "cancel-fixtures");
        Files.createDirectories(folder.toPath());
        byte[] contents = {0};
        for (int i = 0; i < 4_096; i++) {
            Files.write(new File(folder, "ZZZ-" + (20000 + i) + ".mp4").toPath(), contents);
        }
        click("Scanner", "片库");
        click("Scan Library", "扫描片库");
        click("Stop Task", "停止任务");
        awaitNode("cancelled task", node -> {
            String text = label(node);
            return text.contains("Cancelled by user") || text.contains("用户已请求中止任务");
        }, UI_TIMEOUT_MS);
        if (find(node -> label(node).contains("100%")) != null) {
            throw new AssertionError("A cancelled scan rendered as complete");
        }
        click("Tasks", "任务");
        awaitNode("task center", node -> labelled(node, "Task Center", "任务中心"),
                UI_TIMEOUT_MS);
        awaitNode("recent cancelled scan", node -> {
            String text = label(node);
            return text.contains("Cancelled by user") || text.contains("用户已请求中止任务");
        }, UI_TIMEOUT_MS);
        stage("Active scan cancelled and recorded in Task Center");
    }

    private int awaitPlaybackTime(int minimum, long timeout) {
        long deadline = SystemClock.uptimeMillis() + timeout;
        long lastReveal = 0;
        while (SystemClock.uptimeMillis() < deadline) {
            AccessibilityNodeInfo timer = find(node -> PLAYER_TIME.matcher(label(node)).find());
            if (timer != null) {
                Matcher match = PLAYER_TIME.matcher(label(timer));
                if (match.find()) {
                    int seconds = 60 * Integer.parseInt(match.group(1))
                            + Integer.parseInt(match.group(2));
                    if (seconds >= minimum) return seconds;
                }
            } else if (SystemClock.uptimeMillis() - lastReveal > 600) {
                Rect screen = screenBounds();
                tap(screen.centerX(), screen.top + screen.height() * 0.43f);
                lastReveal = SystemClock.uptimeMillis();
            }
            SystemClock.sleep(100);
        }
        throw new AssertionError("Playback did not reach " + minimum + " seconds");
    }

    private void scrollTo(String... labels) {
        for (int i = 0; i < 5 && find(node -> labelled(node, labels)) == null; i++) {
            Rect screen = screenBounds();
            long down = SystemClock.uptimeMillis();
            float x = screen.left + screen.width() * 0.35f;
            float bottom = screen.top + screen.height() * 0.79f;
            float step = screen.height() * 0.03f;
            touch(MotionEvent.ACTION_DOWN, down, x, bottom);
            for (int j = 1; j <= 12; j++) {
                SystemClock.sleep(18);
                touch(MotionEvent.ACTION_MOVE, down, x, bottom - step * j);
            }
            touch(MotionEvent.ACTION_UP, down, x, bottom - step * 12);
            SystemClock.sleep(360);
        }
    }

    private void back() {
        sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);
        SystemClock.sleep(320);
    }

    private void stage(String message) {
        Bundle status = new Bundle();
        status.putString("stream", "\n" + message + "\n");
        sendStatus(0, status);
    }

    private void click(String... labels) {
        tap(awaitNode(String.join(" / ", labels), node -> labelled(node, labels), UI_TIMEOUT_MS));
    }

    private void clickAccessible(String description, Predicate<AccessibilityNodeInfo> matches) {
        AccessibilityNodeInfo node = awaitNode(description,
                candidate -> candidate.isClickable() && matches.test(candidate), UI_TIMEOUT_MS);
        if (!node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            throw new AssertionError("Could not activate " + description);
        }
    }

    private void tap(AccessibilityNodeInfo node) {
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        tap(bounds.centerX(), bounds.centerY());
    }

    private void tap(float x, float y) {
        long down = SystemClock.uptimeMillis();
        touch(MotionEvent.ACTION_DOWN, down, x, y);
        touch(MotionEvent.ACTION_UP, down, x, y);
    }

    private void touch(int action, long down, float x, float y) {
        MotionEvent event = MotionEvent.obtain(down, SystemClock.uptimeMillis(), action, x, y, 0);
        event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        try {
            if (!automation.injectInputEvent(event, true)) {
                throw new AssertionError("Could not inject emulator touch at " + x + ", " + y);
            }
        } finally {
            event.recycle();
        }
    }

    private Rect screenBounds() {
        Rect bounds = new Rect();
        awaitNode("active window", node -> true, UI_TIMEOUT_MS).getBoundsInScreen(bounds);
        return bounds;
    }

    private AccessibilityNodeInfo awaitNode(String description, Predicate<AccessibilityNodeInfo> test,
                                             long timeout) {
        return awaitNode(description, test, timeout, null);
    }

    private AccessibilityNodeInfo awaitNode(String description, Predicate<AccessibilityNodeInfo> test,
                                             long timeout, Intent startup) {
        long deadline = SystemClock.uptimeMillis() + timeout;
        do {
            AccessibilityNodeInfo found = find(test);
            if (found != null) return found;
            if (startup != null && !launcherRecovered && dismissLauncherAnr()) {
                launcherRecovered = true;
                stage("Closed the emulator's unresponsive Pixel Launcher and reopened OpenAver");
                getTargetContext().startActivity(startup);
            }
            SystemClock.sleep(50);
        } while (SystemClock.uptimeMillis() < deadline);
        throw new AssertionError("Timed out waiting for " + description);
    }

    private boolean dismissLauncherAnr() {
        // A hosted emulator can surface the launcher error while the app is starting.
        // Only recover from this system dialog, leaving OpenAver errors visible.
        if (find(node -> labelled(node, "Pixel Launcher isn't responding")) == null) return false;
        AccessibilityNodeInfo close = find(node -> node.isClickable() && labelled(node, "Close app"));
        if (close == null) return false;
        tap(close);
        return true;
    }

    private AccessibilityNodeInfo find(Predicate<AccessibilityNodeInfo> test) {
        if (automation == null) return null;
        AccessibilityNodeInfo root = automation.getRootInActiveWindow();
        if (root == null) return null;
        ArrayDeque<AccessibilityNodeInfo> remaining = new ArrayDeque<>();
        remaining.add(root);
        while (!remaining.isEmpty()) {
            AccessibilityNodeInfo node = remaining.removeFirst();
            if (node.isVisibleToUser() && test.test(node)) return node;
            for (int i = 0; i < node.getChildCount(); i++) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) remaining.addLast(child);
            }
        }
        return null;
    }

    private List<String> visibleLabels() {
        List<String> labels = new ArrayList<>();
        find(node -> {
            String text = label(node);
            if (!text.isEmpty() && labels.size() < 30) labels.add(text);
            return false;
        });
        return labels;
    }

    private static boolean labelled(AccessibilityNodeInfo node, String... labels) {
        String text = label(node);
        for (String expected : labels) {
            if (text.equals(expected) || text.startsWith(expected + "\nTab ")) return true;
        }
        return false;
    }

    private static String label(AccessibilityNodeInfo node) {
        CharSequence value = node.getContentDescription();
        if (value == null || value.length() == 0) value = node.getText();
        return value == null ? "" : value.toString();
    }
}
