package dev.openaver.mobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import java.util.Locale;
import java.util.Objects;

public final class TaskKeepAliveService extends Service {
    private static final String TAG = "OpenAverTaskKeepAlive";
    private static final String CHANNEL_ID = "openaver_task";
    private static final int NOTIFICATION_ID = 17061;
    private static final String PREFS_NAME = "openaver_mobile";
    private static final String PREF_UI_LOCALE = "ui_locale";
    private static final String DEFAULT_UI_LOCALE = "zh-CN";
    private static final long NOTIFICATION_REFRESH_INTERVAL_MS = 750L;

    private static TaskKeepAliveService runningService;
    private static boolean requested = false;
    private static boolean classicRequested = false;
    private static boolean flutterRequested = false;
    private static int flutterTaskCount;
    private static int flutterProgressCurrent;
    private static int flutterProgressTotal;
    private static String flutterTaskSummary;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable notificationRefresh = this::refreshNotificationNow;

    @Override
    protected void attachBaseContext(Context newBase) {
        SharedPreferences preferences =
                newBase.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String localeTag = preferences.getString(PREF_UI_LOCALE, DEFAULT_UI_LOCALE);
        Configuration configuration = new Configuration(
                newBase.getResources().getConfiguration()
        );
        configuration.setLocale(Locale.forLanguageTag(localeTag));
        super.attachBaseContext(newBase.createConfigurationContext(configuration));
    }

    static boolean isRunning() {
        return runningService != null;
    }

    static void start(Context context) {
        classicRequested = true;
        updateRequested(context);
    }

    static void stop(Context context) {
        classicRequested = false;
        updateRequested(context);
    }

    static void setFlutterActive(Context context, boolean active) {
        if (active == flutterRequested) {
            return;
        }
        flutterRequested = active;
        if (!active) {
            clearFlutterNotification();
        }
        updateRequested(context);
        refreshNotification();
    }

    static void stopAll(Context context) {
        classicRequested = false;
        flutterRequested = false;
        clearFlutterNotification();
        updateRequested(context);
    }

    static void updateFlutterNotification(int taskCount, int current, int total, String summary) {
        if (!flutterRequested) {
            return;
        }
        taskCount = Math.max(0, taskCount);
        total = taskCount > 0 ? Math.max(0, total) : 0;
        current = Math.max(0, Math.min(current, total));
        summary = taskCount > 0 && summary != null && !summary.trim().isEmpty() ? summary : null;
        if (taskCount == flutterTaskCount && current == flutterProgressCurrent
                && total == flutterProgressTotal && Objects.equals(summary, flutterTaskSummary)) {
            return;
        }
        flutterTaskCount = taskCount;
        flutterProgressCurrent = current;
        flutterProgressTotal = total;
        flutterTaskSummary = summary;
        if (runningService != null) {
            runningService.scheduleNotificationRefresh();
        }
    }

    static void refreshNotification() {
        if (runningService != null) {
            runningService.refreshNotificationNow();
        }
    }

    private static void clearFlutterNotification() {
        flutterTaskCount = 0;
        flutterProgressCurrent = 0;
        flutterProgressTotal = 0;
        flutterTaskSummary = null;
    }

    private static void updateRequested(Context context) {
        boolean active = classicRequested || flutterRequested;
        if (active == requested) {
            return;
        }
        requested = active;
        if (active) {
            createNotificationChannel(context);
            startNow(context);
        } else {
            stopNow(context);
        }
    }

    private static void startNow(Context context) {
        Intent intent = new Intent(context, TaskKeepAliveService.class);
        try {
            context.startForegroundService(intent);
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to start task keep-alive service", error);
        }
    }

    private static void stopNow(Context context) {
        // A pending foreground start must reach startForeground before being
        // stopped, otherwise Android can kill the app for missing its deadline.
        if (!isRunning()) {
            return;
        }
        try {
            context.stopService(new Intent(context, TaskKeepAliveService.class));
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to stop task keep-alive service", error);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createNotificationChannel(this);
        startForeground(NOTIFICATION_ID, buildNotification());
        runningService = this;
        if (!requested) {
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        runningService = null;
        handler.removeCallbacks(notificationRefresh);
        stopForeground(true);
        super.onDestroy();
    }

    private void scheduleNotificationRefresh() {
        if (!handler.hasCallbacks(notificationRefresh)) {
            handler.postDelayed(notificationRefresh, NOTIFICATION_REFRESH_INTERVAL_MS);
        }
    }

    private void refreshNotificationNow() {
        handler.removeCallbacks(notificationRefresh);
        if (!requested) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID, buildNotification());
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private static void createNotificationChannel(Context context) {
        NotificationManager manager =
                (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.task_keepalive_channel),
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription(context.getString(R.string.task_keepalive_message));
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        boolean flutterUi = "flutter".equals(prefs.getString("ui_mode", "flutter"));
        Class<?> launchActivity = flutterUi && MobileRuntimeSession.isReady()
                ? OpenAverFlutterActivity.class : MainActivity.class;
        Intent launchIntent = new Intent(this, launchActivity)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if (flutterUi) {
            launchIntent.setAction(OpenAverFlutterActivity.ACTION_OPEN_TASK_CENTER);
        }
        PendingIntent contentIntent = PendingIntent.getActivity(
                this,
                0,
                launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        boolean showFlutterTasks = flutterUi && flutterRequested && flutterTaskCount > 0;
        String message = showFlutterTasks && flutterTaskSummary != null
                ? flutterTaskSummary : getString(R.string.task_keepalive_message);
        Notification.Builder builder = new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_openaver)
                .setContentTitle(getString(R.string.task_keepalive_title))
                .setContentText(message)
                .setContentIntent(contentIntent)
                .setColor(getColor(R.color.accent))
                .setCategory(Notification.CATEGORY_PROGRESS)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setVisibility(Notification.VISIBILITY_PUBLIC);
        if (showFlutterTasks) {
            builder.setNumber(flutterTaskCount);
            if (flutterProgressTotal > 0) {
                builder.setProgress(flutterProgressTotal, flutterProgressCurrent, false);
            }
        }
        return builder.build();
    }
}
