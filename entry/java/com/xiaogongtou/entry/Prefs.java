package com.xiaogongtou.entry;

import android.content.Context;
import android.content.SharedPreferences;

/** 极简偏好存储 */
public final class Prefs {
    private static final String NAME = "entry";

    private Prefs() {
    }

    private static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(NAME, Context.MODE_PRIVATE);
    }

    public static String mode(Context c) {
        return sp(c).getString("mode", "auto");
    }

    public static void setMode(Context c, String m) {
        sp(c).edit().putString("mode", m).apply();
    }

    public static int ballX(Context c) {
        return sp(c).getInt("ballX", -1);
    }

    public static int ballY(Context c) {
        return sp(c).getInt("ballY", -1);
    }

    public static void setBallPos(Context c, int x, int y) {
        sp(c).edit().putInt("ballX", x).putInt("ballY", y).apply();
    }

    public static boolean voiceAutoSend(Context c) {
        return sp(c).getBoolean("voiceAutoSend", false);
    }

    public static void setVoiceAutoSend(Context c, boolean v) {
        sp(c).edit().putBoolean("voiceAutoSend", v).apply();
    }
}
