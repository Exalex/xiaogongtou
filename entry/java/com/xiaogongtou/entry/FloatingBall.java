package com.xiaogongtou.entry;

import android.content.Context;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/** 全局悬浮球（由无障碍服务承载：TYPE_ACCESSIBILITY_OVERLAY，免冻结） */
public class FloatingBall {
    private final Context ctx;
    private final WindowManager wm;
    private final TextView view;
    private final WindowManager.LayoutParams lp;
    private final int size;
    private float downRawX, downRawY;
    private int downLpX, downLpY;
    private boolean moved;

    public FloatingBall(Context ctx) {
        this.ctx = ctx;
        this.wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
        this.size = dp(44);

        view = new TextView(ctx);
        view.setText("工");
        view.setTextSize(18);
        view.setTextColor(0xFFFFFFFF);
        view.setGravity(Gravity.CENTER);
        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(0xE62C2C2A);
        bg.setStroke(dp(1), 0x33FFFFFF);
        view.setBackground(bg);

        lp = new WindowManager.LayoutParams(
                size, size,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;

        DisplayMetrics dm = ctx.getResources().getDisplayMetrics();
        int px = Prefs.ballX(ctx);
        int py = Prefs.ballY(ctx);
        if (px < 0 || py < 0) {
            px = dm.widthPixels - size - dp(8);
            py = dm.heightPixels / 3;
        }
        lp.x = clampX(px, dm.widthPixels);
        lp.y = clampY(py, dm.heightPixels);

        view.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent e) {
                switch (e.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        downRawX = e.getRawX();
                        downRawY = e.getRawY();
                        downLpX = lp.x;
                        downLpY = lp.y;
                        moved = false;
                        view.setAlpha(0.75f);
                        return true;
                    case MotionEvent.ACTION_MOVE: {
                        int dx = (int) (e.getRawX() - downRawX);
                        int dy = (int) (e.getRawY() - downRawY);
                        if (!moved && (Math.abs(dx) > dp(6) || Math.abs(dy) > dp(6))) {
                            moved = true;
                        }
                        if (moved) {
                            DisplayMetrics dm = ctx.getResources().getDisplayMetrics();
                            lp.x = clampX(downLpX + dx, dm.widthPixels);
                            lp.y = clampY(downLpY + dy, dm.heightPixels);
                            try {
                                wm.updateViewLayout(view, lp);
                            } catch (Exception ignored) {
                            }
                        }
                        return true;
                    }
                    case MotionEvent.ACTION_UP:
                        view.setAlpha(1f);
                        if (moved) {
                            snapAndSave();
                        } else if (e.getEventTime() - e.getDownTime() > 650) {
                            toggleDebug();   // 长按：切换调试模式
                        } else {
                            openPanel();
                        }
                        return true;
                    case MotionEvent.ACTION_CANCEL:
                        view.setAlpha(1f);
                        if (moved) {
                            snapAndSave();
                        }
                        return true;
                    default:
                        return false;
                }
            }
        });
    }

    public void show() {
        try {
            wm.addView(view, lp);
        } catch (Exception ignored) {
        }
    }

    public void hide() {
        try {
            wm.removeView(view);
        } catch (Exception ignored) {
        }
    }

    private void openPanel() {
        // 用悬浮层展开面板（不启动 Activity：避开后台启动限制与厂商清理）
        PanelOverlay.show(ctx);
    }

    /** 长按浮球：切换调试模式（写控制台 /api/debug，半透明调试窗随开关显示/隐藏） */
    private void toggleDebug() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                String msg;
                try {
                    JSONObject cur = Api.get("/api/debug", 3000);
                    boolean on = cur.optBoolean("on", false);
                    JSONObject body = new JSONObject();
                    body.put("on", !on);
                    Api.post("/api/debug", body.toString(), 4000);
                    msg = on ? "调试模式已关" : "调试模式已开：任务运行时显示半透明链路窗";
                } catch (Exception e) {
                    msg = "调试开关失败（控制台离线？）";
                }
                final String m = msg;
                view.post(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(ctx, m, Toast.LENGTH_SHORT).show();
                    }
                });
            }
        }).start();
    }

    private void snapAndSave() {
        DisplayMetrics dm = ctx.getResources().getDisplayMetrics();
        int half = dm.widthPixels / 2;
        lp.x = (lp.x + size / 2 < half) ? dp(4) : (dm.widthPixels - size - dp(4));
        lp.y = clampY(lp.y, dm.heightPixels);
        try {
            wm.updateViewLayout(view, lp);
        } catch (Exception ignored) {
        }
        Prefs.setBallPos(ctx, lp.x, lp.y);
    }

    private int clampX(int x, int screenW) {
        if (x < 0) {
            return 0;
        }
        if (x > screenW - size) {
            return Math.max(0, screenW - size);
        }
        return x;
    }

    private int clampY(int y, int screenH) {
        if (y < 0) {
            return 0;
        }
        if (y > screenH - size) {
            return Math.max(0, screenH - size);
        }
        return y;
    }

    private int dp(float v) {
        return Math.round(v * ctx.getResources().getDisplayMetrics().density);
    }
}
