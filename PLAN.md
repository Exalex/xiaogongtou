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
