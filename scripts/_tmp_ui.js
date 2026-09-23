
var MODE = 'auto', POLL = null, ST = {state:'idle'}, FAVS = [];
function $(s){ return document.querySelector(s); }
function $$(s){ return [].slice.call(document.querySelectorAll(s)); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function two(n){ return (n < 10 ? '0' : '') + n; }
function fmtTime(ts){
  if(!ts) return '';
  var d = new Date(ts * 1000), now = new Date();
  var same = d.toDateString() === now.toDateString();
  return (same ? '' : (two(d.getMonth()+1) + '-' + two(d.getDate()) + ' ')) + two(d.getHours()) + ':' + two(d.getMinutes());
}
function trunc(s, n){ s = String(s||''); return s.length > n ? s.slice(0, n) + '…' : s; }
function isFav(task){ for(var i=0;i<FAVS.length;i++){ if(FAVS[i].task === task) return true; } return false; }

/* ---------- 顶栏状态 ---------- */
function setNet(ok, d){
  var dot = $('#dot'), tx = $('#nettext');
  if(!ok){ dot.className = 'dot bad'; tx.textContent = '服务离线'; return; }
  var llm = d && d.hb ? d.hb.llm : '-';
  if(llm === 'ok'){ dot.className = 'dot'; tx.textContent = '大脑在线'; }
  else if(llm === 'fail'){ dot.className = 'dot warn'; tx.textContent = '大脑未连上'; }
  else { dot.className = 'dot'; tx.textContent = '在线'; }
}

/* ---------- 模式 ---------- */
function setMode(m){
  MODE = m;
  $$('.mode').forEach(function(b){ b.classList.toggle('on', b.dataset.m === m); });
}
$$('.mode').forEach(function(b){ b.addEventListener('click', function(){ setMode(b.dataset.m); }); });

/* ---------- 输入框 ---------- */
var ta = $('#task');
function autosize(){
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 118) + 'px';
}
ta.addEventListener('input', autosize);
ta.addEventListener('keydown', function(e){
  if(e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229){
    e.preventDefault(); pressGo();
  }
});

/* ---------- 发送 / 停止 ---------- */
function pressGo(){
  if(ST.state === 'running'){ stopTask(); } else { sendTask(ta.value, MODE); }
}
$('#btn-go').addEventListener('click', pressGo);

function sendTask(text, mode){
  text = String(text||'').trim();
  if(!text){ ta.focus(); return; }
  if(ST.state === 'running'){ flash('已有任务在跑'); return; }
  $('#hint').style.display = 'none';
  fetch('api/run', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task: text, mode: mode || MODE})})
  .then(function(r){ return r.json(); })
  .then(function(d){
    if(d.error){ flash('启动失败：' + d.error); return; }
    ta.value = ''; autosize();
    document.getElementById('runsec').scrollIntoView({behavior:'smooth', block:'start'});
    startPoll(true);
  })
  .catch(function(){ showHint(); });
}
function stopTask(){
  fetch('api/stop', {method:'POST'}).catch(function(){});
}
var flashT = null;
function flash(msg){
  var h = $('#hint'); h.textContent = msg; h.style.display = 'block';
  if(flashT) clearTimeout(flashT);
  flashT = setTimeout(function(){ h.style.display = 'none'; h.textContent = ''; }, 2500);
}
function showHint(){
  $('#hint').style.display = 'block';
  if(flashT) clearTimeout(flashT);
  flashT = setTimeout(function(){ $('#hint').style.display = 'none'; }, 6000);
}

/* ---------- 状态轮询 ---------- */
function startPoll(){
  if(POLL) clearInterval(POLL);
  POLL = setInterval(tick, 1200);
  tick();
}
function tick(){
  fetch('api/status').then(function(r){ return r.json(); }).then(function(d){
    ST = d;
    setNet(true, d);
    renderRun(d);
    var running = d.state === 'running';
    var btn = $('#btn-go');
    btn.classList.toggle('stop', running);
    btn.textContent = running ? '■' : '➤';
    if(running){ if(!POLL){ POLL = setInterval(tick, 1200); } }
    else {
      if(POLL){ clearInterval(POLL); POLL = null; }
      if(d.state === 'done' || d.state === 'failed' || d.state === 'stopped'){ loadHistory(); }
    }
  }).catch(function(){
    setNet(false);
  });
}

