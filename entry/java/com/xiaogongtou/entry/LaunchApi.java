package com.xiaogongtou.entry;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.util.Log;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;

/**
 * LaunchApi —— 本机回环「启动应用」小接口（127.0.0.1:8901）。
 *
 * 存在理由（2026-10-27 Y700 免 root 实测暴露）：
 *   非 root 机型上，Termux 里的 agent 无法冷启动别的 App ——
 *     · `am start` 报 "package=com.android.shell does not belong to uid=..."
 *     · `monkey` 报 "Unable to connect to window manager"
 *     · portal /app 报 "Could not create intent"（targetSdk34 无 <queries>，包可见性看不到别人）
 *   本 App 同时具备：无障碍服务宿主（系统绑定）+ 可见悬浮窗（BAL 豁免）+ 自己声明 <queries>，
 *   所以由它代发 startActivity 是免 root 下唯一可靠路径。
 *
 * 端点：
 *   GET /health                → {"ok":true}
 *   GET /launch?pkg=<包名>      → {"ok":true,"pkg":"..."} / {"ok":false,"error":"..."}
 */
public final class LaunchApi {
    private static final String TAG = "xgt-entry";
    public static final int PORT = 8901;

    private static volatile boolean started = false;
    private static volatile Context appCtx;

    private LaunchApi() {
    }

