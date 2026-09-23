(function () {
  var state = null;
  var firstRender = true;      // 首次渲染才做逐行渐入，避免每 60 秒刷新时抖动
  var TICK_MS = 1000;

  function pad(n, w) { n = String(n); while (n.length < w) n = '0' + n; return n; }

  function leftText(sec) {
    if (sec === null || sec === undefined) return '—';
    var neg = sec < 0, s = Math.abs(Math.round(sec));
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
        m = Math.floor(s % 3600 / 60), ss = s % 60;
    var body = d > 0 ? (d + '天 ' + pad(h, 2) + ':' + pad(m, 2) + ':' + pad(ss, 2))
                     : (pad(h, 2) + ':' + pad(m, 2) + ':' + pad(ss, 2));
    return (neg ? '逾期 ' : '') + body;
  }

  function level(h) {
    var l = h.left_seconds;
    if (l === null || l === undefined) return 'lv-ok';
    if (l < 0) return 'lv-bad';
    if (l <= 3600) return 'lv-bad';
    if (l <= 21600) return 'lv-hot';
    if (l <= 86400) return 'lv-soon';
    return 'lv-ok';
  }

  function badge(h) {
    if (!h.unsubmitted) return '<span class="badge ok">已提交</span>';
    var l = h.left_seconds;
    if (l === null || l === undefined) return '<span class="badge">未提交</span>';
    if (l < 0) return '<span class="badge bad">已逾期</span>';
    if (l <= 3600) return '<span class="badge bad">紧急</span>';
    if (l <= 21600) return '<span class="badge hot">6h</span>';
    if (l <= 86400) return '<span class="badge warn">24h</span>';
    return '<span class="badge">未提交</span>';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c];
    });
  }

  function render() {
    if (!state) return;
    var st = state.stats || {};
    document.getElementById('s-unsub').textContent = st.unsubmitted;
    document.getElementById('s-24').textContent = st.within_24h;
    document.getElementById('s-6').textContent = st.within_6h;
    document.getElementById('s-over').textContent = st.overdue;
    document.getElementById('s-done').textContent = st.submitted;
    document.getElementById('s-total').textContent = st.total;

    // 构成比例条：24h 内 / 其余未提交 / 已提交 / 已逾期
    var dist = document.getElementById('dist');
    if (dist) {
      var segs = [
        ['d-24', st.within_24h || 0],
        ['d-un', Math.max(0, (st.unsubmitted || 0) - (st.within_24h || 0))],
        ['d-ok', st.submitted || 0],
        ['d-od', st.overdue || 0]
      ];
      dist.innerHTML = segs.map(function (s) {
        return s[1] ? '<i class="' + s[0] + '" style="flex:' + s[1] + '"></i>' : '';
      }).join('');
    }

    var rows = (state.homeworks || []).slice();
    // 班级过滤由设置页配置、后端执行（不匹配的记录根本不返回），这里只做"只看能提交的"。
    var onlySub = document.getElementById('only-submittable');
    var filtering = onlySub && onlySub.checked;
    if (filtering) {
      rows = rows.filter(function (h) { return h.unsubmitted && h.can_submit; });
    }
    var tb = document.getElementById('rows');
    var hint = document.getElementById('tablehint');
    var hd = state.hidden || {};
    var hidParts = [];
    if (hd.ancient) hidParts.push(hd.ancient + ' 条逾期超 ' + (hd.days || 80) + ' 天的旧记录');
    if (hd.other_class) hidParts.push(hd.other_class + ' 条其他班的实验时段');
    var hidTxt = hidParts.length ? ('，已隐藏 ' + hidParts.join('、')) : '';
    if (hint) {
      hint.textContent = (filtering
        ? ('已过滤：' + rows.length + ' 条可提交 / 共 ' + (state.homeworks || []).length + ' 条记录')
        : ('共 ' + (state.homeworks || []).length + ' 条记录')) + hidTxt;
    }
    if (!rows.length) {
      tb.innerHTML = '<tr><td colspan="6" class="empty">' +
        (filtering ? '当前没有可提交的作业。取消勾选可查看全部记录。' : '尚未扫描。点右上角「立即扫描」。') +
        hidTxt + '</td></tr>';
    } else {
      tb.innerHTML = rows.map(function (h, i) {
        var id = h.course_id + ':' + h.hwtid;
        var conf = (h.confidence && h.confidence !== 'high')
          ? ' <span class="badge">待确认</span>' : '';
        var code = h.class_code ? '<span class="code">' + esc(h.class_code) + '</span>' : '';
        var ls = h.left_seconds;
        var leftCls = 'left' + (ls != null && ls < 0 ? ' over' : '');
        var anim = firstRender ? (' anim" style="animation-delay:' + Math.min(i, 24) * 16 + 'ms') : '';
        var href = '/homework/' + encodeURIComponent(h.course_id) + '/' + encodeURIComponent(h.hwtid);
        return '<tr class="' + level(h) + anim + '" data-key="' + esc(id) + '" data-left="' + (ls == null ? '' : ls) + '">'
          + '<td class="course" title="' + esc(h.course_name) + '">' + esc(h.course_name) + code + '</td>'
          + '<td class="title"><a href="' + href + '">' + esc(h.title) + '</a>' + conf + '</td>'
          + '<td class="ddl">' + esc(h.ddl_raw || '—') + '</td>'
          + '<td class="' + leftCls + '">' + leftText(ls) + '</td>'
          + '<td>' + badge(h) + '</td>'
          + '<td class="act">' + (h.unsubmitted ? '<a class="btn" href="' + href + '">提交</a>' : '') + '</td>'
          + '</tr>';
      }).join('');
      firstRender = false;
    }

    var ls = state.last_scan || {};
    var meta = document.getElementById('scanmeta');
    var busy = state.scanning ? ' · 扫描中…' : '';
    if (ls.at) {
      meta.textContent = '上次扫描 ' + ls.at.replace('T', ' ').slice(5, 16)
        + ' · ' + (ls.courses || 0) + ' 门课 / ' + (ls.homeworks || 0) + ' 个作业'
        + (ls.throttled ? ' · 被限流' : '') + busy;
    } else {
      meta.textContent = state.scanning ? '扫描中…' : '尚未扫描';
    }

    /* 按钮状态由 state.scanning 单一来源驱动：扫描要跑两三分钟，
       期间保持禁用并显示进度，结束后自动恢复 —— 不会出现"点了没反应" */
    var bs = document.getElementById('btn-scan');
    if (bs) {
      bs.disabled = !!state.scanning;
      bs.textContent = state.scanning ? '扫描中…' : '立即扫描';
    }
    var br = document.getElementById('btn-relogin');
    if (br) br.disabled = !!state.scanning;

    var dot = document.getElementById('sessdot'), txt = document.getElementById('sesstext');
    var lg = state.login || {};
    if (lg.last_login_ok) { dot.className = 'dot on'; txt.textContent = '会话 ' + lg.last_login_ok.slice(5, 16); }
    else if (lg.lockout_until) { dot.className = 'dot off'; txt.textContent = '账号锁定中'; }
    else { dot.className = 'dot warn'; txt.textContent = '会话未知'; }
  }

  function tick() {
    if (!state || !state.homeworks) return;
    var rows = document.querySelectorAll('#rows tr[data-left]');
    for (var i = 0; i < rows.length; i++) {
      var v = rows[i].getAttribute('data-left');
      if (v === '') continue;
      var left = parseInt(v, 10) - 1;
      rows[i].setAttribute('data-left', left);
      rows[i].querySelector('td.left').textContent = leftText(left);
    }
    for (var j = 0; j < state.homeworks.length; j++) {
      if (state.homeworks[j].left_seconds != null) state.homeworks[j].left_seconds -= 1;
    }
  }

  async function refresh() {
    var r = await fetch('/api/state');
    state = await r.json();
    state.scanning = state.scanning || false;
    render();
  }

  function pushFeed(ev) {
    var box = document.getElementById('feed');
    if (!box) return;
    if (box.querySelector('.empty')) box.innerHTML = '';
    var div = document.createElement('div');
    div.className = 'feed-item';
    var t = (ev.created_at || '').replace('T', ' ').slice(5, 19);
    div.innerHTML = '<div class="t">' + esc(t) + '</div>'
      + (ev.title ? '<div class="h">' + esc(ev.title) + '</div>' : '')
      + (ev.body ? '<div class="b">' + esc(ev.body) + '</div>' : '')
      + (ev.kind === 'scan_done' ? '<div class="t">扫描完成：' + (ev.homeworks || 0) + ' 个作业</div>' : '');
    box.insertBefore(div, box.firstChild);
  }

  function initSSE() {
    try {
      var es = new EventSource('/api/events');
      es.onmessage = function (e) {
        var ev = JSON.parse(e.data);
        if (ev.kind === 'notify' || ev.kind === 'scan_done' || ev.kind === 'scan_error') pushFeed(ev);
        if (ev.kind === 'scan_done' || ev.kind === 'scan_error') refresh();
      };
    } catch (err) { /* 老浏览器忽略 */ }
  }

  /* 按钮忙碌态：官网风格是等宽大写短标签，不做花哨动画 */
  function busyStart(el, label) {
    el.disabled = true;
    el.dataset.idle = label;
    el.textContent = label;
  }
  function busyStop(el) {
    el.disabled = false;
    el.textContent = el.dataset.idle || el.textContent;
  }

  var btnScan = document.getElementById('btn-scan');
  if (btnScan) btnScan.onclick = async function () {
    if (this.disabled) return;
    var meta = document.getElementById('scanmeta');
    var msg = '';
    try {
      var r = await fetch('/api/scan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csrf: window.CSRF })
      });
      var j = await r.json().catch(function () { return { ok: false, err: 'HTTP ' + r.status }; });
      if (j.ok === false) msg = j.err || '启动失败';
    } catch (e) {
      msg = '请求失败：' + e.message;
    }
    /* 扫描要跑两三分钟：按 1.5s/8s/20s/45s 各刷一次，读数与列表逐步跟上 */
    setTimeout(refresh, 1500); setTimeout(refresh, 8000);
    setTimeout(refresh, 20000); setTimeout(refresh, 45000);
    if (msg) {
      meta.textContent = '✗ ' + msg;
      meta.style.color = 'var(--danger)';
      this.disabled = false; this.textContent = '立即扫描';
    }
  };

  var btnRe = document.getElementById('btn-relogin');
  if (btnRe) btnRe.onclick = async function () {
    busyStart(btnRe, '登录中…');
    try {
      var r = await fetch('/api/diagnostics/relogin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csrf: window.CSRF })
      });
      var j = await r.json().catch(function () { return { ok: false, err: 'HTTP ' + r.status }; });
      alert(j.ok ? '重新登录成功' : ('失败：' + (j.err || '未知错误')));
      refresh();
    } catch (e) {
      alert('请求失败：' + e.message);
    } finally { busyStop(btnRe); }
  };

  refresh();
  setInterval(tick, TICK_MS);
  setInterval(refresh, 60000);
  initSSE();
  var onlySub = document.getElementById('only-submittable');
  if (onlySub) onlySub.onchange = render;
})();
