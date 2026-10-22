package com.xiaogongtou.entry;

import android.animation.ValueAnimator;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.graphics.Shader;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.LinearInterpolator;
import android.view.animation.OvershootInterpolator;
import android.widget.FrameLayout;

/**
 * 「任务栏」——屏幕顶部居中的全局任务进度横条（对照豆包手机的"顶部横条"）。
 *
 * 形态：深色玻璃药丸 + 冰蓝描边；两行信息（任务名 / 最新进展）+ 底部流动光带。
 * 行为（"接管"）：
 *   - 任一入口提交任务（语音对话框 / 悬浮面板 / 对话页）→ 任务栏出现并跟踪进度；
 *   - 运行中：呼吸点 + 流光循环 + 步数/秒数实时刷新；
 *   - 结束：切"✔ 完成 / ⚠ 未完成 / ⏹ 已停止"结果态，停留数秒后自动收起。
 * 载体：TYPE_ACCESSIBILITY_OVERLAY（无障碍服务窗口），任意界面可见。
 *
 * 数据流：Poller（EntryA11yService）任务状态轮询 → onRunning/onResult；
 *         提交方（VoiceBar/PanelBinder）→ kickoff（立即点亮，不等轮询）。
 */
public final class TaskBar {
    public static final int KIND_RUN = 0;
    public static final int KIND_OK = 1;
    public static final int KIND_FAIL = 2;
    public static final int KIND_STOP = 3;

    private static TaskBar inst;

    private final EntryA11yService svc;
    private final WindowManager wm;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final FrameLayout root;
    private final BarView bar;
    private final WindowManager.LayoutParams lp;
    private final int W;
    private final int H;
    private final int RESERVE;   // 顶部预留滑动空间（进场从上滑下）

    private boolean visible = false;
    private boolean attached = false;   // 窗口是否已在 WindowManager 中
    private int kind = KIND_RUN;
    private String head = "";    // 行1 左：任务名 / 结果标题
    private String info = "";    // 行1 右：步数 · 秒数
    private String sub = "";     // 行2：最新进展 / 任务名
    private int step = 0;
    private int elapsed = 0;
    private float phase = 0f;    // 循环相位（呼吸点 + 流光）
    private float pulse = 0f;    // 落地/接力脉冲（描边与内亮）
    private ValueAnimator loop;
    private Runnable autoHide;

    // ------------------------------------------------------------ 对外 API

    /** 提交瞬间点亮（不等轮询；之后 Poller 持续刷新） */
    public static void kickoff(Context c, String task) {
        android.util.Log.i("xgt-taskbar", "kickoff: " + task);
        final TaskBar t = obtain(c);
        if (t == null) {
            android.util.Log.w("xgt-taskbar", "kickoff: obtain null");
            return;
        }
        final String tk = task == null ? "" : task;
        t.ui.post(new Runnable() {
            @Override
            public void run() {
                android.util.Log.i("xgt-taskbar", "kickoff/ui run, visible=" + t.visible);
                boolean wasVisible = t.visible;
                t.kind = KIND_RUN;
                t.head = tk;
                t.info = "启动中…";
                t.sub = "正在准备…";
                t.step = 0;
                t.elapsed = 0;
                t.setTouchable(false);   // 运行中：点击穿透，别抢 App 的点击
                t.showIfNeeded();
                t.startLoop();
                if (wasVisible) {
                    t.firePulse();
                }
                t.bar.invalidate();
            }
        });
    }

