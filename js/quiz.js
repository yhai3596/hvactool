/* quiz.js —— 考证小测引擎：出题 → 即时反馈 → 错因诊断报告 → 留资 CTA
 * 诊断原理：题库中每个干扰项都映射一个误区(misconception)；交卷后按误区聚类，
 * 同一误区命中 ≥2 题标记「反复出现」，全部在浏览器本地推断，无外部调用。
 * 漏斗埋点（events 表）：view(自动) → quiz_start → quiz_answer → quiz_done → quiz_lead / quiz_fb。 */
(function () {
  const $ = id => document.getElementById(id);
  const track = (t, g, v) => { try { window.hvacTrack && window.hvacTrack(t, g, v ?? null); } catch (_) { } };
  const B = window.QUIZ_BANK;
  if (!B || !B.questions || !B.questions.length) return;
  const N = B.questions.length;
  const LETTERS = 'ABCDEF';

  let idx = 0, score = 0, answered = false, done = false;
  let picks = [];   // { qid, qNo, opt(题库序), ok, mc }
  let order = [];   // 每题选项展示顺序（题库序号数组）

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------- 答题 ---------- */
  function renderQ() {
    const q = B.questions[idx];
    answered = false;
    order[idx] = shuffle(q.options.map((_, i) => i));
    $('qzCount').textContent = (idx + 1) + ' / ' + N;
    $('qzFill').style.width = (idx / N * 100) + '%';
    $('qzDomain').textContent = T('qz_domain_' + q.domain);
    $('qzQText').textContent = q.text;
    const box = $('qzOpts');
    box.innerHTML = '';
    order[idx].forEach((bi, pos) => {
      const btn = el('button', 'qz-opt');
      btn.type = 'button';
      btn.dataset.bi = bi;
      btn.appendChild(el('span', 'ltr', LETTERS[pos]));
      btn.appendChild(el('span', '', q.options[bi].t));
      btn.addEventListener('click', () => pick(bi, btn));
      box.appendChild(btn);
    });
    $('qzFb').hidden = true;
    $('qzNext').hidden = true;
  }

  function pick(bi, btn) {
    if (answered) return;
    answered = true;
    const q = B.questions[idx];
    const opt = q.options[bi];
    const ok = bi === q.answer;
    if (ok) score++;
    picks.push({ qid: q.id, qNo: idx + 1, opt: bi, ok, mc: ok ? null : (opt.mc || null) });
    track('quiz_answer', q.id + ':' + bi + ':' + (ok ? 'right' : 'wrong'));

    document.querySelectorAll('#qzOpts .qz-opt').forEach(b => {
      b.disabled = true;
      const i = +b.dataset.bi;
      if (i === q.answer) b.classList.add('is-right');
      else if (b === btn) b.classList.add('is-wrong');
    });

    const fb = $('qzFb');
    fb.className = 'qz-fb ' + (ok ? 'ok' : 'bad');
    fb.innerHTML = '';
    fb.appendChild(el('div', 'verdict', ok ? T('qz_correct') : T('qz_wrong')));
    fb.appendChild(el('div', 'qz-why', ok ? q.why : (opt.why || q.why)));
    if (!ok && opt.mc && B.misconceptions[opt.mc]) {
      const f = el('div', 'qz-flag');
      f.appendChild(el('span', '', '⚠ ' + T('qz_flag') + ': '));
      f.appendChild(el('b', '', B.misconceptions[opt.mc].name));
      fb.appendChild(f);
    }
    fb.hidden = false;

    const next = $('qzNext');
    next.textContent = idx === N - 1 ? T('qz_see_report') : T('qz_next');
    next.hidden = false;
    next.focus({ preventScroll: true });
  }

  /* ---------- 诊断报告 ---------- */
  function clusters() {
    const map = {};
    picks.forEach(p => {
      if (!p.mc || !B.misconceptions[p.mc]) return;
      (map[p.mc] = map[p.mc] || { id: p.mc, qs: [] }).qs.push(p.qNo);
    });
    return Object.values(map).sort((a, b) => b.qs.length - a.qs.length);
  }

  function report() {
    done = true;
    $('qzPlay').hidden = true;
    $('qzReport').hidden = false;
    window.scrollTo({ top: 0 });

    $('qzScore').innerHTML = '';
    $('qzScore').appendChild(document.createTextNode(score));
    $('qzScore').appendChild(el('small', '', '/' + N));
    const lv = score >= N - 1 ? 3 : score >= Math.ceil(N * .75) ? 2 : score >= Math.ceil(N * .5) ? 1 : 0;
    $('qzLevel').textContent = T('qz_lv' + lv);

    // 按主题正确率
    const bars = $('qzBars');
    bars.innerHTML = '';
    const dom = {};
    B.questions.forEach((q, i) => {
      (dom[q.domain] = dom[q.domain] || { n: 0, ok: 0 }).n++;
      if (picks[i] && picks[i].ok) dom[q.domain].ok++;
    });
    let weakest = null;
    Object.entries(dom).forEach(([d, s]) => {
      const pct = Math.round(s.ok / s.n * 100);
      if (!weakest || pct < weakest.pct) weakest = { d, pct };
      const row = el('div', 'qz-bar-row');
      row.appendChild(el('span', '', T('qz_domain_' + d)));
      const bar = el('div', 'qz-bar');
      const fill = el('i');
      fill.style.width = pct + '%';
      bar.appendChild(fill);
      row.appendChild(bar);
      row.appendChild(el('span', 'pct', s.ok + '/' + s.n));
      bars.appendChild(row);
    });

    // 误区聚类卡片
    const cl = clusters();
    const diag = $('qzDiag');
    diag.innerHTML = '';
    if (!cl.length) {
      const b = el('div', 'result-banner', T('qz_diag_none'));
      b.style.marginTop = '12px';
      diag.appendChild(b);
    } else {
      cl.forEach(c => {
        const m = B.misconceptions[c.id];
        const recurring = c.qs.length >= 2;
        const card = el('div', 'qz-diag-card' + (recurring ? '' : ' possible'));
        const head = el('div', 'head');
        head.appendChild(el('span', 'badge', recurring ? T('qz_diag_confirmed') : T('qz_diag_possible')));
        head.appendChild(el('span', 'name', m.name));
        card.appendChild(head);
        card.appendChild(el('div', 'desc', m.desc));
        const ev = el('div', 'row');
        ev.appendChild(el('b', '', T('qz_evidence') + ' '));
        ev.appendChild(document.createTextNode(c.qs.map(n => 'Q' + n).join(' · ')));
        card.appendChild(ev);
        const fx = el('div', 'row fix');
        fx.appendChild(el('b', '', T('qz_fix') + ' '));
        fx.appendChild(document.createTextNode(m.fix));
        card.appendChild(fx);
        if (m.ref) {
          const rf = el('div', 'row');
          rf.appendChild(el('b', '', T('qz_ref') + ' '));
          rf.appendChild(document.createTextNode(m.ref));
          card.appendChild(rf);
        }
        diag.appendChild(card);
      });
    }

    // 下一步建议（内容语言与题目一致：英文）
    const plan = $('qzPlan');
    plan.innerHTML = '';
    cl.slice(0, 3).forEach(c => {
      const m = B.misconceptions[c.id];
      plan.appendChild(el('li', '', m.plan || (m.name + ' — ' + (m.ref || m.fix))));
    });
    if (weakest && weakest.pct < 100) {
      plan.appendChild(el('li', '', 'Drill more "' + T('qz_domain_' + weakest.d) + '" questions — it was your weakest topic today (' + weakest.pct + '%).'));
    }
    if (!plan.children.length) {
      plan.appendChild(el('li', '', 'Keep the edge: take a timed full-length mock before your exam date.'));
    }

    track('quiz_done', score + '/' + N, score);
  }

  /* ---------- 留资 / 反馈 / 分享 ---------- */
  function sendLead(email) {
    let sid = 'nostore';
    try { sid = sessionStorage.getItem('hvac-sid') || sid; } catch (_) { }
    return fetch(SITE_CONFIG.SUPABASE_URL + '/rest/v1/events', {
      method: 'POST',
      signal: (typeof AbortSignal !== 'undefined' && AbortSignal.timeout) ? AbortSignal.timeout(10000) : undefined,
      headers: {
        'apikey': SITE_CONFIG.SUPABASE_KEY, 'Authorization': 'Bearer ' + SITE_CONFIG.SUPABASE_KEY,
        'Content-Type': 'application/json', 'Prefer': 'return=minimal',
      },
      body: JSON.stringify([{ session_id: sid, user_id: null, page: 'quiz', event_type: 'quiz_lead', target: email.slice(0, 120), value: null }]),
    }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); });
  }

  async function submitLead() {
    const input = $('qzEmail'), msg = $('qzLeadMsg'), btn = $('qzLeadBtn');
    const email = (input.value || '').trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
      msg.className = 'qz-lead-msg err';
      msg.textContent = T('qz_email_bad');
      return;
    }
    btn.disabled = true;
    try {
      await sendLead(email);
      msg.className = 'qz-lead-msg ok';
      msg.textContent = T('qz_email_ok');
      input.disabled = true;
      try { localStorage.setItem('hvac-quiz-lead', email); } catch (_) { }
    } catch (_) {
      msg.className = 'qz-lead-msg err';
      msg.textContent = T('qz_email_err');
      btn.disabled = false;
    }
  }

  function bind() {
    $('qzStart').addEventListener('click', () => {
      track('quiz_start', B.version);
      $('qzIntro').hidden = true;
      $('qzPlay').hidden = false;
      renderQ();
    });
    $('qzNext').addEventListener('click', () => {
      if (!answered) return;
      if (idx === N - 1) { $('qzFill').style.width = '100%'; report(); return; }
      idx++;
      renderQ();
    });
    $('qzLeadBtn').addEventListener('click', submitLead);
    $('qzEmail').addEventListener('keydown', e => { if (e.key === 'Enter') submitLead(); });
    $('qzFbYes').addEventListener('click', () => { track('quiz_fb', 'yes'); $('qzFbBtns').textContent = T('qz_fb_ty'); });
    $('qzFbNo').addEventListener('click', () => { track('quiz_fb', 'no'); $('qzFbBtns').textContent = T('qz_fb_ty'); });
    $('qzShare').addEventListener('click', () => {
      const cl = clusters().slice(0, 2).map(c => B.misconceptions[c.id].name);
      const txt = '2026 A2L & EPA 608 Diagnostic Quiz — I scored ' + score + '/' + N +
        (cl.length ? '. Patterns it caught in my thinking: ' + cl.join('; ') : ' (clean run!)') +
        '. Try it free: ' + location.origin + location.pathname;
      (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => {
        const b = $('qzShare');
        b.textContent = T('qz_shared');
        setTimeout(() => { b.textContent = T('qz_share'); }, 1500);
      }).catch(() => { });
    });
    $('qzRetake').addEventListener('click', () => {
      idx = 0; score = 0; answered = false; done = false; picks = []; order = [];
      $('qzReport').hidden = true;
      $('qzLeadMsg').textContent = '';
      $('qzPlay').hidden = false;
      renderQ();
    });
    // 留资框预填（同浏览器再次访问）
    try {
      const saved = localStorage.getItem('hvac-quiz-lead');
      if (saved) $('qzEmail').value = saved;
    } catch (_) { }
  }

  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', bind) : bind();
})();
