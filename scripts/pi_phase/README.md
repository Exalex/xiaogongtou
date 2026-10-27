# pi_phase — 「pi 进手机」实施脚本区（2026-10-01）

> 本目录 = P0~P2 落地过程的一手脚本与文件。最终源码如需维护，以本目录为准
> （手机侧部署位置见各脚本头部注释）。

## 实施顺序（已经跑通的全流程，可复现）

### P0 · 手机装 pi（Node 运行时 + pi + 配置）
1. `root_net_probe.sh` — 探测 root + Termux env 下网络/DNS（结论：root 可达外网；Termux 用户 su 会话 DNS 挂）
2. **离线 deb 路线**（Termux 的 apt 禁 root；su-10353 DNS 不通 → 用 root 下载、Termux 用户安装）：
   - `plan_debs.py`（PC）扫描 Packages 索引算依赖闭包 → `dl_debs.sh`（root 侧下载+sha256 校验）
   - `dl_debs2.sh` 补升级 openssl/libc++/zlib（node 26.4 需要 openssl 3.6 的符号）
   - `dl_npm.sh` 下载 npm 独立包（Termux 的 nodejs 不再内置 npm）
   - `job_dpkg_install.sh` / `job_dpkg_install2.sh` / `job_dpkg_fix.sh` / `job_fix2.sh` — Termux 用户身份 dpkg 安装
3. `pi-build/`（PC）npm 干净安装 pi 0.82.1 → `tar czf pi-runtime-0.82.1.tgz`（23MB）
   → push → `job_finish_p0.sh`（安装 npm + 解包到 `~/pi-runtime`）
4. `user_files/` 配置文件 → `deploy_pi_files.sh` 部署：
   - `~/.pi/agent/models.json`（dgx 局域网 qwen + hdd 云）、`~/.pi/agent/settings.json`
   - `~/pi-runtime/pi`（启动器：Termux env + cwd=~/pi-work，不设 LD_LIBRARY_PATH）
   - `~/pi-work/AGENTS.md`、`~/.pi/agent/skills/phone-control/SKILL.md`
   - `~/bridge/tools/ptool.py`（手机操作工具包）
5. `pi_smoke.sh` — 冒烟：`pi --version` + `pi -p` 工具循环（dgx）→ **rc=0, 24s**

### P1 · 手机工具桥
- `ptool.py`：state/tap/swipe/text/key/open/shot/battery/apps/front/wx-send（`ptool_test.sh` 自检通过）
- `pi_task_a.sh` — pi 独立任务验收（读电量）→ **22s，数值全对**
- `test_pi_wx.sh` / `test_wx_cleanstop.sh` — 微信链路验收：
  - pi 任务「给 exalex 发一条微信，内容：test」→ **78.8s 送达**（pi 自己调 ptool wx-send，回执：身份确权差=0、rc=0、送达校验通过）
  - 干净停探针（目标不存在）→ 0 点击 0 输入安全停（见 `test_wx_cleanstop` 输出）

### P2 · 控制台接入（快慢双轨）
- 改动：`scripts/mini_console.py`（`mode=pi` 分支 + parse_run pi 模式 + 页面 Pi 芯片）、`scripts/chat_ui.py`（Pi 深度 chip）
- `deploy_console_p2` 流程 = 推 `.new` → root cp 到 `$HOME` → `py_compile` → 重启控制台（pkill 按 PID 杀，防自匹配）→ `check_console_new.sh` 验证
- `test_console_pi.sh` — 端到端：POST `/api/run {"mode":"pi"}` → 轮询 status

### 修复轮（2026-10-01 下午，用户实测事故驱动）
- 事故：**"呃，发条微信给EXLEX test。"** 25 步耗尽失败（240s）。三因：① 句首"呃，"让 wx_intent 失配 → 未走技能直通；② 微信界面被屏蔽 → 通用循环瞎转；③ "EXLEX" 疑似 "EXALEX" 误识别。
- 修复三件套：
  1. `scripts/wx_intent.py` → `strip_lead_noise()`（句首口癖/客套清理，含断言自测）；
  2. 步数 **25→100**（`mini_console.py` spawn 参数 + `mini_agent.py` 默认值）；
  3. 入口 APK **v1.7.3 (vc13)**：面板模式芯片加「Pi」（`activity_panel.xml` + `PanelBinder.java`）。
     ⚠️ 光效 v3 轮请用 **vc14**（13 已被本轮占用）。
- 复测脚本：`test_round2.sh`（auto+pi 同句）、`test_pi_retry.sh`（指引更新后 pi 复测）。
- 技能/纪律更新：`phone-control` SKILL.md + `AGENTS.md` 新增「一次运行=无人值守」（不以提问结尾；"给X Y"切分惯例；名字找不到不得自动改名重发）。

## 关键坑（本阶段新增，血泪）
1. **Termux apt 永久禁 root**（"Ability to run this command as root has been disabled permanently"）→ 走离线 deb。
2. **su 10353 会话 DNS 挂**（app 上下文才有 netd 网络）→ 下载一律 root（DNS 正常），安装用 Termux 用户（dpkg 不需要网络）。
3. **node 26.4 需要 openssl 3.6**（3.4.1 缺 `OSSL_PROVIDER_add_conf_parameter` 符号）→ 一并升级 openssl/libc++/zlib。
4. **dpkg conffile 交互卡死**（openssl.cnf）→ `dpkg --force-confnew --configure openssl`。
5. **pgrep -f 自匹配**（脚本名含 "dpkg"/"mini_console.py" 会匹配到自己）→ 用 `pgrep -x` 或 `pattern[.]py` 括号技巧。
6. **pkill -f mini_console.py 会杀掉执行它的 shell 自身**（命令串含关键字）→ 按 PID 杀。
7. **测试脚本一律走文件**（Windows bash → adb → su 三层引号必碎）→ 本地写 .sh/.py → LF 转换 → push → 执行。
8. **pi 输出无 [agent] 标记**（与 mini_agent 不同）→ console 的 parse_run 加 pi_mode 取尾部文本块作结果。