/* ---------- 运行卡 ---------- */
function renderRun(d){
  var card = $('#runcard'), ttl = $('#runttl');
  if(d.state === 'running'){
    ttl.textContent = '⚡ 运行中';
    var meta = '引擎 ' + (d.engine || '…') + ' · 第 ' + (d.step || 0) + ' 步 · ' + Math.round(d.elapsed || 0) + 's';
    card.innerHTML = '<div class="rtop"><span class="badge run">运行中</span><span class="rmeta">' + esc(meta) + '</span>'
      + '<button class="rbtn" id="btn-trace-run" style="margin-left:auto;padding:5px 13px;font-size:12px">🔗 链路</button></div>'
      + '<div class="rtask">' + esc(d.task) + '</div>'
      + '<pre class="rlog">' + esc((d.lines || []).slice(-12).join('\n')) + '</pre>';
    var rl = card.querySelector('.rlog'); if(rl){ rl.scrollTop = rl.scrollHeight; }
    var bt = card.querySelector('#btn-trace-run'); if(bt){ bt.onclick = function(){ showTrace(d.run_id); }; }
    return;
  }
  if(d.state === 'done' || d.state === 'failed' || d.state === 'stopped'){
    var ok = d.state === 'done';
    ttl.textContent = ok ? '✅ 完成' : (d.state === 'stopped' ? '⏹ 已停止' : '⚠️ 未完成');
    var head = '<div class="rtop"><span class="badge ' + (ok ? 'ok' : 'bad') + '">'
      + (ok ? '完成' : (d.state === 'stopped' ? '已停止' : '未完成')) + '</span>'
      + '<span class="rmeta">' + Math.round(d.elapsed || 0) + 's'
      + (d.engine ? ' · 引擎 ' + esc(d.engine) : '')
      + (d.usage ? ' · ' + esc(d.usage) : '') + '</span></div>'
      + '<div class="rtask">' + esc(d.task) + '</div>';
    var body = '';
    if(d.result){ body += '<div class="result' + (ok ? '' : ' fail') + '">' + esc(d.result) + '</div>'; }
    else if(!ok && d.failed_reason){ body += '<div class="result fail" style="font-size:15px">' + esc(d.failed_reason) + '</div>'; }
    var faved = isFav(d.task);
    body += '<div class="ractions">'
      + '<button class="rbtn acc" id="btn-again">↻ 再跑一次</button>'
      + '<button class="rbtn' + (faved ? ' acc' : '') + '" id="btn-fav">' + (faved ? '★ 已收藏' : '☆ 收藏') + '</button>'
      + '<button class="rbtn" id="btn-trace-done">🔗 链路</button>'
      + '</div>';
    card.innerHTML = head + body;
    var bAgain = card.querySelector('#btn-again'), bFav = card.querySelector('#btn-fav');
    if(bAgain) bAgain.onclick = function(){ sendTask(d.task, d.mode); };
    if(bFav) bFav.onclick = function(){ toggleFav(d.task, d.mode); };
    var bTr = card.querySelector('#btn-trace-done'); if(bTr){ bTr.onclick = function(){ showTrace(d.run_id); }; }
    return;
  }
  ttl.textContent = '🏠 当前任务';
  card.innerHTML = '<div class="idlebox">还没有运行中的任务。<b>说一句话</b>，让手机自己去做 👇</div>';
}

