package com.xiaogongtou.entry;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.PixelFormat;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
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

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;

/**
 * 语音输入浮层（音量键/浮球唤起）：
 *
 * 主链路（"去键盘"ASR · v2 边说边识别）：
 *   唤起 → 自动开始录音；录音期间每 ~1.3s 把"从开始到当前"的音频发电脑识别一次，
 *   识别文字实时刷到中央字幕 →（静音 ~2.2s / 30s 上限 / 再按音量▾）停止 → 最终识别定稿
 *   → 显示【重说】【提交】按钮 → 看一眼，点『提交』（或按音量▾）才真正提交。
 *   全程不需要输入法/键盘；点字幕可手动改成任意文字。
 *
 * 回退链路（电脑服务不可达）：搜狗键盘语音（原逻辑）。
 */
public class VoiceBar {
    private static final String TAG = "xgt-entry";
    private static VoiceBar current;

    private final Context ctx;
    private final WindowManager wm;
    private final View rootView;
    private final EditText input;
    private final View card;
    private final GlowFrameView glow;
    private final WaveView wave;
    private final View btnRow;
    private final TextView vbRetry;
    private final TextView vbSubmit;
    private final WindowManager.LayoutParams lp;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private SpeechRecognizer sr;
    private volatile boolean listening = false;
    private volatile boolean busy = false;
    private volatile boolean pendingSubmit = false;
    private int voiceAttempts = 0;

    // —— ASR（电脑识别链路 · 流式版）：边说边出字；确认后提交 ——
    //    电脑侧服务：scripts/_asr_server.py（SenseVoice，:8766）。不可达时自动回退搜狗键盘链路。
    private static final String ASR_URL = "http://192.168.3.179:8766";
    private static final int ASR_SR = 16000;
    private static final int REC_MAX_MS = 30000;      // 单次录音上限
    private static final int SILENCE_MS = 2200;       // 说完静音判定
    private static final int RMS_TH = 220;            // 语音能量阈值（≈-43dBFS；弱声/远场也能触发）
    private static final int STREAM_EVERY_MS = 1300;  // 流式识别节拍
    private volatile boolean asrMode = false;
    private volatile boolean recording = false;
    private volatile boolean recognizing = false;     // 最终识别进行中（兼容旧逻辑命名）
    private volatile boolean finalizing = false;      // 收尾识别中（停止录音→定稿）
    private volatile boolean reviewMode = false;      // 待确认态（显示 重说/提交）
    private volatile boolean retryPending = false;    // "没听清/失败"后：再按音量▾ = 重新录音
    private volatile boolean streamBusy = false;      // 上一轮流式识别请求未回（不并发、防积压）
    private volatile boolean voiceHeard = false;      // 本轮录音是否捕捉到过语音
    private volatile long lastVoiceAt = 0;            // 最后一次"有语音"的时间戳
    private AudioRecord arec;
    private Thread recThread;
    private final ByteArrayOutputStream pcmBuf = new ByteArrayOutputStream();
    private long recStartAt = 0;

    /** 语音输入（搜狗麦克风）是否已成功唤起；自动收键盘只在此后生效 */
    private volatile boolean voiceEngaged = false;
    /** 键盘是否已被"说完自动收起"收起（收起后不再干预，用户可点输入框再唤出） */
    private volatile boolean imeHidden = false;
    private long voiceStartAt = 0;
    private String lastSeenText = "";
    private long lastTextChangeAt = 0;

    /** 看护：语音结果稳定后自动收起输入法（仅搜狗回退链路；ASR 主链路键盘本不出现） */
    private final Runnable imeWatch = new Runnable() {
        @Override
        public void run() {
            if (current != VoiceBar.this || imeHidden) {
                return;
            }
            String t = input.getText().toString().trim();
            long now = SystemClock.uptimeMillis();
            if (!t.equals(lastSeenText)) {
                lastSeenText = t;
                lastTextChangeAt = now;
                if (!t.isEmpty() && voiceEngaged) {
                    setHint("已识别，继续说…说完按音量▾执行", true);
                }
            }
            if (voiceEngaged) {
                boolean settled = !t.isEmpty() && (now - lastTextChangeAt > 3000);
                boolean abandoned = t.isEmpty() && (now - voiceStartAt > 20000);
                if (settled || abandoned) {
                    hideIme();
                    return;
                }
            }
            handler.postDelayed(this, 600);
        }
    };

