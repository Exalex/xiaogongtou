package com.xiaogongtou.entry;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.PathInterpolator;

/**
 * 提交飞行动画：一个"任务胶囊"从对话框/输入框起飞，沿弧线飞向顶部任务栏，缩小淡出——
 * 视觉上"任务被丢进任务栏"。由 VoiceBar / PanelBinder 在提交成功后调用。
 *
 * 载体：全屏透明 TYPE_ACCESSIBILITY_OVERLAY（不可触摸，纯视觉）；动画结束自动移除窗口。
 * 终点 = TaskBar 落点（屏幕顶部中央，状态栏下方）。
 */
public final class FlyView {
    private FlyView() {
    }

    public static void launch(EntryA11yService svc, float fromX, float fromY, String text, final Runnable onLand) {
        if (svc == null) {
            return;
        }
        try {
            new Impl(svc, fromX, fromY, text, onLand).run();
        } catch (Exception e) {
            android.util.Log.w("xgt-entry", "fly view failed", e);
        }
    }

    private static final class Impl {
        private final WindowManager wm;
        private final WindowManager.LayoutParams lp;
        private final Inner inner;

        Impl(EntryA11yService s, float fromX, float fromY, String text, Runnable onLand) {
            wm = (WindowManager) s.getSystemService(Context.WINDOW_SERVICE);
            float d = s.getResources().getDisplayMetrics().density;
            int screenW = s.getResources().getDisplayMetrics().widthPixels;
            int sb = statusBarHeight(s);
            float toX = screenW / 2f;
            float toY = sb + 6f * d + 27f * d;   // 与 TaskBar 的位置公式一致

            inner = new Inner(s, fromX, fromY, toX, toY, text, onLand);

            lp = new WindowManager.LayoutParams(
                    WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                            | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                            | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                    PixelFormat.TRANSLUCENT);
            lp.gravity = Gravity.TOP | Gravity.START;
            if (Build.VERSION.SDK_INT >= 30) {
                lp.setFitInsetsTypes(0);
            }
            lp.layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        }

        void run() {
            wm.addView(inner, lp);
            inner.play();
        }
    }

    private static final class Inner extends View {
        private final Paint pBg = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pStroke = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pText = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF rf = new RectF();
        private final float d;
        private final float fromX, fromY, toX, toY;
        private final float ctrlX, ctrlY;
        private final String label;
        private final float pillW, pillH;
        private final Runnable onLand;
        private float t = 0f;
        private boolean landFired = false;
        private ValueAnimator anim;

        Inner(Context c, float fx, float fy, float tx, float ty, String text, Runnable onLand) {
            super(c);
            d = getResources().getDisplayMetrics().density;
            float sd = getResources().getDisplayMetrics().scaledDensity;
            this.fromX = fx;
            this.fromY = fy;
            this.toX = tx;
            this.toY = ty;
            this.onLand = onLand;
            this.label = clip(text, 20);

            pBg.setColor(0xE60C1523);
            pStroke.setStyle(Paint.Style.STROKE);
            pStroke.setStrokeWidth(1.3f * d);
            pStroke.setColor(0x8C7CC4FF);
            pText.setTextSize(12.5f * sd);
            pText.setColor(0xFFF2F7FF);

            pillH = 40f * d;
            float tw = pText.measureText(label);
            pillW = Math.min(242f * d, Math.max(96f * d, tw + 36f * d));

            // 弧线控制点：中段略上抬（"抛"的观感）
            ctrlX = (fx + tx) / 2f;
            ctrlY = Math.min(fy, ty) - Math.max(60f * d, Math.abs(fy - ty) * 0.16f);
        }

        void play() {
            anim = ValueAnimator.ofFloat(0f, 1f);
            anim.setDuration(720);
            anim.setInterpolator(new PathInterpolator(0.32f, 0f, 0.28f, 1f));
            anim.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override
                public void onAnimationUpdate(ValueAnimator a) {
                    t = (Float) a.getAnimatedValue();
                    if (t >= 0.88f && !landFired) {
                        landFired = true;
                        if (onLand != null) {
                            try {
                                onLand.run();
                            } catch (Exception ignored) {
                            }
                        }
                    }
                    invalidate();
                }
            });
            anim.addListener(new AnimatorListenerAdapter() {
                @Override
                public void onAnimationEnd(Animator a) {
                    try {
                        WindowManager wm = (WindowManager)
                                getContext().getSystemService(Context.WINDOW_SERVICE);
                        if (wm != null) {
                            wm.removeView(Inner.this);
                        }
                    } catch (Exception ignored) {
                    }
                }
            });
            anim.start();
        }

        @Override
        protected void onDraw(Canvas cv) {
            float et = t;
            float x = quad(fromX, ctrlX, toX, et);
            float y = quad(fromY, ctrlY, toY, et);
            float s = 1f - 0.70f * (float) Math.pow(et, 1.5);
            float alpha = et < 0.80f ? 1f : Math.max(0f, 1f - (et - 0.80f) / 0.20f);
            if (alpha <= 0.01f) {
                return;
            }
            int a = (int) (alpha * 255);

            cv.save();
            cv.scale(s, s, x, y);

            pBg.setAlpha(a);
            pStroke.setAlpha((int) (a * 0.62f));
            pText.setAlpha(a);

            rf.set(x - pillW / 2f, y - pillH / 2f, x + pillW / 2f, y + pillH / 2f);
            float r = pillH / 2f;
            cv.drawRoundRect(rf, r, r, pBg);
            rf.inset(0.7f * d, 0.7f * d);
            cv.drawRoundRect(rf, r - 0.7f * d, r - 0.7f * d, pStroke);

            float tw = pText.measureText(label);
            cv.drawText(label, x - tw / 2f, y + pText.getTextSize() * 0.36f, pText);

            cv.restore();
        }

        private static float quad(float a, float b, float c, float t) {
            float u = 1f - t;
            return u * u * a + 2f * u * t * b + t * t * c;
        }

        private static String clip(String s, int n) {
            if (s == null) {
                return "";
            }
            s = s.replace('\n', ' ').trim();
            return s.length() > n ? s.substring(0, n) + "…" : s;
        }
    }

    private static int statusBarHeight(Context c) {
        try {
            int id = c.getResources().getIdentifier("status_bar_height", "dimen", "android");
            if (id > 0) {
                return c.getResources().getDimensionPixelSize(id);
            }
        } catch (Exception ignored) {
        }
        return Math.round(28 * c.getResources().getDisplayMetrics().density);
    }
}
