package dev.openaver.mobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

/** Calm ambient canvas matching the WebView's cinema-dark and clean-light surfaces. */
public final class BackdropView extends View {
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private RadialGradient coralGlow;
    private RadialGradient slateGlow;
    private boolean lightMode;

    public BackdropView(Context context) {
        this(context, null);
    }

    public BackdropView(Context context, AttributeSet attrs) {
        super(context, attrs);
        setWillNotDraw(false);
        lightMode = false;
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        float minSide = Math.min(width, height);
        int baseTransparent = lightMode ? 0x00F5F6F8 : 0x00111317;
        coralGlow = new RadialGradient(
                width * 0.85f,
                height * 0.10f,
                minSide * 0.72f,
                new int[]{lightMode ? 0x16D14E12 : 0x1CFF8A4C, lightMode ? 0x06D14E12 : 0x08FF8A4C, baseTransparent},
                new float[]{0f, 0.45f, 1f},
                Shader.TileMode.CLAMP
        );
        slateGlow = new RadialGradient(
                width * 0.12f,
                height * 0.78f,
                minSide * 0.64f,
                new int[]{lightMode ? 0x124D5562 : 0x183B4A6B, lightMode ? 0x044D5562 : 0x053B4A6B, baseTransparent},
                new float[]{0f, 0.50f, 1f},
                Shader.TileMode.CLAMP
        );
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(lightMode ? 0xFFF5F6F8 : 0xFF111317);

        if (coralGlow != null) {
            glowPaint.setShader(coralGlow);
            canvas.drawRect(0f, 0f, getWidth(), getHeight(), glowPaint);
        }
        if (slateGlow != null) {
            glowPaint.setShader(slateGlow);
            canvas.drawRect(0f, 0f, getWidth(), getHeight(), glowPaint);
        }
        glowPaint.setShader(null);
    }
}
