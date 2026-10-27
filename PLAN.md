# 手机自包含移植计划 — mobilerun on-device

> 目标：**除 LLM API 外，整套系统跑在手机里**——手机自己当「工头」（决策循环）+「手和眼睛」（portal）；智力调用外部 API（局域网 `192.168.3.75:8888` 或任意云端 OpenAI 兼容 API）。
> 立项：2026-09-21（用户指令：「创建一个计划 怎么移植到安卓手机 单独文件夹里创建 开始移植 就是整套除了api 其他都在手机上」）

## 一、现状 vs 目标

**现状（三体分离）**
- 手机：portal app（= 手和眼睛）
- PC（192.168.3.179）：mobilerun agent（= 工头）+ 控制台
- 服务器（192.168.3.75）：LLM（= 智力）

**目标（单体 + 外部 API）**
- 手机：portal（手）＋ Termux 里的 mobilerun agent（工头）
- 外部：只剩 LLM API

```
[手机]
 ├─ portal（已有）         ← 手和眼睛
 └─ Termux（Linux 沙箱）    ← 要新建的部分
     ├─ Python + mobilerun  ← 工头
     ├─ 与 portal 通信：HTTP → 127.0.0.1:8080（不需要 adb！）
     └─ 与 LLM 通信：网络 → 192.168.3.75:8888（或云端 API）
```

## 二、已探明的关键事实（2026-09-21 实测 / 源码级）

1. **portal 自带 HTTP 控制服务**（`MobilerunSocketServer`，端口 8080，绑定全接口）。
   - 端点：`/ping` `/version` `/state_full` `/screenshot` `/keyboard/input` 等；鉴权 `Authorization: Bearer <token>`（`/ping` `/version` 公开）。
   - **手机本机程序（Termux）可直接访问 `http://127.0.0.1:8080`——不需要 adb。这是整个移植的基石。**
2. **token**：固定 UUID，可在 portal 界面「Connection Details」直接读取（带复制按钮）；root 可读 `shared_prefs/mobilerun_secrets.xml` 兜底。
3. **官方有无 ADB 驱动**：`mobilerun_core_local.driver.android.http.AndroidPortalHttpDriver`
   - 构造：`AndroidPortalHttpDriver(url, token)`，url = `http://127.0.0.1:8080`
   - 能力：tap / swipe / input_text / start_app / stop_app / screenshot / get_ui_tree / get_apps / list_packages（仅 install/uninstall APK 需要 adb，本场景不需要）
4. **MobileAgent 支持 driver 注入**：构造签名含 `driver: DeviceDriver | None = None`（droid_agent.py）。
5. 手机已 root（Magisk）：`su -c` 可读 content provider / shared_prefs（token、socket server 开关的兜底通道）。
6. LLM 端点：局域网 `http://192.168.3.75:8888/v1`（key=123）；手机同 WiFi 直连可用。
7. 手机端 portal 的 socket server 状态：当前 Running（曾为 Stopped，需注意重启后是否恢复——P6 自检项）。

## 三、技术路线

**主选：mobilerun 官方包 + AndroidPortalHttpDriver 注入**（保持"整套原版"）
```python
from mobilerun_core_local import AndroidPortalHttpDriver
driver = AndroidPortalHttpDriver("http://127.0.0.1:8080", token="<portal UUID>")
# → 注入 MobileAgent 或走 CLI（CLI 若无现成路径，先用 Python API）
```

**备选 A（降级）**：只装 `mobilerun_core_local` + `httpx`，自写 ~100 行迷你循环（看→问→做），直接调 portal HTTP + LLM API。
**备选 B（再降级）**：纯 `httpx` 手写全部（绕开 mobilerun）——效果等价，维护成本高，仅保底。

**触发降级的条件**：P3 依赖安装连续两次失败（编译卡死/包缺失无法解决）。

## 四、分阶段计划（每阶段有验证标准）

| 阶段 | 内容 | 验证标准 |
|---|---|---|
| **P0** | PC 侧准备：下载 Termux APK（v0.118.3 arm64-v8a）+ 校验；写部署脚本 | APK sha256 校验通过 |
| **P1** | adb 安装 Termux + 首次启动初始化（home 目录生成） | `com.termux` 出现在包列表；Termux 可打开 |
| **P2** | 打通「PC → Termux」无人值守命令通道（RUN_COMMAND intent；root 写 `termux.properties` 开 allow-external-apps） | 从 PC 能触发 Termux 执行 `echo ok` 并读到输出 |
| **P3** | Termux 装 Python + pip 依赖（mobilerun 全套） | `python -c "import mobilerun, mobilerun_core_local"` 成功 |
| **P4** | 部署 on-device 入口脚本（driver 注入版 + LLM 配置） | 脚本连通 portal（/ping→pong）并拿到一次 /state_full |
| **P5** | 端到端：手机里跑第一个任务（例：打开设置读电量） | agent 循环完成，任务结果落盘 |
| **P6** | 常驻与保活（termux-wake-lock、后台执行、portal server 自检、可选开机自启） | 锁屏 5 分钟后仍可跑任务 |

## 五、风险与对策

| # | 风险 | 对策 |
|---|---|---|
| R1 | Termux 里 pip 装 mobilerun 失败（pydantic-core 等需编译、llama-index 全家桶太重） | ① 先装 `pkg install python python-pip rust`；② 失败→备选 A 迷你循环；③ 保底备选 B |
| R2 | driver 注入路径有隐藏依赖（状态 provider / RecordingDriver wrap 等假设） | 读源码逐个解决；必要时小 patch |
| R3 | portal socket server 掉线（重启后不回） | 自检脚本：HTTP 不通时 `su -c content insert toggle_socket_server`；跑前检查 |
| R4 | token 轮换（server 重启可能生成新 token） | 脚本自动从 shared_prefs 读（root）；或检测 401 时刷新 |
| R5 | Android 杀 Termux 后台 | `termux-wake-lock`；长任务走前台；必要时用 `sv`/`nohup` |
| R6 | 网络：出门后 192.168.3.75 不可达 | 配置里可切换云端 API（离线时任务照常等网） |

## 六、回退方案

- 若 P3 失败两次：切备选 A（mini 循环），移植继续但**明确告知用户"部分非原版"**。
- 若 P5 仍不可行：保留现状（PC 编排）+ 沉淀所有探明事实，报告"卡点 + 下一步建议"。
- **日常生产链路（PC 控制台）不做任何破坏性改动**——移植全程在 Termux 侧进行，互不影响。

## 七、目录结构

```
mobilerun-ondevice/
├─ PLAN.md          ← 本文件（计划 + 进度）
├─ apk/             ← Termux APK（下载产物）
├─ scripts/         ← 部署脚本 / on-device 入口脚本
└─ logs/            ← 安装与运行日志
```

## 八、进度记录（滚动更新）

- [x] 2026-09-21 14:55 立项；实测确认 portal HTTP 直连 / AndroidPortalHttpDriver 存在 / driver 可注入
- [x] P0 下载 Termux APK（v0.118.3 arm64-v8a，sha256 校验通过）
- [x] P1 安装 Termux：adb install 被 ColorOS「安装确认页」拦（需点「继续安装」）→ 已过；bootstrap 解压完成
- [x] P2 命令通道（2026-09-21 15:15 定稿）：
  - ❌ RUN_COMMAND 直发（adb shell 身份）被系统拦：`requires com.termux.permission.RUN_COMMAND`（shell 拿不到该权限）
  - ✅ **正解 = 「Termux 身份自调用」**：`adb shell "su 10353 -c 'sh /data/local/tmp/fire.lf.sh'"`，fire.lf.sh 内 `am startservice -n com.termux/com.termux.app.RunCommandService ...` → 同 uid 自调用放行 → 命令由 Termux app 执行（沙箱内，网络/DNS 正常，文件权限天然正确）
  - ⚠️ 直连 `su 10353` 跑命令（不经 RUN_COMMAND）**DNS 会挂**（`unknown host`——su 进程无 netd 网络上下文）；因此一切需要网络的命令都必须走 RUN_COMMAND
  - 通道范式：`push job → tr -d '\r' → job.lf.sh` + `su 10353 -c 'sh fire.lf.sh'`（fire 只认 `/data/local/tmp/job.lf.sh`）；结果回传 = job 自写 `$HOME/bridge/out/*.out`，PC 用 root 读
- [x] P3 Termux 环境就绪（Python 3.14.6 + pip 26.2.1，apt 清华源）；**官方 mobilerun 包不兼容**：pip dry-run 确认所有版本 `Requires-Python >=3.11,<3.14` → 触发备选 A
- ⏩ 决策（15:25）：先落地**备选 A（mini agent，纯标准库 + portal HTTP）**；"原版 mobilerun on-device"列为后续候选（proot-distro Ubuntu + Python 3.12）
- [x] P4 入口脚本：**mini_agent.py v2 双引擎已部署**（`AGENT_ENGINE=qwen|jev`；纯标准库；portal HTTP 直连）
- [x] **Jev 引擎对比实测（2026-09-21 16:15，同任务「打开设置读电量」/同起点桌面）**：**Jev 版 7 秒**（每步决策 1.1-1.6s；答案直接从屏幕元素提取「34%」，全程不依赖 qwen）vs **qwen 版 16 秒（热态）/ 130 秒（冷启动）**——Jev 绕开 vLLM 冷启动抖动（60-124s），快 2.3-18× 且方差小。用法：TypeSafe System One，两题打包（下一步动作 choice + 答案元素 choice）。
- [x] **测试口径（"这个结果怎么测的"→2026-09-21 晚补记）**：同任务（打开设置读电量）/同起点（桌面主页、真「设置」图标可见）；两引擎各跑一遍（唯一差异 = job 脚本的 `AGENT_ENGINE` 环境变量）；**计时 = 手机端自己打的表**（job 写 `TS_JOB_START/TS_END` + mini_agent 每步打印 `llm=X.Xs`）；答案对照手机系统真值 `dumpsys battery`。PC 只在三处出现：开跑前 push / 按开始 fire / 跑完读日志——**不在工作循环里**。
- [x] **断线实验（证明"循环零依赖 PC"）**：fire 后立刻 `adb kill-server` 切断 PC↔手机通道 30 秒——
  - 实验 A（17:22，`logs/agent_nopc.out`）：任务照常跑完（第 2、3 步+收尾全程在断线期），读数 38% = 真值；
  - 实验 B（17:34，"全程断线"版，`logs/agent_blackout3.out`）：发射与掐线同秒，**任务 6 秒 3 步完整跑完、全部落在断线窗口内**，读数 39% = 真值。
