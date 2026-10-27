package com.xiaogongtou.entry;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.SweepGradient;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.util.Log;
import android.view.View;

/**
 * 语音速记 · 全屏「边缘流光」v3 —— Siri / Gemini 式 edge glow
 * （配方参考 aravi365/react-native-edge-glow：12 层同心环 + 扫描渐变 + 低峰值透明度）
 *
 * 为什么是 v3（对 v2 的三个根治）：
 *   ① 颗粒感：不再预生成任何位图，全部实时矢量绘制 —— 渐隐由 12 层同心圆角环
 *      （同一描边路径、递变宽度、恒定低透明度）叠加而成，扫描渐变由 GPU shader 插值，
 *      天然无色带、无 dither 噪点、无分辨率损耗；
 *   ② 厚重：峰值透明度 ~0.58（12 环 × α0.070 叠加：1-(1-0.07)^12≈0.58），
 *      外缘一条极细亮线（1.6dp）+ 向内 24dp 薄雾渐隐 —— 通透、不刷漆；
 *   ③ 假静态：颜色沿整圈缓慢流动（SweepGradient.localMatrix 每帧旋转，2.6s/圈）。
 *
 * 动效编排（playEnter）：
 *   0-170ms   「噌」快速点亮（global 0→1，easeOut）
 *   170-730ms 光由外向内注入：12 环级联依次点亮（像光从边缘灌进来）
 *   730ms+    转入常驻呼吸（1.7s 周期，幅度 0.74~1.0）
 *   全程      色环持续旋转（2.6s/圈）
 *
 * 配色两套（入口 App 从 Settings.System「xgt_glow_palette」读取）：
 *   siri = 紫→蓝→青→绿→粉 彩流（默认）；ice = 纯冰蓝。
 */
public class GlowFrameView extends View {

    private static final String TAG = "xgt-glow";

    // 预设配色（首尾同色 → 扫描渐变无缝循环）
    private static final int[] PAL_SIRI = new int[]{
            0xFFB06BFF, 0xFF6B8CFF, 0xFF4FD8FF, 0xFF7BF0B0, 0xFFFF9AD5, 0xFFB06BFF};
    private static final int[] PAL_ICE = new int[]{
            0xFF8FCBFF, 0xFF6FB4FF, 0xFF4D9FFF, 0xFF3D7FE8, 0xFF9BD4FF, 0xFF8FCBFF};
    private static final float[] PAL_STOPS = new float[]{0f, 0.22f, 0.45f, 0.65f, 0.85f, 1f};

    private static final int RINGS = 12;             // 同心环层数
    private static final float DEPTH_DP = 24f;       // 光带总深度（从屏幕边往内, dp）
    private static final float CORE_DP = 1.6f;       // 外缘亮线宽度（dp）
    private static final float RING_ALPHA = 0.070f;  // 单环透明度（叠加峰值 ≈0.58）

    private final Paint pRing = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pCore = new Paint(Paint.ANTI_ALIAS_FLAG);

    private Path framePath;
    private SweepGradient sweep;
    private final Matrix sweepM = new Matrix();
    private int[] palette = PAL_SIRI;

    private float global = 0f;      // 0..1 全局亮度
    private float inject = 1f;      // 0..1 注入进度（环由外向内级联点亮）
    private float breath = 1f;      // 呼吸倍率
    private float rotDeg = 0f;      // 色环旋转角
    private long phaseStart = 0;    // 进场时间基准
    private ValueAnimator anim;
    private boolean pendingEnter = false;

    public GlowFrameView(Context c) {
        super(c);
        init();
    }

    public GlowFrameView(Context c, AttributeSet a) {
        super(c, a);
        init();
    }

    private void init() {
        pRing.setStyle(Paint.Style.STROKE);
        pCore.setStyle(Paint.Style.STROKE);
        pCore.setStrokeCap(Paint.Cap.ROUND);
    }

    /** 配色切换：siri（彩流，默认）/ ice（纯冰蓝） */
    public void setPalette(String name) {
        palette = "ice".equalsIgnoreCase(name) ? PAL_ICE : PAL_SIRI;
        sweep = null;   // 下次绘制时按当前尺寸重建
        invalidate();
    }

