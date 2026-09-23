#!/bin/bash
# termux_exec.sh — PC 侧工具：操作手机上的 Termux（mobilerun-ondevice 项目）
# 用法：
#   ./termux_exec.sh push <本地脚本> [手机路径]   # 推送到 /data/local/tmp 并生成 LF 版本
#   ./termux_exec.sh run <手机脚本路径>           # 以 Termux 身份（uid 10353）执行
#   ./termux_exec.sh sh "<简短命令>"              # 以 Termux 身份执行简短命令（勿含单引号）
set -euo pipefail

ADB="D:/workspace/workbuddySpace/githubResearch/.tools/platform-tools/adb.exe"
SERIAL="${TERMUX_SERIAL:-32cfccdf}"

case "${1:-}" in
  push)
    src="$2"
    dst="${3:-/data/local/tmp/$(basename "$src")}"
    "$ADB" -s "$SERIAL" push "$src" "$dst" | tail -1
    "$ADB" -s "$SERIAL" shell "tr -d '\r' < $dst > $dst.lf; chmod 755 $dst.lf"
    echo "LF copy ready: $dst.lf"
    ;;
  run)
    remote="${2:?usage: run <remote-script>}"
    "$ADB" -s "$SERIAL" shell "su 10353 -c 'sh $remote'"
    ;;
  sh)
    cmd="${2:?usage: sh \"<cmd>\"}"
    "$ADB" -s "$SERIAL" shell "su 10353 -c '$cmd'"
    ;;
  *)
    echo "usage: $0 push <src> [dst] | run <remote-script> | sh \"<cmd>\""
    ;;
esac