- [x] **系统冻结机制定位（断线实验副产品，重要）**：OplusHansManager 状态机——**有网络流量则拒绝冻结**（logcat `cannot transition from M to F, importance=traffic`）；**静默 ~5 秒即冻结**（`F enter(), M stay=5`）；冻结后拉到前台即恢复。推论：正常任务被自身 API 流量护住（实测 17:34 全程被 traffic 顶住、任务结束后 ~35s 流量过期才被冻）；**静默间隙（纯 sleep 等）必挂**（延迟启动实测 2 次印证）；**wake-lock 持锁也不能免冻**（冻结名单含持锁进程）→ P6 加固：延迟启动/间隙用 keep-alive 流量或前台化。
- [x] **桌面伪装 "Settings" 陷阱（插曲）**：root 隐藏用的管理应用（`rx.ocsakp.mfz`，显示名 Settings）在**桌面第 2 页有图标**（此前"桌面无图标"的记录更正）；小工头任务「打开设置」曾被它骗、连点 12 步失败（`logs/agent_blackout3a_fake_settings.out`）→ 规避：**任务起点须留在主页**（真「设置」可见）+ 待办：是否收起该图标 / 给 agent 加同名防呆。
- [x] P5 端到端首任务成功（15:32:58）：**「打开设置 → 滑找"电池" → 点击 → 读出 31% 充电中」3 步 16 秒，全程手机自主**；读数与 `dumpsys battery`（level=31 / charging）完全一致
- [x] P6 保活（2026-09-21 晚**终局：root 常驻根治**——见下「root 常驻根治」节；防冻三件套降级为辅助）

## 手机本机控制台（"入口"）—— 2026-09-21 落地

**目标**：手机上自然语言入口，全程脱离电脑。**默认 Jev，卡住自动切 qwen，可手动选**。

**组件**（全部在手机 Termux `$HOME`，纯标准库、零第三方依赖）：
- `mini_agent.py` v3：`--engine auto|jev|qwen` 三模式。auto = Jev 起步；「连续无进展分」（执行失败/重复动作/动作循环/屏幕卡死/低置信度，有进展回血）≥3 → 自动切 qwen 接管（含 history 提示注入）。判定逻辑单测 `_test_progress.py`（PC 离线，6/6 通过）。
- `mini_console.py`（**v2，2026-09-23**）：本机 Web 控制台（`127.0.0.1:8900`）。App 式界面 = 底部输入条 + 模式分段 + ⭐常用（收藏，点一下就跑）+ 🕐历史记录 + 结果大卡；API `/api/run|status|stop|history|favorites`；心跳已改为 30s LLM 探测（root 常驻后原"防冻心跳"无必要）。
- `start-console.sh`：一键启动/停止/自检；`~/.bashrc` 已加幂等自启（打开 Termux 自动拉起控制台）。
- `job_deploy_console.sh`：fire 通道一键部署+重启；`console_post.py`：本机脚本化入口（断线实验用）。

**实测（2026-09-21 18:31-18:49）**：
- ① POST 直跑：auto 模式读电量 **10s 成功**（jev 4 步，answer 46%）。
- ② **浏览器真实用户流**：手机 Edge 打开控制台 → 点「读电量」→ 点「开始」→ 从浏览器起跑（更难起点）→ jev 卡在页面循环 5 步 → **自动升级 qwen** → open_app→设置→电池→**「46%，充电中」**，全程 25s（jev=5/qwen=3）——「持续出错再调千问」完整演示 ✓。
- ③ 断线实验（控制台版）：手机本机 POST → 掐 adb 45s：**12 步 jev 全在断线期**；中途遇 qwen 冷启动静默被冻（见下），解冻后自动续跑完成（161s，46%）。
- 截图：`logs/entry_page.png`、`entry_result.png`、`entry_final.png`。

**冻结问题（未根治，重要）**：
- 实测**否定**全部轻量对策：LAN 请求 1/s、公网请求 1/s、wake/unknown 按键注入、`appops RUN_IN_BACKGROUND/RUN_ANY_IN_BACKGROUND allow`、wake-lock、standby bucket —— 后台 Termux 静置 **5-60 秒内必被冻**。
- 有效豁免：**前台**（Termux 在最前 → HANS 直接 "M exit" 不管它）；任务活跃期一般安全（~40-55s 活动宽限），但**长静默（qwen 冷启动 ~100s）仍会中途被冻**（183257 实证）。
- 兜底：① 打开一次 Termux 即解冻（.bashrc 顺带自愈重启）；② 页面内置"打开一次 Termux"提示；③ 重启手机后 `bash ~/start-console.sh`。
- 下一步修复方向：a) 系统设置给 Termux「允许完全后台行为」+「允许自启动」（OPPO 口径：自启动/关联启动任一开 → 应用速冻失效，待验证对 HANS 是否有效）；b) 任务管理器锁定卡片；c) 深挖"前台/手势切换 → 冻结豁免"因果（唯一未证伪的保护因子）；d) 或把 agent 挪回常开服务器。

## root 常驻根治（2026-09-21 晚终局）✅

**发现**：OplusHansManager 冻结只覆盖**应用进程**（uid ≥ 10000）；**uid 0（root）完全不在冻结管辖内**——实锤：root 进程静置 160s，`freeze uid: 0` 一条都没有。

**方案**：控制台（含其 spawn 的 agent 子进程）改以 **root 身份常驻**：
- 运行器 `/data/adb/mobilerun-console/run.sh`：设置 Termux env（TERMUX_PREFIX/HOME/PATH/LD_LIBRARY_PATH），exec `termux-python3 mini_console.py`；
- 守护 `/data/adb/mobilerun-console/supervisor-loop.sh`：开机后每 60s 巡检 `pgrep -U 0 -f mini_console.py`，掉线即拉起（setsid 后台）；
- 开机自启 `/data/adb/service.d/console-autostart.sh`（Magisk；秒退 fork 守护，不阻塞启动）；
- `~/.bashrc` 改为"控制台 HTTP 不通才兜底拉起 Termux 版"（防抢 8900 端口）。

**实测**：root 版静置 160s 在线（`do_sys_poll`、HTTP 200）；kill 后 **75s 内自动复活**（`console_supervisor.log` 记 "console down -> starting as root"）；手机浏览器打开即渲染；端到端任务（auto 模式读电量）30s 完成、Jev→qwen 自动升级链路正常（截图 `logs/root_console_browser.png`、`root_console_live.png`）。

**否定实验（留档）**：① `setprop sys.hans.enable false` 停 hans **不能**免冻（决策在 system_server 的 OplusHansManager，继续 freeze）；② athena.db `app_frozen/no_frozen` 已加 `com.termux` 但**未生效**（未重启 athena，留观察）；③ 冻结状态机 = R→M(5s)→F，目前仅见 `importance=accessibility` 豁免（portal 因无障碍免冻）。

## 控制台 v2（App 式界面 + 收藏 + 历史）—— 2026-09-23 ✅

**背景**：用户反馈 v1 界面"太网页版"；要求手机 App 式输入框、运行记录、收藏常用、更易用。

**v2 内容**（`mini_console.py` 重写后部署于手机 `$HOME/mini_console.py`，root 常驻运行）：
- **UI**：顶栏（"大脑在线"状态）；⭐常用（收藏 chips，**点一下即跑、长按删除**）；🏠当前任务（运行中=步骤+实时日志；完成=结果大卡 +「↻再跑一次」「☆收藏」）；🕐历史记录（时间/状态徽标/结果摘要，**点任务填入输入框**、☆收藏、↻重跑）；**底部固定输入条**（自动增高、Enter 发送、中文输入法兼容）+ 模式分段（智能/极速/深度）。
- **后端新增**：`GET/POST /api/favorites`、`POST /api/favorites/del`（JSON 持久化 `~/bridge/favorites.json`，同任务去重置顶，上限 20）；历史列表自动清理"夭折的 running"（out 超 3 分钟无更新 → 标为"中断"）；移除旧 WAN 心跳（改 30s LLM 探测，省流量）。

**实测（2026-09-23 14:35–14:50，真机）**：
- 页面渲染（uiautomator dump 核对）：顶栏 / 常用 / 当前任务 / 历史 / 输入条元素齐全；收藏 API 往返（add → dedup 置顶 → del）全通过。
- **端到端**：从新 UI 发起任务（auto）→ Jev 4 步 → 自动升级 qwen 3 步 → **21.6s 完成「22%，充电中」**；结果卡（含 `jev=4 qwen=3` 引擎统计）、历史自动新增记录，全部正常。
- 截图：`logs/ui_v2_home.png`（首页）、`logs/ui_v2_result.png`（结果页）。

**插曲：portal 掉线修复（新坑位）**：任务报 `portal unreachable`；根因 = portal 无障碍服务 **Crashed**（`dumpsys accessibility` 可见）、8080 未监听。**修复三部曲**：① `settings put` 清空 → 重设 `enabled_accessibility_services` + `accessibility_enabled 1`（清掉 crash 记录）；② `kill -9` portal 进程（系统重绑服务 → Bound services 出现）；③ `content insert toggle_socket_server enabled:true`（8080 恢复监听；loopback 探测：`/ping` 返 401=鉴权正常、连接 OK）。
**portal 守护已上线（2026-09-23 晚）**：`supervisor-loop.sh` 升级 v2 —— 每 5 分钟自检 portal（进程 + 8080 监听），异常时自动执行修复三部曲（清空重设 a11y → 必要时 monkey 拉起 → toggle socket server；全程 root 身份，实测 root 跑 `content insert` rc=0）。当晚 portal 第二次掉线（a11y 启用列表整个被清空）按此流程修复，并已接入守护。

