package com.xiaogongtou.entry;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;

import org.json.JSONObject;

/**
 * 小工头的无障碍服务：
 *  - 悬浮球宿主（TYPE_ACCESSIBILITY_OVERLAY，无需浮窗权限）
 *  - 系统「无障碍按钮」触发点 → 唤出输入面板
 *  - 任务结果轮询 → 系统通知回执
 *  - 附带收益：importance=accessibility 免 ColorOS 冻结（与 portal 同款机制）
 * 不读取任何屏幕内容（canRetrieveWindowContent=false）。
 */
public class EntryA11yService extends AccessibilityService {
    private static final String TAG = "xgt-entry";
    private static volatile EntryA11yService instance;

    private FloatingBall ball;
    private Poller poller;
    private DebugOverlay dbg;
    private volatile boolean treeLoopAlive = false;
    private volatile String lastTreeSeq = "";
    private java.io.File treeDir;

    /** 音量键快捷键（默认开）：按一下唤起面板，再按一下执行；长按则由本服务模拟"降低音量" */
    private volatile boolean hotkeyOn = true;
    private volatile boolean volHandled = false;
    private volatile boolean volLongPress = false;
    private volatile long volDownAt = 0;
    private static final long VOL_TAP_MAX_MS = 650;
    private static final long VOL_LONG_PRESS_MS = 480;
    private final android.os.Handler volHandler =
            new android.os.Handler(android.os.Looper.getMainLooper());

    public static boolean isRunning() {
        return instance != null;
    }

