package com.xiaogongtou.entry;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

/** 主界面：全屏 WebView 壳，加载本机控制台（127.0.0.1:8900） */
public class MainActivity extends Activity {
    private static final int REQ_NOTIF = 31;

    private WebView web;
    private TextView hintBar;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (handleShare(getIntent())) {
            return;
        }
        buildUi();
        maybeAskNotifications();
        web.loadUrl(Api.BASE + "/");
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateHintBar();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (handleShare(intent)) {
            return;
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        super.onBackPressed();
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    showOffline();
                }
            }
        });
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        hintBar = new TextView(this);
        hintBar.setText("悬浮球未开启 · 点这里去打开");
        hintBar.setTextSize(13);
        hintBar.setTextColor(0xFF7A5B00);
        hintBar.setBackgroundColor(0xFFFFF3CD);
        float d = getResources().getDisplayMetrics().density;
        int ph = Math.round(14 * d);
        int pv = Math.round(10 * d);
        hintBar.setPadding(ph, pv, ph, pv);
        hintBar.setGravity(Gravity.CENTER);
        hintBar.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                try {
                    startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
                } catch (Exception ignored) {
                }
            }
        });
        FrameLayout.LayoutParams hp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hp.gravity = Gravity.BOTTOM;
        hintBar.setVisibility(View.GONE);
        root.addView(hintBar, hp);

        setContentView(root);
    }

    private void updateHintBar() {
        if (hintBar != null) {
            hintBar.setVisibility(a11yEnabled() ? View.GONE : View.VISIBLE);
        }
    }

    private boolean a11yEnabled() {
        try {
            String svc = getPackageName() + "/" + EntryA11yService.class.getName();
            String enabled = Settings.Secure.getString(getContentResolver(),
                    Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
            return enabled != null && enabled.contains(svc);
        } catch (Exception e) {
            return false;
        }
    }

    private boolean handleShare(Intent intent) {
        if (intent != null && Intent.ACTION_SEND.equals(intent.getAction())) {
            String text = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (text != null && !text.trim().isEmpty()) {
                Intent p = new Intent(this, QuickPanelActivity.class);
                p.putExtra("prefill", text.trim());
                try {
                    startActivity(p);
                } catch (Exception ignored) {
                }
                finish();
                return true;
            }
        }
        return false;
    }

    private void maybeAskNotifications() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                    != PackageManager.PERMISSION_GRANTED) {
                try {
                    requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, REQ_NOTIF);
                } catch (Exception ignored) {
                }
            }
        }
    }

    private void showOffline() {
        String html = "<html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                + "<style>body{font-family:sans-serif;padding:28px;color:#2C2C2A;background:#FBF9F4}"
                + "h2{font-size:17px}p{font-size:14px;line-height:1.7;color:#5F5E5A}"
                + "a{display:inline-block;margin-top:14px;padding:10px 18px;background:#2C2C2A;"
                + "color:#fff;border-radius:10px;text-decoration:none;font-size:14px}</style></head><body>"
                + "<h2>控制台离线了</h2>"
                + "<p>小工头的大脑（控制台）没在响应。通常是：<br>"
                + "1. 控制台刚经历异常，守护会在 60 秒内自动拉起；<br>"
                + "2. 手机刚重启，需要打开一次 Termux 或等待开机自启。</p>"
                + "<a href=\"" + Api.BASE + "/\">重试</a>"
                + "</body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }
}