**待办**：a) 下次重启手机验证 service.d 自动拉起（今天用同一脚本手动启动验证过逻辑）；b) 任务起点在控制台页面时 Jev 会被页面 chips 文字误导（点了"读电量"按钮）——可在 agent 起跑前自动 HOME 一次；c) `mini_console` 的 keep-alive 心跳已无必要（root 不再被冻），可清理。

**LLM 延迟基线（2026-09-21 实测，`192.168.3.75:8888` / qwen3.8-flash-next）**
- 思考模式（默认）：响应带独立 `reasoning` 字段；简单请求首次 21-60s、预热后 ~1.8s
- `chat_template_kwargs:{"enable_thinking":false}`：reasoning_tokens=0，稳定 **~1.3-2s/次**（1982 tokens 长 prompt 实测 1.9s）→ mini agent 默认用它（`LLM_THINK=1` 可开回）
- 注意：切换 think/no-think 后**首次调用**会冷启动变慢（~60s），之后稳定

**备注**
- `~/.termux/termux.properties` 已被写入 `allow-external-apps=true`（单行；原版注释模板被覆盖，无功能影响）。
- **防冻诊断法**：任务卡死时 `su -c 'cat /proc/<pid>/wchan'`；若为 `do_freezer_trap` 即 ColorOS 后台冻结（非死锁）→ 防冻三件套：`svc power stayon true` + `termux-wake-lock` + `dumpsys deviceidle whitelist +com.termux`。
- `/data/data/com.termux/files/usr/etc/apt/sources.list` 已改清华源（`mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main`）。
- Termux uid = 10353；手机 root（Magisk）供通道的"发令"环节使用。

## 调试模式 + 经验库（"Jev 引入 skill"）—— 2026-09-24 凌晨 ✅

**背景**：用户提两个需求：① 调试模式（设置里可开，半透明看执行步骤 / prompt / 回复 / 链路）；② Jev 能否引入"skill/记忆"（自动记录弯路，下次少走）。

**实现**：
- `mini_agent.py` v4：
  - **每任务 trace**：`~/bridge/runs/<rid>.trace.jsonl`（Tracer 类；prompt / reply / action / result / done 五类记录，含 engine、置信度、耗时）；
  - **经验库**：`~/bridge/skills/examples.json` —— 任务成功后自动存轨迹（按任务文本去重置顶，上限 50）；新任务开始时按 **2-gram Jaccard 相似度**检索相似历史，注入 prompt（Jev：注入 target instructions「参考经验」段；qwen：注入 user 消息段）。
- `mini_console.py` v3：新增 `GET/POST /api/debug`（开关，持久化 `~/bridge/debug.json`）与 `GET /api/trace?rid=&from=`（增量链路）；前端加 🐞 开关按钮 + 「🔗 链路」查看浮层（运行卡/结果卡均有入口）；启动 agent 时注入 `TRACE_PATH` 环境变量。
- 入口 APK v2（新增 `DebugOverlay.java`）：**半透明调试浮窗**（约 72% 黑底、等宽小字、自动滚动到底）——
  `FLAG_NOT_TOUCHABLE`（不拦触摸）+ `IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS`（不进无障碍树，不干扰 agent 的"看/点"）；
  显示由调试开关控制（Poller 每轮同步）；**长按浮球**就地切换调试模式。

**实测（2026-09-24 00:51–00:56）**：
- 首跑「回到桌面」（jev 2 步）：trace 落盘 ✓、调试浮窗实时显示链路 ✓、经验自动保存 ✓；
- **第二次同任务：trace 首条 prompt 含 `[已注入经验 1 条]`，Jev 首步置信度 0.38 → 0.85**（初步观察，长期效果待积累验证）；
- 网页端：🐞 点击切换 ✓、「🔗 链路」浮层显示完整链路 ✓；长按浮球切换开关 ✓（900ms 长按实测）。
- 截图：`logs/debugoverlay_done.png`（半透明调试窗）、`logs/console_ui_trace.png`（网页链路浮层）。

**结论（回答"Jev 能不能引入 skill"）**：合理且是正路——Jev 本身无状态（每次调用独立、不记忆），
所以"经验"必须由本地系统外挂：**执行时自动记录轨迹 → 成功后入库 → 下次检索注入 prompt**。
当前是"范例检索"版（MVP）；下一步可用 qwen 把多次同类轨迹**归纳成 App 经验卡**（类似官方 App Card）。

## 音量键快捷键 + 未来感面板 UI —— 2026-09-24 凌晨（迭代三）✅

**需求**：① 快捷键唤醒：默认「音量下按一下弹出面板，再按一下执行」，可关闭；② 面板要有酷炫动画、未来感 AI 对话框设计。

**实现**：
- **音量键快捷键**（无障碍按键过滤）：`accessibility_service_config.xml` 加 `canRequestFilterKeyEvents="true"` + `flagRequestFilterKeyEvents`；
  `onKeyEvent` 三态逻辑：短按（<650ms）→ 面板未开则唤起 / 已开则提交；**按住 480ms 判定长按 → 服务自己模拟连续降音量**（见坑位）；
  开关持久化在控制台 `~/bridge/hotkey.json`（网页顶栏 ⌨ 按钮切换，App 每轮轮询同步；默认开）。
- **未来感 UI**：面板重设计为深色玻璃卡片（`#F20B1512`）+ 霓虹绿发光描边 + 脉冲状态点 + 小标签（"VOL▾ 唤起 · 再按执行"）；
  动画 = 入场（整体淡入 + 卡片上浮放大 260ms）+ 光晕呼吸（alpha 0.35↔1.0，1.5s 循环）+ 关闭淡出 150ms。

**关键坑（新）**：
1. **`adb shell input keyevent 25` 注入的按键不经过无障碍按键过滤**（onKeyEvent 收不到）→ 测试必须用 **`sendevent` 模拟物理按键**：
   `sendevent /dev/input/event3 1 114 1; sendevent … 0 0 0; sendevent … 1 114 0`（event3 = gpio-keys = KEY_VOLUMEDOWN；音量上在 event0）。
2. **DOWN 被无障碍拦截后，系统不再为该键生成 repeat** → 长按不会自动调音量。
   → 对策：服务在 480ms 后判定长按，每 200ms `AudioManager.adjustStreamVolume(STREAM_MUSIC, ADJUST_LOWER, FLAG_SHOW_UI)`。
3. **一加 9 / ColorOS 音量分组**：`settings system volume_music`（15）≠ 当前生效的 `volume_music_speaker`（0）；
   App 的 `AudioManager.getStreamVolume` 读到的是"当前路由组"——调试音量时以它为准。
4. `adjustStreamVolume` 返回 **void**（不是 int）；`MODIFY_AUDIO_SETTINGS` 是 normal 权限（装包即得）。

**实测（01:0x–01:20）**：
- 按一下音量下 → 面板弹出（截图 `logs/hotkey_panel_v2.png`：深色玻璃 + 发光描边 + 键盘自动弹出）✓；
  输入 "home" → 再按 → 任务提交并完成（`result: 点击底部导航栏最左侧的"首页"按钮`）✓；
- 长按 1.2s → 音量 3→0（每 200ms 一格、带系统音量条）✓；长按不触发面板 ✓；
- 网页顶栏 ⌨ 开关（默认开，`logs/console_ui_hotkey.png`）✓；关闭后按键完全放行。

## 执行链路改善（治"重复瞎试"）+ 面板去呼吸 —— 2026-09-24 凌晨（迭代四）✅

**背景**：用户实测「查一下今天天气怎么样？」失败——**25 步用尽，其中 qwen 连续 18 次 `open_app(com.miui.weather)` 全部失败**（"包名幻觉"：模型记住的是小米包名，本机一加的天气是 `com.coloros.weather2`）；且 Jev 阶段（7 步）只能在当前 App 里瞎点——**Jev 根本没有"打开应用"这个选项**。

**四剂药（全部落地并实测）**：
1. **包名矫正**：启动时从 portal `/packages` 拉已安装应用列表（本机 81 个）；`open_app` 落地前解析（精确 → 关键词模糊 → 明确不存在则直接判失败，不再徒劳往返）。
2. **Jev 增加"打开应用"选项**：从任务文本匹配相关 App（label 子串 + 同 label 取最短包名），作为 `open_app_N` 选项注入；qwen 的 prompt 同步注入"本机可用应用（真实包名），不要臆造"。
3. **重复失败动作硬阻断**：同一动作签名连续失败 ≥2 次 → **直接拒绝执行**，并回一条明确反馈（"换一种完全不同的做法"+ 本机相关应用提示）。此前只有 Jev 阶段有软升级机制，qwen 阶段是无限重试。
4. **失败原因回传**：history 从"执行(失败)"升级为"失败：<具体原因>"（如"本机未找到应用「com.miui.weather」（已核对全部已安装应用）"）。

**实测对比（同一任务「查一下今天天气怎么样？」，起点都在微博）**：

| | 改进前 0924-012129 | 改进后 0924-012758 |
|---|---|---|
| 结果 | ✗ 失败（步数用尽） | ✓ **成功：22℃,多云,22~29℃** |
| 步数 | 25（用尽） | **8** |
| 引擎 | jev=7 + qwen=18（死循环） | **jev=8、qwen=0** |
| 首步决策 | 微博里瞎点（conf 0.48） | **第 1 步 open_app(com.coloros.weather2)（conf 0.99）** |

- 调试浮窗可见 Jev 选择 `open_app_0`（置信度 0.96）——新选项被实际采纳；trace 全程可复盘。
- 同批 UI 调整：按要求**移除面板"呼吸灯"循环动画**（保留入场动画），面板视觉不变、不再持续闪动（截图 `logs/panel_no_breath.png`）。

