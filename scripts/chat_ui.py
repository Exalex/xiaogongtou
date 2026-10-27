# -*- coding: utf-8 -*-
"""chat_ui.py — 「对话壳」页面（v2 双视图重构）：会话历史列表 ⇄ 会话详情。
- 列表视图：分页加载（20/页 + 加载更多 + 总数）、按日期分组、搜索；
- 详情视图：独立滚动容器，点列表即切换（不再"滚过全量历史"）；含数据卡/历史对比/再跑一次；
- 返回：页面内「‹ 历史」按钮 + 安卓系统返回键（popstate）；
- 桌面（≥760px）：左右分栏（列表左 340px 常驻）。
由 mini_console.py 提供 GET /chat（不依赖任何外部资源）。"""

CHAT_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<title>对话 · 手机助手</title>
<style>
:root{
  --bg:#eef3f1;--card:#ffffff;--fg:#15211d;--mut:#66766f;
  --acc:#0f6e56;--acc-soft:rgba(15,110,86,.10);--acc-bd:rgba(15,110,86,.35);
  --red:#c04a4a;--red-soft:rgba(192,74,74,.10);
  --bd:#e0e8e4;--shadow:0 1px 3px rgba(16,42,35,.07);
  --topbg:linear-gradient(135deg,#0f6e56,#128a6f);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f1514;--card:#181f1d;--fg:#e8f1ed;--mut:#8fa29b;
  --acc:#3cc39b;--acc-soft:rgba(60,195,155,.13);--acc-bd:rgba(60,195,155,.40);
  --red:#e07a7a;--red-soft:rgba(224,122,122,.12);
  --bd:#243029;--shadow:0 1px 3px rgba(0,0,0,.35);
  --topbg:linear-gradient(135deg,#0b3d31,#0e5344);
}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;margin:0;padding:0;overflow:hidden}
body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;flex-direction:column}
button{font:inherit;color:inherit;cursor:pointer}
a{color:var(--acc);text-decoration:none}

