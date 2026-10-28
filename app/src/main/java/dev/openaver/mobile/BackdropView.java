package dev.openaver.mobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

public final class BackdropView extends View {
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint gridPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint accentPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private RadialGradient blueGlow;
    private RadialGradient warmGlow;
    private LinearGradient accentLine;

    public BackdropView(Context context) {
        this(context, null);
    }

    public BackdropView(Context context, AttributeSet attrs) {
        super(context, attrs);
        setWillNotDraw(false);
        gridPaint.setStyle(Paint.Style.STROKE);
        gridPaint.setStrokeWidth(dp(1));
        gridPaint.setColor(0x0EFFFFFF);
        accentPaint.setStyle(Paint.Style.STROKE);
        accentPaint.setStrokeWidth(dp(1.2f));
        accentPaint.setColor(0x335DE1C1);
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        float minSide = Math.min(width, height);
        blueGlow = new RadialGradient(
                width * 0.88f,
                height * 0.08f,
                minSide * 0.58f,
                new int[]{0x3074A0FF, 0x0C74A0FF, 0x00090D13},
                new float[]{0f, 0.42f, 1f},
                Shader.TileMode.CLAMP
        );
        warmGlow = new RadialGradient(
                width * 0.02f,
                height * 0.72f,
                minSide * 0.48f,
                new int[]{0x20FFBE78, 0x08FFBE78, 0x00090D13},
                new float[]{0f, 0.48f, 1f},
                Shader.TileMode.CLAMP
        );
        accentLine = new LinearGradient(
                0f,
                0f,
                width,
                0f,
                new int[]{0x005DE1C1, 0x665DE1C1, 0x0074A0FF},
                null,
                Shader.TileMode.CLAMP
        );
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(0xFF090D13);

        if (blueGlow != null) {
            glowPaint.setShader(blueGlow);
            canvas.drawRect(0f, 0f, getWidth(), getHeight(), glowPaint);
        }
        if (warmGlow != null) {
            glowPaint.setShader(warmGlow);
            canvas.drawRect(0f, 0f, getWidth(), getHeight(), glowPaint);
        }
        glowPaint.setShader(null);

        float step = dp(34);
        for (float x = -step; x < getWidth() + step; x += step) {
            canvas.drawLine(x, 0f, x, getHeight(), gridPaint);
        }
        for (float y = -step; y < getHeight() + step; y += step) {
            canvas.drawLine(0f, y, getWidth(), y, gridPaint);
        }

        if (accentLine != null) {
            accentPaint.setShader(accentLine);
            float startY = getHeight() * 0.31f;
            float endY = getHeight() * 0.07f;
            canvas.drawLine(-dp(20), startY, getWidth() + dp(20), endY, accentPaint);
            accentPaint.setShader(null);
        }
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }
}