    /** 运行中刷新（Poller 每 ~2s） */
    public static void onRunning(Context c, String task, int step, double elapsed, String line) {
        android.util.Log.i("xgt-taskbar", "onRunning: " + task + " step=" + step);
        final TaskBar t = obtain(c);
        if (t == null) {
            android.util.Log.w("xgt-taskbar", "onRunning: obtain null");
            return;
        }
        final String tk = task == null ? "" : task;
        final String ln = line == null ? "" : line;
        final int st = step;
        final int el = (int) Math.round(elapsed);
        t.ui.post(new Runnable() {
            @Override
            public void run() {
                android.util.Log.i("xgt-taskbar", "onRunning/ui run, visible=" + t.visible);
                boolean fresh = !t.visible;
                t.kind = KIND_RUN;
                t.head = tk;
                t.step = st;
                t.elapsed = el;
                t.info = (st > 0 ? "第 " + st + " 步" : "运行中") + " · " + el + "s";
                t.sub = ln.isEmpty() ? "正在干活…" : ln;
                t.setTouchable(false);   // 运行中：点击穿透
                t.showIfNeeded();
                t.startLoop();
                if (fresh) {
                    t.firePulse();
                }
                t.bar.invalidate();
            }
        });
    }

    /** 结束：结果态（停留数秒自动收起） */
    public static void onResult(Context c, int kind, String task, String text) {
        android.util.Log.i("xgt-taskbar", "onResult kind=" + kind + " " + task);
        final TaskBar t = obtain(c);
        if (t == null) {
            android.util.Log.w("xgt-taskbar", "onResult: obtain null");
            return;
        }
        final int k = kind;
        final String tk = task == null ? "" : task;
        final String tx = text == null ? "" : text;
        t.ui.post(new Runnable() {
            @Override
            public void run() {
                android.util.Log.i("xgt-taskbar", "onResult/ui run, visible=" + t.visible);
                t.kind = k;
                t.info = t.elapsed > 0 ? t.elapsed + "s" : "";
                if (k == KIND_OK) {
                    t.head = "✔ " + clip(tx.isEmpty() ? "任务完成" : tx, 30);
                } else if (k == KIND_FAIL) {
                    t.head = "⚠ " + clip(tx.isEmpty() ? "没完成" : tx, 30);
                } else {
                    t.head = "⏹ 已停止";
                }
                t.sub = tk;
                t.stopLoop();
                t.setTouchable(true);    // 已结束：恢复可点（点它进对话页看结果）
                t.showIfNeeded();
                t.firePulse();
                t.bar.invalidate();
                // 完成提醒：轻震动一下（成功短促、失败双击），停留加长到 8s 让人看清结果
                t.buzz(k == KIND_OK);
                t.scheduleHide(k == KIND_OK ? 8000 : (k == KIND_FAIL ? 8000 : 3500));
            }
        });
    }

    /** 飞行动画"落地"脉冲（FlyView 到达任务栏位置时调用） */
    public static void landed() {
        final TaskBar t = inst;
        if (t == null) {
            return;
        }
        t.ui.post(new Runnable() {
            @Override
            public void run() {
                t.firePulse();
            }
        });
    }

    public static boolean isShowing() {
        TaskBar t = inst;
        return t != null && t.visible;
    }

    /** 服务退出清理（强拆，不动画） */
    public static synchronized void tearDown() {
        if (inst != null) {
            inst.destroy();
            inst = null;
        }
    }

    // ------------------------------------------------------------ 内部实现

    private static synchronized TaskBar obtain(Context c) {
        EntryA11yService s = (c instanceof EntryA11yService) ? (EntryA11yService) c : EntryA11yService.svc();
        if (s == null) {
            return null;
        }
        if (inst == null || inst.svc != s) {
            if (inst != null) {
                inst.destroy();
            }
            try {
                inst = new TaskBar(s);
            } catch (Exception e) {
                android.util.Log.w("xgt-entry", "taskbar create failed", e);
                inst = null;
            }
        }
        return inst;
    }

