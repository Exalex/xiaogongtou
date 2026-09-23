package com.xiaogongtou.entry;

import android.content.Context;
import android.graphics.PixelFormat;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.DecelerateInterpolator;
import android.widget.FrameLayout;
import android.widget.Toast;

/**
 * 悬浮输入面板（不启动 Activity）：未来感深色玻璃卡片 + 发光呼吸动画。
 * 彻底避开 Android 后台启动限制与 ColorOS 对「后台启动 Activity」的 o-stop 清理。
 */
public class PanelOverlay {
    private static PanelOverlay current;

    private final Context ctx;
    private final WindowManager wm;
    private final View rootView;
    private final View glowWrap;
    private final WindowManager.LayoutParams lp;
    private final PanelBinder binder;

    public static void show(Context ctx) {
        hideCurrent();
        PanelOverlay p = new PanelOverlay(ctx);
        p.attach();
        current = p;
    }

    public static void hideCurrent() {
        PanelOverlay p = current;
        current = null;
        if (p != null) {
            p.detach();
        }
    }

    public static boolean isShowing() {
        return current != null;
    }

    /** 快捷键入口：面板已开 → 提交（"再按一下执行"）；未开 → 唤起 */
    public static void hotkeyAction(Context ctx) {
        if (current != null && current.binder != null) {
            current.binder.submitNow();
        } else {
            show(ctx);
        }
    }

    private PanelOverlay(Context ctx) {
        this.ctx = ctx;
        this.wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
        LayoutInflater inflater = LayoutInflater.from(ctx);
        rootView = inflater.inflate(R.layout.activity_panel, null);
        glowWrap = rootView.findViewById(R.id.glowWrap);

        DisplayMetrics dm = ctx.getResources().getDisplayMetrics();
        FrameLayout.LayoutParams cp = (FrameLayout.LayoutParams) glowWrap.getLayoutParams();
        cp.topMargin = Math.round(dm.heightPixels * 0.14f);
        glowWrap.setLayoutParams(cp);

        binder = new PanelBinder(ctx, rootView, new PanelBinder.Host() {
            @Override
            public void onSubmitSuccess(String task) {
                hideCurrent();
            }

            @Override
            public void onCancel() {
                hideCurrent();
            }

            @Override
            public void toast(String msg) {
                Toast.makeText(ctx, msg, Toast.LENGTH_SHORT).show();
            }
        });

        lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
                | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE;
    }

    public void setPrefill(String text) {
        binder.setPrefill(text);
    }

    private void attach() {
        try {
            wm.addView(rootView, lp);
            playEnter();
            rootView.post(new Runnable() {
                @Override
                public void run() {
                    binder.focusInput();
                }
            });
        } catch (Exception e) {
            android.util.Log.w("xgt-entry", "panel show failed: " + e, e);
        }
    }

    /** 入场：整体淡入 + 卡片上浮放大 + 光晕随后开始呼吸 */
    private void playEnter() {
        rootView.setAlpha(0f);
        rootView.animate().alpha(1f).setDuration(200).start();

        glowWrap.setTranslationY(dp(28));
        glowWrap.setScaleX(0.96f);
        glowWrap.setScaleY(0.96f);
        glowWrap.animate()
                .translationY(0f)
                .scaleX(1f)
                .scaleY(1f)
                .setDuration(260)
                .setInterpolator(new DecelerateInterpolator())
                .start();
    }

    private void detach() {
        final View rv = rootView;
        try {
            rv.animate().alpha(0f).setDuration(150).withEndAction(new Runnable() {
                @Override
                public void run() {
                    try {
                        wm.removeView(rv);
                    } catch (Exception ignored) {
                    }
                }
            }).start();
        } catch (Exception e) {
            try {
                wm.removeView(rv);
            } catch (Exception ignored) {
            }
        }
        binder.destroy();
    }

    private int dp(float v) {
        return Math.round(v * ctx.getResources().getDisplayMetrics().density);
    }
}
