#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""shadow_client.py — 影子屏「哑客户端」（P1）

scrcpy-server(4.1, tunnel_forward=true) 会先在本机监听抽象 socket `scrcpy_<scid>`，
按顺序 accept 各条流（video → control），然后才创建虚拟屏（"影子屏"）。
本脚本扮演那个客户端：连两次 + 持续把数据读丢，从而让影子屏被创建并长期保持。

用法: python3 shadow_client.py [scid]
退出: 两条连接都断开（= 服务端没了）→ 进程退出，交给管家/supervisor 重启。
"""
import os
import socket
import sys
import threading
import time

SCID = sys.argv[1] if len(sys.argv) > 1 else "05ad0001"
NAME = "\0scrcpy_" + SCID

_alive = 2
_lock = threading.Lock()


def drain(s, tag):
    global _alive
    n = 0
    try:
        while True:
            b = s.recv(262144)
            if not b:
                break
            n += len(b)
    except Exception:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass
        with _lock:
            _alive -= 1
        print("shadow_client: %s closed after %d bytes" % (tag, n), flush=True)


def connect_retry(timeout=25.0):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(NAME)
            return s
        except Exception as e:
            last = e
            try:
                s.close()
            except Exception:
                pass
            time.sleep(0.4)
    raise SystemExit("shadow_client: connect timeout: %r" % (last,))


def main():
    print("shadow_client: connecting %r ..." % NAME, flush=True)
    v = connect_retry()          # 1) video（服务端先 accept 这条）
    print("shadow_client: video connected", flush=True)
    threading.Thread(target=drain, args=(v, "video"), daemon=True).start()
    time.sleep(0.3)
    c = connect_retry()          # 2) control
    print("shadow_client: control connected", flush=True)
    threading.Thread(target=drain, args=(c, "control"), daemon=True).start()
    while True:
        time.sleep(5)
        if _alive <= 0:
            print("shadow_client: all closed, exit", flush=True)
            os._exit(0)


if __name__ == "__main__":
    main()