    private TaskBar(EntryA11yService s) {
        svc = s;
        wm = (WindowManager) s.getSystemService(Context.WINDOW_SERVICE);
        float d = s.getResources().getDisplayMetrics().density;
        int screenW = s.getResources().getDisplayMetrics().widthPixels;
        W = Math.min(dp(340, d), screenW - dp(56, d));
        H = dp(54, d);
        RESERVE = dp(34, d);

        bar = new BarView(s);
        root = new FrameLayout(s);
        FrameLayout.LayoutParams bp = new FrameLayout.LayoutParams(W, H,
                Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        root.addView(bar, bp);
        // 点任务栏 = 打开对话页看结果（完成态停留 8s，看不够就点进去）
        root.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                try {
                    Intent it = new Intent(svc, MainActivity.class);
                    it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_ACTIVITY_SINGLE_TOP
                            | Intent.FLAG_ACTIVITY_BROUGHT_TO_FRONT);
                    svc.startActivity(it);
                } catch (Exception e) {
                    android.util.Log.w("xgt-taskbar", "taskbar tap -> open main failed", e);
                }
            }
        });

        lp = new WindowManager.LayoutParams(W, H + RESERVE,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        // 2026-10-22：默认不可点，运行中一律让点击穿透（见 setTouchable）
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        if (Build.VERSION.SDK_INT >= 30) {
            lp.setFitInsetsTypes(0);
        }
        lp.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        int sb = statusBarHeight(s);
        lp.y = Math.max(0, sb + dp(6, d) - RESERVE);
    }

    /** 2026-10-22：运行中必须让点击穿透。
     *  实测：任务栏是「顶部居中 340dp」，正好盖住目标 App 的顶部标签栏
     *  （B站「热门」在屏幕正中 x=1081，被完全覆盖），把本该给 App 的点击吃掉 →
     *  agent 反复点不动、被判"动作循环"提前放弃，白烧十几步。
     *  规则：运行中 = NOT_TOUCHABLE（纯展示）；结果态 = 可点（点它进对话页看结果）。 */
    private void setTouchable(boolean touchable) {
        if (lp == null) {
            return;
        }
        boolean notTouchable =
                (lp.flags & WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE) != 0;
        if (touchable == !notTouchable) {
            return;   // 已是目标状态
        }
        if (touchable) {
            lp.flags &= ~WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE;
        } else {
            lp.flags |= WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE;
        }
        if (attached) {
            try {
                wm.updateViewLayout(root, lp);
            } catch (Exception e) {
                android.util.Log.w("xgt-taskbar", "updateViewLayout failed", e);
            }
        }
    }

    private void showIfNeeded() {
        cancelAutoHide();
        if (attached && !root.isAttachedToWindow()) {
            // 异常态自愈：窗口已被系统移除但状态未同步（如服务重绑/系统清窗）
            android.util.Log.w("xgt-taskbar", "window detached unexpectedly -> re-add");
            attached = false;
            visible = false;
        }
        if (visible) {
            return;
        }
        visible = true;
        bar.animate().cancel();
        if (!attached) {
            try {
                wm.addView(root, lp);
                attached = true;
                android.util.Log.i("xgt-taskbar", "window added " + W + "x" + (H + RESERVE)
                        + " y=" + lp.y + " py=" + bar.getY());
            } catch (Exception e) {
                android.util.Log.w("xgt-taskbar", "taskbar show failed", e);
                visible = false;
                return;
            }
        }
        bar.setAlpha(0f);
        bar.setTranslationY(-RESERVE);
        bar.animate().alpha(1f).translationY(0f)
                .setDuration(310)
                .setInterpolator(new OvershootInterpolator(0.55f))
                .start();
    }

    private void hideAnimated() {
        if (!visible) {
            return;
        }
        visible = false;
        stopLoop();
        cancelAutoHide();
        bar.animate().cancel();
        bar.animate().alpha(0f).translationY(-RESERVE * 0.85f)
                .setDuration(240)
                .withEndAction(new Runnable() {
                    @Override
                    public void run() {
                        // 注意：动画被 cancel 也会走这里 → 用 visible 再确认一次
                        if (!visible && attached) {
                            try {
                                wm.removeView(root);
                            } catch (Exception ignored) {
                            }
                            attached = false;
                        }
                    }
                }).start();
    }

    private void destroy() {
        stopLoop();
        cancelAutoHide();
        try {
            bar.animate().cancel();
        } catch (Exception ignored) {
        }
        visible = false;
        if (attached) {
            try {
                wm.removeView(root);
            } catch (Exception ignored) {
            }
            attached = false;
        }
    }

    private void scheduleHide(long delay) {
        cancelAutoHide();
        autoHide = new Runnable() {
            @Override
            public void run() {
                hideAnimated();
            }
        };
        ui.postDelayed(autoHide, delay);
    }

    /** 完成提醒震动：成功短促一下，失败双击（更"有事"的感觉） */
    private void buzz(boolean ok) {
        try {
            Vibrator v = (Vibrator) svc.getSystemService(Context.VIBRATOR_SERVICE);
            if (v == null || !v.hasVibrator()) {
                return;
            }
            if (ok) {
                v.vibrate(VibrationEffect.createOneShot(60, VibrationEffect.DEFAULT_AMPLITUDE));
            } else {
                v.vibrate(VibrationEffect.createWaveform(
                        new long[]{0, 60, 110, 60}, new int[]{0, 200, 0, 220}, -1));
            }
        } catch (Exception ignored) {
        }
    }

    private void cancelAutoHide() {
        if (autoHide != null) {
            ui.removeCallbacks(autoHide);
            autoHide = null;
        }
    }

    private void startLoop() {
        if (loop != null) {
            return;
        }
        loop = ValueAnimator.ofFloat(0f, 1f);
        loop.setDuration(1700);
        loop.setRepeatCount(ValueAnimator.INFINITE);
        loop.setInterpolator(new LinearInterpolator());
        loop.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override
            public void onAnimationUpdate(ValueAnimator a) {
                phase = (Float) a.getAnimatedValue();
                bar.invalidate();
            }
        });
        loop.start();
    }

    private void stopLoop() {
        if (loop != null) {
            loop.cancel();
            loop = null;
        }
    }

    private void firePulse() {
        ValueAnimator va = ValueAnimator.ofFloat(1f, 0f);
        va.setDuration(560);
        va.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override
            public void onAnimationUpdate(ValueAnimator a) {
                pulse = (Float) a.getAnimatedValue();
                bar.invalidate();
            }
        });
        va.start();
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

    private static int dp(float v, float d) {
        return Math.round(v * d);
    }

    private static String clip(String s, int n) {
        if (s == null) {
            return "";
        }
        s = s.replace('\n', ' ').trim();
        return s.length() > n ? s.substring(0, n) + "…" : s;
    }

    // ------------------------------------------------------------ 横条视图（全自绘）

    private final class BarView extends View {
        private final Paint pBg = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pPulse = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pStroke = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pDot = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pT1 = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pTr = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pT2 = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pLine = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pGlow = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path clipPath = new Path();
        private final RectF rf = new RectF();
        private final float d;
        private final float sd;

        BarView(Context c) {
            super(c);
            d = getResources().getDisplayMetrics().density;
            sd = getResources().getDisplayMetrics().scaledDensity;
            pBg.setColor(0xE60C1523);
            pPulse.setColor(0xFFFFFFFF);
            pStroke.setStyle(Paint.Style.STROKE);
            pT1.setTextSize(13.5f * sd);
            pT1.setColor(0xFFF2F7FF);
            pT1.setFakeBoldText(true);
            pTr.setTextSize(11.5f * sd);
            pTr.setColor(0xFF9FC0E8);
            pT2.setTextSize(11.5f * sd);
            pT2.setColor(0xFF8FA2B8);
            pGlow.setStyle(Paint.Style.FILL);
        }

        @Override
        protected void onDraw(Canvas cv) {
            final float w = getWidth(), h = getHeight();
            final float r = h / 2f;
            int accent = accentColor(kind);

            rf.set(0f, 0f, w, h);
            clipPath.reset();
            clipPath.addRoundRect(rf, r, r, Path.Direction.CW);
            cv.save();
            cv.clipPath(clipPath);

            // 背景
            cv.drawRoundRect(rf, r, r, pBg);

            // 落地脉冲：内部点亮 + 描边增强
            if (pulse > 0.01f) {
                pPulse.setAlpha((int) (pulse * 38));
                cv.drawRoundRect(rf, r, r, pPulse);
            }

            // 描边（呼吸 + 脉冲）
            float breath = (kind == KIND_RUN) ? 0.10f * (0.5f + 0.5f * (float) Math.sin(phase * 2 * Math.PI)) : 0f;
            float strokeBase = (kind == KIND_RUN) ? 0.36f : (kind == KIND_OK ? 0.55f : (kind == KIND_FAIL ? 0.52f : 0.34f));
            int strokeA = (int) (255 * Math.min(1f, strokeBase + breath + pulse * 0.5f));
            pStroke.setColor(accent);
            pStroke.setAlpha(strokeA);
            pStroke.setStrokeWidth(1.2f * d + pulse * 1.6f * d);
            rf.set(0.6f * d, 0.6f * d, w - 0.6f * d, h - 0.6f * d);
            cv.drawRoundRect(rf, r - 0.6f * d, r - 0.6f * d, pStroke);

            // 底部光带
            float ly = h - 5f * d;
            float lh = 2.4f * d;
            if (kind == KIND_RUN) {
                // 基线（暗）
                pLine.setColor(0x2A3E5B85);
                rf.set(16f * d, ly, w - 16f * d, ly + lh);
                cv.drawRoundRect(rf, lh / 2, lh / 2, pLine);
                // 流光段（循环扫过）
                float segW = 74f * d;
                float span = w + segW * 2;
                float gx = -segW + phase * span;
                LinearGradient sh = new LinearGradient(gx, 0f, gx + segW, 0f,
                        new int[]{0x009CCBFF, 0xB39CCBFF, 0x009CCBFF},
                        new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP);
                pGlow.setShader(sh);
                cv.drawRect(gx, ly, gx + segW, ly + lh, pGlow);
                pGlow.setShader(null);
            } else {
                pLine.setColor(accent);
                pLine.setAlpha(115);
                rf.set(16f * d, ly, w - 16f * d, ly + lh);
                cv.drawRoundRect(rf, lh / 2, lh / 2, pLine);
            }

            // 状态点（呼吸）
            float cx = 21f * d, cy = 18f * d, rDot = 4.6f * d;
            int dotA;
            if (kind == KIND_RUN) {
                dotA = (int) (255 * (0.40f + 0.60f * (0.5f + 0.5f * (float) Math.sin(phase * 2 * Math.PI))));
            } else {
                dotA = 255;
            }
            pDot.setColor(accent);
            pDot.setAlpha(dotA / 6);
            cv.drawCircle(cx, cy, rDot * 2.15f, pDot);
            pDot.setAlpha(dotA);
            cv.drawCircle(cx, cy, rDot, pDot);

            // 行1：左侧
            float x1 = 36f * d;
            float y1 = 23.5f * d;
            String h1 = fit(head, pT1, w - x1 - 20f * d);
            // 行1：右侧 info 先量宽，左侧让位
            float infoW = info.isEmpty() ? 0f : pTr.measureText(info);
            if (infoW > 0f) {
                h1 = fit(head, pT1, w - x1 - infoW - 30f * d);
            }
            cv.drawText(h1, x1, y1, pT1);
            if (infoW > 0f) {
                cv.drawText(info, w - 20f * d - infoW, y1, pTr);
            }

            // 行2：最新进展
            String h2 = fit(sub, pT2, w - 36f * d - 20f * d);
            cv.drawText(h2, 36f * d, 41.5f * d, pT2);

            cv.restore();
        }

        private int accentColor(int k) {
            if (k == KIND_OK) {
                return 0xFF59D9A2;
            }
            if (k == KIND_FAIL) {
                return 0xFFFF9E7C;
            }
            if (k == KIND_STOP) {
                return 0xFF9FAAB8;
            }
            return 0xFF5B9BFF;
        }

        private String fit(String s, Paint p, float maxW) {
            if (s == null) {
                return "";
            }
            if (p.measureText(s) <= maxW) {
                return s;
            }
            int n = s.length();
            while (n > 1 && p.measureText(s, 0, n) + p.measureText("…") > maxW) {
                n--;
            }
            return s.substring(0, Math.max(1, n)) + "…";
        }
    }
}
