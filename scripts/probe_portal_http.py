# -*- coding: utf-8 -*-
"""probe portal HTTP reachability on the phone: v4/v6/localhost"""
import socket
import urllib.request

for u in ["http://127.0.0.1:8080/version", "http://[::1]:8080/version", "http://localhost:8080/version"]:
    try:
        r = urllib.request.urlopen(u, timeout=5)
        print("HTTP OK  ", u, r.status, r.read()[:60])
    except Exception as e:
        print("HTTP FAIL", u, repr(e))

for fam, addr in ((socket.AF_INET, ("127.0.0.1", 8080)), (socket.AF_INET6, ("::1", 8080))):
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(4)
    try:
        s.connect(addr)
        print("CONN OK  ", addr)
    except Exception as e:
        print("CONN FAIL", addr, repr(e))
    finally:
        s.close()
