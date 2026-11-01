package dev.openaver.mobile;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Rect;
import android.os.Handler;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.TouchDelegate;
import android.view.View;
import android.view.ViewConfiguration;
import android.widget.FrameLayout;
import android.widget.ImageButton;

final class MenuHandleController {
    private static final long MENU_HANDLE_IDLE_MS = 2600L;
    private static final long INITIAL_POSITION_RETRY_MS = 50L;
    private static final int INITIAL_POSITION_MAX_ATTEMPTS = 20;
    private static final int MENU_HANDLE_VERTICAL_SAFE_INSET_DP = 8;
    private static final String PREF_MENU_HANDLE_X = "menu_handle_x";
    private static final String PREF_MENU_HANDLE_Y = "menu_handle_y";

    private final Context context;
    private final FrameLayout root;
    private final FrameLayout webContainer;
    private final ImageButton menuHandle;
    private final SharedPreferences preferences;
    private final Handler mainHandler;
    private final Runnable showMenu;
    private final Runnable initialPositionTask;
    private final View.OnLayoutChangeListener menuHandleLayoutListener =
            this::onMenuHandleLayoutChanged;
    private int touchSlop;
    private float touchDownRawX;
    private float touchDownRawY;
    private int dragStartLeft;
    private int dragStartTop;
    private int initialPositionAttempts;
    private boolean touchMoved;
    private boolean menuHandleTouching;
    private final Runnable menuHandleIdleCollapse;
    private final View.OnLayoutChangeListener layoutChangeListener =
            (view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> {
                int width = right - left;
                int height = bottom - top;
                int oldWidth = oldRight - oldLeft;
                int oldHeight = oldBottom - oldTop;
                if (width != oldWidth || height != oldHeight) {
                    view.post(this::applySavedPosition);
                }
            };

    MenuHandleController(
            Context context,
            FrameLayout root,
            FrameLayout webContainer,
            ImageButton menuHandle,
            SharedPreferences preferences,
            Handler mainHandler,
            Runnable showMenu
    ) {
        this.context = context;
        this.root = root;
        this.webContainer = webContainer;
        this.menuHandle = menuHandle;
        this.preferences = preferences;
        this.mainHandler = mainHandler;
        this.showMenu = showMenu;
        this.initialPositionTask = this::applyInitialPosition;
        this.menuHandleIdleCollapse = () -> {
            if (menuHandleTouching) return;
            menuHandle.animate()
                    .alpha(0.38f)
                    .scaleX(0.76f)
                    .setDuration(180L)
                    .start();
        };
    }

    @SuppressLint("ClickableViewAccessibility")
    void configure() {
        touchSlop = Math.max(
                ViewConfiguration.get(context).getScaledTouchSlop(),
                Math.round(8f * context.getResources().getDisplayMetrics().density)
        );
        menuHandle.setOnClickListener(view -> showMenu.run());
        menuHandle.setOnTouchListener(this::handleTouch);
        menuHandle.addOnLayoutChangeListener(menuHandleLayoutListener);
        root.addOnLayoutChangeListener(layoutChangeListener);
        menuHandle.post(initialPositionTask);
    }

    void applySavedPosition() {
        if (root.getWidth() == 0 || menuHandle.getWidth() == 0 || menuHandleTouching) {
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
            menuHandle.setTranslationX(0f);
            menuHandle.setBackgroundResource(R.drawable.bg_edge_handle);
            menuHandle.setPivotX(menuHandle.getWidth());
            menuHandle.setPivotY(menuHandle.getHeight() / 2f);
            menuHandle.post(this::updateTouchDelegate);
            scheduleCollapse();
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
        int minLeft = root.getPaddingLeft();
        int maxLeft = root.getPaddingLeft() + Math.max(0, availableWidth);
        int targetLeft = left + menuHandle.getWidth() / 2 < root.getWidth() / 2
                ? minLeft
                : maxLeft;
        move(targetLeft, top);
        savePosition(targetLeft, top);
        scheduleCollapse();
    }

    void destroy() {
        mainHandler.removeCallbacks(menuHandleIdleCollapse);
        menuHandle.removeCallbacks(initialPositionTask);
        menuHandle.removeOnLayoutChangeListener(menuHandleLayoutListener);
        root.removeOnLayoutChangeListener(layoutChangeListener);
    }

    private void onMenuHandleLayoutChanged(
            View view,
            int left,
            int top,
            int right,
            int bottom,
            int oldLeft,
            int oldTop,
            int oldRight,
            int oldBottom
    ) {
        if (view.getWidth() <= 0 || view.getHeight() <= 0) return;
        view.removeOnLayoutChangeListener(menuHandleLayoutListener);
        view.removeCallbacks(initialPositionTask);
        applySavedPosition();
    }

    private void applyInitialPosition() {
        if (root.getWidth() > 0 && menuHandle.getWidth() > 0) {
            applySavedPosition();
            return;
        }
        initialPositionAttempts++;
        if (initialPositionAttempts < INITIAL_POSITION_MAX_ATTEMPTS) {
            menuHandle.postDelayed(initialPositionTask, INITIAL_POSITION_RETRY_MS);
        }
    }

    private boolean handleTouch(View view, MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                menuHandleTouching = true;
                touchMoved = false;
                mainHandler.removeCallbacks(menuHandleIdleCollapse);
                view.animate().alpha(0.96f).scaleX(1f).setDuration(120L).start();
                touchDownRawX = event.getRawX();
                touchDownRawY = event.getRawY();
                dragStartLeft = view.getLeft();
                dragStartTop = view.getTop();
                view.getParent().requestDisallowInterceptTouchEvent(true);
                return true;
            case MotionEvent.ACTION_MOVE:
                if (!touchMoved) {
                    float dx = event.getRawX() - touchDownRawX;
                    float dy = event.getRawY() - touchDownRawY;
                    touchMoved = Math.hypot(dx, dy) >= touchSlop;
                }
                if (touchMoved) {
                    move(
                            dragStartLeft + Math.round(event.getRawX() - touchDownRawX),
                            dragStartTop + Math.round(event.getRawY() - touchDownRawY)
                    );
                }
                return true;
            case MotionEvent.ACTION_UP:
                menuHandleTouching = false;
                view.getParent().requestDisallowInterceptTouchEvent(false);
                if (touchMoved) {
                    snapToEdge(true);
                } else {
                    view.performClick();
                    scheduleCollapse();
                }
                return true;
            case MotionEvent.ACTION_CANCEL:
                menuHandleTouching = false;
                view.getParent().requestDisallowInterceptTouchEvent(false);
                if (touchMoved) {
                    snapToEdge(true);
                } else {
                    scheduleCollapse();
                }
                return true;
            default:
                return false;
        }
    }

    private void updateTouchDelegate() {
        if (!(menuHandle.getParent() instanceof View)) return;
        View parent = (View) menuHandle.getParent();
        if (menuHandle.getWidth() <= 0 || menuHandle.getHeight() <= 0) return;

        int targetSize = dpToPx(48);
        int extraX = Math.max(0, (targetSize - menuHandle.getWidth()) / 2);
        int extraY = Math.max(0, (targetSize - menuHandle.getHeight()) / 2);
        Rect area = new Rect(
                menuHandle.getLeft() - extraX,
                menuHandle.getTop() - extraY,
                menuHandle.getRight() + extraX,
                menuHandle.getBottom() + extraY
        );
        area.intersect(0, 0, parent.getWidth(), parent.getHeight());
        parent.setTouchDelegate(area.isEmpty() ? null : new TouchDelegate(area, menuHandle));
    }

    private void updateEdgeStyle(int left) {
        boolean onLeftEdge = left + menuHandle.getWidth() / 2 < root.getWidth() / 2;
        menuHandle.setBackgroundResource(onLeftEdge
                ? R.drawable.bg_edge_handle_left
                : R.drawable.bg_edge_handle);
        menuHandle.setPivotX(onLeftEdge ? 0f : menuHandle.getWidth());
        menuHandle.setPivotY(menuHandle.getHeight() / 2f);
    }

    private void scheduleCollapse() {
        mainHandler.removeCallbacks(menuHandleIdleCollapse);
        mainHandler.postDelayed(menuHandleIdleCollapse, MENU_HANDLE_IDLE_MS);
    }

    private void snapToEdge(boolean animate) {
        if (menuHandle.getWidth() == 0) return;
        int minLeft = root.getPaddingLeft();
        int maxLeft = root.getWidth() - root.getPaddingRight() - menuHandle.getWidth();
        if (maxLeft < minLeft) maxLeft = minLeft;

        int currentRootLeft = webContainer.getLeft() + menuHandle.getLeft();
        int targetLeft = currentRootLeft + menuHandle.getWidth() / 2
                < root.getWidth() / 2 ? minLeft : maxLeft;
        targetLeft = clamp(targetLeft, minLeft, maxLeft);
        int top = webContainer.getTop() + menuHandle.getTop();

        if (!animate) {
            move(targetLeft, top);
            savePosition(targetLeft, top);
            scheduleCollapse();
            return;
        }

        float deltaX = targetLeft - currentRootLeft;
        int snappedLeft = targetLeft;
        int snappedTop = top;
        menuHandle.animate()
                .translationX(deltaX)
                .alpha(0.78f)
                .setDuration(180L)
                .withEndAction(() -> {
                    menuHandle.setTranslationX(0f);
                    move(snappedLeft, snappedTop);
                    savePosition(snappedLeft, snappedTop);
                    scheduleCollapse();
                })
                .start();
    }

    private void move(int requestedLeft, int requestedTop) {
        int verticalSafeInset = dpToPx(MENU_HANDLE_VERTICAL_SAFE_INSET_DP);
        int availableWidth = root.getWidth() - root.getPaddingLeft()
                - root.getPaddingRight() - menuHandle.getWidth();
        int availableHeight = root.getHeight() - root.getPaddingTop()
                - root.getPaddingBottom() - menuHandle.getHeight();
        int minLeft = root.getPaddingLeft();
        int maxLeft = root.getPaddingLeft() + Math.max(0, availableWidth);
        int minTop = root.getPaddingTop() + verticalSafeInset;
        int maxTop = root.getPaddingTop() + Math.max(0, availableHeight) - verticalSafeInset;
        if (maxLeft < minLeft) maxLeft = minLeft;
        if (maxTop < minTop) maxTop = minTop;
        int left = clamp(requestedLeft, minLeft, maxLeft);
        int top = clamp(requestedTop, minTop, maxTop);

        FrameLayout.LayoutParams params =
                (FrameLayout.LayoutParams) menuHandle.getLayoutParams();
        params.gravity = Gravity.TOP | Gravity.START;
        params.leftMargin = left - root.getPaddingLeft();
        params.topMargin = top - root.getPaddingTop();
        menuHandle.setLayoutParams(params);
        updateEdgeStyle(left);
        menuHandle.post(this::updateTouchDelegate);
    }

    private void savePosition(int rootLeft, int rootTop) {
        int availableWidth = root.getWidth() - root.getPaddingLeft()
                - root.getPaddingRight() - menuHandle.getWidth();
        int availableHeight = root.getHeight() - root.getPaddingTop()
                - root.getPaddingBottom() - menuHandle.getHeight();
        float x = availableWidth > 0
                ? (rootLeft - root.getPaddingLeft()) / (float) availableWidth
                : 0f;
        float y = availableHeight > 0
                ? (rootTop - root.getPaddingTop()) / (float) availableHeight
                : 0.5f;
        preferences.edit()
                .putFloat(PREF_MENU_HANDLE_X, clamp(x, 0f, 1f))
                .putFloat(PREF_MENU_HANDLE_Y, clamp(y, 0f, 1f))
                .commit();
    }

    private int dpToPx(int dp) {
        return Math.round(dp * context.getResources().getDisplayMetrics().density);
    }

    private static int clamp(int value, int minimum, int maximum) {
        return Math.max(minimum, Math.min(value, maximum));
    }

    private static float clamp(float value, float minimum, float maximum) {
        return Math.max(minimum, Math.min(value, maximum));
    }
}