/* ── 顶栏 ── */
.topwrap{flex:none;background:var(--topbg);padding-top:env(safe-area-inset-top)}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:10px 14px}
.brand{color:#fff;font-size:16.5px;font-weight:700}
.topact{display:flex;align-items:center;gap:9px}
.tstat{color:#d7efe6;font-size:12px}
.tbtn{display:inline-block;background:rgba(255,255,255,.16);color:#fff;border-radius:999px;padding:6px 13px;font-size:12.5px}

/* ── 双视图容器（各自独立滚动，互不干扰） ── */
.views{flex:1;min-height:0;display:flex;position:relative}
.view{flex:1;min-width:0;height:100%;overflow-y:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
#view-detail{animation:vin .18s ease}
@keyframes vin{from{opacity:.35;transform:translateY(6px)}to{opacity:1;transform:none}}
body.view-detail #view-list{display:none}
body.view-list #view-detail{display:none}

/* ── 列表视图 ── */
.lhead{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 12px 4px}
#q{width:100%;border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:12px;padding:9px 13px;font:14px inherit;outline:none}
.lmeta{display:flex;justify-content:space-between;font-size:11.5px;color:var(--mut);margin:7px 4px 3px}
#sesslist{display:flex;flex-direction:column;gap:7px;padding:0 12px}
.daydiv{font-size:11.5px;color:var(--mut);margin:9px 4px 1px}
.sitem{display:flex;align-items:center;gap:6px;background:var(--card);border:1px solid var(--bd);border-radius:13px;padding:9px 10px 9px 12px;box-shadow:var(--shadow)}
.sitem.cur{border-color:var(--acc-bd);background:var(--acc-soft)}
.sitem:active{transform:scale(.99)}
.sleft{flex:1;min-width:0}
.chev{color:var(--mut);font-size:17px;flex:none;opacity:.55;padding:0 2px}
.st1{display:flex;align-items:center;gap:7px;margin-bottom:2px}
.stime{font-size:11.5px;color:var(--mut);flex:none}
.sbadge{font-size:10.5px;font-weight:700;border-radius:999px;padding:2px 8px;flex:none}
.sbadge.ok{background:var(--acc-soft);color:var(--acc)}
.sbadge.bad{background:var(--red-soft);color:var(--red)}
.sbadge.run{background:#fff3d6;color:#8a6a12}
@media (prefers-color-scheme:dark){.sbadge.run{background:rgba(255,209,102,.18);color:#ffd166}}
.stask{font-size:13.5px;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical}
.sres{font-size:11.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.morebtn{display:block;margin:12px auto 0;border:1px dashed var(--bd);background:transparent;color:var(--acc);border-radius:999px;padding:8px 20px;font-size:13px;font-weight:600}
.morebtn[hidden]{display:none}
.lpad{height:16px}
.empty{color:var(--mut);font-size:13px;background:var(--card);border:1px dashed var(--bd);border-radius:14px;padding:16px;text-align:center}

/* ── 详情视图 ── */
.dhead{position:sticky;top:0;z-index:6;background:var(--bg);padding:9px 12px;border-bottom:1px solid var(--bd)}
.drow1{display:flex;align-items:center;gap:9px}
.back{flex:none;border:1px solid var(--bd);background:var(--card);border-radius:999px;padding:6px 13px;font-size:13px;font-weight:600}
.dtitle{flex:1;min-width:0;font-size:14px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dsub{font-size:11.5px;color:var(--mut);margin-top:3px;padding-left:2px}
.dsub:empty{display:none}
.dbody{padding:12px 12px 18px;display:flex;flex-direction:column;gap:10px}
.turn{border:1px solid var(--bd);border-radius:16px;overflow:hidden;box-shadow:var(--shadow);background:var(--card)}
.turn .u{display:flex;justify-content:flex-end;padding:10px 12px 6px}
.bubble{background:var(--acc);color:#fff;border-radius:16px 16px 4px 16px;padding:8px 13px;font-size:14px;max-width:86%;white-space:pre-wrap;word-break:break-word}
.turn .a{padding:4px 12px 12px}
.ameta{font-size:11.5px;color:var(--mut);margin:2px 0 6px}
.atext{font-size:15px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
.atext.fail{color:var(--red)}
.ds{margin-top:9px;border:1px solid var(--bd);border-radius:12px;overflow:hidden}
.dshead{display:flex;align-items:center;gap:7px;padding:7px 11px;background:var(--acc-soft);font-size:12.5px;font-weight:700;color:var(--acc)}
.dsbody{padding:6px 11px 9px}
.drow{display:flex;gap:9px;padding:4px 0;border-bottom:1px dashed var(--bd);font-size:13.5px}
.drow:last-child{border-bottom:0}
.dn{color:var(--acc);font-weight:700;flex:none;min-width:18px;text-align:right}
.acts{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.abtn{border:1px solid var(--bd);background:transparent;border-radius:999px;padding:6px 14px;font-size:12.5px;font-weight:600}
.abtn.acc{border-color:var(--acc-bd);background:var(--acc-soft);color:var(--acc)}
.live{font-size:12.5px;color:var(--mut)}
.live .lg{font:11.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;background:var(--bg);border-radius:9px;padding:8px 9px;margin-top:6px;max-height:130px;overflow:auto}
.samecard{border:1px solid var(--bd);border-radius:14px;background:var(--card);padding:10px 12px}
/* 详情视图里「历史数据对比」空态等无需外边距 */
.dbody .empty,.dbody .samecard{margin:0}

/* ── 底部（常驻输入条 + 模式） ── */
footer{flex:none;padding:6px 10px calc(10px + env(safe-area-inset-bottom))}
.fin{width:100%}
.chips{display:flex;gap:6px;justify-content:center;margin-bottom:7px;flex-wrap:wrap}
.chip{border:1px solid var(--bd);background:var(--card);border-radius:999px;padding:4px 11px;font-size:11.5px;font-weight:600;color:var(--mut)}
.chip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.chip.warn.on{background:#8a6a12;border-color:#8a6a12}
.inputrow{display:flex;gap:8px;align-items:flex-end;background:var(--card);border:1px solid var(--bd);border-radius:24px;padding:5px 5px 5px 14px;box-shadow:0 4px 18px rgba(10,30,25,.14)}
@media (prefers-color-scheme:dark){.inputrow{box-shadow:0 4px 18px rgba(0,0,0,.5)}}
#task{flex:1;border:0;outline:0;background:transparent;color:var(--fg);font:16px/1.5 inherit;resize:none;max-height:110px;padding:9px 0;overflow-y:auto}
#task::placeholder{color:var(--mut)}
.go{width:44px;height:44px;border:0;border-radius:50%;background:var(--acc);color:#fff;font-size:19px;flex:none}
.go.stop{background:var(--red)}
#hint{display:none;text-align:center;color:var(--red);font-size:12.5px;padding:6px 10px 0}

/* ── 提交飞行动画：任务胶囊从输入框飞向屏幕顶部（任务栏落点） ── */
.flypill{position:fixed;z-index:2147483000;pointer-events:none;max-width:68vw;
  background:rgba(12,21,35,.93);border:1px solid rgba(124,196,255,.55);color:#f2f7ff;
  border-radius:999px;padding:9px 15px;font-size:12.5px;line-height:1.25;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;box-shadow:0 6px 24px rgba(6,16,30,.45)}

/* ── 桌面：左右分栏（列表常驻 + 详情并排） ── */
@media (min-width:760px){
  .topbar,.views,.fin{width:100%;max-width:1080px;margin-left:auto;margin-right:auto}
  body.view-detail #view-list,body.view-list #view-detail{display:block}
  #view-list{flex:none;width:340px;border-right:1px solid var(--bd)}
  #view-detail{flex:1}
  #back{display:none}
  .dsub{padding-left:0}
}
</style>
</head>
<body class="view-list">
<div class="topwrap"><div class="topbar">
  <div class="brand">💬 对话</div>
  <div class="topact"><span class="tstat" id="runstat"></span><a class="tbtn" href="/">⌂ 控制台</a></div>
</div></div>

<div class="views">
  <!-- 列表视图 -->
  <section class="view" id="view-list">
    <div class="lhead">
      <input id="q" placeholder="搜索任务 / 结果…（如：微博）" autocomplete="off">
      <div class="lmeta"><span id="cnt"></span><span>点一条看详情</span></div>
    </div>
    <div id="sesslist"><div class="empty">加载中…</div></div>
    <button class="morebtn" id="more" hidden></button>
    <div class="lpad"></div>
  </section>

  <!-- 详情视图 -->
  <section class="view" id="view-detail">
    <div class="dhead">
      <div class="drow1">
        <button class="back" id="back">‹ 历史</button>
        <div class="dtitle" id="streamttl">会话详情</div>
      </div>
      <div class="dsub" id="streamhint"></div>
    </div>
    <div class="dbody" id="stream">
      <div class="empty">从「历史」里选一条会话，<br>或直接在下面发一句新任务 👇</div>
    </div>
  </section>
</div>

<footer><div class="fin">
  <div class="chips">
    <button class="chip" id="m-test">测试模式 · 主屏可见</button>
    <button class="chip warn" id="m-rec">录屏 ⏺</button>
    <button class="chip" id="m-prod">正式模式 · 影子屏</button>
    <button class="chip" id="m-pi" title="Pi 深度引擎：多轮工具循环（发复杂任务更会自己想办法）">Pi 深度</button>
  </div>
  <div class="inputrow">
    <textarea id="task" rows="1" enterkeyhint="send" placeholder="发新任务，比如：去微博找热搜前五…"></textarea>
    <button class="go" id="go">➤</button>
  </div>
  <div id="hint"></div>
</div></footer>

<script>
var CUR = null, POLL = null, SESS = [], TOTAL = 0, LIMIT = 20, RUNNING = false, EX = {mode:'test', rec:false}, VIEW = 'list', GOMODE = 'auto';
function $(s){ return document.querySelector(s); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function two(n){ return (n < 10 ? '0' : '') + n; }
function fmtTime(ts){
  if(!ts) return '';
  var d = new Date(ts * 1000), now = new Date();
  var same = d.toDateString() === now.toDateString();
  return (same ? '' : (two(d.getMonth()+1) + '-' + two(d.getDate()) + ' ')) + two(d.getHours()) + ':' + two(d.getMinutes());
}
function dayLabel(ts){
  if(!ts) return '更早';
  var d = new Date(ts * 1000), n = new Date();
  var t0 = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
  var t = ts * 1000;
  if(t >= t0) return '今天';
  if(t >= t0 - 86400000) return '昨天';
  return (d.getMonth()+1) + '月' + d.getDate() + '日';
}
function trunc(s, n){ s = String(s||''); return s.length > n ? s.slice(0, n) + '…' : s; }
var fT = null;
function flash(msg){
  var h = $('#hint'); h.textContent = msg; h.style.display = 'block';
  if(fT) clearTimeout(fT);
  fT = setTimeout(function(){ h.style.display = 'none'; h.textContent = ''; }, 2800);
}

/* ---------- 视图切换 ---------- */
function setView(v){
  VIEW = v;
  document.body.className = 'view-' + v;
}
function openDetail(rid, push){
  CUR = rid;
  if(push){ try{ history.pushState({v:'detail', rid:rid}, ''); }catch(e){} }
  setView('detail');
  try{ $('#view-detail').scrollTop = 0; }catch(e){}
  markCur();
  refreshDetail();
}
function goList(){
  if(history.state && history.state.v === 'detail'){ history.back(); return; }
  setView('list');
}
function applyState(st){
  if(st && st.v === 'detail'){ CUR = st.rid; setView('detail'); markCur(); refreshDetail(); }
  else { setView('list'); markCur(); }
}
window.addEventListener('popstate', function(e){ applyState(e.state); });
$('#back').onclick = goList;

/* ---------- 列表视图 ---------- */
function loadSessions(reset){
  if(reset) SESS = [];
  var q = encodeURIComponent($('#q').value.trim());
  fetch('api/sessions?limit=' + LIMIT + '&offset=' + SESS.length + '&q=' + q)
  .then(function(r){ return r.json(); }).then(function(d){
    TOTAL = (typeof d.total === 'number') ? d.total : (SESS.length + (d.items||[]).length);
    SESS = SESS.concat(d.items || []);
    renderList();
  }).catch(function(){});
}
function statBadge(s){
  var cls = s.state === 'done' ? 'ok' : (s.state === 'running' ? 'run' : 'bad');
  var stx = s.state === 'done' ? '完成' : (s.state === 'running' ? '运行中' : '未完成');
  return '<span class="sbadge ' + cls + '">' + stx + '</span>';
}
function itemHtml(s){
  var res = s.result ? ('→ ' + trunc(s.result, 52)) : (s.failed_reason ? ('→ ' + trunc(s.failed_reason, 52)) : '');
  return '<div class="sitem' + (CUR === s.rid ? ' cur' : '') + '" data-rid="' + esc(s.rid) + '">'
    + '<div class="sleft">'
    + '<div class="st1"><span class="stime">' + esc(fmtTime(s.started)) + '</span>'
    + statBadge(s)
    + (s.rec ? '<span class="stime">⏺</span>' : '')
    + (s.exec_mode && s.exec_mode !== 'test' ? '<span class="stime">副屏</span>' : '')
    + '</div>'
    + '<div class="stask">' + esc(s.task || '') + '</div>'
    + (res ? '<div class="sres">' + esc(res) + '</div>' : '')
    + '</div><div class="chev">›</div></div>';
}
function renderList(){
  var el = $('#sesslist');
  $('#cnt').textContent = TOTAL ? ('共 ' + TOTAL + ' 条') : '';
  if(!SESS.length){
    el.innerHTML = '<div class="empty">' + ($('#q').value.trim() ? '没有匹配的会话' : '还没有会话——在下面发个任务试试') + '</div>';
    $('#more').hidden = true;
    return;
  }
  var html = '', last = null;
  SESS.forEach(function(s){
    var d = dayLabel(s.started);
    if(d !== last){ html += '<div class="daydiv">' + esc(d) + '</div>'; last = d; }
    html += itemHtml(s);
  });
  el.innerHTML = html;
  var rest = TOTAL - SESS.length, mb = $('#more');
  mb.hidden = rest <= 0;
  if(rest > 0) mb.textContent = '加载更多 · 还有 ' + rest + ' 条';
}
function markCur(){
  var els = document.querySelectorAll('.sitem');
  for(var i = 0; i < els.length; i++){ els[i].classList.toggle('cur', els[i].dataset.rid === CUR); }
}
$('#sesslist').addEventListener('click', function(e){
  var it = e.target.closest('.sitem'); if(!it) return;
  openDetail(it.dataset.rid, true);
});
$('#more').onclick = function(){ $('#more').textContent = '加载中…'; loadSessions(false); };
var qt = null;
$('#q').addEventListener('input', function(){
  clearTimeout(qt); qt = setTimeout(function(){ loadSessions(true); }, 300);
});

/* ---------- 详情视图 ---------- */
function refreshDetail(){
  if(!CUR){
    $('#streamttl').textContent = '会话详情';
    $('#streamhint').textContent = '';
    $('#stream').innerHTML = '<div class="empty">从「历史」里选一条会话，<br>或直接在下面发一句新任务 👇</div>';
    return;
  }
  fetch('api/session?rid=' + encodeURIComponent(CUR)).then(function(r){ return r.json(); }).then(function(d){
    if(d.error){ $('#stream').innerHTML = '<div class="empty">没有找到这个会话</div>'; return; }
    renderSession(d);
    var st = (d.session || {}).state;
    RUNNING = st === 'running';
    renderGo();
    if(RUNNING){ startLive(); } else if(POLL){ clearInterval(POLL); POLL = null; }
    markCur();
  }).catch(function(){});
}
function renderSession(d){
  var s = d.session || {};
  $('#streamttl').textContent = s.task || '会话';
  $('#streamhint').textContent = (s.rid || '') + ' · ' + fmtTime(s.started);
  var umsg = null, amsg = null;
  (d.messages || []).forEach(function(m){
    if(m.role === 'user' && !umsg) umsg = m;
    if(m.role === 'assistant') amsg = m;
  });
  var ok = s.state === 'done';
  var meta = (ok ? '✅ 完成' : (s.state === 'running' ? '⚡ 运行中' : (s.state === 'stopped' ? '⏹ 已停止' : '⚠️ 未完成')))
    + (s.engine ? ' · 引擎 ' + s.engine : '')
    + (s.usage ? ' · ' + s.usage : '')
    + (s.ended && s.started ? ' · ' + Math.round(s.ended - s.started) + 's' : '')
    + (s.exec_mode === 'test' ? ' · 测试模式(主屏)'
       : (s.exec_mode === 'prod' ? ' · 正式模式(影子屏)' : (s.exec_mode ? ' · ' + s.exec_mode : '')));
  var html = '<div class="turn">'
    + '<div class="u"><div class="bubble">' + esc(umsg ? umsg.text : (s.task || '')) + '</div></div>'
    + '<div class="a"><div class="ameta">' + esc(meta) + '</div>';
  if(amsg){
    html += '<div class="atext' + (ok ? '' : ' fail') + '">' + esc(amsg.text) + '</div>';
  } else {
    html += '<div class="live" id="liveline">正在跑…</div>';
  }
  (d.datasets || []).forEach(function(ds){
    html += '<div class="ds"><div class="dshead">📊 ' + esc(ds.title || '数据') + ' · ' + ((ds.rows || []).length) + ' 行</div><div class="dsbody">';
    (ds.rows || []).forEach(function(r){
      html += '<div class="drow"><span class="dn">' + esc(r[0]) + '</span><span>' + esc(r[1]) + '</span></div>';
    });
    html += '</div></div>';
  });
  html += '<div class="acts">'
    + '<button class="abtn acc" id="b-again">↻ 再跑一次</button>'
    + (s.rec ? '<button class="abtn" id="b-rec">⏺ 看录屏</button>' : '')
    + '<button class="abtn" id="b-trace">🔗 链路</button>'
    + '</div></div></div>';
  if((d.same_topic || []).length){
    html += '<div class="samecard"><div class="ameta" style="margin:0 0 4px">🕘 同一任务的历史数据（点一条切换查看）</div>';
    (d.same_topic).forEach(function(x){
      html += '<div class="drow srow" data-rid="' + esc(x.rid) + '"><span class="dn">•</span><span>' + esc(fmtTime(x.started)) + ' · ' + x.count + ' 行 · ' + esc(x.rid) + '</span></div>';
    });
    html += '</div>';
  }
  $('#stream').innerHTML = html;
  var b = $('#b-again'); if(b) b.onclick = function(){ sendTask(s.task, s.mode); };
  var br = $('#b-rec'); if(br) br.onclick = function(){
    var u = '/api/rec?rid=' + encodeURIComponent(s.rid);
    if(/; wv\)/.test(navigator.userAgent)){ location.href = u; return; }  /* WebView(APK) 内不支持多窗口 → 当前页打开 */
    var w = window.open(u); if(!w){ location.href = u; }
  };
  var bt = $('#b-trace'); if(bt) bt.onclick = function(){ location.href = '/'; };
  var rows = document.querySelectorAll('#stream .srow');
  for(var i = 0; i < rows.length; i++){
    rows[i].onclick = function(){ openDetail(this.dataset.rid, true); };
  }
}
function startLive(){
  if(POLL) clearInterval(POLL);
  POLL = setInterval(function(){
    fetch('api/status').then(function(r){ return r.json(); }).then(function(d){
      if(d.state !== 'running'){
        if(POLL){ clearInterval(POLL); POLL = null; }
        RUNNING = false; renderGo();
        if(d.run_id === CUR){ refreshDetail(); }
        loadSessions(true);
        return;
      }
      var el = document.getElementById('liveline');
      if(el){ el.innerHTML = '⚡ 运行中 · 第 ' + (d.step || 0) + ' 步 · ' + Math.round(d.elapsed || 0) + 's'
        + '<div class="lg">' + esc((d.lines || []).slice(-8).join('\n')) + '</div>'; }
    }).catch(function(){});
  }, 1500);
}

/* ---------- 发送 / 停止 ---------- */
function renderGo(){
  var b = $('#go');
  b.classList.toggle('stop', RUNNING);
  b.textContent = RUNNING ? '■' : '➤';
  $('#runstat').textContent = RUNNING ? '⚡ 运行中' : '';
}
$('#go').onclick = function(){
  if(RUNNING){ fetch('api/stop', {method:'POST'}).catch(function(){}); return; }
  sendTask($('#task').value);
};
var ta = $('#task');
ta.addEventListener('input', function(){ ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 110) + 'px'; });
ta.addEventListener('keydown', function(e){
  if(e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229){ e.preventDefault(); $('#go').click(); }
});
function sendTask(text, mode){
  text = String(text || '').trim();
  if(!text){ ta.focus(); return; }
  fetch('api/run', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task: text, mode: mode || GOMODE})})
  .then(function(r){ return r.json(); })
  .then(function(d){
    if(d.error){ flash('启动失败：' + d.error); return; }
    flyToTaskbar(text);              /* 任务胶囊飞向顶部任务栏 */
    $('#task').value = ''; ta.style.height = 'auto';
    RUNNING = true; renderGo();
    openDetail(d.run_id, true);
  }).catch(function(){ flash('连不上服务'); });
}

/* 提交动画：把任务"丢到"任务栏——胶囊从输入框起飞，飞向屏幕顶部中央（任务栏落点） */
function flyToTaskbar(text){
  try{
    var r = ta.getBoundingClientRect();
    var el = document.createElement('div');
    el.className = 'flypill';
    el.textContent = text.length > 16 ? (text.slice(0, 16) + '…') : text;
    document.body.appendChild(el);
    var h = el.offsetHeight || 34;
    el.style.left = Math.round(r.left + 4) + 'px';
    el.style.top = Math.round(r.top + r.height / 2 - h / 2) + 'px';
    var sx = r.left + 4 + el.offsetWidth / 2;
    var sy = r.top + r.height / 2;
    var dx = Math.round((window.innerWidth / 2) - sx);
    var dy = Math.round(70 - sy);
    var anim = el.animate([
      {transform:'translate(0,0) scale(1)', opacity:1},
      {transform:'translate(' + Math.round(dx * 0.55) + 'px,' + Math.round(dy * 0.70) + 'px) scale(.72)', opacity:.95, offset:.6},
      {transform:'translate(' + dx + 'px,' + dy + 'px) scale(.38)', opacity:0}
    ], {duration:660, easing:'cubic-bezier(.34,.72,.28,1)', fill:'forwards'});
    anim.onfinish = function(){ try{ el.remove(); }catch(e){} };
    setTimeout(function(){ try{ el.remove(); }catch(e){} }, 1100);   /* 兜底清理 */
  }catch(e){}
}

/* ---------- 执行模式（测试/正式）+ 录屏 ---------- */
function renderEx(){
  $('#m-test').classList.toggle('on', EX.mode === 'test');
  $('#m-rec').classList.toggle('on', EX.rec);
  $('#m-prod').classList.toggle('on', EX.mode === 'prod');
}
function pushEx(){
  fetch('api/exec', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({mode: EX.mode, rec: EX.rec})}).catch(function(){});
}
$('#m-test').onclick = function(){ EX.mode = 'test'; renderEx(); pushEx(); flash('测试模式：自动化在主屏上跑（看得见）'); };
$('#m-prod').onclick = function(){
  flash('正在确认影子屏…');
  fetch('api/shadow', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'start'})}).then(function(r){ return r.json(); }).then(function(d){
    if(d.id){
      EX.mode = 'prod'; renderEx(); pushEx();
      flash('正式模式：任务在影子屏（display ' + d.id + '）上跑，主屏不受影响');
    } else {
      flash('影子屏启动失败：' + (d.out || '未知原因'));
    }
  }).catch(function(){ flash('连不上控制台'); });
};
$('#m-rec').onclick = function(){
  EX.rec = !EX.rec; renderEx(); pushEx();
  flash(EX.rec ? '录屏开：下一个任务将录制主屏（最长 179 秒）' : '录屏关');
};
$('#m-pi').onclick = function(){
  GOMODE = (GOMODE === 'pi') ? 'auto' : 'pi';
  this.classList.toggle('on', GOMODE === 'pi');
  flash(GOMODE === 'pi' ? 'Pi 深度已开：新任务走 Pi（多轮工具循环，会自己拆步骤/查证）' : '已回到默认引擎');
};

/* ---------- 启动 ---------- */
fetch('api/exec').then(function(r){ return r.json(); }).then(function(d){
  EX.mode = d.mode || 'test'; EX.rec = !!d.rec; renderEx();
}).catch(function(){});
fetch('api/status').then(function(r){ return r.json(); }).then(function(d){
  RUNNING = d.state === 'running'; renderGo();
}).catch(function(){});
loadSessions(true);
</script>
</body>
</html>
"""