    private void ensureShader() {
        int w = getWidth(), h = getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        if (sweep == null) {
            sweep = new SweepGradient(w / 2f, h / 2f, palette, PAL_STOPS);
        }
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        float d = getResources().getDisplayMetrics().density;
        float r = 20f * d;   // 屏幕物理圆角（60px@1080 ≈ 20dp）
        framePath = new Path();
        framePath.addRoundRect(new RectF(0.75f, 0.75f, w - 0.75f, h - 0.75f), r, r,
                Path.Direction.CW);
        sweep = null;
        ensureShader();
        if (pendingEnter) {
            pendingEnter = false;
            startEnterAnim();
        }
    }

    @Override
    protected void onDraw(Canvas cv) {
        if (framePath == null || global <= 0.004f) {
            return;
        }
        ensureShader();
        if (sweep == null) {
            return;
        }
        final float d = getResources().getDisplayMetrics().density;
        sweepM.setRotate(rotDeg, getWidth() / 2f, getHeight() / 2f);
        sweep.setLocalMatrix(sweepM);

        // —— 12 层同心环：居中描边（外半幅天然出屏），由外向内级联点亮 ——
        final float step = DEPTH_DP * d / RINGS;
        pRing.setShader(sweep);
        for (int j = RINGS - 1; j >= 0; j--) {
            float reach = step * (j + 1);
            float start = j / (float) (RINGS - 1) * 0.66f;
            float e = (inject - start) / 0.34f;
            if (e <= 0f) {
                continue;
            }
            if (e > 1f) {
                e = 1f;
            }
            float a = RING_ALPHA * global * breath * e;
            if (a < 0.004f) {
                continue;
            }
            pRing.setAlpha((int) (a * 255f));
            pRing.setStrokeWidth(reach * 2f);
            cv.drawPath(framePath, pRing);
        }

        // —— 外缘亮线（灯丝）：细、亮、随扫描渐变着色 ——
        pCore.setShader(sweep);
        pCore.setAlpha((int) (Math.min(1f, 0.92f * global) * 255f));
        pCore.setStrokeWidth(CORE_DP * d);
        cv.drawPath(framePath, pCore);
    }

    /** 进场：「噌」点亮 → 光由外向内注入 → 呼吸（贴图/尺寸未就绪则挂起） */
    public void playEnter() {
        stop();
        if (getWidth() <= 0 || framePath == null) {
            pendingEnter = true;
            return;
        }
        Log.i(TAG, "playEnter v3 " + getWidth() + "x" + getHeight());
        startEnterAnim();
    }

    private void startEnterAnim() {
        stop();
        phaseStart = SystemClock.uptimeMillis();
        anim = ValueAnimator.ofFloat(0f, 1f);
        anim.setDuration(1);
        anim.setRepeatCount(ValueAnimator.INFINITE);
        anim.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override
            public void onAnimationUpdate(ValueAnimator a) {
                update();
            }
        });
        anim.start();
        update();
    }

    private void update() {
        if (phaseStart <= 0) {
            return;
        }
        long el = SystemClock.uptimeMillis() - phaseStart;
        // ① 快开（170ms easeOut）
        float g = Math.min(1f, el / 170f);
        global = 1f - (1f - g) * (1f - g);
        // ② 注入：光从边缘灌入（560ms easeOutCubic → 环级联）
        if (el <= 170) {
            inject = 0f;
        } else {
            float p = Math.min(1f, (el - 170f) / 560f);
            inject = 1f - (1f - p) * (1f - p) * (1f - p);
        }
        // ③ 呼吸（1.7s 周期，0.74~1.0）
        if (el < 760) {
            breath = 1f;
        } else {
            double ph = (el - 760) * 2.0 * Math.PI / 1700.0;
            breath = 0.74f + 0.13f * (float) (1.0 + Math.sin(ph));
        }
        // ④ 色环扫动（2.6s/圈）
        rotDeg = (el % 2600L) / 2600f * 360f;
        invalidate();
    }

    /** 退出：快速淡出 */
    public void playExit() {
        stop();
        final float g0 = global;
        anim = ValueAnimator.ofFloat(g0, 0f);
        anim.setDuration(160);
        anim.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override
            public void onAnimationUpdate(ValueAnimator a) {
                global = (Float) a.getAnimatedValue();
                invalidate();
            }
        });
        anim.addListener(new AnimatorListenerAdapter() {
            @Override
            public void onAnimationEnd(Animator a) {
                phaseStart = 0;
            }
        });
        anim.start();
    }

    private void stop() {
        if (anim != null) {
            anim.cancel();
            anim = null;
        }
    }
}