---

## 9-24 凌晨（续）· 架构分析 v2：六环节注入盘点 + 「四本账」设计 【待拍板】

背景：三案复盘（查天气 V1 25 步失败 / 微博热搜 25 步失败（0924-002758）/ 「home」假完成（0924-011141））后，用户要求回到架构层面：**每个环节注入了什么（技能/成功经验/失败经验）、该怎么改**。上轮四个补丁（App 户口本、open_app 选项、连败阻断、失败原因回传）定性为"给 ③④ 打的应急补丁，方向对但不成体系"。

**现状盘点（六环节）**
- ① 任务进入：仅"任务文本 + App 名匹配"；缺"任务翻译"（「home」案翻车点）
- ② 感知：每步 a11y 读取；缺"屏幕身份"（哪个 App 哪页）与"变化结论回传"（微博案 qwen 连点 5 次还以为成功）
- ③ 决策：Jev=元素菜单+open_app+范例×2；qwen=SYSTEM+history+经验块；缺 App 经验卡、失败教训（负样本）
- ④ 执行：包名矫正 + 连败 2 次阻断；缺"效果校验"（点了没变化不算失败）
- ⑤ 收尾：qwen 总结；缺"done 验证"与总结 prompt 修正（「home」案答非所问也收工）
- ⑥ 反思：**不存在** ← 经验的唯一产地缺失（失败不入库；成功只存裸动作步，且混着一次性弹窗/授权步骤）

**目标设计：四本账 + 三段注入 + 两级失败经验**
- 账本（`~/bridge/skills/`）：`device.json`（设备档案）/ `apps.json`（App 经验卡）/ `examples.json`（成功范例，清洗版）/ `failures.json`（失败教训）
- 注入：①开工前（翻译任务 + 设备档案）｜③每步（卡片 + 范例 + 教训）｜⑥收工后（写回）
- 失败经验两级利用：软注入（"别这么做"提示）→ 高频再犯则硬编译（检查器/拦截，如连败阻断）
- 反馈闭环：④ 屏幕变化回传 + 无效点击拦截；⑤ done 前先验证答案

**分批改造**（P0 三刀治三案 / P1 账本成型+经验清洗 / P2 自动归纳+检索升级）
**状态**：待拍板；建议 P0 先做，用"微博热搜"老失败案复测验收。

---

## 9-24 凌晨（五）· 语音速记条：音量下键改「纯语音」形态【已上线验证】

用户需求：按音量下**不弹大面板**，直接进语音输入（只留键盘+输入框），说完**再按一下执行**。

**实现**（`entry/` 新增 `VoiceBar.java` + `layout/voice_bar.xml` + `bar_bg.xml`）：
- 按一下「音量下」→ 轻量语音速记条（贴键盘上方）+ 聚焦弹键盘 + **自动唤起输入法语音键**；再按 → 结束听写并提交（空 → 关闭）；点空白/× → 取消。
- **本机语音输入 = 搜狗输入法键盘的麦克风键**（本机无系统语音识别服务：`voice_recognition_service=null`）。
- 自动点麦克风 **三级方案**：① a11y 节点搜索（搜狗键盘树只有"返回/切换输入法"2 节点，失败）→ ② **portal `/tap` 坐标注入**（可靠；坐标 = 键盘顶(1488) + 77px、屏宽 59.7% → (645,1565)）→ ③ `dispatchGesture` 手势（**本机被搜狗忽略**，仅兜底）。
- 面板「说话」按钮统一改为"切到语音条"（原系统 SpeechRecognizer 本机不可用）。

**坑位（新增）**：
- `dispatchGesture` 合成触摸对搜狗语音键**无效**，`input tap`/portal 注入有效；
- `getWindowVisibleDisplayFrame().bottom` 与物理坐标一致（键盘顶 = 物理 1488）；
- 构建环境 **safe-delete 拦截单次删 >50 文件**（原 build.py 清 build 122 文件 rc=1）→ **build.py 改唯一 run-<ts> 目录、不做批量删除**；
- onServiceConnected 增加"先 hide 旧浮球"防御（服务重连防双浮球）。

**实测**：按音量下 → 条+键盘+搜狗语音面板自动弹出（`logs/voicebar_v5.png`）→ 文字上屏（`voicebar_v7.png`）→ 再按 → `voice: submitted: home` → 控制台 running→done ✓；面板「说话」→ 自动切换语音条 ✓（`logs/panel_speak_switch.png`）。

---

## 9-27 · 豆包手机思路调研 + 「影子屏」实测打通 ✅【新方向，待拍板】

用户带来"豆包手机自动化跑在后台虚拟屏、手机可正常用"的说法，要求调研 + 评估我们能否改造。
**结论：能改，且最大不确定性已在今天实测消掉** —— 完整方案文档：`豆包手机思路调研与改造方案.md`。

实测（一加9 / Android14 / root，scrcpy v4.1 `--new-display`，全程约 30 分钟）：
- 影子屏创建成功（id=64/65/66/67，**每次动态**），flags 含 FLAG_OWN_FOCUS / FLAG_OWN_DISPLAY_GROUP / FLAG_ALWAYS_UNLOCKED；物理屏 0 全程不受影响；
- `am start --display N` 把设置 App 开上影子屏 ✓；`input -d N tap` 点进 WLAN 页 ✓；
- **关键**：EntryA11yService + portal `/state_full` 直接读到影子屏页面元素（WLAN / 已连接 / 可用网络）—— 现有 agent 元素清单链路可平移到影子屏；
- 并行验证：自动化进行中主屏实拍停在桌面、前后两次主屏截图字节级一致；
- 收尾：杀手机侧 server → "Recording complete" + 虚拟屏自动销毁，无残留。
- 坑：`screencap -d` 抓不了虚拟屏（本 ROM 限制）；录屏用 mkv + 杀"服务端"收尾才完整；录屏色彩标签 ycgco/log316 需 ffmpeg setparams 重标（抽帧脚本 `logs/vdtest/make_evidence.py`）。
- 证据：`logs/vdtest/`（evidence_side_by_side.png / newdisp4.mkv / portal_*.txt）；技能沉淀：`android-shadow-display`。

**待用户拍板**：① 启动 POC（建议）② 管家首版借 scrcpy-server（建议）③ 敏感 App 白名单策略（建议）。

---

## 9-27 下午 · P0 交付：「数据仓 + 对话壳 v0 + 测试模式」✅【已上机验证】

用户「开始吧」放行后当天完成（含双任务实测）。**一句话**：执行照旧，但结果从"网页临时状态"升级为"手机本机数据库"，界面 = 对话 + 历史（刷新/重启不丢）。

**交付物**（源码 `scripts/`，已部署手机 `~`）：
- `store.py` — 数据仓：SQLite `~/bridge/store.db`，三表（sessions / messages / datasets）；结果自动抽结构化列表（"1. xx 2. yy…" → 行）；`import_runs()` 回填老任务（首启回填 92 条历史）。
- `chat_ui.py` — 对话壳 v0：`/chat` 页 = 会话历史（最近 40 条 + 搜索框）+ 结果卡（结构化「列表·N行」表 +「同一任务的历史数据（可对比）」+ 再跑一次 / 看录屏 / 复制链接）。
- `mini_console.py` — 集成落库（开工/收工写库）+ 新 API：`/api/sessions`（历史/搜索）、`/api/session?rid=`（详情）、`/api/exec`（执行方式：测试模式 + 录屏开关）。
- `deploy_p0.sh` — 一键部署链（push → cp → 重启控制台 → 探活）。

**实测（全过）**：
- 「去微博找一下热搜前五是什么？」→ 完成（引擎 jev、9 步、45 秒），录屏 43s / 1080×2400 / 10.8MB → 库中 5 行结构化数据；09:47 同任务的 5 行出现在「历史数据（可对比）」区 ✓
- 重启控制台后数据仍在：94 条会话（done 67 / failed 25 / stopped 2 = 92 条历史回填 + 2 条新任务）✓
- 手机浏览器开 `127.0.0.1:8900/chat` 直接可用（`logs/p0/phone_chat.png`）；PC 侧整页截图 `logs/p0/chat_tall.png` ✓

**新坑（血泪）**：
- **screenrecord 被 Termux 环境变量毒死**：root 控制台 spawn `/system/bin/screenrecord` 时继承了 `LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib` → 系统二进制去加载 Termux 的错 so → `CANNOT LINK EXECUTABLE … cannot locate symbol "Xzs_Construct"`，**最阴的是 rc=0 却没产出文件**。修复：spawn 前 `env.pop("LD_LIBRARY_PATH")`（rec_start 内）。诊断法：同一条命令 `su -c` 裸跑成功、从 python spawn 失败 = 环境继承差异。
- **重启控制台**：`pkill -f mini_console.py` 与启动**必须分两条命令**（同一条会自匹配杀链）；部署脚本已按此写（+ setsid）。

**双模式现状**：测试模式 = 主屏执行 + 录屏 + 徽章「测试模式(主屏)」；正式模式（影子屏）UI 已留位（灰显"正式模式（P1 未上线）"）。

**下一步（待拍板）**：P1 影子屏管家（建议开工，首版借 scrcpy-server）→ 正式模式；P2 应用地图；P3 微信通知通道（并行）。

---

## 9-27 下午（二）· 入口 APK 化 v1.1：点图标 = 对话页 ✅【已装机实测】

用户拍板：**「入口我还是要坚持变成 APK——生成快、稳定性高」** → 当天落地 + 装机验证。

