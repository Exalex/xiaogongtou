# 变更记录

> 规则：每次动过代码或文档都要发布一版（`./release.sh "说明"`），tag 与 `entry/AndroidManifest.xml` 的 versionName 对齐。
> 具体技术细节不重复写在这里——每一版在 `PLAN.md`（滚动日志）、`开发笔记.md`（迭代账本）和日期化实测报告里都有完整记录。

## v1.9.1 · 2026-10-28

**方案 A「修地基」的三件事，真机验证通过。** 本次只动端侧脚本，APK 仍是 1.9 / vc15。

- **真源收敛**：`scripts/{mini_agent,mini_console,scripts_lib}.py` 改成转发壳（`exec` 真源同名文件），
  import 与直接运行行为一致；至此改代码只有一个地方可改，不会再分叉。旧副本已核对无任何独有实现
- **感知自报 + 降级**：新增 `percept_health()` 输出元素数/横向覆盖/纵向覆盖/等级；
  横向覆盖 < 50% 时自动调 `uiautomator` 补一次通道（每任务一次）。
  同时给 `uiauto_elements` 加不可用缓存 —— 无 root 机型原来每步白等 8 秒超时，现在只试一次
- **失败自动分类**：新增 `classify_code()`，把失败判成 10 类病种
  （P-COVER/P-EMPTY/P-BLIND、D-LOOP/D-ANCHOR、A-REJECT、E-LOGIN/E-TIMEOUT/E-LAUNCH、X-UNKNOWN），
  写进 `failures.json` 和 trace；`metrics.py` 新增「失败病种」报表（按 code 与按族两级汇总）
- **修掉一个静默 bug**：「无进展兜底放弃」原来用 `_stage=` / `_pattern=` 传参，
  而形参名是 `stage` / `pattern` → 每次都 TypeError 被 except 吞掉，这条失败从来没落过盘
- **真机验证**（Y700 / Android 16 / 无 root，经反向隧道接模型）：
  `卡点: stage=环境 | code=E-TIMEOUT | 覆盖=50% | 盲点=0 | 步数=4/4`

## v1.9.0 · 2026-10-28

**首次把「真正在跑的东西」完整纳入版本控制。** 此前仓库里跟的是 10 月 12 日的旧副本，手机上的端侧真源大半没入库。

- 端侧真源 `tabletbrain/` 全量入库（`mini_agent.py` 4359 行，领先 `scripts/` 同名副本 1050 行），含三级锚点 `anchors.py`、探索地图 `appmap.py`、控制台 `mini_console.py`、自愈守护 `supervisor-loop.sh`
- 13 份架构/实测/方案文档入库（此前 README 引用的总文档长期游离在版本控制之外）
- 入口 APK 1.9（vc15）：语音条视觉层 `FlyView`/`GlowFrameView`/`WaveView` + 6 个 drawable；`LaunchApi`（127.0.0.1:8901）作为无 root 机型唯一可用的 App 启动通路
- 仓库卫生：拦截 130MB `full_dex.txt`（超 GitHub 单文件限制）、`portal.apk`/`termux.apk` 二进制、`secrets_tablet.json`（含 portal token）
- 新增 `release.sh`：一键提交 + 打 tag + 推送，含敏感文件硬闸门

## v0.9.0 · 2026-10-24（补记）

- App 探索地图第二轮验证：n=3 均净负（+0.7 步 / +8s）→ **默认关闭**
- 三处修正：通用格式、消费端、探索器收敛

## v0.8.0 · 2026-10-22（补记）

- 导航图谱 `app_paths.json` + 登录浮层识别 + 锚点纠偏豁免：酷安搜索 17 步失败 → 10 步成功
- TaskBar 运行中抢点击 → 改点击穿透：B站排行榜 29 步失败 → 4 步成功
- 榜单覆盖误触发把正确答案改错（高危）→ 加排行榜语义前置条件
- 第二轮压测：历史失败样本全部翻盘，连续 5 次任务零浪费

## v0.7.0 · 2026-10-12（补记）

- 三段式定稿：模型只在规划期/异常期/收工三处介入，常规步 0 模型
- 五道关卡：开工闸门 / 起点归位 / 脚本重放 / 子目标步进 / 收工复核
- 真机随机验收 R4 达 5/5；大型 App 路径发现仍未过关（头条/B站）
