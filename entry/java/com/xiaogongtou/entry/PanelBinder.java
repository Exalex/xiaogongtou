package com.xiaogongtou.entry;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.TextView;

import java.util.ArrayList;

/** 输入面板的共用交互逻辑（Activity 宿主 / 悬浮层宿主 通用） */
public class PanelBinder {

    public interface Host {
        void onSubmitSuccess(String task);

        void onCancel();

        void toast(String msg);
    }

    private final Context ctx;
    private final Host host;
    private final EditText input;
    private final TextView btnSend;
    private final TextView btnMic;
    private final TextView hintLine;
    private final TextView modeAuto;
    private final TextView modeJev;
    private final TextView modeQwen;

    private String mode;
    private SpeechRecognizer sr;
    private boolean listening = false;
    private boolean busy = false;

    public PanelBinder(Context ctx, View root, Host host) {
        this.ctx = ctx;
        this.host = host;
        input = (EditText) root.findViewById(R.id.taskInput);
        btnSend = (TextView) root.findViewById(R.id.btnSend);
        btnMic = (TextView) root.findViewById(R.id.btnMic);
        hintLine = (TextView) root.findViewById(R.id.hintLine);
        modeAuto = (TextView) root.findViewById(R.id.modeAuto);
        modeJev = (TextView) root.findViewById(R.id.modeJev);
        modeQwen = (TextView) root.findViewById(R.id.modeQwen);

        View card = root.findViewById(R.id.card);
        if (card != null) {
            card.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    // 吃掉点击：点卡片内部不关闭
                }
            });
        }
        root.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                cancel();
            }
        });

        mode = Prefs.mode(ctx);
        applyModeChips();

        modeAuto.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                setMode("auto");
            }
        });
        modeJev.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                setMode("jev");
            }
        });
        modeQwen.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                setMode("qwen");
            }
        });
        btnSend.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                doSubmit();
            }
        });
        btnMic.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                toggleVoice();
            }
        });
        input.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int actionId, KeyEvent e) {
                if (actionId == EditorInfo.IME_ACTION_SEND
                        || (e != null && e.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                    doSubmit();
                    return true;
                }
                return false;
            }
        });
    }

    public void setPrefill(String text) {
        if (text == null || text.trim().isEmpty()) {
            return;
        }
        if (text.length() > 300) {
            text = text.substring(0, 300);
        }
        input.setText(text.trim());
        input.setSelection(input.getText().length());
    }

    /** 供外部（音量键快捷键等）直接触发提交 */
    public void submitNow() {
        doSubmit();
    }

    public void focusInput() {
        input.requestFocus();
    }

    public void destroy() {
        if (sr != null) {
            try {
                sr.destroy();
            } catch (Exception ignored) {
            }
            sr = null;
        }
    }

    private void cancel() {
        if (listening) {
            stopListen();
        }
        host.onCancel();
    }

    private void setMode(String m) {
        mode = m;
        Prefs.setMode(ctx, m);
        applyModeChips();
    }

    private void applyModeChips() {
        setChip(modeAuto, "auto".equals(mode));
        setChip(modeJev, "jev".equals(mode));
        setChip(modeQwen, "qwen".equals(mode));
    }

    private void setChip(TextView v, boolean on) {
        v.setBackgroundResource(on ? R.drawable.chip_bg_on : R.drawable.chip_bg);
        v.setTextColor(on ? 0xFFFFFFFF : 0xFF9FE1CB);
    }

    private void doSubmit() {
        if (busy) {
            return;
        }
        final String task = input.getText().toString().trim();
        if (task.isEmpty()) {
            host.toast("先说一下要干什么");
            return;
        }
        if (listening) {
            stopListen();
        }
        busy = true;
        btnSend.setAlpha(0.5f);
        btnSend.setText("提交中");
        final String m = mode;
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String err = Api.submit(task, m);
                android.os.Handler h = new android.os.Handler(ctx.getMainLooper());
                h.post(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        btnSend.setAlpha(1f);
                        btnSend.setText("发送");
                        if (err == null) {
                            Notifier.showRunning(ctx, task);
                            host.onSubmitSuccess(task);
                        } else {
                            host.toast("没提交成功：" + err);
                        }
                    }
                });
            }
        }).start();
    }

    private void toggleVoice() {
        if (listening) {
            stopListen();
            return;
        }
        // 统一走「语音速记条」：自动唤起本机输入法的语音输入（无系统识别服务时也能用）
        VoiceBar.show(ctx);
        host.onCancel();
    }

    private void startListen() {
        if (!SpeechRecognizer.isRecognitionAvailable(ctx)) {
            host.toast("系统语音识别不可用");
            return;
        }
        if (sr == null) {
            sr = SpeechRecognizer.createSpeechRecognizer(ctx);
            sr.setRecognitionListener(new RecListener());
        }
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN");
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
        listening = true;
        btnMic.setText("停");
        btnMic.setBackgroundResource(R.drawable.chip_bg_on);
        btnMic.setTextColor(0xFFFFFFFF);
        hintLine.setVisibility(View.VISIBLE);
        hintLine.setText("正在听…说完再点一次「停」");
        try {
            sr.startListening(i);
        } catch (Exception e) {
            listening = false;
            resetMicUi();
            host.toast("语音启动失败");
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
        resetMicUi();
    }

    private void resetMicUi() {
        btnMic.setText("说话");
        btnMic.setBackgroundResource(R.drawable.chip_bg);
        btnMic.setTextColor(0xFF9FE1CB);
    }

    private class RecListener implements RecognitionListener {
        @Override
        public void onReadyForSpeech(Bundle params) {
        }

        @Override
        public void onBeginningOfSpeech() {
        }

        @Override
        public void onRmsChanged(float rmsdB) {
        }

        @Override
        public void onBufferReceived(byte[] buffer) {
        }

        @Override
        public void onEndOfSpeech() {
        }

        @Override
        public void onError(int error) {
            listening = false;
            resetMicUi();
            String extra = "";
            if (error == SpeechRecognizer.ERROR_NO_MATCH) {
                extra = "：没听清";
            } else if (error == SpeechRecognizer.ERROR_NETWORK
                    || error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT) {
                extra = "：网络问题";
            }
            hintLine.setVisibility(View.VISIBLE);
            hintLine.setText("语音识别出错(" + error + ")" + extra);
        }

        @Override
        public void onResults(Bundle results) {
            listening = false;
            resetMicUi();
            ArrayList<String> r = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            if (r == null || r.isEmpty()) {
                hintLine.setText("没听清，再说一次");
                return;
            }
            String text = r.get(0);
            input.setText(text);
            input.setSelection(text.length());
            hintLine.setText("已填入，确认后点「发送」");
        }

        @Override
        public void onPartialResults(Bundle partialResults) {
            ArrayList<String> r = partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            if (r != null && !r.isEmpty()) {
                hintLine.setText("听到：" + r.get(0));
            }
        }

        @Override
        public void onEvent(int eventType, Bundle params) {
        }
    }
}