**改了什么**（`entry/` + `scripts/chat_ui.py`）：
- `MainActivity` 默认页 `/` → `/chat`（常量 `HOME_PATH`）：点桌面图标**直接进对话页**；页内「⌂ 控制台」↔ 控制台顶栏「💬」双向可达。
- 对话页两处交互补丁：点历史卡片**自动滚到结果详情**（`#streamsec` scrollIntoView）；「看录屏」在 App 内**当前页播放**（UA 含 `; wv)` 判定）；PC 浏览器行为不变（仍新开标签）。
- 无障碍按钮回调 `QuickPanelActivity`（Activity，会被 o-stop 拦）→ **`PanelOverlay.show`**（就地 overlay，与浮球同路径）。注：真机上暂未定位到按钮实体（ColorOS 需用户在无障碍设置里开启"快捷方式"才显示），此改动为预防性修复。
- 版本 `1.1 (versionCode 2)`。构建 `python entry/build.py`（~1 分钟）→ `adb push` + `su -c pm install -r`。

**实测链（全过）**：开 App 直达对话页 ✓ → 点卡片滚到详情（结果+5 行列表+同任务对比）✓ → ⏺看录屏（43s 实录在 App 内播放）✓ → BACK 回对话 ✓ → ⌂控制台 ✓ → 💬 回对话 ✓ → 输入框弹键盘、界面自动上移 ✓。证据：`logs/p0/apk_chat1.png`、`apk_chat3.png`、`apk_rec.png`、`apk_kb.png`、`apk_console2.png`。

**坑（血泪）**：
- **`am force-stop com.xiaogongtou.entry` 会被 ColorOS 顺带摘掉它的 a11y 服务**（浮球消失、App 内出现"悬浮球未开启"黄条）→ 手动补回（写 `portal:小工头` 两个服务名 + `accessibility_enabled 1`）或等 supervisor ≤5 分钟自动补。**不要用 force-stop 重启该 App**。
- 排查乌龙记录：装机后桌面右缘出现「小工头」图标气泡，一度误判为"系统无障碍按钮"。实际 = **ColorOS 装机后的提示样式**（点它打开应用抽屉、会自行消失）；把入口 a11y 服务临时摘掉它依然在 → 不属于本 App 悬浮窗。以后看到 = 正常现象。
- 顺带：`Eden Nightly` 弹了一个"允许安装应用"系统弹窗（与本次改动无关），已点「拒绝」关闭；如需让 Eden 装 APK 请自行再授权。

---

## 9-27 傍晚 · P1 交付：「影子屏管家 + 正式模式」✅【已上机实测】

用户拍板「一（P1 管家）和二（App 地图）先做」。本节 = P1。

**一句话**：手机靠自己（不再需要电脑）开机后台的"影子屏"，任务可以在影子屏上跑、主屏照常用——「正式模式」从灰按钮变成了真功能。

**交付物**（都在 `scripts/`，已部署手机）：
- `shadow.sh`（部署到 `/data/adb/mobilerun-console/`）——影子屏管家：`start/stop/status`；开屏 = 手机端 root 起 scrcpy-server 4.1（`tunnel_forward=true`）+「哑客户端」连两条流（video+control）并读丢，屏由本机进程自持（不依赖 PC）。
- `shadow_client.py`——哑客户端：连 `@scrcpy_05ad0001` 两次、持续 drain；服务端死了自己退出。
- `supervisor-loop.sh` v4——新增第 5 项守护：`shadow.on` 开关打开时，影子屏不在就自动拉起（开机/崩溃都兜）。
- `mini_console.py`——`/api/shadow`（GET 状态 / POST start|stop）；`start_run` 在「正式模式」下先确保影子屏并给 agent 传 `--display N`。
- `mini_agent.py`——新增 `--display N`：**正式模式全链路改走 display**（感知 = 桥树按 displayId 过滤；动作 = `input -d N`；开 App = `am start --display N`）。
- `chat_ui.py`——「正式模式 · 影子屏」按钮变真：点它启动影子屏并切换模式；结果卡徽章显示「正式模式(影子屏)」。

**支撑改动（入口 App v1.1 再更新）**：
- `EntryA11yService` 树导出升级：① `getWindows()` → **`getWindowsOnAllDisplays()`**（关键坑：前者只看默认屏，影子屏整屏元素会丢）；② 元素第 6 位加 **displayId**（影子屏过滤靠它）；③ 元素上限 400→700。

**实测（全过）**：
- 手机端自开影子屏：`shadow.sh start` → ~2.5s 出屏（id=70），15s 后仍持久 ✓；`stop` → 屏销毁、无残留 ✓。
- 同一任务「微博热搜前五」在**正式模式**跑：**5 步 60 秒**完成（jev 一路），返回 5 条真热搜 ✓；结果自动入库（exec_mode=prod）。
- **主屏零影响（像素级）**：任务全程对主屏截 3 张图（开始/中途/结束），剔掉状态栏后**像素差 0**（只有时钟在走）✓。
- 桥树多屏输出验证：同一次取树 = 主屏 66 + 影子屏 18 个元素（带 displayId）✓。

**坑（血泪，全当天踩出来的）**：
- **Termux 的 `am` 会顶掉系统的 `am`**：agent 环境 PATH 里 Termux bin 在前，`subprocess(["am", ...])` 实际执行 Termux:API 的 am（只打印帮助文本）→ **open_app 全部静默失败**（首轮正式模式任务 25 步全废就死在这）。→ 系统二进制一律 `/system/bin/` 绝对路径（`am/cmd/dumpsys/input` 已全改）。
- **`getWindows()` 只看默认屏**：影子屏元素整屏丢失 → 必须 `getWindowsOnAllDisplays()`。
- `scid` 必须是 ≤0x7FFFFFFF 的十六进制数字（`fad00001` 溢出崩）。
- 正式模式下**不要回退用 portal 树**（portal 焦点跟"最后被触的那块屏"漂移，会混入主屏元素、点下去指错地方）→ 影子屏空树就按空屏处理。
- 正式模式**感知只认桥树**（`getWindowsOnAllDisplays` 天然含全部显示屏 + displayId）。

**证据**：`logs/shadow/`（main_t0/t1/t2.png 主屏三连、prod_run2.out 任务日志、tree_dpy2.json 多屏树、atlas_scan_live.png 扫描现场）。

---

## 9-27 夜间 · 微信首次操作实测：「点得动、看不着」（P3/P4 前置侦察）

用户「测试一下微信的操作」→ 对微信做了一次**最小化首触测试**（低频 1 次、白天、主屏短促；共 3 次点击、零消息发送 / 零输入）。

**结果一句话**：微信 **"点得动、看不着"** —— 打开 / 切标签页正常；第三方 a11y 读微信界面 **整树为空**；截图正常。

**实测明细**（一加9 / A14 / 微信 8.0.78）：
- 打开微信（monkey）✓ → 点「发现」/「微信」标签页（root 桥 `input tap`）✓（`logs/wechat_test/wx_taps.mp4` 录屏可见切换全程）→ HOME ✓。
- **取树 4 次全空**（仅系统状态栏 21–22 元素；对照：桌面 37–52 元素正常）。ViewDebug 交叉验证：微信界面是标准控件（TextView / ConversationListView）→ **不是"没法读"，是 a11y 层被拦**。
- 机理（社区交叉验证）：微信 8.0.52+ 对**非系统白名单**的 a11y 服务**直接不给节点**（空值）；已知绕过 = ①服务名伪装（SelectToSpeak 式，灰区待拍板）②截图+OCR/VLM（干净路线）。
- 全程**无安全提醒 / 异常弹窗**。

**新增工具 / 修复**：
- `scripts/pc_bridge.py`：PC 侧 root 桥操作台（tree / tap / swipe / key / open / shot），手测回归用。
- `scripts/pc_portal.py`：修系统代理坑（`ProxyHandler({})` 直连；否则 127.0.0.1:7897 把局域网请求转成 502）。
- 坑：`screenrecord` **shell 用户段错误（RC=139）/ root 正常**；adb pull 远端路径要 `MSYS_NO_PATHCONV=1`；拉 root 文件先 `chmod 644`。

**策略影响**（已同步 `实施总方案-v2.md` §1.1 / §1.7 / §4 / §5）：微信 UI 的"读"≈0 → **P3 通知直回优先**；P4 先定感知路线；agent 需加"前台=微信且树空 → 拒绝乱点"保护（新增待办）。

**证据**：`logs/wechat_test/`（README + 截图 8 张 + 录屏 + 树 JSON ×7）。

---

## 9-28 傍晚 · 微信"读被屏蔽"的机理坐实 + 视觉兜底路线跑通 🚧【代码就绪，待部署】

用户问「现在的问题是什么？怎么解决？给方案+胜率+调研」→ 当天完成：机理定位、视觉路线端到端实测、代码落地（待部署）。

**机理（决定性证据）**：微信前台时 portal 直接报 `No active window or root filtered out` —— 不是"节点属性被混淆"，是**根节点被过滤**（窗口内容一点都不给）。对照：同刻桌面/其他 App 树 30–50 元素正常。

**视觉兜底实测（portal 8080 经局域网，全程未用 adb）**：
- 截图 ✅（1080×2400；portal 返回 base64 JSON、PNG 为 RGBA —— 两个坑）
- 多模态读屏 ✅ 准确（会话名/时间/角标全对）；坐标 = **0–1000 归一化**（换算后与真实控件误差 ±3~30px）
- 闭环点击 ✅：发现✓ / 通讯录✓ / 我✓（"微信号"误匹配的坑：元素匹配要"精确优先"，别用子串）
- 延迟 ⚠️ ~12s/次；**关思考**（`enable_thinking=false`）后输出稳定（否则偶发空）
- 稳定复现一次反例：探针在微信个人资料页把"微信号：ghostex"当成"微信"标签点进去 → 记录为工程注意项

**代码落地（`scripts/mini_agent.py`，PC 侧干跑已验，待上手机）**：
- 新增 `vision_apps()`（内置 `com.tencent.mm`，可外部 `~/bridge/skills/vision_apps.json` 扩展）
- 新增 `vision_elements()`：截图 → 多模态模型 → 伪元素清单（坐标自动归一化→像素、空输出重试、25 项上限）
- 主循环新增：**前台 App 命中 vision_apps → 视觉接管感知**（下游 Jev/qwen/动作**零改动**）
- 干跑实测：桌面 24 元素、微信页 15 元素（坐标与真实控件吻合）

