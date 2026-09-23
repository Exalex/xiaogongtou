# -*- coding: utf-8 -*-
"""把核心源码全文追加到《项目完整文档.md》末尾(附录),便于单文件携带。"""
import os

PROJ = r'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice'
DOC = os.path.join(PROJ, '项目完整文档.md')

FILES = [
    ('scripts/mini_agent.py', 'python', '手机端小工头(任务引擎,纯标准库;看→问→做)'),
    ('scripts/mini_console.py', 'python', '控制台 v2(App 式 Web 界面 + 任务调度 + 历史/收藏)'),
    ('scripts/run.sh', 'shell', 'root 运行器(以 root 启动控制台;Termux 环境)'),
    ('scripts/supervisor-loop.sh', 'shell', '守护循环(console 60s 自愈 + portal 5min 自检自愈)'),
    ('scripts/console-autostart.sh', 'shell', 'Magisk service.d 开机启动器(秒退)'),
    ('scripts/bashrc.new', 'shell', 'Termux .bashrc(控制台离线才兜底拉起)'),
    ('scripts/fire.sh', 'shell', 'PC→Termux 发令通道(以 Termux 身份发 RUN_COMMAND)'),
    ('scripts/termux_exec.sh', 'shell', '通道工具集'),
    ('scripts/probe_portal_http.py', 'python', 'portal HTTP 连通性探针(v4/v6/localhost)'),
    ('scripts/console_post.py', 'python', '本机脚本化提交(断线实验用)'),
]

out = []
out.append('\n\n---\n\n# 附录:核心源码全文\n\n')
out.append('> 以下为运行时核心源码全文(与手机端部署版本一致),用于单文件携带与迁移。\n'
           '> 其余实验/工具脚本见第 4 节清单(位于 `scripts/` 目录)。\n')

for path, lang, desc in FILES:
    full = os.path.join(PROJ, path)
    try:
        code = open(full, encoding='utf-8').read()
    except Exception as e:
        code = '(读取失败: %r)' % (e,)
    safe = code.replace('```', '`` `')
    out.append('\n## %s\n\n**%s**\n\n```%s\n%s\n```\n' % (path, desc, lang, safe.rstrip()))

with open(DOC, 'a', encoding='utf-8') as f:
    f.write(''.join(out))

size = os.path.getsize(DOC)
print('appended ok; doc size = %.1f KB' % (size / 1024))
