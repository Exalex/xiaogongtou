
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