**新增脚本**：`_vision_probe.py`（视觉闭环探针）· `_tree_stats.py`（树解剖：一眼看出是不是被屏蔽）· `_vlm_probe.py`（模型视觉能力探测）· `_wx_back.py`（退回微信主界面）· `pc_portal.py`（已修代理坑）

**文档**：`微信自动化方案评估.md`（问题/五套方案与胜率/调研/执行计划）· `实施总方案-v2.md` §1.8

**待办（阻塞项）**：测试机无线调试断了（重启后 5555 未起，只剩 portal 8080）→ **需插一次数据线**才能部署上机 + 跑 `isAccessibilityTool` 对照实验。

**调研要点（2026）**：微信 8.0.58 起第三方无障碍"布局分析"不可用（AutoJs6 #463）；社区绕过=服务名伪装（Assists/Auto.js Pro，灰区、随时可补）；主流开源手机 agent（UI-TARS / AppAgent / Open-AutoGLM / Mobile-Agent）**统一走"截图+视觉"**；Ruto（iamr0s）用 Shizuku+虚拟屏+Open-AutoGLM —— 与我们"影子屏"同构，方向被独立印证。

**✅ 端到端跑通（同日追加）**：新增 `scripts/_agent_pc_run.py`（PC 侧干跑：portal 8080 + LAN 模型；主屏模式全程无需 adb）。
任务「打开微信，列出聊天列表前 5 个会话（只读不点）」→ **2 步完成**：
`open_app` → portal 报 `root filtered out` ×3 → 桥超时 → **视觉兜底 16 元素** → qwen `done` 作答，**5 个会话名逐字吻合**、全程零点击。
证据：`logs/wechat_test/vision/agent_run_readonly.md` + `agent_trace.jsonl`。
附带补丁：portal 状态读取"抛异常"时也能进入视觉兜底（`_LAST_PKG` 推定前台包名；`pre_elems is None` 防重复调用视觉）。

---

## 9-27 傍晚 · 对话页 v4 双视图重构（用户反馈：「历史全量展示 + 点开要滚很远」）

**用户反馈**：前端界面奇怪——任务对话历史全量铺开；点一条后要"跳很远"才能看到详情。

**根因**：原 `/chat` 是**单页堆叠**：列表区（最多 40 条全渲染）在上、详情区在下，同处一个滚动流 → 点卡片只能往下滚过整段列表才能看到详情。

**重构（`chat_ui.py` 整页重写 + 两个数据接口小改）**：
1. **双视图架构**：列表视图 ⇄ 详情视图 = **两个独立滚动容器**（`body.view-list / view-detail` 切 `display`）——点一条**即时切换、零滚动**（详情从顶部开始）；0.18s 入场动画。
2. **列表分页**：20 条/页 +「加载更多 · 还有 N 条」+「共 N 条」；搜索同样分页。数据层：`store.list_sessions(offset=)` + 新增 `store.count_sessions()`；`/api/sessions` 返回 `{items,total,offset}`。
3. **日期分组**：今天 / 昨天 / MM月DD日。
4. **导航语义**：页内「‹ 历史」+ **安卓返回键**（`history.pushState/popstate` —— 与 MainActivity.onBackPressed→web.goBack 天然打通，**APK 无需改**）；详情内「同一任务历史数据」行也可点击切换。
5. **桌面自适应**：≥760px 自动左右分栏（列表 340px 常驻 + 详情并排，「‹ 历史」隐藏）。
6. 顶栏运行态提示（⚡ 运行中）；发新任务自动进详情看实时进度。

**验收（两层全过）**：
- **PC 探针** `scripts/probe_chat_ui.mjs`（playwright-core + Edge headless，移动视口 393×852）：首屏=列表（20 条/共 98 条）→ 点会话 `view-detail` 且 `scrollTop=0`、数据卡在列 → 「‹ 历史」/浏览器后退均回列表 → 加载更多 20→40 → 搜索"微博"共 43 条 → 宽屏 340px 分栏 → **0 JS 报错**。截图 `logs/p0/ui/01~07`。
- **真机（APK 跑在影子屏 72）**：a11y 树证列表在列 → `input -d 72 tap` 点第 2 条 → 树变详情（‹历史/数据5行/再跑一次/同任务对比）→ **`input -d 72 keyevent BACK` 回列表** ✓；物理屏（用户正在用淘宝）全程零影响。

**新坑**：桥树请求 `.xgt_req` 的 **seq 每次必须不同**——相同 seq 被工程端跳过重建，`cat .tree.json` 读到**旧树**（本次差点误判成"影子屏 a11y 读不到"）。

**证据**：`logs/p0/ui/`（截图 7 张 + probe-report.txt + tree_app72b/c/d.json）。

---

## 9-29 凌晨 · 防检测总纲 + 脚本封装方案定稿（用户三问：截屏 / 输入 / 点击的检测面）

**用户关切**：① 封装成"直接脚本"，但担心"识别会出问题、不知道操作得怎么样"；② 截屏会不会触发封号（一天几百几千次肯定有问题？）；③ 打字（弹键盘）、点屏幕，人和机器有没有区别。要求"全链路都不能被微信检测到"。

**调研结论（官方文档 + 社区交叉验证 + 本项目实测）**：
- **截屏：微信看不见**——Android 14 截屏检测 API 仅覆盖"用户按硬件键"的截屏；官方明确 adb / 程序化截屏**不触发**；我们的通道不落相册、不用 MediaProjection → 风险≈0。
- **打字：正常链路**——字由搜狗输入法提交，与真人打字无链路区别。
- **点击：唯一理论检测面**——注入事件微观特征（deviceId / 时长 / 压力 / 坐标静态性 / 节奏）理论可查；无证据微信启用（它防"读"不防"点"）。对策 = 拟人化三层：坐标抖动 ±3~15px、按压 60–180ms、间隔 0.4–1.5s 随机；P4 可选 sendevent 内核级注入。
- **真正的风险在行为层（消息频率 → 限速白名单）与环境层（root 未藏 → Shamiko 待办=高优先级）。**

**脚本封装定稿**：目标形态 `wx_send.py --to "hao" --text "test" [--dry-run|--confirm]`；五方案 = A 全视觉 / B 固定坐标 / **C 状态机+双重校验（推荐骨架）** / D 人工确认 / E 影子预演；上线节奏 **E→D→C**；回执 = 每步截图 + 结果报告 + 会话列表侧证（"不知道操作得怎么样"的答案）。

**产出**：`微信自动化-防检测与封装方案.md`（三个担心的直接回答 / 全链路检测面表 / 五方案 / 识别出错对策表 / 运行纪律参数表 / 待办优先级）。

---

## 9-29 凌晨（二）· 执行架构设计定稿（视觉调用时机 + Jev 分工 + 时间预算）

**用户要求**：① 全部事情同时做；② 回答"视觉识别在固定/随机事件什么时候调用效率最高"；③ 把 Jev 融入（不是什么都给千问走）；④ 预估最快几秒（20 分钟太慢）；⑤ 先把整个方案设计好。

**实测底数（本次新测）**：
- **Jev 云决策 0.74s / 1.58s**（且决策正确：给"hao 发消息"场景选中 hao 行 conf=0.95）；
- 千问文本 0.62~0.74s（短答）；千问视觉 ~12s（沿用）；**portal 截图 ~1.05s**；portal 状态 0.14~0.27s。

**定型架构（三级感知调度）**：L0 本地对账（~0.1s，全程用）→ L1 Jev 快决策（0.7~1.6s，仅清单有歧义）→ L2 视觉（~12s，**只在两个时点：任务入口 + 校验失败**）。三条原则：一图多问 / 调用必沉淀经验卡 / 单任务 ≤2 次。加速三招：搜索直达（把"找行"变固定路径）、缓存+校验、置顶（可选）。

**时间预算**：全固定 0 视觉 **≈12-15s**（优化目标 ≤10s）；含 1 次定位 ≈25-30s；对照今晚人工遥控 ~20 分钟（约 100 倍）。

**实施**：T1 Shamiko / T2 拟人化 / T3 wx_send.py 三模式 / T4 回执 / T5 三级感知进 agent / T6 sendevent 评估——**全部放行，PC 侧三件先全开**。

**产出**：`微信自动化-执行架构设计.md`；探针 `scripts/_latency_probe.py`。

---

## 9-29 傍晚 · T5 技能接入完成：前端"给exalex发 test" → 11.1 秒送达（3/3 全绿）

**里程碑**：技能接入手机 agent（意图路由 + 预编译技能），从前端同一 API（`POST /api/run`）三轮实测 **3/3 成功、0 误发**；修完计时后热态 **11.1s**（技能）/ ~12s（含 agent 启动），0 模型 0 视觉。

**上机文件（4）**：`~/wx_intent.py`（意图解析·复用）· `~/wx_send.py`（技能 v2.3）· `~/mini_agent.py`（路由钩子）· `~/mini_console.py`（`ensure_portal()` 预检）。

**三个新坑（详见取证 README）**：① **LD_LIBRARY_PATH 毒杀系统二进制**（console root 上下文 → screencap 0 字节，CANNOT LINK；正解=系统调用前剥 LD_LIBRARY_PATH/LD_PRELOAD）；② **搜狗中文组合态**（无发送键 → 点首候选提交；判据"深绿发送键 ⇔ 有已提交文字"）；③ **前台检测 `grep -m1` 拿到的第一行是影子屏** → 必须全文匹配（8.7s→1.1s）。

**时间账（#3）**：起步-列表 2.5s → 定位 0.05 → 进会话+标题 1.4 → 打字 4.2 → 提交 1.2 → 发送+验证 1.7。
**纪律**：wxsend 路由只在**测试模式·主屏可见**下生效（影子屏模式跳过）。
**证据**：`logs/wechat_test/agent_route/`（README + 状态 JSON + 17:14 成功截图）。

