package dev.openaver.mobile;

import android.content.Context;

/** Holds a real service notification while the first host activity is still uncreated. */
public final class ColdTaskNotification {
    private ColdTaskNotification() {}

    public static void start(Context context) {
        if (MobileRuntimeSession.isReady() || TaskKeepAliveService.isRunning()) {
            throw new AssertionError("Cold notification requires a fresh runtime and service");
        }
        TaskKeepAliveService.setFlutterActive(context, true);
    }

    public static void stop(Context context) {
        TaskKeepAliveService.setFlutterActive(context, false);
    }
}
