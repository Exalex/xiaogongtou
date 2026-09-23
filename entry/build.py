# -*- coding: utf-8 -*-
"""入口 APK「小工头」构建脚本（无 gradle 五步法）

aapt2 compile -> aapt2 link -> javac -> d8 -> (zip dex) -> zipalign -> apksigner

用法: python build.py
依赖: .tools/jdk17 + .tools/android-sdk（见 入口固化方案.md）
产物: entry/dist/xiaogongtou-entry.apk

注：中间产物使用唯一 run 目录（不做批量删除——环境 safe-delete 会拦截 >50 文件
的一次性清理；旧 run-* 目录可之后分批手工清理）。
"""
import json
import os
import subprocess
import sys
import time
import zipfile

TOOLS = r"D:\workspace\workbuddySpace\githubResearch\.tools"
JDK = os.path.join(TOOLS, "jdk17")
SDK = os.path.join(TOOLS, "android-sdk")
BT = os.path.join(SDK, "build-tools", "35.0.1")
ANDROID_JAR = os.path.join(SDK, "platforms", "android-35", "android.jar")

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_ROOT = os.path.join(HERE, "build")
RUN = os.path.join(BUILD_ROOT, "run-%d" % int(time.time()))
DIST = os.path.join(HERE, "dist")
APK_NAME = "xiaogongtou-entry.apk"
KS = os.path.join(HERE, "debug.keystore")

MIN_API = "26"


def sh(cmd, env=None):
    print(">>> " + " ".join(('"%s"' % c if " " in str(c) else str(c)) for c in cmd))
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        print("STEP FAILED rc=%d" % r.returncode)
        sys.exit(1)
    return r


def main():
    os.makedirs(RUN, exist_ok=True)
    os.makedirs(DIST, exist_ok=True)

    env = dict(os.environ)
    env["JAVA_HOME"] = JDK
    env["PATH"] = os.path.join(JDK, "bin") + os.pathsep + env.get("PATH", "")

    if not os.path.exists(ANDROID_JAR):
        sys.exit("android.jar 不存在: " + ANDROID_JAR)
    if not os.path.exists(os.path.join(HERE, "AndroidManifest.xml")):
        sys.exit("AndroidManifest.xml 不存在")

    aapt2 = os.path.join(BT, "aapt2.exe")
    javac = os.path.join(JDK, "bin", "javac.exe")
    jar = os.path.join(JDK, "bin", "jar.exe")
    d8 = os.path.join(BT, "d8.bat")
    zipalign = os.path.join(BT, "zipalign.exe")
    apksigner = os.path.join(BT, "apksigner.bat")
    keytool = os.path.join(JDK, "bin", "keytool.exe")

    print("== run dir: %s ==" % RUN)

    print("== 1/7 aapt2 compile ==")
    sh([aapt2, "compile", "--dir", os.path.join(HERE, "res"),
        "-o", os.path.join(RUN, "res.zip")], env=env)

    print("== 2/7 aapt2 link ==")
    sh([aapt2, "link", "-o", os.path.join(RUN, "base.apk"),
        "-I", ANDROID_JAR,
        "--manifest", os.path.join(HERE, "AndroidManifest.xml"),
        "-R", os.path.join(RUN, "res.zip"),
        "--java", os.path.join(RUN, "gen"),
        "--auto-add-overlay"], env=env)

    print("== 2.5/7 generate Secrets.java ==")
    gen_pkg_dir = os.path.join(RUN, "gen", "com", "xiaogongtou", "entry")
    os.makedirs(gen_pkg_dir, exist_ok=True)
    portal_token = ""
    sec_path = os.path.join(HERE, "local_secrets.json")
    if os.path.exists(sec_path):
        try:
            with open(sec_path, encoding="utf-8") as f:
                portal_token = str(json.load(f).get("portal_token", ""))
        except Exception as e:
            print("local_secrets.json 读取失败: %r" % (e,))
    with open(os.path.join(gen_pkg_dir, "Secrets.java"), "w", encoding="utf-8") as f:
        f.write("package com.xiaogongtou.entry;\n")
        f.write("// 由 build.py 依据 entry/local_secrets.json 生成（不进 git）\n")
        f.write("public final class Secrets {\n")
        f.write("    public static final String PORTAL_TOKEN = \"%s\";\n" % portal_token)
        f.write("}\n")
    print("   portal_token: %s" % ("(已配置)" if portal_token else "(未配置 -> 空)"))

    print("== 3/7 javac ==")
    sources = []
    for root, _dirs, files in os.walk(os.path.join(HERE, "java")):
        for f in files:
            if f.endswith(".java"):
                sources.append(os.path.join(root, f))
    for root, _dirs, files in os.walk(os.path.join(RUN, "gen")):
        for f in files:
            if f.endswith(".java"):
                sources.append(os.path.join(root, f))
    if not sources:
        sys.exit("no java sources")
    argfile = os.path.join(RUN, "sources.txt")
    with open(argfile, "w", encoding="utf-8") as f:
        for s in sources:
            # javac 的 @argfile 会吞反斜杠，统一转成正斜杠
            f.write('"%s"\n' % s.replace("\\", "/"))
    os.makedirs(os.path.join(RUN, "classes"), exist_ok=True)
    sh([javac, "-encoding", "UTF-8", "-source", "8", "-target", "8",
        "-bootclasspath", ANDROID_JAR, "-cp", ANDROID_JAR,
        "-d", os.path.join(RUN, "classes"),
        "-nowarn", "-Xlint:-options", "@" + argfile], env=env)

    print("== 4/7 d8 ==")
    sh([jar, "cf", os.path.join(RUN, "classes.jar"),
        "-C", os.path.join(RUN, "classes"), "."], env=env)
    os.makedirs(os.path.join(RUN, "dex"), exist_ok=True)
    sh(["cmd", "/c", d8, "--release", "--lib", ANDROID_JAR, "--min-api", MIN_API,
        "--output", os.path.join(RUN, "dex"),
        os.path.join(RUN, "classes.jar")], env=env)

    print("== 5/7 zip dex into apk ==")
    base_apk = os.path.join(RUN, "base.apk")
    dex = os.path.join(RUN, "dex", "classes.dex")
    if not os.path.exists(dex):
        sys.exit("classes.dex missing")
    with zipfile.ZipFile(base_apk, "a", zipfile.ZIP_STORED) as z:
        z.write(dex, "classes.dex")

    print("== 6/7 zipalign ==")
    sh([zipalign, "-f", "4", base_apk, os.path.join(RUN, "aligned.apk")], env=env)

    print("== 7/7 sign ==")
    if not os.path.exists(KS):
        sh([keytool, "-genkeypair", "-keystore", KS,
            "-alias", "androiddebugkey",
            "-storepass", "android", "-keypass", "android",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-dname", "CN=Android Debug,O=Android,C=US"], env=env)
    out_apk = os.path.join(DIST, APK_NAME)
    if os.path.exists(out_apk):
        os.remove(out_apk)
    sh(["cmd", "/c", apksigner, "sign",
        "--ks", KS, "--ks-pass", "pass:android", "--key-pass", "pass:android",
        "--out", out_apk, os.path.join(RUN, "aligned.apk")], env=env)

    print("== verify ==")
    sh(["cmd", "/c", apksigner, "verify", "--print-certs", out_apk], env=env)

    size = os.path.getsize(out_apk)
    print("")
    print("APK OK: %s (%.1f KB)" % (out_apk, size / 1024.0))


if __name__ == "__main__":
    main()
