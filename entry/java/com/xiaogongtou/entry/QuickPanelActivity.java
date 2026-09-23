package com.xiaogongtou.entry;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.WindowManager;
import android.widget.Toast;

/** 迷你输入面板（Activity 版：从通知 / 分享 / 无障碍按钮进入） */
public class QuickPanelActivity extends Activity {
    private PanelBinder binder;

    public static void open(Context c) {
        try {
            Intent i = new Intent(c, QuickPanelActivity.class);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            c.startActivity(i);
        } catch (Exception ignored) {
        }
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_panel);
        binder = new PanelBinder(this, findViewById(R.id.root), new PanelBinder.Host() {
            @Override
            public void onSubmitSuccess(String task) {
                finish();
            }

            @Override
            public void onCancel() {
                finish();
            }

            @Override
            public void toast(String msg) {
                Toast.makeText(QuickPanelActivity.this, msg, Toast.LENGTH_SHORT).show();
            }
        });
        binder.setPrefill(getIntent().getStringExtra("prefill"));
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
                | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        binder.focusInput();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (binder != null) {
            binder.setPrefill(intent.getStringExtra("prefill"));
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (binder != null) {
            binder.destroy();
            binder = null;
        }
    }
}