/* ---------- 收藏 ---------- */
function loadFavs(){
  fetch('api/favorites').then(function(r){ return r.json(); }).then(function(d){
    FAVS = d.items || [];
    renderFavs();
  }).catch(function(){});
}
function renderFavs(){
  var el = $('#favwrap');
  if(!FAVS.length){
    el.innerHTML = '<div class="favwrap-empty">把常做的任务收藏到这里（历史记录里点 ☆ 收藏）</div>';
    return;
  }
  el.innerHTML = FAVS.map(function(f){
    return '<button class="fav" data-task="' + esc(f.task) + '" data-mode="' + esc(f.mode || 'auto') + '" title="' + esc(f.task) + '">'
      + esc(trunc(f.task, 12)) + '</button>';
  }).join('');
}
function toggleFav(task, mode){
  var has = isFav(task);
  var url = has ? 'api/favorites/del' : 'api/favorites';
  fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task: task, mode: mode || MODE})})
  .then(function(r){ return r.json(); })
  .then(function(){
    loadFavs();
    renderRun(ST);
  }).catch(function(){});
}
/* 收藏 chips：点一下就跑；长按删除 */
var lpT = null, lpFired = false;
var favWrap = $('#favwrap');
favWrap.addEventListener('pointerdown', function(e){
  var c = e.target.closest('.fav'); if(!c) return;
  lpFired = false;
  lpT = setTimeout(function(){
    lpFired = true;
    if(confirm('删除这个常用？\n「' + c.dataset.task + '」')){ toggleFav(c.dataset.task, c.dataset.mode); }
  }, 550);
});
['pointerup','pointerleave','pointercancel'].forEach(function(ev){
  favWrap.addEventListener(ev, function(){ if(lpT){ clearTimeout(lpT); lpT = null; } });
});
favWrap.addEventListener('click', function(e){
  var c = e.target.closest('.fav'); if(!c) return;
  if(lpFired){ e.preventDefault(); return; }
  sendTask(c.dataset.task, c.dataset.mode);
});

/* ---------- 历史 ---------- */
function loadHistory(){
  fetch('api/history').then(function(r){ return r.json(); }).then(function(items){
    var el = $('#histlist');
    if(!items || !items.length){ el.innerHTML = '<div class="empty">跑过的任务会出现在这里</div>'; return; }
    el.innerHTML = items.map(function(it, idx){
      var st = it.state === 'done' ? 'ok' : (it.state === 'running' ? 'run' : 'bad');
      var stx = it.state === 'done' ? '完成' : (it.state === 'running' ? '运行中' : (it.state === 'stopped' ? '已停止' : '未完成'));
      var res = it.result ? ('→ ' + trunc(it.result, 30)) : (it.failed_reason ? ('→ ' + trunc(it.failed_reason, 30)) : '');
      return '<div class="hitem" data-idx="' + idx + '">'
        + '<div class="htop"><span class="htime">' + esc(fmtTime(it.started)) + '</span>'
        + '<span class="hbadge ' + st + '">' + stx + '</span>'
        + '<span class="hres">' + esc(res) + '</span></div>'
        + '<div class="hmain"><span class="htask">' + esc(it.task || '') + '</span>'
        + '<span class="hacts">'
        + '<button class="hstar' + (isFav(it.task) ? ' staron' : '') + '" data-act="star">' + (isFav(it.task) ? '★' : '☆') + '</button>'
        + '<button data-act="replay">↻</button>'
        + '</span></div></div>';
    }).join('');
    el._items = items;
  }).catch(function(){});
}
$('#histlist').addEventListener('click', function(e){
  var item = e.target.closest('.hitem'); if(!item) return;
  var data = $('#histlist')._items || [];
  var it = data[Number(item.dataset.idx)]; if(!it) return;
  var act = e.target.closest('button');
  if(act){
    if(act.dataset.act === 'star'){ toggleFav(it.task, it.mode); return; }
    if(act.dataset.act === 'replay'){ sendTask(it.task, it.mode); return; }
    return;
  }
  ta.value = it.task || ''; autosize(); ta.focus();
});

