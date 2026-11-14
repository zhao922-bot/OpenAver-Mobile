package dev.openaver.mobile;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.view.View;

/** Native dialogs and system bars share the WebView's selected palette. */
final class NativeUiTheme {
    private static final String PREFS = "native_appearance";
    private static final String KEY = "theme";

    private NativeUiTheme() {}

    static int dialogStyle(Context context) {
        return "light".equals(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY, "dim"))
                ? R.style.Theme_OpenAverMobile_Dialog_Light
                : R.style.Theme_OpenAverMobile_Dialog;
    }

    static void apply(Activity activity, String theme) {
        if (!"light".equals(theme) && !"dim".equals(theme)) return;
        activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, theme).apply();
        boolean light = "light".equals(theme);
        int color = Color.parseColor(light ? "#FFFFFF" : "#212429");
        activity.getWindow().setStatusBarColor(color);
        activity.getWindow().setNavigationBarColor(color);
        View decor = activity.getWindow().getDecorView();
        int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        int current = decor.getSystemUiVisibility();
        decor.setSystemUiVisibility(light ? current | flags : current & ~flags);
    }
}
