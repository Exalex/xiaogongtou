package com.xiaogongtou.entry;

import android.content.Context;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 半透明调试浮窗：实时显示任务执行链路（prompt / 回复 / 动作 / 结果）。
 * 纯展示层——不接收触摸（FLAG_NOT_TOUCHABLE）且不进无障碍树，
 * 保证 agent 既不会被挡住点击、也不会在 a11y 树里"看到"它。
 */
public class DebugOverlay {
    private static final int MAX_CHARS = 12000;

    private final Context ctx;
    private final WindowManager wm;
    private final android.os.Handler main;
    private final LinearLayout root;
    private final TextView body;
    private final ScrollView scroll;
    private final WindowManager.LayoutParams lp;

    private String lastRid = "\u0000";
    private int nextFrom = 0;
    private final StringBuilder lines = new StringBuilder();

    public DebugOverlay(Context ctx) {
        this.ctx = ctx;
        this.wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
        this.main = new android.os.Handler(android.os.Looper.getMainLooper());

        root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xB80B1310); // 约 72% 不透明：半透明可透视
        int pad = dp(10);
        root.setPadding(pad, dp(6), pad, dp(8));

        TextView title = new TextView(ctx);
        title.setText("调试 · 执行链路（长按浮球可关闭）");
        title.setTextSize(11);
        title.setTextColor(0xFF9FE1CB);
        root.addView(title);

        body = new TextView(ctx);
        body.setTextSize(10f);
        body.setTextColor(0xFFE8F1ED);
        body.setTypeface(Typeface.MONOSPACE);

        scroll = new ScrollView(ctx);
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        // 关键：不让无障碍服务（含 portal / uiautomator）读到本窗口
        root.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);

        DisplayMetrics dm = ctx.getResources().getDisplayMetrics();
        lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                Math.round(dm.heightPixels * 0.34f),
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.BOTTOM | Gravity.START;
    }

    public void show() {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (root.getParent() != null) {
                    return;
                }
                try {
                    wm.addView(root, lp);
                } catch (Exception ignored) {
                }
            }
        });
    }

    public void hide() {
        main.post(new Runnable() {
            @Override
            public void run() {
                try {
                    wm.removeView(root);
                } catch (Exception ignored) {
                }
            }
        });
    }

    public boolean isShown() {
        return root.getParent() != null;
    }

    /** 轮询增量（主线程外调用；UI 更新会 post 到主线程） */
    public void poll(String rid) {
        try {
            if (rid == null) {
                rid = "";
            }
            if (!rid.equals(lastRid)) {
                lastRid = rid;
                nextFrom = 0;
                lines.setLength(0);
                setBody("");
            }
            String url = "/api/trace?from=" + nextFrom + "&limit=200";
            if (rid.length() > 0) {
                url += "&rid=" + rid;
            }
            JSONObject d = Api.get(url, 3500);
            JSONArray arr = d.optJSONArray("lines");
            if (arr == null || arr.length() == 0) {
                return;
            }
            nextFrom = d.optInt("next", nextFrom + arr.length());
            for (int i = 0; i < arr.length(); i++) {
                JSONObject r = arr.optJSONObject(i);
                if (r != null) {
                    lines.append(formatLine(r)).append('\n');
                }
            }
            if (lines.length() > MAX_CHARS) {
                lines.delete(0, lines.length() - MAX_CHARS);
            }
            setBody(lines.toString());
            final ScrollView sc = scroll;
            sc.post(new Runnable() {
                @Override
                public void run() {
                    sc.fullScroll(View.FOCUS_DOWN);
                }
            });
        } catch (Exception ignored) {
        }
    }

    private void setBody(final String text) {
        body.post(new Runnable() {
            @Override
            public void run() {
                body.setText(text);
            }
        });
    }

    private String formatLine(JSONObject r) {
        String kind = r.optString("kind", "text");
        int step = r.optInt("step", 0);
        String eng = r.optString("engine", "");
        String tag;
        if ("prompt".equals(kind)) {
            tag = "▶ 输入";
        } else if ("reply".equals(kind)) {
            tag = "◀ 返回";
        } else if ("action".equals(kind)) {
            tag = "⚡ 动作";
        } else if ("result".equals(kind)) {
            tag = "✓ 结果";
        } else if ("done".equals(kind)) {
            tag = "🏁 完成";
        } else {
            tag = kind;
        }
        String text = r.optString("text", "");
        if (text.length() > 180) {
            text = text.substring(0, 180) + "…";
        }
        String head = (step > 0 ? ("第" + step + "步 ") : "") + tag
                + (eng.length() > 0 ? (" [" + eng + "]") : "");
        return head + "\n" + text;
    }

    private int dp(float v) {
        return Math.round(v * ctx.getResources().getDisplayMetrics().density);
    }
}