/* ---------- 调试模式（🐞 开关 + 执行链路查看） ---------- */
var DBG = false;
function toastMsg(t){
  var el = $('#toast'); if(!el) return;
  el.textContent = t; el.style.display = 'block';
  clearTimeout(toastMsg._t);
  toastMsg._t = setTimeout(function(){ el.style.display = 'none'; }, 2600);
}
function renderDbg(){
  var b = $('#dbgbtn'); if(!b) return;
  b.className = 'dbgbtn' + (DBG ? ' on' : '');
  b.title = DBG ? '调试模式：已开（手机上将出现半透明调试窗）' : '调试模式：已关（点按开启）';
}
function setDbg(on, silent){
  fetch('api/debug', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({on: on})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      DBG = !!d.on; renderDbg();
      if(!silent){
        toastMsg(DBG ? '调试已开：手机上将出现半透明调试窗；本页点「🔗 链路」看完整细节'
                     : '调试已关');
      }
    })
    .catch(function(){ if(!silent) toastMsg('设置失败（服务离线？）'); });
}
$('#dbgbtn').onclick = function(){ setDbg(!DBG); };
fetch('api/debug').then(function(r){ return r.json(); })
  .then(function(d){ DBG = !!d.on; renderDbg(); }).catch(function(){});

/* —— 音量键快捷键开关（默认开：按一下唤起面板 / 再按一下执行） —— */
var HK = true;
function renderHk(){
  var b = $('#hkbtn'); if(!b) return;
  b.className = 'dbgbtn' + (HK ? ' on' : '');
  b.title = HK ? '音量键快捷键：已开（按一下唤起 / 再按执行）' : '音量键快捷键：已关（音量键恢复普通调节）';
}
$('#hkbtn').onclick = function(){
  fetch('api/hotkey', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({on: !HK})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      HK = !!d.on; renderHk();
      toastMsg(HK ? '音量键快捷键已开：按一下「音量下」唤起面板，再按一下执行'
                  : '音量键快捷键已关（音量键恢复普通调节）');
    })
    .catch(function(){ toastMsg('设置失败（服务离线？）'); });
};
fetch('api/hotkey').then(function(r){ return r.json(); })
  .then(function(d){ HK = !!d.on; renderHk(); }).catch(function(){});

var traceFrom = 0, traceRid = null;
function showTrace(rid){
  traceRid = rid || null;
  traceFrom = 0;
  $('#tracepre').textContent = '加载中…';
  $('#tracebox').classList.add('show');
  loadTrace(true);
}
function closeTrace(){ $('#tracebox').classList.remove('show'); }
$('#traceclose').onclick = closeTrace;
$('#tracebox').onclick = function(e){ if(e.target === $('#tracebox')) closeTrace(); };
function fmtTrace(lines){
  var out = [];
  lines.forEach(function(r){
    var k = r.kind || 'text';
    var tag = {prompt:'▶ 输入(prompt)', reply:'◀ 返回(reply)', action:'⚡ 动作',
               result:'✓ 结果', done:'🏁 完成'}[k] || k;
    var head = (r.step ? ('第' + r.step + '步 ') : '') + tag + (r.engine ? (' [' + r.engine + ']') : '');
    if(r.ms != null){ head += ' ' + r.ms + 'ms'; }
    if(r.ok === false){ head += ' ✗'; }
    var txt = String(r.text == null ? '' : r.text);
    if(txt.length > 700){ txt = txt.slice(0, 700) + ' …'; }
    out.push(head + '\n' + txt);
  });
  return out.join('\n\n');
}
function loadTrace(reset){
  var url = 'api/trace?limit=1000&from=' + (reset ? 0 : traceFrom)
    + (traceRid ? ('&rid=' + encodeURIComponent(traceRid)) : '');
  fetch(url).then(function(r){ return r.json(); })
    .then(function(d){
      if(reset){ $('#tracepre').textContent = ''; }
      if(!d.lines || !d.lines.length){
        if(reset){ $('#tracepre').textContent = '（这条任务还没有链路记录）'; }
        return;
      }
      traceFrom = d.next || (traceFrom + d.lines.length);
      var pre = $('#tracepre');
      pre.textContent += (pre.textContent ? '\n\n' : '') + fmtTrace(d.lines);
      pre.scrollTop = pre.scrollHeight;
    })
    .catch(function(){ if(reset){ $('#tracepre').textContent = '加载失败（服务离线？）'; } });
}

/* ---------- 启动 ---------- */
loadFavs();
loadHistory();
fetch('api/status').then(function(r){ return r.json(); }).then(function(d){
  ST = d; setNet(true, d); renderRun(d);
  if(d.state === 'running'){ startPoll(true); }
}).catch(function(){ setNet(false); });
