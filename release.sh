#!/usr/bin/env bash
# 小工头 · 小版本发布（一键 commit + tag + push）
#
# 用法：
#   ./release.sh "一句话说明这次改了什么"            # 用 manifest 版本打 tag
#   ./release.sh "说明" v1.9.1                      # 手动指定 tag
#   ./release.sh "说明" --no-tag                    # 只提交推送，不打 tag
#
# 规则（对应 2026-10-28 定的流程）：
#   1. 每次动过代码或文档，都要跑一次，保证 GitHub 上永远有当前状态
#   2. tag 名 = v<versionName>，与 entry/AndroidManifest.xml 对齐
#   3. 推送前强制扫描敏感文件，命中即中止（portal token / 设备序列号 / 大二进制）

set -euo pipefail
cd "$(dirname "$0")"

MSG="${1:-}"
TAG_ARG="${2:-}"

if [ -z "$MSG" ]; then
  echo "用法: ./release.sh \"这次改了什么\" [tag] [--no-tag]" >&2
  exit 1
fi

# ---------- 1. 读版本号 ----------
VERSION=$(grep -o 'versionName="[^"]*"' entry/AndroidManifest.xml | head -1 | cut -d'"' -f2)
VCODE=$(grep -o 'versionCode="[^"]*"' entry/AndroidManifest.xml | head -1 | cut -d'"' -f2)
[ -n "$VERSION" ] || { echo "读不到 versionName，检查 entry/AndroidManifest.xml" >&2; exit 1; }
TAG="v${VERSION}"
[ "$TAG_ARG" = "--no-tag" ] && TAG="" || [ -n "$TAG_ARG" ] && TAG="$TAG_ARG"

echo "== 版本 $VERSION (vc$VCODE)  tag=${TAG:-<不打>}"

# ---------- 2. 敏感文件闸门（硬拦） ----------
BLOCKED=$(git status --porcelain | awk '{print $2}' | grep -iE 'secrets?(_tablet)?\.json|\.apk$|\.img$|\.bin$|fpinfo_|full_dex|\.tgz$|node_modules/' || true)
if [ -n "$BLOCKED" ]; then
  echo "!! 检测到不该入库的文件，已中止推送：" >&2
  echo "$BLOCKED" >&2
  echo "   请把它们加进 .gitignore 后重试。" >&2
  exit 2
fi

# ---------- 3. 提交 ----------
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "$MSG"
  echo "== 已提交: $(git log --oneline -1)"
else
  echo "== 工作区干净，跳过提交"
fi

# ---------- 4. 打 tag ----------
if [ -n "$TAG" ]; then
  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "== tag $TAG 已存在，跳过（要重打请先 git tag -d $TAG）"
  else
    git tag -a "$TAG" -m "$MSG"
    echo "== 已打 tag: $TAG"
  fi
fi

# ---------- 5. 推送（自动挑可用代理） ----------
PROXY=""
for p in "http://127.0.0.1:7897" "http://127.0.0.1:7890"; do
  if timeout 6 curl -s -o /dev/null -x "$p" https://api.github.com 2>/dev/null; then PROXY="$p"; break; fi
done

PUSH_ARGS=()
[ -n "$PROXY" ] && PUSH_ARGS=(-c "http.proxy=$PROXY" -c "https.proxy=$PROXY") && echo "== 走代理 $PROXY"

git "${PUSH_ARGS[@]}" push origin HEAD
[ -n "$TAG" ] && git "${PUSH_ARGS[@]}" push origin "$TAG"

echo "== 完成。https://github.com/Exalex/xiaogongtou"
