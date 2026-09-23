package com.xiaogongtou.entry;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.LayoutInflater;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.widget.TextView;

import java.util.ArrayList;

/**
 * 语音速记条（音量键快捷键的主形态）：
 *   按一下「音量下」→ 弹轻量输入条 + 键盘 + 自动开始本机语音听写；
 *   说完（或再按一下「音量下」）→ 提交执行；点空白处 / × → 取消。
 * 不启动 Activity（仅 a11y overlay），规避 ColorOS 后台启动限制。
 */
public class VoiceBar {
    private static final String TAG = "xgt-entry";
    private static VoiceBar current;

    private final Context ctx;
    private final WindowManager wm;
    private final View rootView;
    private final EditText input;
    private final TextView hint;
    private final WindowManager.LayoutParams lp;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private SpeechRecognizer sr;
    private volatile boolean listening = false;
    private volatile boolean busy = false;
    private volatile boolean pendingSubmit = false;
    private int voiceAttempts = 0;

    public static boolean isShowing() {
        return current != null;
    }

    public static void show(Context ctx) {
        hide();
        VoiceBar b = new VoiceBar(ctx);
        b.attach();
        current = b;
    }

    public static void hide() {
        VoiceBar b = current;
        current = null;
        if (b != null) {
            b.detach();
        }
    }

    /** 快捷键第二下：结束听写并提交（空内容则关闭） */
    public static void hotkeySubmit() {
        VoiceBar b = current;
        if (b != null) {
            b.finishAndSubmit();
        }
    }

