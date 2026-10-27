package com.xiaogongtou.entry;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

/** 通知：常驻入口 + 任务进行中 + 结果回执 */
public final class Notifier {
    private static final String CH_STANDBY = "standby";
    private static final String CH_RESULT = "result";
    private static final int ID_STANDBY = 1001;
    private static final int ID_RUNNING = 1002;
    private static final int ID_RESULT = 1003;

    private Notifier() {
    }

    public static void ensureChannels(Context c) {
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) {
            return;
        }
        if (nm.getNotificationChannel(CH_STANDBY) == null) {
            NotificationChannel a = new NotificationChannel(CH_STANDBY, "待命入口",
                    NotificationManager.IMPORTANCE_LOW);
            a.setShowBadge(false);
            a.enableVibration(false);
            nm.createNotificationChannel(a);
        }
        if (nm.getNotificationChannel(CH_RESULT) == null) {
            NotificationChannel b = new NotificationChannel(CH_RESULT, "任务结果",
                    NotificationManager.IMPORTANCE_DEFAULT);
            b.setShowBadge(true);
            nm.createNotificationChannel(b);
        }
    }

    public static void showStandby(Context c) {
        ensureChannels(c);
        Notification.Builder b = base(c, CH_STANDBY);
        b.setContentTitle("小工头待命");
        b.setContentText("点这里说一句，让它去干");
        b.setContentIntent(pi(c, QuickPanelActivity.class, 1));
        b.setOngoing(false);
        b.setShowWhen(false);
        b.setOnlyAlertOnce(true);
        notify(c, ID_STANDBY, b);
    }

    public static void showRunning(Context c, String task) {
        ensureChannels(c);
        Notification.Builder b = base(c, CH_RESULT);
        b.setContentTitle("正在干活…");
        b.setContentText(task == null || task.isEmpty() ? "任务进行中，请先别操作手机" : task);
        b.setContentIntent(pi(c, MainActivity.class, 2));
        b.setOngoing(true);
        b.setOnlyAlertOnce(true);
        b.setShowWhen(false);
        notify(c, ID_RUNNING, b);
    }

    public static void cancelRunning(Context c) {
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            nm.cancel(ID_RUNNING);
        }
    }

    /** 收起"待命"常驻通知（任务运行中调用，避免与"正在干活"两条并存） */
    public static void cancelStandby(Context c) {
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            nm.cancel(ID_STANDBY);
        }
    }

    /** 运行中进度更新：第 N 步 + 最新动作 + 已运行时长（状态栏常驻、下拉可见完整文本） */
    public static void updateRunning(Context c, String task, int step, String line, double elapsedSec) {
        ensureChannels(c);
        Notification.Builder b = base(c, CH_RESULT);
        b.setContentTitle(step > 0 ? "正在干活…（第 " + step + " 步）" : "正在干活…");
        StringBuilder sb = new StringBuilder();
        if (task != null && !task.isEmpty()) {
            sb.append(task);
        }
        if (line != null && !line.isEmpty()) {
            if (line.length() > 140) {
                line = line.substring(line.length() - 140);
            }
            if (sb.length() > 0) {
                sb.append("\n");
            }
            sb.append(line);
        }
        String txt = sb.toString();
        b.setContentText(txt);
        b.setStyle(new Notification.BigTextStyle().bigText(txt));
        if (elapsedSec > 0) {
            b.setSubText("已运行 " + (int) elapsedSec + " 秒");
        }
        b.setProgress(0, 0, true);
        b.setContentIntent(pi(c, MainActivity.class, 2));
        b.setOngoing(true);
        b.setOnlyAlertOnce(true);
        b.setShowWhen(false);
        notify(c, ID_RUNNING, b);
    }

    public static void showResult(Context c, String title, String text) {
        ensureChannels(c);
        cancelRunning(c);
        Notification.Builder b = base(c, CH_RESULT);
        b.setContentTitle(title);
        b.setContentText(text == null ? "" : text);
        b.setContentIntent(pi(c, MainActivity.class, 2));
        b.setAutoCancel(true);
        b.setWhen(System.currentTimeMillis());
        notify(c, ID_RESULT, b);
    }

    private static Notification.Builder base(Context c, String channel) {
        Notification.Builder b = new Notification.Builder(c, channel);
        b.setSmallIcon(R.drawable.ic_stat_work);
        b.setColor(0xFF2C2C2A);
        return b;
    }

    private static PendingIntent pi(Context c, Class<?> cls, int req) {
        Intent i = new Intent(c, cls);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getActivity(c, req, i, flags);
    }

    private static void notify(Context c, int id, Notification.Builder b) {
        try {
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.notify(id, b.build());
            }
        } catch (Exception ignored) {
        }
    }
}