    /** 待确认态看护：90s 不操作 → 自动收起（不提交、零副作用） */
    private final Runnable reviewTimeout = new Runnable() {
        @Override
        public void run() {
            if (reviewMode && current == VoiceBar.this) {
                Log.i(TAG, "voice: review timeout -> auto cancel");
                cancel();
            }
        }
    };

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

    /** 快捷键再按一下：
     *  录音中 → 结束录音进"待确认"；待确认 → 提交；"没听清"后 → 重录；其余沿用旧逻辑 */
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
        card = rootView.findViewById(R.id.vbCard);
        glow = (GlowFrameView) rootView.findViewById(R.id.vbGlow);
        wave = (WaveView) rootView.findViewById(R.id.vbWave);
        btnRow = rootView.findViewById(R.id.vbBtns);
        vbRetry = (TextView) rootView.findViewById(R.id.vbRetry);
        vbSubmit = (TextView) rootView.findViewById(R.id.vbSubmit);

        if (vbRetry != null) {
            vbRetry.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    retryFromReview();
                }
            });
        }
        if (vbSubmit != null) {
            vbSubmit.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    submitFromReview();
                }
            });
        }
        card.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                // 吃掉内容区点击：不关闭
            }
        });
        // 输入框只要有可提交的文字，就让【提交】可见（手打/键盘路线也能提交）
        input.addTextChangedListener(new android.text.TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int st, int c, int a) {
            }

            @Override
            public void onTextChanged(CharSequence s, int st, int b, int c) {
            }

            @Override
            public void afterTextChanged(android.text.Editable s) {
                if (s == null || !isMeaningful(s.toString().trim())) {
                    return;
                }
                if (btnRow != null && btnRow.getVisibility() != View.VISIBLE) {
                    btnRow.setVisibility(View.VISIBLE);
                    btnRow.setAlpha(1f);
                }
                if (vbSubmit != null && vbSubmit.getVisibility() != View.VISIBLE) {
                    vbSubmit.setVisibility(View.VISIBLE);
                }
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
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        // 贴屏幕物理边缘：不避让状态栏/导航栏（否则光效框从状态栏下方开始、不贴边）
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            lp.setFitInsetsTypes(0);
        }
        lp.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        // 不自动弹键盘（语音默认走"电脑识别"；键盘只在回退模式或用户主动点输入框时出现）
        lp.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_STATE_UNSPECIFIED
                | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE;
    }

    private void attach() {
        try {
            wm.addView(rootView, lp);
        } catch (Exception e) {
            Log.w(TAG, "voice bar show failed", e);
            return;
        }
        // 视觉进场：轻幕淡入 + 边缘灯管点亮→光渗入→光斑跑圈→呼吸；内容层轻浮起
        View dim = rootView.findViewById(R.id.vbDim);
        if (dim != null) {
            dim.setAlpha(0f);
            dim.animate().alpha(1f).setDuration(260).start();
            // 2026-10-19：点灰幕空白处 = 取消（此前窗口全屏且无手势出口，
            // 用户在平板上会以为"卡住了/没反应"；返回键也关不掉）
            dim.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    Log.i(TAG, "voice: dim tapped -> cancel");
                    cancel();
                }
            });
        }
        // 返回键兜底：根视图吃一次 BACK 就收窗（不进入"卡住"状态）
        rootView.setFocusableInTouchMode(true);
        rootView.setOnKeyListener(new View.OnKeyListener() {
            @Override
            public boolean onKey(View v, int keyCode, KeyEvent event) {
                if (keyCode == KeyEvent.KEYCODE_BACK
                        && event.getAction() == KeyEvent.ACTION_UP) {
                    Log.i(TAG, "voice: back key -> cancel");
                    cancel();
                    return true;
                }
                return false;
            }
        });
        rootView.requestFocus();
        try {
            String pal = android.provider.Settings.System.getString(
                    ctx.getContentResolver(), "xgt_glow_palette");
            glow.setPalette(pal);
        } catch (Throwable ignored) {
        }
        glow.playEnter();
        float d = ctx.getResources().getDisplayMetrics().density;
        card.setAlpha(0f);
        card.setTranslationY(12f * d);
        card.animate().alpha(1f).translationY(0f)
                .setDuration(300)
                .setInterpolator(new android.view.animation.DecelerateInterpolator())
                .start();
        rootView.post(new Runnable() {
            @Override
            public void run() {
                // 语音入口：优先"电脑识别"（边说边出字、全程无键盘）；连不上则回退搜狗键盘链路
                startVoiceSmart();
                voiceStartAt = SystemClock.uptimeMillis();
                lastTextChangeAt = voiceStartAt;
                handler.postDelayed(imeWatch, 1000);
            }
        });
    }

    /** 智能语音入口：先探"电脑识别"服务；可达→流式录音模式（无键盘）；不可达→回退搜狗键盘链路 */
    private void startVoiceSmart() {
        setHint("正在连接识别服务…", true);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final boolean ok = asrPing();
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (current != VoiceBar.this) {
                            return;
                        }
                        if (ok) {
                            asrMode = true;
                            startRecording();
                        } else {
                            Log.i(TAG, "asr: unreachable -> fallback to sogou keyboard");
                            setHint("识别服务不在线 → 键盘模式", false);
                            try {
                                input.requestFocus();
                            } catch (Exception ignored) {
                            }
                            handler.postDelayed(new Runnable() {
                                @Override
                                public void run() {
                                    try {
                                        InputMethodManager imm = (InputMethodManager)
                                                ctx.getSystemService(Context.INPUT_METHOD_SERVICE);
                                        if (imm != null) {
                                            imm.showSoftInput(input,
                                                    InputMethodManager.SHOW_IMPLICIT);
                                        }
                                    } catch (Exception ignored) {
                                    }
                                }
                            }, 150);
                            startVoice();   // 原搜狗链路（350ms 后 attemptVoice，会等键盘）
                        }
                    }
                });
            }
        }).start();
    }

    private boolean asrPing() {
        try {
            HttpURLConnection c = (HttpURLConnection)
                    new URL(ASR_URL + "/ping").openConnection();
            c.setConnectTimeout(1200);
            c.setReadTimeout(1200);
            int code = c.getResponseCode();
            c.disconnect();
            return code == 200;
        } catch (Exception e) {
            return false;
        }
    }

    /** 开始录音（16k/mono/PCM16 内存缓冲）+ 启动流式识别；
     *  停止条件：说完静音 ~2.2s / 30s 上限 / 再按音量▾；停止后进"待确认"，不自动提交 */
    private void startRecording() {
        try {
            int min = AudioRecord.getMinBufferSize(ASR_SR,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (min <= 0) {
                min = 4096;
            }
            // MIC 源（而非 VOICE_RECOGNITION）：后者的 AEC 会把"手机自身扬声器"的声音当回声消掉
            arec = new AudioRecord(MediaRecorder.AudioSource.MIC,
                    ASR_SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    min * 2);
            if (arec.getState() != AudioRecord.STATE_INITIALIZED) {
                throw new IllegalStateException("AudioRecord 初始化失败");
            }
            pcmBuf.reset();
            recording = true;
            reviewMode = false;
            voiceHeard = false;
            lastVoiceAt = 0;
            recStartAt = SystemClock.uptimeMillis();
            arec.startRecording();
            recThread = new Thread(new Runnable() {
                @Override
                public void run() {
                    byte[] buf = new byte[3200];
                    while (recording) {
                        int n;
                        try {
                            n = arec.read(buf, 0, buf.length);
                        } catch (Exception e) {
                            break;
                        }
                        if (n <= 0) {
                            continue;
                        }
                        synchronized (pcmBuf) {
                            pcmBuf.write(buf, 0, n);
                        }
                        // —— 语音能量检测（16-bit LE RMS）→ 说完静音自动收工 ——
                        long sum = 0;
                        int cnt = n / 2;
                        for (int i = 0; i + 1 < n; i += 2) {
                            int s = (short) ((buf[i] & 0xFF) | (buf[i + 1] << 8));
                            sum += (long) s * s;
                        }
                        double rms = Math.sqrt((double) sum / Math.max(1, cnt));
                        long now = SystemClock.uptimeMillis();
                        if (rms > RMS_TH) {
                            voiceHeard = true;
                            lastVoiceAt = now;
                        }
                        // 声波线：把音量包络送到 UI（感知曲线：开方）
                        final float nv = (float) Math.min(1.0, Math.sqrt(rms / 1500.0));
                        handler.post(new Runnable() {
                            @Override
                            public void run() {
                                if (wave != null && current == VoiceBar.this) {
                                    wave.push(nv);
                                }
                            }
                        });
                        boolean silenceStop = voiceHeard && (now - lastVoiceAt > SILENCE_MS);
                        boolean nothingStop = !voiceHeard && (now - recStartAt > 6000);
                        if (silenceStop || nothingStop) {
                            Log.i(TAG, "asr: auto-stop (" + (silenceStop ? "silence" : "no-voice") + ")");
                            handler.post(new Runnable() {
                                @Override
                                public void run() {
                                    stopAndReview();
                                }
                            });
                            break;
                        }
                    }
                }
            });
            recThread.start();
            setHint("正在听…（说完停一下）", true);
            if (wave != null) {
                wave.setLive(true);   // 声波线进入活跃态（清空历史、开始波动）
            }
            Log.i(TAG, "asr: recording started (stream mode)");
            handler.postDelayed(recTimeout, REC_MAX_MS);
            handler.postDelayed(streamTick, 1100);   // 流式第一拍（先攒 ~1.1s 音频）
        } catch (Exception e) {
            recording = false;
            asrMode = false;
            Log.w(TAG, "asr: record start failed", e);
            setHint("录音启动失败，可点输入框打字", false);
            releaseRecorder();
        }
    }

    /** 30s 上限：自动停止并进"待确认"（防忘记） */
    private final Runnable recTimeout = new Runnable() {
        @Override
        public void run() {
            if (recording) {
                Log.i(TAG, "asr: 30s timeout -> review");
                stopAndReview();
            }
        }
    };

    /** 流式识别节拍：每 ~1.3s 把"从开始到当前"的音频发电脑识别，文字实时上屏（不并发、防积压） */
    private final Runnable streamTick = new Runnable() {
        @Override
        public void run() {
            if (current != VoiceBar.this || !recording) {
                return;
            }
            if (streamBusy) {
                handler.postDelayed(this, 400);
                return;
            }
            byte[] pcm;
            synchronized (pcmBuf) {
                pcm = pcmBuf.toByteArray();
            }
            if (pcm.length >= ASR_SR / 2) {   // ≥0.5s 才值得识别
                streamBusy = true;
                final byte[] wav = buildWav(pcm);
                new Thread(new Runnable() {
                    @Override
                    public void run() {
                        final String text = asrUpload(wav, true);
                        handler.post(new Runnable() {
                            @Override
                            public void run() {
                                streamBusy = false;
                                if (current != VoiceBar.this || !recording) {
                                    return;   // 已停止/已关闭：丢弃在途结果
                                }
                                if (text == null) {
                                    return;   // 单拍失败静默，下一拍继续
                                }
                                applyLiveText(text.trim());
                            }
                        });
                    }
                }).start();
            }
            handler.postDelayed(this, STREAM_EVERY_MS);
        }
    };

    /** 把流式识别结果刷到中央字幕（用户正在手动编辑时不覆盖；噪声不上屏） */
    private void applyLiveText(String t) {
        if (t.isEmpty() || input.hasFocus()) {
            return;
        }
        if (!isMeaningful(t)) {
            return;   // 纯标点/单字符（如安静的"。"）不上屏
        }
        if (t.equals(input.getText().toString())) {
            return;
        }
        input.setText(t);
        input.setSelection(t.length());
    }

    /** 文本是否有实际内容（过滤纯标点/单字符噪声，如"。"） */
    private static boolean isMeaningful(String t) {
        if (t == null || t.isEmpty()) {
            return false;
        }
        String core = t.replaceAll(
                "[\\p{Punct}\\s。，、！？：；…—·「」『』【】（）《》〈〉\"'‘’“”]+", "");
        return core.length() >= 2;
    }

    /** 停止录音 → 最终识别定稿 → 进"待确认"（不自动提交；确认动作由用户给出） */
    private void stopAndReview() {
        if (!recording) {
            return;
        }
        recording = false;
        if (wave != null) {
            wave.setLive(false);   // 声波线平息
        }
        handler.removeCallbacks(recTimeout);
        try {
            if (arec != null) {
                arec.stop();
            }
        } catch (Exception ignored) {
        }
        try {
            if (recThread != null) {
                recThread.join(500);
            }
        } catch (Exception ignored) {
        }
        byte[] pcm;
        synchronized (pcmBuf) {
            pcm = pcmBuf.toByteArray();
        }
        releaseRecorder();
        Log.i(TAG, "asr: stopped, " + pcm.length + " bytes, "
                + (SystemClock.uptimeMillis() - recStartAt) + "ms");
        if (pcm.length < ASR_SR / 4) {   // <0.25s：太短，判为没说话
            retryPending = true;
            showReview(false);
            setHint("没听到声音——点『重说』再试一次", false);
            return;
        }
        finalizing = true;
        recognizing = true;
        setHint("识别中…", true);
        final byte[] wav = buildWav(pcm);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String text = asrUpload(wav, false);
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        finalizing = false;
                        recognizing = false;
                        if (current != VoiceBar.this) {
                            return;
                        }
                        if (text == null) {
                            // 最终识别失败：若流式已给出可用文字，允许直接确认提交
                            if (isMeaningful(input.getText().toString())) {
                                showReview(true);
                                setHint("网络识别未完成——确认已有内容，点『提交』", false);
                            } else {
                                retryPending = true;
                                showReview(false);
                                setHint("识别失败（服务/网络）——点『重说』重试", false);
                            }
                            return;
                        }
                        String t = text.trim();
                        if (!isMeaningful(t)) {
                            Log.i(TAG, "asr: noise-only result -> " + t);
                            if (isMeaningful(input.getText().toString())) {
                                showReview(true);
                                setHint("识别不稳定——确认已有内容，点『提交』", false);
                            } else {
                                retryPending = true;
                                showReview(false);
                                setHint("没听清——点『重说』再说，或点文字自己打字", false);
                            }
                            return;
                        }
                        Log.i(TAG, "asr: recognized -> " + t);
                        if (!input.hasFocus()) {
                            input.setText(t);
                            input.setSelection(t.length());
                        }
                        showReview(true);
                        setHint("看一眼，点『提交』发送（或按音量▾）", true);
                    }
                });
            }
        }).start();
    }

    /** 待确认态：显示【重说】【提交】按钮（withSubmit=false 时只给"重说"） */
    private void showReview(final boolean withSubmit) {
        reviewMode = true;
        handler.post(new Runnable() {
            @Override
            public void run() {
                if (current != VoiceBar.this) {
                    return;
                }
                if (btnRow != null) {
                    btnRow.setVisibility(View.VISIBLE);
                    btnRow.setAlpha(0f);
                    btnRow.animate().alpha(1f).setDuration(220).start();
                }
                if (vbSubmit != null) {
                    vbSubmit.setVisibility(withSubmit ? View.VISIBLE : View.GONE);
                }
                handler.removeCallbacks(reviewTimeout);
                handler.postDelayed(reviewTimeout, 90000);
            }
        });
    }

    private void hideBtns() {
        handler.post(new Runnable() {
            @Override
            public void run() {
                if (btnRow != null) {
                    btnRow.setVisibility(View.GONE);
                }
            }
        });
    }

    /** 待确认 → 提交（读字幕当前文本；用户可先手动改字再提交） */
    private void submitFromReview() {
        if (busy) {
            return;
        }
        String t = input.getText().toString().trim();
        if (!isMeaningful(t)) {
            setHint("内容太短或没听清——点『重说』重讲一句", false);
            return;
        }
        handler.removeCallbacks(reviewTimeout);
        submit(t);
    }

    /** 待确认 → 重说（清空重录，循环） */
    private void retryFromReview() {
        if (busy) {
            return;
        }
        reviewMode = false;
        retryPending = false;
        handler.removeCallbacks(reviewTimeout);
        hideBtns();
        input.setText("");
        voiceHeard = false;
        lastVoiceAt = 0;
        startRecording();
    }

    /** PCM(16k mono s16le) → WAV 字节 */
    private byte[] buildWav(byte[] pcm) {
        int dataLen = pcm.length;
        java.nio.ByteBuffer h = java.nio.ByteBuffer.allocate(44)
                .order(java.nio.ByteOrder.LITTLE_ENDIAN);
        h.put(new byte[]{'R', 'I', 'F', 'F'});
        h.putInt(36 + dataLen);
        h.put(new byte[]{'W', 'A', 'V', 'E'});
        h.put(new byte[]{'f', 'm', 't', ' '});
        h.putInt(16);
        h.putShort((short) 1);
        h.putShort((short) 1);
        h.putInt(ASR_SR);
        h.putInt(ASR_SR * 2);
        h.putShort((short) 2);
        h.putShort((short) 16);
        h.put(new byte[]{'d', 'a', 't', 'a'});
        h.putInt(dataLen);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(h.array(), 0, 44);
        out.write(pcm, 0, dataLen);
        return out.toByteArray();
    }

    /** 上传 WAV 到电脑识别服务；返回识别文本（失败 null）。
     *  stream=true 时带 X-Stream 头（服务端跳过落盘，见 _asr_server.py） */
    private String asrUpload(byte[] wav, boolean stream) {
        try {
            HttpURLConnection c = (HttpURLConnection)
                    new URL(ASR_URL + "/asr").openConnection();
            c.setRequestMethod("POST");
            c.setConnectTimeout(2500);
            c.setReadTimeout(8000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "audio/wav");
            if (stream) {
                c.setRequestProperty("X-Stream", "1");
            }
            c.setFixedLengthStreamingMode(wav.length);
            OutputStream os = c.getOutputStream();
            try {
                os.write(wav);
            } finally {
                os.close();
            }
            int code = c.getResponseCode();
            if (code != 200) {
                c.disconnect();
                return null;
            }
            InputStream is = c.getInputStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] b = new byte[1024];
            int n;
            while ((n = is.read(b)) > 0) {
                bo.write(b, 0, n);
            }
            is.close();
            c.disconnect();
            JSONObject j = new JSONObject(new String(bo.toByteArray(), "UTF-8"));
            return j.optString("text", "");
        } catch (Exception e) {
            Log.w(TAG, "asr: upload failed: " + e);
            return null;
        }
    }

    private void releaseRecorder() {
        try {
            if (arec != null) {
                arec.release();
            }
        } catch (Exception ignored) {
        }
        arec = null;
        recThread = null;
    }

    /** 收声清理（取消/关闭时）：停止并释放录音，不提交 */
    private void stopRecordingIfAny() {
        if (recording) {
            recording = false;
            handler.removeCallbacks(recTimeout);
            handler.removeCallbacks(streamTick);
            try {
                if (arec != null) {
                    arec.stop();
                }
            } catch (Exception ignored) {
            }
            releaseRecorder();
        }
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
        }, 350);
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
        if (!keyboardUp && voiceAttempts < 8) {
            voiceAttempts++;
            handler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    attemptVoice();
                }
            }, 150);
            return;
        }
        if (!keyboardUp) {
            // 键盘始终没弹：绝不盲点（下面的坐标都是"给键盘用的"）——如实提示走打字
            Log.w(TAG, "voice: keyboard not shown after retries -> give up (no blind tap)");
            setHint("键盘没出来——点输入框用键盘麦克风，或直接打字", false);
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
            voiceEngaged = true;
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
                            voiceEngaged = true;
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
                            voiceEngaged = true;
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

    /** 音量▾ 再按路由：
     *  录音中 → 结束录音进"待确认"；待确认 → 提交；"没听清"后 → 重录；其余沿用旧逻辑 */
    private void finishAndSubmit() {
        if (busy) {
            return;
        }
        if (recording) {
            stopAndReview();
            return;
        }
        if (finalizing || recognizing) {
            setHint("正在识别，稍候…", true);
            return;
        }
        if (retryPending) {              // "没听清/失败"态优先：再按 = 重说（而非把噪声提交出去）
            // 例外：用户已经手动打字（键盘路线）——文字优先，直接提交，不能清空重录
            String typed = input.getText().toString().trim();
            if (isMeaningful(typed)) {
                retryPending = false;
                submit(typed);
                return;
            }
            retryFromReview();
            return;
        }
        if (reviewMode) {
            submitFromReview();
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

    /** busy 看门狗：极端情况下（网络卡死/回调丢失）25s 后强制解锁，避免按钮永久点不动 */
    private final Runnable busyWatchdog = new Runnable() {
        @Override
        public void run() {
            if (busy) {
                busy = false;
                Log.w(TAG, "voice: busy watchdog fired");
                setHint("提交超时，请再点一次提交", false);
            }
        }
    };

    private void submit(final String task) {
        busy = true;
        hideIme();
        // 点下即响应：不等网络往返（console 启动含预检，实测可达 10s）——
        // 先点亮任务栏 + 飞行动画 + 关闭语音窗；失败由任务栏红字回报
        setHint("提交中…", true);
        try {
            TaskBar.kickoff(ctx, task);
            flyToTaskBar(task);
        } catch (Exception ignored) {
        }
        hide();
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String err = Api.submit(task, Prefs.mode(ctx), true);
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        handler.removeCallbacks(busyWatchdog);
                        if (err == null) {
                            Log.i(TAG, "voice: submitted: " + task);
                            Notifier.showRunning(ctx, task);
                        } else {
                            Log.w(TAG, "voice: submit failed: " + err);
                            try {
                                TaskBar.onResult(ctx, TaskBar.KIND_FAIL, task,
                                        "提交失败：" + err);
                            } catch (Exception ignored) {
                            }
                            Notifier.showResult(ctx, "提交失败", err);
                        }
                    }
                });
            }
        }).start();
    }

    private void cancel() {
        stopRecordingIfAny();
        stopListen();
        handler.removeCallbacks(reviewTimeout);
        hide();
    }

    /** 提交成功：任务胶囊从输入框飞向顶部任务栏（"把任务丢到任务栏"） */
    private void flyToTaskBar(String task) {
        try {
            int[] loc = new int[2];
            input.getLocationOnScreen(loc);
            float cx = loc[0] + input.getWidth() / 2f;
            float cy = loc[1] + input.getHeight() / 2f;
            EntryA11yService s = EntryA11yService.svc();
            if (s != null) {
                FlyView.launch(s, cx, cy, task, new Runnable() {
                    @Override
                    public void run() {
                        TaskBar.landed();
                    }
                });
            }
        } catch (Exception ignored) {
        }
    }

    /** 收起输入法（键盘 + 搜狗语音面板）。
     *  注意：收起即断开键盘麦克风通道；已识别的文字保留，可继续提交。 */
    private void hideIme() {
        imeHidden = true;
        try {
            InputMethodManager imm = (InputMethodManager)
                    ctx.getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null) {
                imm.hideSoftInputFromWindow(input.getWindowToken(), 0);
            }
        } catch (Exception ignored) {
        }
        String t = input.getText().toString().trim();
        if (!t.isEmpty()) {
            setHint("已识别 · 再按音量▾执行（点文字可修改）", true);
        } else {
            setHint("没听清？点输入框重试，或直接打字", false);
        }
        Log.i(TAG, "voice: ime auto-hidden (text=" + t.length() + " chars)");
    }

    /** 提示语不再上屏（用户要求"其他乱七八糟的提示字都不要"）——仅记日志供排查 */
    private void setHint(final String s, final boolean okTone) {
        Log.i(TAG, "hint: " + s);
        // 2026-10-19：以前只写日志、屏幕零文字 → 服务连不上时用户只看到一条静止横线，
        // 表现为"没有反应"。改成把状态写进输入框的 placeholder（有内容时自动不显示）。
        try {
            handler.post(new Runnable() {
                @Override
                public void run() {
                    try {
                        if (input != null) {
                            input.setHint(s);
                        }
                    } catch (Exception ignored) {
                    }
                }
            });
        } catch (Exception ignored) {
        }
    }

    private void detach() {
        stopRecordingIfAny();
        listening = false;
        pendingSubmit = false;
        try {
            InputMethodManager imm = (InputMethodManager)
                    ctx.getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null && input.getWindowToken() != null) {
                imm.hideSoftInputFromWindow(input.getWindowToken(), 0);
            }
        } catch (Exception ignored) {
        }
        handler.removeCallbacksAndMessages(null);
        if (sr != null) {
            final SpeechRecognizer s = sr;
            sr = null;
            try {
                s.destroy();
            } catch (Exception ignored) {
            }
        }
        // 光效退场：绝不因为动画异常而卡住窗口（曾出现"提交后窗口不消失"）
        try {
            glow.playExit();
        } catch (Exception ignored) {
        }
        try {
            card.animate().alpha(0f).setDuration(150).start();
        } catch (Exception ignored) {
        }
        final View rv = rootView;
        // 兜底：无论动画是否正常结束，600ms 后强制移除（removeView 失败会被吞掉，幂等）
        try {
            handler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    try {
                        wm.removeView(rv);
                    } catch (Exception ignored) {
                    }
                }
            }, 600);
        } catch (Exception ignored) {
        }
        try {
            rv.animate().alpha(0f).setDuration(240).withEndAction(new Runnable() {
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