---

## 9-29 晚 · 认错人事故 + 加固（用户实测逼出来的 v2.5→v2.9）

**事故**（19:45 用户跑"给exalex发条微信 hello"）：列表被滚到旧会话区 → "微信支付"行宽 177px 落进 exalex 的过宽容差窗（±15%）→ 点错人 → 标题复核同一松窗又放行 → 在服务页/网页上盲点 ~8 处（打字/候选/空格全打空）→ 误入淘宝登录页（FLAG_SECURE，系统级禁截屏）→ 截图变黑/被拒 → 安全中止（**未发错消息**）。

**加固（全部上机+验证）**：宽度窗收紧（首次±9% + 成功后指纹记忆 `~/bridge/wx_contacts.json`；中文估宽 36→43.5px/字）· 键盘硬闸门（`mInputShown`，没弹键盘=不许打字）· 取消一切盲点（候选/空格/发送键都必须先在屏幕上检测到；发送键加尺寸窗 [1500,3600]）· 列表滚动恢复（先滑到顶；**到顶标志=拉出微信「小程序面板」（暗比例 0.89）→ 上滑关闭**；找不到目标上滑翻页≤3屏）· 找不到=安全停。

**验证**：安全停 ✓（0 点 0 输）· 送达 14.4s ✓（v2.9 全链路）· 滚动探针两场景 ✓（深位/顶部快路径 5.4s）。证据 `logs/wechat_test/agent_route/`（final_status7/8/9 + user_run_1945）。
**音量下快捷键**：实测活着（sendevent 模拟物理键 → 服务日志 + 听写面板弹出，截图存证）；已把手机从怪状态清理回正常。

---

## 9-29 深夜 · "宽度≠身份"事故 → v3.0 身份确权（模板+视觉）三轮实测全绿

**事故**（20:12 用户实测）：目标「微信团队」不在列表 → 宽度窗(158-189px)命中「微信支付」行(177px)——**两者都是 4 汉字、宽度几乎相同** → 标题校验（同为宽度比对）误判通过 → 在支付页戳输入框位×2 → 键盘闸门拦停（未输入未发送）→ 手机留在怪页（用户观感"又乱点了"）。

**根因**：身份判据从头到尾=宽度；**宽度是位置，不是身份**。

**v3.0（已上机+实测）**：
- 未建档联系人 → **视觉读名单**（1 调用读全屏名字+坐标→精确匹配→点行）→ **视觉读标题**确权 → 存墨迹模板；
- 已建档 → **标题墨迹网格**本地比对（96×24；阈值 差≤3.0/大格比≤0.02；标定：同名 0.0，异名≥63）；
- 找不到 = **0 点击 0 输入干净停** + 自动回列表 + 终帧留证；视觉预算 ≤4 次/run。

**实测**：A 微信团队→干净停（34.5s，0 点 0 输）｜B exalex 首建→送达（31.7s，2 视觉）｜C exalex 复跑→**模板 差=0.0，0 视觉，14.7s 送达**。
**证据**：`logs/wechat_test/run_2012/`（README + final_A/B/C + 截图）；标定工具 `scripts/_title_calib.py`。
**认知**：① 同标题跨运行墨迹网格差=0.0 → 渲染确定性，像素模板可行；② 标题带 y138-208（上方是状态栏污染区）、x150-770（左徽标/右图标之外）。

---

## 9-30 中午 · 入口 App v1.2：浮球=语音入口 / 状态栏任务进度 / 语音自动收键盘（全部上机实测）

**① 浮球**（用户反馈"没啥用"→ 诊断=交互分工不清）：**单击 → 语音速记条**（路由与音量▾同款）；**长按 → 文字面板**；调试开关移出浮球（对话页 Web UI）。
**② 状态栏进度**：Notifier+Poller 重写——任何任务类型都更新"正在干活…（第N步）· 已运行Xs·进度条"；修复"技能任务 step=0 从不更新"的旧 bug；跳过 `[wxsend] exec:` 行；运行中收起待命通知、结束恢复；空闲轮询 12s→4s。实测：运行中通知 ✓（13:38）、结束后结果+待命 ✓（13:51）。
**③ 语音收键盘**：`VoiceBar.imeWatch`——识别文本稳定 3s/静默 20s → 自动收起输入法（实测 ✓ 13:37）；提交/取消也收。硬约束坐实：本机无系统 ASR（讯飞=仅TTS、LAN 模型拒音频、IME z序在 overlay 之上）→ 说话期间搜狗面板必须存在，只能"说完即收"。
**④ 弹窗 UI**：3 方案 mockup 已交付（A 量子边框·四边流光 / B 太空舱·呼吸描边 / C 数据洪流·分段流光），待用户选型。

**wx_send v3.1**（顺带上机）：兜底确权改模板优先（省一次视觉调用）；宽度窗 ±12；回顶后加"在列表"预检。实测：14.7s（模板0.0）/ 49.6s（两候选被拒→视觉兜底=完整安全链）。

**事故**：测试中途展开通知栏干扰一轮（已加预检 + 纪律"运行中不碰通知栏"）；微信 zygote64 ART SIGSEGV 崩溃一次（平台级，已恢复）；FLAG_SECURE（淘宝登录页）再现（HOME 恢复）。
**证据**：`logs/entry_ui/`（27 张）；APK v1.2（versionCode 3）；技能 v3.1。

---

## 10-01 凌晨 · 入口 App v1.7：顶部「任务栏」+ 提交飞行动画（用户需求："提交任务要有动画，从对话框把任务丢到任务栏；任务栏要接管进度"）

**需求解读**：对照豆包手机的"顶部横条"（调研文档 §2 待办）——任务提交时从对话框"飞"进屏幕顶部的任务栏；只有一个任务在跑时，任务栏全程显示进度（"接管"）。

**交付（全部上机实测）**：
1. **`TaskBar.java`（新）**——屏幕顶部居中"任务进度横条"（深色玻璃药丸 + 冰蓝描边，912x162px@1080）：
   - 两行：任务名 + 「第 N 步 · Xs」（右）；副行=最新动作（剥 `[step N]`/`[agent]` 前缀）；
   - 动效：顶部滑入（Overshoot）+ 描边落地脉冲 + 呼吸点 + 底部流光循环（1.7s 相位）；
   - 结果态：`✔ 完成 / ⚠ 未完成 / ⏹ 已停止` + 描边变绿/橙，停留 3.4/4.6/2.4s 自动收起；
   - 数据双路：`kickoff()`（语音/面板提交时立即点亮，不等轮询）+ Poller（每 2s 状态驱动）；含"窗口意外脱离自愈"（isAttachedToWindow 检测重挂）。
2. **`FlyView.java`（新）**——提交"飞行动画"：任务胶囊（深色玻璃+蓝边+任务文字）从对话框/面板输入框起飞，二次贝塞尔弧线飞向任务栏落点，720ms（PathInterpolator），缩到 0.3 淡出；到 88% 时触发 `TaskBar.landed()` 落地脉冲。载体=全屏透明不可触摸 a11y overlay，动画完自动移除。
3. **集成**：`VoiceBar.submit()` / `PanelBinder.doSubmit()` 成功分支 → `TaskBar.kickoff + FlyView.launch`（面板/语音两条原生路径）；`chat_ui.py` 对话页 → 新增 `.flypill` Web 动画（输入框 → 屏幕顶部中央，660ms，WAAPI）。
4. **Poller 提速**：空闲轮询 4s→2s（对话页提交后任务栏 ≤2s 内亮起）；`[step N]`/`[agent]` 前缀剥离；诊断日志保留（tag `xgt-taskbar`，每任务 4-6 行）。

**实测矩阵（全绿）**：
| 场景 | 证据 |
|---|---|
| 运行态（第 N 步 · Xs + 流光） | 日志 step1→10 连续 + 截图（"第 7 步 · 35s"），像素级测得横条 912px 居中 |
| kickoff"启动中…/正在准备…" | 录屏帧 T=9.10s |
| 飞行动画 | 录屏帧 T=8.93s（胶囊在输入框位置起飞）→ 面板淡出 → 任务栏"启动中" |
| 结果态 + 自动收起 | 截图 6 连（亮度 91.5→58.8→91.5）+ 日志 |
| 服务重启后（kill+设置重写） | 新进程 29985 一轮正常 |
| 安装后自动重建进程 | 18314/31680 均正常 |
| Web 动画（playwright 采样） | 7/26 采样命中，轨迹 (43,706)→(169,86)→(176,64)，0 JS 错误 |
| 对话页部署 | `chat_ui.py` 已上机（diff 确认仅新增动画部分）+ console 重启自检 200 |

**部署链（可复用）**：chat_ui.py → `adb push /data/local/tmp` → `su cp` 到 `~/.termux home`（root:root 700，mini_console.py `import chat_ui`）→ `su -c "bash ~/start-console.sh"` 重启 console（pkill+Popen+自检）。

**坑与观察**：
- **安装 v1.7 后的一代进程（9027）TaskBar 两轮未显示**（日志静默、无崩溃、服务功能正常）——后续 4 代进程（重装/重启）均复现不出；已加"失败路径日志 + 窗口自愈"防复现，**列为观察项**。
- `su kill` 杀 a11y 进程后 **ColorOS 不会自动拉起服务** → 用 `settings put enabled_accessibility_services`（先仅 portal 再 portal+小工头）触发重绑；**用户日常重装 APK 后如遇浮球/任务栏不动，按此拉回**（supervisor 5 分钟也会兜）。
- `shell` 用户跑 `screenrecord` 段错误（RC=139）——**已知坑复发**：录像一律 `su -c`。
- logcat 用 `-t N 行` 过滤会被系统日志挤掉 → 用 `-d` 全量 + grep，或加大窗口。

