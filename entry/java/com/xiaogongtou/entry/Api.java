package com.xiaogongtou.entry;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** 与控制台（127.0.0.1:8900）的最小 HTTP 客户端（纯框架 API） */
public final class Api {
    public static final String BASE = "http://127.0.0.1:8900";

    private Api() {
    }

    public static JSONObject get(String path, int timeoutMs) throws Exception {
        HttpURLConnection c = open(path, "GET", timeoutMs);
        try {
            return read(c);
        } finally {
            c.disconnect();
        }
    }

    public static JSONObject post(String path, String json, int timeoutMs) throws Exception {
        HttpURLConnection c = open(path, "POST", timeoutMs);
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        byte[] data = json.getBytes("UTF-8");
        c.setFixedLengthStreamingMode(data.length);
        OutputStream os = c.getOutputStream();
        try {
            os.write(data);
        } finally {
            os.close();
        }
        try {
            return read(c);
        } finally {
            c.disconnect();
        }
    }

    /** 提交任务。返回 null = 成功；否则返回错误文案。 */
    public static String submit(String task, String mode) {
        try {
            JSONObject body = new JSONObject();
            body.put("task", task);
            body.put("mode", mode);
            JSONObject res = post("/api/run", body.toString(), 5000);
            if (res.optInt("_http", 0) == 200 && res.optBoolean("ok", false)) {
                return null;
            }
            String err = res.optString("error", "");
            return err.isEmpty() ? ("HTTP " + res.optInt("_http", 0)) : err;
        } catch (Exception e) {
            return "控制台离线";
        }
    }

    /** 探测控制台是否在线（用于界面提示） */
    public static boolean online() {
        try {
            JSONObject st = get("/api/status", 2500);
            return st.optInt("_http", 0) == 200;
        } catch (Exception e) {
            return false;
        }
    }

    // ---------------------------------------------------------------- portal（root 注入）

    private static final String PORTAL_BASE = "http://127.0.0.1:8080";

    /** 经 portal（root 注入）点击屏幕坐标 —— 用于自动点输入法键盘上的语音键。返回 null=成功 */
    public static String tap(int x, int y) {
        if (Secrets.PORTAL_TOKEN.isEmpty()) {
            return "未配置 portal token（构建时见 local_secrets.json）";
        }
        try {
            JSONObject body = new JSONObject();
            body.put("x", x);
            body.put("y", y);
            JSONObject res = portalPost("/tap", body.toString(), 4000);
            if (res.optInt("_http", 0) == 200) {
                return null;
            }
            return "portal HTTP " + res.optInt("_http", 0);
        } catch (Exception e) {
            return "portal 不可达";
        }
    }

    private static JSONObject portalPost(String path, String json, int timeoutMs) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(PORTAL_BASE + path).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(timeoutMs);
        c.setReadTimeout(timeoutMs);
        c.setRequestProperty("Authorization", "Bearer " + Secrets.PORTAL_TOKEN);
        c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        c.setDoOutput(true);
        byte[] data = json.getBytes("UTF-8");
        c.setFixedLengthStreamingMode(data.length);
        OutputStream os = c.getOutputStream();
        try {
            os.write(data);
        } finally {
            os.close();
        }
        try {
            return read(c);
        } finally {
            c.disconnect();
        }
    }

    private static HttpURLConnection open(String path, String method, int timeoutMs) throws Exception {
        URL url = new URL(BASE + path);
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(timeoutMs);
        c.setReadTimeout(timeoutMs);
        c.setRequestProperty("Accept", "application/json");
        return c;
    }

    private static JSONObject read(HttpURLConnection c) throws Exception {
        int code = c.getResponseCode();
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        String text = "";
        if (in != null) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                bos.write(buf, 0, n);
            }
            in.close();
            text = new String(bos.toByteArray(), "UTF-8");
        }
        JSONObject obj = text.trim().isEmpty() ? new JSONObject() : new JSONObject(text);
        obj.put("_http", code);
        return obj;
    }
}