    public static void openPanelFromService() {
        EntryA11yService s = instance;
        if (s != null) {
            PanelOverlay.show(s);
        }
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        Log.i(TAG, "a11y service connected");
        try {
            AccessibilityServiceInfo info = getServiceInfo();
            if (info != null) {
                info.flags |= AccessibilityServiceInfo.FLAG_REQUEST_ACCESSIBILITY_BUTTON;
                info.flags |= AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS;
                setServiceInfo(info);
            }
        } catch (Exception ignored) {
        }
        Notifier.ensureChannels(this);
        Notifier.showStandby(this);
        try {
            if (ball != null) {
                ball.hide();   // 服务重连时避免残留双浮球
                ball = null;
            }
            ball = new FloatingBall(this);
            ball.show();
        } catch (Exception e) {
            Log.w(TAG, "floating ball failed", e);
        }
        try {
            poller = new Poller();
            poller.start();
        } catch (Exception e) {
            Log.w(TAG, "poller failed", e);
        }
        try {
            startTreeExporter();
        } catch (Exception e) {
            Log.w(TAG, "tree exporter failed", e);
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // 不消费屏幕内容
    }

    @Override
    public void onInterrupt() {
    }

    /**
     * 系统「无障碍按钮」回调。
     * 注：android-35 的 stub jar 已不含该方法，故不加 @Override——
     * 运行时按虚方法分派，签名匹配即会被系统调用（API 34+ 无参 / 26-33 带 displayId）。
     */
    public void onAccessibilityButtonClicked() {
        QuickPanelActivity.open(this);
    }

    public void onAccessibilityButtonClicked(int displayId) {
        QuickPanelActivity.open(this);
    }

    /**
     * 音量键快捷键：按一下唤起面板 / 再按一下执行（提交）。
     * 短按（<650ms）拦截；按住 480ms 后判定为长按 → 由本服务模拟连续"降低音量"（含系统音量条）。
     * 注：DOWN 被拦截后系统不会再生成按键 repeat，因此长按的音量调节必须由服务自己补上。
     */
    @Override
    protected boolean onKeyEvent(KeyEvent event) {
        if (event.getKeyCode() != KeyEvent.KEYCODE_VOLUME_DOWN) {
            return false;
        }
        Log.i(TAG, "vol-down: action=" + event.getAction() + " repeat="
                + event.getRepeatCount() + " hotkeyOn=" + hotkeyOn);
        if (!hotkeyOn) {
            return false;
        }
        int action = event.getAction();
        if (action == KeyEvent.ACTION_DOWN) {
            if (event.getRepeatCount() == 0) {
                volDownAt = SystemClock.uptimeMillis();
                volHandled = true;
                volLongPress = false;
                volHandler.removeCallbacksAndMessages(null);
                volHandler.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        if (!volHandled) {
                            return;   // 已抬起（短按）
                        }
                        volLongPress = true;
                        startVolumeRepeat();
                    }
                }, VOL_LONG_PRESS_MS);
                return true;   // 短按候选：先吞掉，避免误调音量
            }
            return true;   // 内核 repeat 也吞掉：音量调节由本服务统一模拟，避免双重
        }
        if (action == KeyEvent.ACTION_UP) {
            volHandler.removeCallbacksAndMessages(null);
            boolean wasHandled = volHandled;
            boolean wasLong = volLongPress;
            volHandled = false;
            volLongPress = false;
            if (wasHandled) {
                long dt = SystemClock.uptimeMillis() - volDownAt;
                if (!wasLong && dt <= VOL_TAP_MAX_MS) {
                    Log.i(TAG, "hotkey fire (dt=" + dt + "ms)");
                    fireHotkey();
                } else {
                    Log.i(TAG, "vol long-press end (dt=" + dt + "ms)");
                }
                return true;
            }
            return false;
        }
        return false;
    }

    /**
     * 快捷键路由：
     *  大面板开着 → 提交面板内容；语音条开着 → 提交语音内容；都没有 → 弹语音速记条。
     *  语音条 = 本机语音听写 + 键盘 + 输入框（再按一下执行），不再弹大面板。
     */
    private void fireHotkey() {
        if (PanelOverlay.isShowing()) {
            PanelOverlay.hotkeyAction(this);
        } else if (VoiceBar.isShowing()) {
            VoiceBar.hotkeySubmit();
        } else {
            VoiceBar.show(this);
        }
    }

    /**
     * 自动点击输入法（IME）键盘上的「麦克风 / 语音输入」键 —— 本机语音输入的入口。
     * 需要 canRetrieveWindowContent + flagRetrieveInteractiveWindows（见 XML 配置）。
     * 只读键盘窗口的按钮元信息（描述/ID/边界），不读取输入内容。
     */
    public boolean clickImeVoiceButton() {
        try {
            java.util.List<android.view.accessibility.AccessibilityWindowInfo> wins = getWindows();
            if (wins == null || wins.isEmpty()) {
                Log.i(TAG, "ime: no windows");
                return false;
            }
            for (android.view.accessibility.AccessibilityWindowInfo w : wins) {
                if (w.getType() != android.view.accessibility.AccessibilityWindowInfo.TYPE_INPUT_METHOD) {
                    continue;
                }
                android.view.accessibility.AccessibilityNodeInfo root = w.getRoot();
                if (root == null) {
                    Log.i(TAG, "ime: window found, root null");
                    continue;
                }
                android.view.accessibility.AccessibilityNodeInfo hit = findVoiceNode(root, 0);
                if (hit == null) {
                    Log.i(TAG, "ime: voice key not in a11y tree");
                    continue;
                }
                android.graphics.Rect b = new android.graphics.Rect();
                hit.getBoundsInScreen(b);
                Log.i(TAG, "ime voice node: cls=" + hit.getClassName()
                        + " id=" + hit.getViewIdResourceName()
                        + " desc=" + trim40(String.valueOf(hit.getContentDescription()))
                        + " bounds=" + b.toShortString());
                boolean ok = false;
                try {
                    ok = hit.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK);
                } catch (Exception ignored) {
                }
                Log.i(TAG, "ime voice performClick=" + ok);
                if (!ok) {
                    ok = tapByGesture(b.centerX(), b.centerY());
                    Log.i(TAG, "ime voice gestureTap=" + ok);
                }
                return ok;
            }
        } catch (Exception e) {
            Log.w(TAG, "clickImeVoiceButton failed", e);
        }
        return false;
    }

    private static final String[] VOICE_HINTS = {
            "语音输入", "voice_input", "voiceinput",
            "语音", "麦克风", "话筒", "听写", "voice", "speech", "microphone"};

    private android.view.accessibility.AccessibilityNodeInfo findVoiceNode(
            android.view.accessibility.AccessibilityNodeInfo node, int depth) {
        if (node == null || depth > 14) {
            return null;
        }
        try {
            String desc = stringOf(node.getContentDescription());
            String text = stringOf(node.getText());
            String id = stringOf(node.getViewIdResourceName());
            String hay = (desc + "|" + text + "|" + id).toLowerCase();
            for (String k : VOICE_HINTS) {
                if (hay.contains(k)) {
                    if (node.isClickable()) {
                        return node;
                    }
                    android.view.accessibility.AccessibilityNodeInfo p = node.getParent();
                    if (p != null && p.isClickable()) {
                        return p;
                    }
                }
            }
        } catch (Exception ignored) {
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            android.view.accessibility.AccessibilityNodeInfo r = findVoiceNode(node.getChild(i), depth + 1);
            if (r != null) {
                return r;
            }
        }
        return null;
    }

    /** 找不到语音键时的诊断输出（全节点 + 边界，限 100 行） */
    private void dumpImeNodes(android.view.accessibility.AccessibilityNodeInfo node, int depth, int[] count) {
        if (node == null || depth > 14 || count[0] >= 100) {
            return;
        }
        try {
            String desc = stringOf(node.getContentDescription());
            String text = stringOf(node.getText());
            String id = stringOf(node.getViewIdResourceName());
            String cls = stringOf(node.getClassName());
            int dot = cls.lastIndexOf('.');
            if (dot >= 0) {
                cls = cls.substring(dot + 1);
            }
            android.graphics.Rect b = new android.graphics.Rect();
            node.getBoundsInScreen(b);
            Log.i(TAG, "imenode d" + depth + " clk=" + (node.isClickable() ? 1 : 0)
                    + " " + cls + " " + b.width() + "x" + b.height() + "@" + b.left + "," + b.top
                    + " id=" + trim40(id) + " desc=" + trim40(desc) + " txt=" + trim40(text));
            count[0]++;
        } catch (Exception ignored) {
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            dumpImeNodes(node.getChild(i), depth + 1, count);
        }
    }

    private boolean tapByGesture(int x, int y) {
        try {
            if (x <= 0 && y <= 0) {
                return false;
            }
            android.graphics.Path path = new android.graphics.Path();
            path.moveTo(x, y);
            android.accessibilityservice.GestureDescription.StrokeDescription stroke =
                    new android.accessibilityservice.GestureDescription.StrokeDescription(path, 0, 80);
            android.accessibilityservice.GestureDescription gd =
                    new android.accessibilityservice.GestureDescription.Builder().addStroke(stroke).build();
            return dispatchGesture(gd, null, null);
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * 几何法点击键盘「麦克风」键（搜狗默认布局）：a11y 树里没有麦克风节点时的兜底。
     * 坐标 = 键盘顶部（getWindowVisibleDisplayFrame().bottom）+ 工具栏偏移；横向取屏宽 59.7%。
     * 本机（1080x2400）实测：麦克风位于 (645,1565) = 键盘顶 1488 + 77。
     */
    public boolean tapVoiceByGeometry(android.view.View anyView) {
        try {
            if (anyView == null) {
                return false;
            }
            android.graphics.Rect r = new android.graphics.Rect();
            anyView.getWindowVisibleDisplayFrame(r);
            int kbTop = r.bottom;
            int w = r.right;
            if (kbTop <= 0 || w <= 0) {
                return false;
            }
            int x = Math.round(w * 0.597f);
            int y = kbTop + 77;
            Log.i(TAG, "ime voice geom: tap (" + x + "," + y + ") kbTop=" + kbTop + " w=" + w);
            return tapByGesture(x, y);
        } catch (Exception e) {
            Log.w(TAG, "tapVoiceByGeometry failed", e);
            return false;
        }
    }

    private static String stringOf(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static String trim40(String s) {
        if (s == null) {
            return "";
        }
        return s.length() > 40 ? s.substring(0, 40) : s;
    }

    /** 长按期间：每 200ms 降低一格音量（带系统音量 UI） */
    private void startVolumeRepeat() {
        volHandler.post(new Runnable() {
            @Override
            public void run() {
                if (!volLongPress || !volHandled) {
                    return;
                }
                try {
                    android.media.AudioManager am =
                            (android.media.AudioManager) getSystemService(Context.AUDIO_SERVICE);
                    if (am != null) {
                        int before = am.getStreamVolume(android.media.AudioManager.STREAM_MUSIC);
                        am.adjustStreamVolume(android.media.AudioManager.STREAM_MUSIC,
                                android.media.AudioManager.ADJUST_LOWER,
                                android.media.AudioManager.FLAG_SHOW_UI);
                        int after = am.getStreamVolume(android.media.AudioManager.STREAM_MUSIC);
                        Log.i(TAG, "vol adjust " + before + "->" + after);
                    } else {
                        Log.w(TAG, "vol adjust: AudioManager is null");
                    }
                } catch (Exception e) {
                    Log.w(TAG, "vol adjust failed", e);
                }
                volHandler.postDelayed(this, 200);
            }
        });
    }

    @Override
    public boolean onUnbind(Intent intent) {
        shutdown();
        return super.onUnbind(intent);
    }

    @Override
    public void onDestroy() {
        shutdown();
        super.onDestroy();
    }

    private void shutdown() {
        instance = null;
        if (ball != null) {
            ball.hide();
            ball = null;
        }
        if (poller != null) {
            poller.shutdown();
            poller = null;
        }
        if (dbg != null) {
            dbg.hide();
            dbg = null;
        }
        try {
            volHandler.removeCallbacksAndMessages(null);
        } catch (Exception ignored) {
        }
        treeLoopAlive = false;
    }

    /** 调试浮窗同步：debug 开关（控制台设置）打开时显示并刷新执行链路；关闭时隐藏 */
    private void syncDebug(String rid) {
        boolean on = false;
        try {
            JSONObject d = Api.get("/api/debug", 3000);
            on = d.optBoolean("on", false);
        } catch (Exception ignored) {
        }
        if (on) {
            if (dbg == null) {
                dbg = new DebugOverlay(this);
            }
            dbg.show();
            dbg.poll(rid);
        } else if (dbg != null) {
            dbg.hide();
        }
    }

    /** ============ 树导出：供 Termux 侧 agent 经 root 桥按需拉取（替代 uiautomator，避免其副作用） ============ */
    private void startTreeExporter() {
        java.io.File d = getExternalFilesDir(null);
        if (d == null) {
            Log.w(TAG, "tree exporter: no external dir");
            return;
        }
        treeDir = d;
        treeLoopAlive = true;
        final android.os.Handler h = new android.os.Handler(android.os.Looper.getMainLooper());
        h.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (!treeLoopAlive) {
                    return;
                }
                try {
                    exportTreeIfRequested();
                } catch (Exception ignored) {
                }
                h.postDelayed(this, 250);
            }
        }, 250);
    }

    private void exportTreeIfRequested() {
        if (treeDir == null) {
            return;
        }
        java.io.File reqF = new java.io.File(treeDir, "tree_req");
        if (!reqF.exists()) {
            return;
        }
        String seq = readTextFile(reqF);
        if (seq == null) {
            return;
        }
        seq = seq.trim();
        if (seq.isEmpty() || seq.equals(lastTreeSeq)) {
            return;
        }
        String json = buildTreeJson(seq);
        if (json != null) {
            writeTextFile(new java.io.File(treeDir, "tree.json"), json);
            lastTreeSeq = seq;
        }
    }

    private String buildTreeJson(String seq) {
        try {
            org.json.JSONArray arr = new org.json.JSONArray();
            java.util.List<android.view.accessibility.AccessibilityWindowInfo> ws = getWindows();
            int idx = 0;
            if (ws != null) {
                for (android.view.accessibility.AccessibilityWindowInfo w : ws) {
                    int type = w.getType();
                    if (type == android.view.accessibility.AccessibilityWindowInfo.TYPE_INPUT_METHOD
                            || type == android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION
                            || type == android.view.accessibility.AccessibilityWindowInfo.TYPE_SYSTEM) {
                        android.view.accessibility.AccessibilityNodeInfo root = w.getRoot();
                        if (root != null) {
                            idx = collectNodes(root, arr, idx, 0);
                        }
                    }
                }
            }
            org.json.JSONObject out = new org.json.JSONObject();
            out.put("seq", seq);
            out.put("ts", System.currentTimeMillis());
            out.put("elems", arr);
            return out.toString();
        } catch (Exception e) {
            Log.w(TAG, "buildTreeJson failed", e);
            return null;
        }
    }

    private int collectNodes(android.view.accessibility.AccessibilityNodeInfo n,
                             org.json.JSONArray arr, int idx, int depth) {
        if (n == null || depth > 40 || idx >= 400) {
            return idx;
        }
        try {
            String t = n.getText() == null ? "" : n.getText().toString().trim();
            String d = n.getContentDescription() == null ? "" : n.getContentDescription().toString().trim();
            String label = !t.isEmpty() ? t : d;
            if (!label.isEmpty()) {
                android.graphics.Rect b = new android.graphics.Rect();
                n.getBoundsInScreen(b);
                if (b.width() > 0 && b.height() > 0) {
                    boolean clk = n.isClickable() || n.isLongClickable();
                    org.json.JSONArray one = new org.json.JSONArray();
                    one.put(idx);
                    one.put(b.centerX());
                    one.put(b.centerY());
                    one.put(label.length() > 220 ? label.substring(0, 220) : label);
                    one.put(clk);
                    arr.put(one);
                    idx++;
                }
            }
        } catch (Exception ignored) {
        }
        int cnt = n.getChildCount();
        for (int i = 0; i < cnt && idx < 400; i++) {
            idx = collectNodes(n.getChild(i), arr, idx, depth + 1);
        }
        return idx;
    }

    private static String readTextFile(java.io.File f) {
        try (java.io.FileInputStream in = new java.io.FileInputStream(f)) {
            byte[] buf = new byte[(int) Math.min(f.length(), 4096)];
            int n = in.read(buf);
            return n > 0 ? new String(buf, 0, n, "UTF-8") : "";
        } catch (Exception e) {
            return null;
        }
    }

    private static void writeTextFile(java.io.File f, String s) {
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(f)) {
            out.write(s.getBytes("UTF-8"));
        } catch (Exception ignored) {
        }
    }

    /** 音量键快捷键开关同步（默认开；控制台 /api/hotkey 可关） */
    private void syncHotkey() {
        try {
            JSONObject d = Api.get("/api/hotkey", 3000);
            hotkeyOn = d.optBoolean("on", true);
        } catch (Exception ignored) {
        }
    }

    /** 轮询控制台状态：任务开始/结束 → 系统通知；调试模式 → 调试浮窗 */
    private class Poller extends Thread {
        private final Context app;
        private volatile boolean alive = true;
        private String prevState = null;
        private String prevRid = null;
        private String lastNotifiedRid = null;

        Poller() {
            super("xgt-poller");
            setDaemon(true);
            app = getApplicationContext();
        }

        void shutdown() {
            alive = false;
            interrupt();
        }

        @Override
        public void run() {
            while (alive) {
                long sleepMs = 12000;
                try {
                    JSONObject st = Api.get("/api/status", 4000);
                    String state = st.optString("state", "idle");
                    String rid = st.optString("run_id", "");
                    String task = st.optString("task", "");
                    boolean running = "running".equals(state);
                    if (running) {
                        sleepMs = 2000;
                        // 运行中：更新通知（第 N 步 + 最新动作）
                        try {
                            int stepNo = st.optInt("step", 0);
                            String latest = "";
                            org.json.JSONArray ls = st.optJSONArray("lines");
                            if (ls != null) {
                                for (int i = ls.length() - 1; i >= 0; i--) {
                                    String s = ls.optString(i, "").trim();
                                    if (s.startsWith("[step ")) {
                                        latest = s;
                                        break;
                                    }
                                }
                            }
                            if (stepNo > 0) {
                                Notifier.updateRunning(app, task, stepNo, latest);
                            }
                        } catch (Exception ignored) {
                        }
                    }

                    if (prevState != null) {
                        boolean finished = "running".equals(prevState)
                                || (prevRid != null && rid.length() > 0 && !rid.equals(prevRid));
                        if (!running && finished && rid.length() > 0
                                && !rid.equals(lastNotifiedRid) && !"idle".equals(state)) {
                            lastNotifiedRid = rid;
                            if ("done".equals(state)) {
                                String result = st.optString("result", "");
                                Notifier.showResult(app,
                                        "完成：" + (result.isEmpty() ? "任务结束" : result), task);
                            } else if ("failed".equals(state)) {
                                String why = st.optString("failed_reason", "");
                                Notifier.showResult(app,
                                        "未完成：" + (why.isEmpty() ? "失败" : why), task);
                            } else if ("stopped".equals(state)) {
                                Notifier.showResult(app, "已停止", task);
                            }
                        }
                    }
                    prevState = state;
                    prevRid = rid;
                    // 调试浮窗（独立开关，失败不影响通知逻辑）
                    try {
                        syncDebug(rid);
                    } catch (Exception ignored) {
                    }
                    // 音量键快捷键开关
                    try {
                        syncHotkey();
                    } catch (Exception ignored) {
                    }
                } catch (Exception e) {
                    sleepMs = 15000;
                }
                try {
                    Thread.sleep(sleepMs);
                } catch (InterruptedException e) {
                    return;
                }
            }
        }
    }
}