    private VoiceBar(Context ctx) {
        this.ctx = ctx;
        wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
        rootView = LayoutInflater.from(ctx).inflate(R.layout.voice_bar, null);
        input = (EditText) rootView.findViewById(R.id.vbInput);
        hint = (TextView) rootView.findViewById(R.id.vbHint);
        View card = rootView.findViewById(R.id.vbCard);
        View close = rootView.findViewById(R.id.vbClose);

        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                cancel();
            }
        });
        card.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                // 吃掉卡片内点击：不关闭
            }
        });
        rootView.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                // 点空白 = 取消（与大面板一致）
                cancel();
            }
        });
        input.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int actionId, KeyEvent e) {
                if (actionId == EditorInfo.IME_ACTION_SEND
                        || (e != null && e.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                    finishAndSubmit();
                    return true;
                }
                return false;
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

    private void attach() {
        try {
            wm.addView(rootView, lp);
        } catch (Exception e) {
            Log.w(TAG, "voice bar show failed", e);
            return;
        }
        rootView.setAlpha(0f);
        rootView.animate().alpha(1f).setDuration(140).start();
        rootView.post(new Runnable() {
            @Override
            public void run() {
                input.requestFocus();
                try {
                    InputMethodManager imm = (InputMethodManager)
                            ctx.getSystemService(Context.INPUT_METHOD_SERVICE);
                    if (imm != null) {
                        imm.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
                    }
                } catch (Exception ignored) {
                }
                startVoice();
                // 键盘位置探针：确认 overlay 是否随 IME 上推（日志排查用）
                rootView.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            Rect r = new Rect();
                            rootView.getWindowVisibleDisplayFrame(r);
                            int sh = ctx.getResources().getDisplayMetrics().heightPixels;
                            Log.i(TAG, "vb frame bottom=" + r.bottom + " screenH=" + sh
                                    + " imeGuess=" + (sh - r.bottom));
                        } catch (Exception ignored) {
                        }
                    }
                }, 1500);
            }
        });
    }

    /** 语音入口：自动点输入法键盘的「麦克风/语音」键（= 本机语音输入）；不行再退回静默识别 */
    private void startVoice() {
        setHint("正在唤起语音输入…", true);
        voiceAttempts = 0;
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                attemptVoice();
            }
        }, 500);
    }

    /** 尝试唤起语音键：等键盘升起 → ①a11y 节点 ②portal 坐标注入 ③无障碍手势兜底 */
    private void attemptVoice() {
        if (current != VoiceBar.this) {
            return;
        }
        final android.graphics.Rect r = new android.graphics.Rect();
        rootView.getWindowVisibleDisplayFrame(r);
        int screenH = ctx.getResources().getDisplayMetrics().heightPixels;
        boolean keyboardUp = (screenH - r.bottom) > 300;
        if (!keyboardUp && voiceAttempts < 5) {
            voiceAttempts++;
            handler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    attemptVoice();
                }
            }, 200);
            return;
        }
        // ① 无障碍节点法（部分输入法可点）
        boolean ok = false;
        try {
            if (ctx instanceof EntryA11yService) {
                ok = ((EntryA11yService) ctx).clickImeVoiceButton();
            }
        } catch (Exception ignored) {
        }
        if (ok) {
            Log.i(TAG, "voice: ime voice key clicked (a11y)");
            setHint("听写已开启，说完再按音量▾执行", true);
            return;
        }
        // ② 几何坐标 → portal（root 注入，本机搜狗实测可靠；异步避免卡主线程）
        final int fx = Math.round(r.right * 0.597f);
        final int fy = r.bottom + 77;
        final int kbTop = r.bottom;
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String err = Api.tap(fx, fy);
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (current != VoiceBar.this) {
                            return;
                        }
                        if (err == null) {
                            Log.i(TAG, "voice: voice key tapped via portal (" + fx + "," + fy
                                    + ") kbTop=" + kbTop);
                            setHint("听写已开启，说完再按音量▾执行", true);
                            return;
                        }
                        Log.w(TAG, "voice: portal tap failed: " + err);
                        // ③ 无障碍手势兜底（部分 ROM 合成触摸会被输入法忽略）
                        boolean g = false;
                        try {
                            if (ctx instanceof EntryA11yService) {
                                g = ((EntryA11yService) ctx).tapVoiceByGeometry(rootView);
                            }
                        } catch (Exception ignored) {
                        }
                        if (g) {
                            setHint("听写已开启，说完再按音量▾执行", true);
                            return;
                        }
                        startLocalListen();
                    }
                });
            }
        }).start();
    }

    /** 回退通道：设备自带系统语音识别服务时，静默听写（无系统 UI），结果直接填入输入框 */
    private void startLocalListen() {
        if (ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            setHint("请点键盘上的麦克风说话，或直接打字", false);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(ctx)) {
            setHint("请点键盘上的麦克风说话，或直接打字", false);
            return;
        }
        try {
            if (sr == null) {
                sr = SpeechRecognizer.createSpeechRecognizer(ctx);
                sr.setRecognitionListener(new RecListener());
            }
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN");
            i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
            i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
            listening = true;
            setHint("正在听…", true);
            sr.startListening(i);
            Log.i(TAG, "voice: local listening started");
        } catch (Exception e) {
            listening = false;
            setHint("语音启动失败：" + e, false);
        }
    }

    private void stopListen() {
        listening = false;
        if (sr != null) {
            try {
                sr.stopListening();
            } catch (Exception ignored) {
            }
        }
    }

    /** 结束听写 → 提交（若仍在识别，先停、等最终结果，1.6s 超时兜底） */
    private void finishAndSubmit() {
        if (busy) {
            return;
        }
        if (listening) {
            pendingSubmit = true;
            stopListen();
            handler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    if (pendingSubmit) {
                        pendingSubmit = false;
                        submitOrClose();
                    }
                }
            }, 1600);
        } else {
            submitOrClose();
        }
    }

    private void submitOrClose() {
        String t = input.getText().toString().trim();
        if (t.isEmpty()) {
            Log.i(TAG, "voice: empty -> cancel");
            hide();
            return;
        }
        submit(t);
    }

    private void submit(final String task) {
        busy = true;
        setHint("提交中…", true);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String err = Api.submit(task, Prefs.mode(ctx));
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        if (err == null) {
                            Log.i(TAG, "voice: submitted: " + task);
                            Notifier.showRunning(ctx, task);
                            hide();
                        } else {
                            setHint("提交失败：" + err, false);
                        }
                    }
                });
            }
        }).start();
    }

    private void cancel() {
        stopListen();
        hide();
    }

    private void setHint(final String s, final boolean okTone) {
        handler.post(new Runnable() {
            @Override
            public void run() {
                if (hint != null) {
                    hint.setText(s);
                    hint.setTextColor(okTone ? 0xFF9FE1CB : 0xFFEF9F27);
                }
            }
        });
    }

    private void detach() {
        listening = false;
        pendingSubmit = false;
        handler.removeCallbacksAndMessages(null);
        if (sr != null) {
            final SpeechRecognizer s = sr;
            sr = null;
            try {
                s.destroy();
            } catch (Exception ignored) {
            }
        }
        final View rv = rootView;
        try {
            rv.animate().alpha(0f).setDuration(120).withEndAction(new Runnable() {
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
    }

    private class RecListener implements RecognitionListener {
        @Override
        public void onReadyForSpeech(Bundle params) {
            setHint("正在听…", true);
        }

        @Override
        public void onBeginningOfSpeech() {
            setHint("听到声音了…", true);
        }

        @Override
        public void onRmsChanged(float rmsdB) {
        }

        @Override
        public void onBufferReceived(byte[] buffer) {
        }

        @Override
        public void onEndOfSpeech() {
            setHint("识别中…", true);
        }

        @Override
        public void onError(int error) {
            listening = false;
            if (pendingSubmit) {
                pendingSubmit = false;
                submitOrClose();
                return;
            }
            String extra = "";
            if (error == SpeechRecognizer.ERROR_NO_MATCH) {
                extra = "（没听清）";
            } else if (error == SpeechRecognizer.ERROR_NETWORK
                    || error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT) {
                extra = "（网络问题）";
            }
            setHint("语音识别失败" + extra + "，再说一次或直接打字", false);
        }

        @Override
        public void onResults(Bundle results) {
            listening = false;
            ArrayList<String> r = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            if (r != null && !r.isEmpty()) {
                String text = r.get(0);
                input.setText(text);
                input.setSelection(text.length());
            }
            if (pendingSubmit) {
                pendingSubmit = false;
                submitOrClose();
            } else {
                setHint("已填入，再按一下音量▾执行", true);
            }
        }

        @Override
        public void onPartialResults(Bundle partialResults) {
            ArrayList<String> r = partialResults.getStringArrayList(
                    SpeechRecognizer.RESULTS_RECOGNITION);
            if (r != null && !r.isEmpty()) {
                String text = r.get(0);
                input.setText(text);
                input.setSelection(text.length());
                setHint("正在听…", true);
            }
        }

        @Override
        public void onEvent(int eventType, Bundle params) {
        }
    }
}
