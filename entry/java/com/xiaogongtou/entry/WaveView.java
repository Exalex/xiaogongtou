package com.xiaogongtou.entry;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.util.AttributeSet;
import android.view.View;

/**
 * 语音声波线 v3 —— 「平线鼓出波峰」波浪式
 * （形态参考 BambooAppsDevTeam/speechwavesanimation 的 SpeechWaveView）
 *
 * 一条横贯全宽的平滑线：说话时从线上"鼓"出 2 个上下对称的波峰（叶形/眼形），
 * 随音量长高、随时间左右漂移、宽窄起伏；停下后振幅快速收敛，缓缓归为一条安静平线。
 * 音量数据 = 录音线程 push(0..1) 送入的 RMS 包络（取最近若干点的均值）。
 */
public class WaveView extends View {
    private static final int N = 80;

    private final float[] vals = new float[N];
    private float level = 0f;    // 平滑后的振幅（0..1）
    private float phase = 0f;    // 漂移相位
    private boolean live = false;
    private boolean loop = false;

    private final Paint pGlow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pLine = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            phase += 0.0075f;   // 漂移速度（≈2.2s 一个调制周期）
            float target = live ? curAmp() : 0f;
            // 快升慢降：说话立即起伏，停止后缓缓平息
            level += (target - level) * (target > level ? 0.42f : 0.085f);
            if (level < 0.006f) {
                level = 0f;
            }
            invalidate();
            if (live || level > 0f) {
                postDelayed(this, 16);
            } else {
                loop = false;
            }
        }
    };

    public WaveView(Context c) {
        super(c);
        init();
    }

    public WaveView(Context c, AttributeSet a) {
        super(c, a);
        init();
    }

    private void init() {
        float d = getResources().getDisplayMetrics().density;
        pGlow.setStyle(Paint.Style.STROKE);
        pGlow.setStrokeWidth(7.5f * d);
        pGlow.setStrokeCap(Paint.Cap.ROUND);
        pGlow.setStrokeJoin(Paint.Join.ROUND);
        pGlow.setColor(0xFF6FA8FF);
        pLine.setStyle(Paint.Style.STROKE);
        pLine.setStrokeWidth(2.6f * d);
        pLine.setStrokeCap(Paint.Cap.ROUND);
        pLine.setStrokeJoin(Paint.Join.ROUND);
        pLine.setColor(0xFFA9CCFF);
    }

    /** 送入一个音量包络值（0..1）。录音线程按音频块调用 */
    public void push(float v) {
        System.arraycopy(vals, 1, vals, 0, N - 1);
        vals[N - 1] = Math.max(0f, Math.min(1f, v));
        startLoop();
    }

    /** true=录音中（活跃，从平线开始）；false=停说（波形收敛） */
    public void setLive(boolean b) {
        live = b;
        if (b) {
            for (int i = 0; i < N; i++) {
                vals[i] = 0f;
            }
            level = 0f;
            phase = 0f;
        }
        startLoop();
    }

    private void startLoop() {
        if (!loop) {
            loop = true;
            postDelayed(tick, 16);
        }
    }

    /** 最近 6 个包络点的均值 = 当前目标振幅 */
    private float curAmp() {
        float s = 0f;
        for (int i = N - 6; i < N; i++) {
            s += vals[i];
        }
        return s / 6f;
    }

    @Override
    protected void onDraw(Canvas cv) {
        final float w = getWidth();
        final float h = getHeight();
        final float cy = h / 2f;

        if (level < 0.015f) {
            // 安静态：一条横贯全宽的平线
            pLine.setAlpha(135);
            cv.drawLine(4f, cy, w - 4f, cy, pLine);
            return;
        }

        // —— 两个对称高斯“包”：位置左右漂移、宽窄/高矮各自起伏 ——
        final float amp = level * (h * 0.40f);
        final float tp = phase * 6.2832f;
        final float c1 = w * (0.36f + 0.20f * (float) Math.sin(tp));
        final float c2 = w * (0.64f + 0.17f * (float) Math.sin(tp * 0.78f + 2.0f));
        final float s1 = w * (0.115f + 0.045f * (float) Math.sin(tp * 1.31f + 0.7f));
        final float s2 = w * (0.135f + 0.045f * (float) Math.sin(tp * 1.07f + 1.9f));
        float m1 = 0.60f + 0.40f * (float) Math.sin(tp * 0.91f + 0.4f);
        float m2 = 0.55f + 0.45f * (float) Math.sin(tp * 0.83f + 2.6f);
        if (m1 < 0f) {
            m1 = 0f;
        }
        if (m2 < 0f) {
            m2 = 0f;
        }

        // 闭合路径：上沿左→右，下沿右→左 → 上下对称的叶形
        path.reset();
        final int steps = 120;
        final float x0 = 4f, x1 = w - 4f;
        for (int i = 0; i <= steps; i++) {
            float x = x0 + (x1 - x0) * i / steps;
            float hh = hgt(x, amp, c1, s1, m1, c2, s2, m2);
            if (i == 0) {
                path.moveTo(x, cy - hh);
            } else {
                path.lineTo(x, cy - hh);
            }
        }
        for (int i = steps; i >= 0; i--) {
            float x = x0 + (x1 - x0) * i / steps;
            float hh = hgt(x, amp, c1, s1, m1, c2, s2, m2);
            path.lineTo(x, cy + hh);
        }
        path.close();

        float lv = Math.min(1f, level * 1.25f);
        pGlow.setAlpha((int) (34 + 88 * lv));
        cv.drawPath(path, pGlow);
        pLine.setAlpha((int) (150 + 100 * lv));
        cv.drawPath(path, pLine);
    }

    /** 双高斯包高度 */
    private static float hgt(float x, float amp, float c1, float s1, float m1,
                             float c2, float s2, float m2) {
        float d1 = (x - c1) / s1;
        float d2 = (x - c2) / s2;
        return amp * (m1 * (float) Math.exp(-d1 * d1) + m2 * (float) Math.exp(-d2 * d2));
    }
}
