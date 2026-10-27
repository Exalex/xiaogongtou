#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_asr_server.py — 局域网语音识别服务（SenseVoice 中文识别，给手机"语音速记"用）

背景：手机端无系统 ASR、搜狗语音必须弹键盘 → "去键盘"的关键是把识别搬到 PC。
手机录 WAV（16k/mono/PCM16）→ POST 到本服务的 /asr → 返回识别文本。

用法（PC）：
  python _asr_server.py [--port 8766]

接口：
  GET  /ping   → {"ok": true, "model": "sensevoice"}   （手机探活用）
  POST /asr    → body = WAV 原始字节 → {"text": "识别结果"} / {"error": "..."}

依赖：sherpa-onnx + numpy（default venv 已装）；模型见 MODEL_DIR。
"""
import argparse
import io
import json
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import sherpa_onnx

MODEL_DIR = ("D:/workspace/workbuddySpace/githubResearch/.tools/asr/"
             "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
_rec = None
_lock = threading.Lock()


def get_recognizer():
    global _rec
    if _rec is None:
        _rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=MODEL_DIR + "/model.int8.onnx",
            tokens=MODEL_DIR + "/tokens.txt",
            use_itn=True,
            language="zh",
            num_threads=4,
            debug=False,
        )
    return _rec


def transcribe(wav_bytes: bytes) -> str:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        ch = w.getnchannels()
        sr = w.getframerate()
        sw = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if ch != 1 or sw != 2:
        raise ValueError("expect mono/16bit, got ch=%d sw=%d" % (ch, sw))
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    rec = get_recognizer()
    with _lock:
        stream = rec.create_stream()
        stream.accept_waveform(sample_rate=sr, waveform=samples)
        rec.decode_stream(stream)
        return (stream.result.text or "").strip()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[asr] " + (fmt % args) + "\n")

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/ping":
            self._json({"ok": True, "model": "sensevoice"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/asr":
            self._json({"error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(n)
            # 调试留档：保存每次上传的音频（排查"录没录到声音"）
            # 流式请求（X-Stream:1，边说边识别用）跳过落盘，避免每 1.3s 堆一个文件
            if self.headers.get("X-Stream", "") != "1":
                try:
                    import os
                    import time as _t
                    d = "D:/workspace/workbuddySpace/githubResearch/.tools/asr/uploads"
                    os.makedirs(d, exist_ok=True)
                    with open(d + "/u_%s.wav" % _t.strftime("%H%M%S"), "wb") as f:
                        f.write(body)
                except Exception:
                    pass
            self._json({"text": transcribe(body)})
        except Exception as e:
            self._json({"error": repr(e)}, 500)


class SingleInstanceServer(ThreadingHTTPServer):
    """Windows 下 SO_REUSEADDR 会让第二个实例静默抢占同一端口 → 两个 socket 分流水，
    旧进程不干活时表现为"能连上但空回复"（2026-10-19 实测踩坑：8766 双进程）。
    这里关掉端口复用，让第二个实例直接 bind 失败退出。"""
    allow_reuse_address = False
    allow_reuse_port = False
    daemon_threads = True


def _already_running(port):
    """服务已在跑就干净退出（计划任务 + 开机自启两路同时拉起时避免打架）。"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/ping" % port, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    if _already_running(a.port):
        print("[asr] already running on :%d -> exit" % a.port, flush=True)
        return
    print("[asr] loading model ...", flush=True)
    get_recognizer()
    print("[asr] model ready. serving on 0.0.0.0:%d" % a.port, flush=True)
    try:
        srv = SingleInstanceServer(("0.0.0.0", a.port), H)
    except OSError as e:
        print("[asr] bind failed (%r) -> another instance holds the port" % (e,), flush=True)
        return
    srv.serve_forever()


if __name__ == "__main__":
    main()
