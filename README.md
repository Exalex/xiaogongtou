# 小工头（Xiaogongtou）· 手机里的安卓自动化 Agent

**说一句话，手机自己动手干活。** 决策、执行、语音输入、后台守护——整条链路全部运行在手机本地，**不需要电脑**。

> 面向 Android（ColorOS/一加真机深度适配）。核心是一个「看 → 想 → 做」闭环：无障碍读取屏幕 → 双脑决策 → 无障碍/root 注入操作 → 直到完成任务。

---

## ✨ 特性

| | 说明 |
|---|---|
| 🧠 **双脑决策** | **Jev**（TypeSafe System One，~1s/步）起步，卡住自动升级 **qwen** 接管；两个引擎共享同一套经验注入 |
| 📱 **纯手机运行** | Agent 跑在手机 Termux（Python 标准库），控制台是手机上的 HTTP 服务，入口是自研 APK |
| 🎈 **系统级入口** | 桌面图标 / 无障碍悬浮球 / **音量下键**（语音速记条）/ 通知栏 |
| 🎙 **语音速记** | 按一下音量下 → 输入条+键盘+**自动唤起输入法语音**；说完再按一下 → 直接执行 |
| 📚 **经验库（外挂 skill）** | 成功任务的轨迹自动入库，同类任务按相似度检索并注入决策 prompt |
| 🐞 **调试模式** | 手机上实时看到每步的 prompt / 回复 / 动作 / 结果（半透明浮窗）；网页端可回看完整链路 |
| 🛡 **自愈守护** | root 守护脚本每 5 分钟自检：控制台 / portal / 无障碍服务掉线自动补回 |

## 🏗 架构

```
┌────────────────────────────  手机（同一台设备）  ───────────────────────────┐
│                                                                             │
│  ┌─ 入口 APK「小工头」──────────┐       ┌─ 控制台（Termux, root）──────────┐  │
│  │  浮球 / 音量键语音条 / 通知   │       │  mini_console.py  :8900         │  │
│  │  无障碍服务 + 结果轮询        │──────▶│  · 任务队列 / 历史 / 收藏        │  │
│  └──────────────────────────────┘  提交  │  · 调试开关 / 链路 trace         │  │
│              ▲                            └───────────┬────────────────────┘  │
│              │ 通知                                   │ 启动子进程             │
│              │                                        ▼                        │
│              │                            ┌─ mini_agent.py（看→想→做循环）──┐ │
│              │                            │ ① 看：portal /state_full（a11y）│ │
│              │                            │ ② 想：Jev ↔ qwen（经验注入）    │ │
│              │                            │ ③ 做：tap/swipe/input/open_app  │ │
│              │                            └───────┬────────────────────────┘ │
│              │                                    │ HTTP :8080（Bearer）      │
│              │                            ┌───────▼────────────────────────┐ │
│              └────────────────────────────│ portal（mobilerun）无障碍桥     │ │
│                                           │ root 注入直点 = 稳定可靠        │ │
│                                           └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🚀 快速开始

> 前置：一台 **root 的 Android 手机**（本项目在 ColorOS/一加上实测）、PC 或直接手机端脚本。

### 1. 手机侧（控制台 + Agent）

```bash
# 依赖：Termux + Python3（本仓库脚本仅用标准库）
# 把 scripts/ 下的文件推到 Termux：
#   mini_agent.py / mini_console.py / start-console.sh / supervisor-loop.sh / run.sh
# 密钥（不进 git）：
cat > ~/bridge/secrets.json <<'EOF'
{
  "portal_token": "<你的 mobilerun portal token>",
  "jev_key": "<你的 TypeSafe Jev API key>"
}
EOF
bash ~/start-console.sh          # 控制台起在 127.0.0.1:8900
```

### 2. 入口 APK（小工头）

```bash
cd entry
echo '{"portal_token": "<你的 portal token>"}' > local_secrets.json   # 构建时注入（不进 git）
python build.py                  # aapt2 → javac → d8 → zipalign → apksigner（无需 gradle）
# 装机（ColorOS 需 root 安装绕开「安装确认页」）：
adb push dist/xiaogongtou-entry.apk /data/local/tmp/
adb shell "su -c 'pm install -r /data/local/tmp/xiaogongtou-entry.apk'"
```

### 3. 使用

- **按一下「音量下」** → 语音速记条（键盘 + 自动唤起输入法语音）→ 说完**再按一下** → 执行
- 或点**悬浮球** → 输入面板；或打开 App 用网页控制台
- 结果：通知栏 + App 内历史大卡（含「🔗 链路」回看）

## 📁 目录结构

```
entry/                     入口 APK 工程（纯 Java + 无 gradle 构建）
  java/com/xiaogongtou/entry/
    EntryA11yService.java  无障碍服务（浮球宿主 / 音量键过滤 / 语音键辅助点击）
    VoiceBar.java          语音速记条（输入条 + 自动唤起输入法语音）
    PanelOverlay.java      悬浮输入面板 / FloatingBall.java 悬浮球
    MainActivity.java      WebView 壳（承载控制台页面）
    Api.java               控制台 & portal HTTP 客户端
    build.py               五步构建脚本
scripts/                   手机端与控制侧脚本
  mini_agent.py            ★ Agent 主循环（Jev/qwen 双引擎 + 经验库 + trace）
  mini_console.py          控制台（HTTP 服务 + 网页 UI + 任务调度）
  supervisor-loop.sh       自愈守护（控制台/portal/a11y）
  其他                    探测/工具脚本
*.md                       项目文档（见下）
```

## 📖 文档

| 文档 | 内容 |
|---|---|
| `项目完整文档.md` | 自包含总文档：架构、机制、坑位、时间线 |
| `PLAN.md` | 一手滚动开发日志（最详尽） |
| `入口固化方案.md` | 入口 APK 的决策与实施记录 |
| `手机入口使用说明.md` | 使用者手册（大白话） |
| `开发笔记.md` | 迭代开发笔记（每轮：问题 → 改动 → 验证） |

## ⚠️ 免责声明

- 本项目通过**无障碍服务 + root 注入**自动化操作手机，仅用于**自己的设备、自己的账号**。
- 自动化操作存在风险（误点、误提交），请勿在涉及支付/隐私的界面上无人值守运行。
- 不同 ROM/输入法差异较大（本项目在 ColorOS + 搜狗输入法上深度验证），其他环境请自行适配。

## 📄 License

MIT