    public static void start(Context ctx) {
        appCtx = ctx.getApplicationContext();
        if (started) {
            return;
        }
        started = true;
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                serve();
            }
        }, "xgt-launch-api");
        t.setDaemon(true);
        t.start();
    }

    private static void serve() {
        ServerSocket ss = null;
        try {
            ss = new ServerSocket(PORT, 8, InetAddress.getByName("127.0.0.1"));
            Log.i(TAG, "launch api listening 127.0.0.1:" + PORT);
            while (ss != null && !ss.isClosed()) {
                Socket s = null;
                try {
                    s = ss.accept();
                    handle(s);
                } catch (Exception e) {
                    Log.w(TAG, "launch api conn: " + e);
                } finally {
                    closeQuietly(s);
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "launch api bind failed: " + e);
        } finally {
            started = false;
            try {
                if (ss != null) {
                    ss.close();
                }
            } catch (Exception ignored) {
            }
        }
    }

    private static void handle(Socket s) throws Exception {
        s.setSoTimeout(4000);
        BufferedReader r = new BufferedReader(new InputStreamReader(s.getInputStream(), "UTF-8"));
        String line = r.readLine();
        String body;
        if (line == null) {
            body = "{\"ok\":false,\"error\":\"empty request\"}";
        } else if (line.startsWith("GET /health")) {
            body = health();
        } else if (line.startsWith("GET /apps")) {
            body = appsJson();
        } else if (line.startsWith("GET /launch")) {
            body = launch(param(line, "pkg"), param(line, "cmp"));
        } else {
            body = "{\"ok\":false,\"error\":\"unknown endpoint\"}";
        }
        byte[] out = body.getBytes("UTF-8");
        OutputStream os = s.getOutputStream();
        String head = "HTTP/1.1 200 OK\r\n"
                + "Content-Type: application/json; charset=utf-8\r\n"
                + "Content-Length: " + out.length + "\r\n"
                + "Connection: close\r\n\r\n";
        os.write(head.getBytes("UTF-8"));
        os.write(out);
        os.flush();
    }

    private static String health() {
        Context ctx = appCtx;
        int installed = -1;
        int launchers = -1;
        int probeWeibo = -1;
        try {
            if (ctx != null) {
                PackageManager pm = ctx.getPackageManager();
                java.util.List<android.content.pm.ApplicationInfo> apps = pm.getInstalledApplications(0);
                installed = apps == null ? -1 : apps.size();
                Intent all = new Intent(Intent.ACTION_MAIN);
                all.addCategory(Intent.CATEGORY_LAUNCHER);
                java.util.List<android.content.pm.ResolveInfo> rs = pm.queryIntentActivities(all, 0);
                launchers = rs == null ? -1 : rs.size();
                Intent one = new Intent(Intent.ACTION_MAIN);
                one.addCategory(Intent.CATEGORY_LAUNCHER);
                one.setPackage("com.sina.weibo");
                java.util.List<android.content.pm.ResolveInfo> rs2 = pm.queryIntentActivities(one, 0);
                probeWeibo = rs2 == null ? -1 : rs2.size();
            }
        } catch (Exception e) {
            Log.w(TAG, "health probe failed", e);
        }
        return "{\"ok\":true,\"installed\":" + installed + ",\"launchers\":" + launchers
                + ",\"probe_weibo\":" + probeWeibo + "}";
    }

    private static String param(String line, String key) {
        int q = line.indexOf('?');
        if (q < 0) {
            return "";
        }
        String qs = line.substring(q + 1);
        int sp = qs.indexOf(' ');
        if (sp >= 0) {
            qs = qs.substring(0, sp);
        }
        String[] parts = qs.split("&");
        for (String p : parts) {
            int eq = p.indexOf('=');
            if (eq <= 0) {
                continue;
            }
            if (p.substring(0, eq).equals(key)) {
                String v = p.substring(eq + 1);
                try {
                    return URLDecoder.decode(v, "UTF-8");
                } catch (Exception e) {
                    return v;
                }
            }
        }
        return "";
    }

    /** 已安装（可启动）应用清单。非 root 机型上 portal /packages 只看得到它自己，agent 的
     *  "应用列表"要塌，导致模型误判"本机未安装 → 改走浏览器"。这里补齐同一份数据。 */
    private static String appsJson() {
        Context ctx = appCtx;
        if (ctx == null) {
            return "{\"ok\":false,\"error\":\"no context\"}";
        }
        StringBuilder sb = new StringBuilder("{\"ok\":true,\"apps\":[");
        try {
            PackageManager pm = ctx.getPackageManager();
            Intent q = new Intent(Intent.ACTION_MAIN);
            q.addCategory(Intent.CATEGORY_LAUNCHER);
            java.util.List<android.content.pm.ResolveInfo> rs = pm.queryIntentActivities(q, 0);
            java.util.Set<String> seen = new java.util.HashSet<String>();
            boolean first = true;
            int n = 0;
            for (android.content.pm.ResolveInfo ri : rs) {
                if (ri == null || ri.activityInfo == null) {
                    continue;
                }
                String p = ri.activityInfo.packageName;
                if (p == null || !seen.add(p)) {
                    continue;
                }
                String lb = p;
                try {
                    CharSequence cs = ri.loadLabel(pm);
                    if (cs != null) {
                        lb = cs.toString();
                    }
                } catch (Exception ignored) {
                }
                if (!first) {
                    sb.append(',');
                }
                first = false;
                sb.append("{\"packageName\":\"").append(esc(p))
                        .append("\",\"label\":\"").append(esc(lb)).append("\"}");
                n++;
            }
            sb.append("],\"count\":").append(n).append('}');
        } catch (Exception e) {
            Log.w(TAG, "apps failed", e);
            return "{\"ok\":false,\"error\":\"" + e.getClass().getSimpleName() + "\"}";
        }
        return sb.toString();
    }

    private static String esc(String s) {
        if (s == null) {
            return "";
        }
        StringBuilder b = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"' || c == '\\') {
                b.append('\\').append(c);
            } else if (c == '\n' || c == '\r' || c == '\t') {
                b.append(' ');
            } else {
                b.append(c);
            }
        }
        return b.toString();
    }

    private static String launch(String pkg, String cmp) {
        Context ctx = appCtx;
        if (ctx == null) {
            return "{\"ok\":false,\"error\":\"no context\"}";
        }
        try {
            // ① 显式组件优先：setClassName 不受包可见性限制（本机 ZUI/Android16 上
            //    QUERY_ALL_PACKAGES 已授予但 getInstalledApplications 仍只返回自己，
            //    queryIntentActivities 恒 0 条 —— 只有显式组件这条路能走）
            if (cmp != null && cmp.indexOf('/') > 0) {
                String p = cmp.substring(0, cmp.indexOf('/'));
                String c = cmp.substring(cmp.indexOf('/') + 1);
                if (c.startsWith(".")) {
                    c = p + c;
                }
                Intent it = new Intent(Intent.ACTION_MAIN);
                it.addCategory(Intent.CATEGORY_LAUNCHER);
                it.setClassName(p, c);
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(it);
                Log.i(TAG, "launched explicit " + p + "/" + c);
                return "{\"ok\":true,\"pkg\":\"" + p + "\",\"cmp\":\"" + c + "\"}";
            }
            if (pkg == null || pkg.length() == 0) {
                return "{\"ok\":false,\"error\":\"pkg/cmp missing\"}";
            }
            PackageManager pm = ctx.getPackageManager();
            Intent probe = new Intent(Intent.ACTION_MAIN);
            probe.addCategory(Intent.CATEGORY_LAUNCHER);
            probe.setPackage(pkg);
            java.util.List<android.content.pm.ResolveInfo> list =
                    pm.queryIntentActivities(probe, 0);
            Log.i(TAG, "launch probe " + pkg + " -> " + (list == null ? -1 : list.size()));
            if (list == null || list.isEmpty()) {
                return "{\"ok\":false,\"error\":\"no launcher entry and no cmp given\",\"pkg\":\"" + pkg + "\"}";
            }
            android.content.pm.ResolveInfo ri = list.get(0);
            Intent it = new Intent(Intent.ACTION_MAIN);
            it.addCategory(Intent.CATEGORY_LAUNCHER);
            it.setClassName(ri.activityInfo.packageName, ri.activityInfo.name);
            it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(it);
            Log.i(TAG, "launched " + pkg + " via " + ri.activityInfo.name);
            return "{\"ok\":true,\"pkg\":\"" + pkg + "\"}";
        } catch (Exception e) {
            Log.w(TAG, "launch failed " + pkg + " / " + cmp, e);
            return "{\"ok\":false,\"error\":\"" + e.getClass().getSimpleName() + "\"}";
        }
    }

    private static void closeQuietly(Socket s) {
        if (s == null) {
            return;
        }
        try {
            s.close();
        } catch (Exception ignored) {
        }
    }
}
