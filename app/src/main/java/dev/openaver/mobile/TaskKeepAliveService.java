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
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import java.util.Locale;

public final class TaskKeepAliveService extends Service {
    private static final String TAG = "OpenAverTaskKeepAlive";
    private static final String CHANNEL_ID = "openaver_task";
    private static final int NOTIFICATION_ID = 17061;
    private static final String PREFS_NAME = "openaver_mobile";
    private static final String PREF_UI_LOCALE = "ui_locale";
    private static final String DEFAULT_UI_LOCALE = "zh-CN";

    private static volatile boolean running = false;
    private static volatile boolean requested = false;

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
        return running;
    }

    static void start(Context context) {
        requested = true;
        createNotificationChannel(context);
        startNow(context);
    }

    private static void startNow(Context context) {
        Intent intent = new Intent(context, TaskKeepAliveService.class);
        try {
            context.startForegroundService(intent);
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to start task keep-alive service", error);
        }
    }

    static void stop(Context context) {
        requested = false;
        // A pending foreground start must reach startForeground before being
        // stopped, otherwise Android can kill the app for missing its deadline.
        if (!running) {
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
        running = true;
        if (!requested) {
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        stopForeground(true);
        super.onDestroy();
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
        Intent launchIntent = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent contentIntent = PendingIntent.getActivity(
                this,
                0,
                launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification.Builder builder = new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_openaver)
                .setContentTitle(getString(R.string.task_keepalive_title))
                .setContentText(getString(R.string.task_keepalive_message))
                .setContentIntent(contentIntent)
                .setColor(getColor(R.color.accent))
                .setCategory(Notification.CATEGORY_PROGRESS)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setVisibility(Notification.VISIBILITY_PUBLIC);
        return builder.build();
    }
}