**产物**：APK v1.7.2（versionCode 12）已装机；`scripts/chat_ui.py`（已上机）；探针 `scripts/_probe_fly_anim.mjs`；演示视频 `logs/entry_ui/v17_demo_fly.mp4`（3.8s）+ 全片 `v17_fly2.mp4`（12s）；截图 `v17_tc_5.png`（结果态）、`v17_run1.png`（运行态）、`v17_web_fly.png`（Web 动画）。

---

## 10-01 凌晨 · pi 进手机：后台架构盘点 + 可行性分析【待拍板】

**需求**：「现在框架里手机后台到底有哪些架构，画个架构图。想把 pi 部署进手机，这样可以执行工作流，而不是单次请求 api（智力不够）。」

**产出**：`pi进手机-后台架构分析与方案.md`（六层盘点 + 实测证据 + 四期方案 + 拍板项）。

**核心结论**：
- 现役后台 = 六层自包含体系（入口/控制/执行/手眼/数据/外脑）；常驻件生存前提 = **root 域 + 无障碍**两把「免冻护身符」。
- **四个关键可行性点今天全部实测消掉**：① pi 官方支持 Termux（docs/termux.md）；② Termux 源 nodejs **26.4.0**（要求 ≥22.19）；③ 局域网 qwen（dgx）**支持 function calling**（tool_calls 实测、热态 1.02s）；④ pi 0.82.1 + dgx **工具循环干跑 rc=0**（2 次 bash 调用 + 汇总，65s）。
- 坑（已沉淀）：pi 连 LAN 模型在带代理环境会**静默挂起**（NO_PROXY 空 / CIDR 不被 undici 认）→ 运行时清代理 env 即通。已补进技能 `clash-proxy-lan-triage`。
- 方案骨架：P0 手机装 pi 冒烟（半天）→ P1 工具桥 ptool + phone-control 技能（1~2 天）→ P2 接入控制台做「快慢双轨」路由（2~3 天）→ P3（选做）移植 piHarness 工作流引擎（3~5 天）。
- 现状核对（adb）：入口 APK v1.7.2（vc12；当日已升 **v1.7.3** 含 Pi 芯片，见下午修复轮）；存储剩 59G；console(root) + shadow_client 运行中。

**状态**：待拍板（形态 / 权限边界 / 常驻方式 / 版本对齐，建议倾向见文档 §7）。

---

## 10-01 中午 · pi 进手机：P0~P2 全量落地 ✅（用户「开始吧」放行）

**一句话**：pi 0.82.1 装进手机 root 域（Node 26.4.0）；`ptool` 工具桥把手机操作封装给 pi；控制台新增「Pi」模式——发任务即走 pi，**结果照常入库/通知**（快慢双轨齐活）。

**P0 · 手机装 pi**：
- Termux 侧两堵墙实测：① apt **永久禁 root**（"Ability to run this command as root..."）；② `su 10353` 会话 **DNS 挂**（app 上下文才有网络）→ 定案 **离线 deb 路线**（root 下载 + sha256 校验 → Termux 用户 `dpkg -i`）。
- 依赖闭包：c-ares / libicu / nodejs 26.4.0 / git / npm 11.20 + **openssl 3.6.3 / libc++ 30 / zlib 1.3.2 升级**（node 缺 `OSSL_PROVIDER_add_conf_parameter` 符号→CANNOT LINK，升级后解决）；openssl conffile 交互坑用 `--force-confnew` 过。
- pi 运行时：PC 干净 npm 装 0.82.1 → tar（23MB）→ 推手机解包 `~/pi-runtime`；配置 `~/.pi/agent/{models.json,settings.json}`（dgx 局域网 + hdd 云）。
- 冒烟：`pi -p --provider dgx` 工具循环 **rc=0 / 24s**。

**P1 · 工具桥**：
- `~/bridge/tools/ptool.py`（state/tap/swipe/text/key/open/shot/battery/apps/front/**wx-send**；主屏+影子屏双模式）；
- `~/.pi/agent/skills/phone-control/SKILL.md` + `~/pi-work/AGENTS.md`（纪律与红线写进技能，渐进式披露）。
- 验收：pi 独立读电量 **22s 全对**（level/充电/温度）。

**P2 · 控制台双轨**：
- `mini_console.py`：`mode=pi` 分支（spawn `~/pi-runtime/pi -p --name console-<rid>`，env 去 LD_LIBRARY_PATH、cwd=~/pi-work）+ `parse_run(pi_mode)` 取尾部文本作结果 + 页面「Pi」芯片；`chat_ui.py` 加「Pi 深度」chip。
- 端到端：`POST /api/run {"mode":"pi"}` → **26.6s done**（engine=pi、结果入库）；双轨回归：auto（老链路 jev 18s）与 pi（新链路 9s）先后跑通。

**关键坑（本阶段）**：Termux apt 禁 root；su-10353 无 DNS；node 需 openssl≥3.6；dpkg conffile 交互；`pgrep -f`/`pkill -f` **自匹配**（脚本名含关键字→按 PID 杀）；pi 输出无 `[agent]` 标记（console 解析适配）；Windows→adb→su 三层引号必碎（一律走脚本文件 + LF）。
**脚本与文件**：`scripts/pi_phase/`（README 含完整可复现流程）；手机侧 `~/pi-runtime/`、`~/pi-work/`、`~/.pi/agent/`、`~/bridge/tools/ptool.py`。
**待办**：① 真机推磨更多 pi 任务（微信发送走 ptool wx-send 验收）；② 影子屏模式下 pi 任务实测；③ P3（工作流引擎移植）待拍板。

---

## 10-01 下午 · 修复轮：语音意图路由 + 步数上限 100 + APK「Pi」芯片（v1.7.3 / vc13）✅

**起因**：用户实测「呃，发条微信给EXLEX test。」（12:38，auto 模式）**25 步耗尽失败（240s）**。诊断三因：
1. 句首 **"呃，"** 让 `wx_intent` 整句失配 → 没走"给X发Y"技能直通 → 进入通用循环；
2. 恰好落在微信（a11y 被屏蔽、portal 报 `root filtered out`）→ 感知为空 → open_app/wait 空转到 25 步；
3. 目标名 **"EXLEX" 疑似 "EXALEX" 的语音误识别**（真名 EXALEX）——即便路由成功也会干净停（安全）。

**修复（4 件，全部落地）**：
1. `wx_intent.py`：新增 `strip_lead_noise()`——句首语音口癖/客套清理（呃/嗯/那个/帮我/请/我想…，最多 4 轮；不含"给/发"结构词）。新事故样本+老用例断言全过。
2. 步数上限 **25 → 100**：`mini_console.py`（spawn 参数）+ `mini_agent.py`（默认值 2 处）。
3. 入口 APK **v1.7.3 (vc13)**：面板模式芯片新增「Pi」（`activity_panel.xml` + `PanelBinder.java`）；**浮球/音量键语音路径从此也能选 Pi**（走 Prefs.mode，持久化）。
   ⚠️ **版本号提醒（多会话共享目录）**：vc13 已被本轮占用——**光效 v3 轮请从 vc14 / v1.7.4 起**。
4. `phone-control` 技能 + `AGENTS.md`：新增「一次运行=无人值守」纪律——不以提问结尾；"给X Y"切分惯例（X=首名、Y=其余）；名字找不到**不得自动改名重发**，给候选待确认。

**复测（用户原句，全绿）**：
- **auto**：29.05s 直通技能 → **干净停**（0 点击 0 输入），失败原因明确："名单里没有「EXLEX」…（28.5 秒，安全中止）"——对比旧版 240s/25 步毫无结论。
- **pi（指引更新前）**：15.9s 但以提问结尾（误把"test"当名字一部分）→ 暴露缺口。
- **pi（指引更新后）**：96.2s 完整闭环——正确切分 `--to EXLEX --text test` → 走 wx-send 安全链 → 翻两屏未找到 → 干净停 → 报告"未发送（干净停 rc=6）"，并给候选 **EXALEX**（"需你确认，我不会自行改名重发"）。

**产物**：`scripts/pi_phase/`（`test_round2.sh` / `test_pi_retry.sh` / `deploy_fix_round.sh`；README 已更新）；APK `entry/dist/xiaogongtou-entry.apk`（v1.7.3）。

---

## 10-01 晚 · 排查「动不动跳淘宝登录页」：定位 = 淘宝后台弹页 + 关闭其权限 ✅

**现象**（用户 bug 清单 #1）：手机（LE2110）日常使用中"动不动"自动跳到淘宝登录页。
**定位**：非系统故障、非我方系统——**淘宝 App 自己「后台弹页」**（`com.ali.user.mobile.login.ui.UserLoginActivity` 被直接弹到前台）；本机 `appops` 给淘宝 `BACKGROUND_START_ACTIVITY: allow`（ColorOS"后台弹出界面"放行）＝ 通行证。

**证据（android events buffer，40 分钟窗口 4 次）**：17:12:55 / 17:18:31 / 17:20:32 / 17:32:45 —— 每次均为"淘宝进程被系统/推送复活（`heytap.mcssdk.AppPushService` ×2、清理/死亡后系统调度重启 ×2）→ 1~3s 内弹登录页 → 顶掉前台 App（夸克×2、天气×1）→ 自关或用户按返回"。窗口内淘宝**零通知入队**（排除点通知）；同期 console/bridge 无任务、全记录 grep taobao 零命中（排除我方系统）。第 3 次连带拉起支付宝"一键登录"组件（`AliAuthLoginContentProvider`）。

**处置（用户指令执行）**：`appops set com.taobao.taobao BACKGROUND_START_ACTIVITY deny` + `SYSTEM_ALERT_WINDOW deny`（shell 即可，无需 root）→ 双 deny ✓；回滚 = `default`。
**验证（已收官）**：观察哨覆盖 16:58~18:19 完整事件史（`logs/taobao_pop/events_watch.log`）——修复前 40 分钟弹 4 次；**修复后 41 分钟零弹页** ✓（观察哨 18:20 按用户要求停止）。

**档案**：`淘宝后台弹页-诊断.md`（根目录，含复核命令）；证据 `logs/taobao_pop/`。
