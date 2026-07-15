/* quiz.js —— 考证小测引擎：出题 → 即时反馈 → 错因诊断报告 → 留资 CTA
 * 诊断原理：题库中每个干扰项都映射一个误区(misconception)；交卷后按误区聚类，
 * 同一误区命中 ≥2 题标记「反复出现」，全部在浏览器本地推断，无外部调用。
 * 出题策略：题库 40 题分 9 个板块；每次作答按板块分层抽样（每板块最多 QUOTA 题，
 * 不足则取全部），抽样结果再整体打乱顺序 —— 每次/每次重测题目组合都不同，控制单次时长。
 * 漏斗埋点（events 表）：view(自动) → quiz_start → quiz_answer → quiz_done → quiz_lead / quiz_fb。 */
(function () {
  const $ = id => document.getElementById(id);
  const track = (t, g, v) => { try { window.hvacTrack && window.hvacTrack(t, g, v ?? null); } catch (_) { } };
  const QUOTA_PER_DOMAIN = 2;
  const LETTERS = 'ABCDEF';

  /* ---------- 题库装载：manifest + 板块分片按需并行拉取（编写源 js/quiz-bank.js 不再入页） ---------- */
  let B = null;       // { version, total, misconceptions }
  let POOLS = null;   // domain -> questions[]
  let bankPromise = null;
  function fetchJson(url) {
    return fetch(url).then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
      return r.json();
    });
  }
  function loadBank() {
    if (!bankPromise) {
      bankPromise = (async () => {
        const mf = await fetchJson('bank/manifest.json?v=228');
        const shards = await Promise.all(mf.domains.map(d => fetchJson('bank/' + d.file + '?v=228')));
        const pools = {};
        shards.forEach(s => { pools[s.domain] = s.questions; });
        B = { version: mf.version, total: mf.total, misconceptions: mf.misconceptions };
        POOLS = pools;
      })().catch(e => { bankPromise = null; throw e; });
    }
    return bankPromise;
  }

  let Q = [];   // 本次作答抽样出的题目子集（长度 = N）
  let N = 0;
  let idx = 0, score = 0, answered = false, done = false;
  let picks = [];   // { qid, qNo, opt(题库序), ok, mc }
  let order = [];   // 每题选项展示顺序（题库序号数组）
  let authUser = null;   // 由 hvac-auth-ready 事件更新，供 AI 深挖判断登录态
  window.addEventListener('hvac-auth-ready', e => { authUser = (e.detail && e.detail.user) || null; });

  /* ---------- 本地错题本（Leitner-lite，localStorage，匿名可用） ----------
   * 每题记 { w:答错次数, r:答对次数, streak:连对次数, ts }；
   * 「曾答错且未连对 2 次」= 待复习（due）→ 抽样时同板块内优先出现；连对 2 次视为已掌握。
   * attempts 记最近 20 次成绩，供首屏进度与报告页「较上次」。 */
  const HIST_KEY = 'hvac-quiz-hist';
  function loadHist() {
    try {
      const j = JSON.parse(localStorage.getItem(HIST_KEY));
      if (j && j.q && Array.isArray(j.attempts)) return j;
    } catch (_) { }
    return { q: {}, attempts: [] };
  }
  function saveHist() { try { localStorage.setItem(HIST_KEY, JSON.stringify(HIST)); } catch (_) { } }
  const HIST = loadHist();
  const isDue = qid => { const h = HIST.q[qid]; return !!(h && h.w > 0 && h.streak < 2); };
  function recordAnswer(qid, ok) {
    const h = HIST.q[qid] || (HIST.q[qid] = { w: 0, r: 0, streak: 0 });
    if (ok) { h.r++; h.streak++; } else { h.w++; h.streak = 0; }
    h.ts = Date.now();
    saveHist();
  }
  function renderIntroProgress() {
    const el = $('qzProgress');
    if (!el) return;
    const last = HIST.attempts[HIST.attempts.length - 1];
    if (!last) { el.hidden = true; return; }
    let due = 0;
    if (POOLS) Object.values(POOLS).forEach(list => list.forEach(q => { if (isDue(q.id)) due++; }));
    else due = Object.keys(HIST.q).filter(isDue).length;
    el.hidden = false;
    el.textContent = due > 0 ? T('qz_prev_line', { s: last.s, n: last.n, due }) : T('qz_prev_line0', { s: last.s, n: last.n });
  }

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  /* 按板块分层抽样：同板块内「待复习错题」优先、新题随机补位，每板块取 QUOTA_PER_DOMAIN 题
   * （不足则全取），各板块结果拼接后整体再 shuffle 一次，避免题目按板块扎堆出现。 */
  function sampleQuestions() {
    const picked = [];
    Object.values(POOLS).forEach(list => {
      const due = [], fresh = [];
      list.forEach(q => {
        const d = isDue(q.id);
        q._due = d;               // 抽样时点快照，供答题界面标「复习」徽标
        (d ? due : fresh).push(q);
      });
      picked.push(...shuffle(due).concat(shuffle(fresh)).slice(0, QUOTA_PER_DOMAIN));
    });
    return shuffle(picked);
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------- 答题 ---------- */
  function renderQ() {
    const q = Q[idx];
    answered = false;
    order[idx] = shuffle(q.options.map((_, i) => i));
    $('qzCount').textContent = (idx + 1) + ' / ' + N;
    $('qzFill').style.width = (idx / N * 100) + '%';
    $('qzDomain').textContent = T('qz_domain_' + q.domain);
    $('qzReview').hidden = !q._due;
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
    const q = Q[idx];
    const opt = q.options[bi];
    const ok = bi === q.answer;
    if (ok) score++;
    picks.push({ qid: q.id, qNo: idx + 1, opt: bi, ok, mc: ok ? null : (opt.mc || null) });
    recordAnswer(q.id, ok);
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
    if (!ok) fb.appendChild(buildAiBox(q, opt));
    fb.hidden = false;

    const next = $('qzNext');
    next.textContent = idx === N - 1 ? T('qz_see_report') : T('qz_next');
    next.hidden = false;
    next.focus({ preventScroll: true });
  }

  /* ---------- AI 深挖（登录 + 积分门；同源代理优先，回退直连 Edge Function） ---------- */
  async function callQuizAi(payload, accessToken) {
    try {
      const r = await fetch('api/fn/quiz-ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + accessToken },
        body: JSON.stringify(payload),
      });
      if (r.status === 404 || r.status === 501 || r.status === 502 || r.status === 504) throw new Error('proxy-unavailable');
      return { status: r.status, data: await r.json() };
    } catch (e) {
      if (String(e && e.message) === 'proxy-unavailable' || e instanceof TypeError) {
        const { data, error } = await window.sbClient.functions.invoke('quiz-ai', { body: payload });
        if (!error) return { status: 200, data };
        let biz = null, status = 500;
        try { biz = await error.context.json(); status = error.context.status || 500; } catch (_) { }
        return { status, data: biz || { error: 'network' } };
      }
      throw e;
    }
  }

  function buildAiBox(q, opt) {
    const wrap = el('div', 'qz-ai');
    const btn = el('button', 'btn ghost small qz-ai-btn', '🤖 ' + T('qz_ai_btn'));
    btn.type = 'button';
    btn.dataset.track = 'quiz_ai_deepdive';
    const resultBox = el('div', 'qz-ai-result');
    resultBox.hidden = true;
    wrap.appendChild(btn);
    wrap.appendChild(resultBox);

    btn.addEventListener('click', async () => {
      track('quiz_ai_click', q.id);
      if (!authUser || !window.sbClient) {
        resultBox.hidden = false;
        resultBox.className = 'qz-ai-result note';
        resultBox.innerHTML = T('qz_ai_login_html', { next: encodeURIComponent(location.pathname.split('/').pop()) });
        return;
      }
      btn.disabled = true;
      btn.textContent = '🤖 ' + T('qz_ai_loading');
      resultBox.hidden = false;
      resultBox.className = 'qz-ai-result';
      resultBox.textContent = T('qz_ai_loading');
      try {
        const { data: { session } } = await window.sbClient.auth.getSession();
        if (!session) throw { code: 'no_session' };
        const payload = {
          question: q.text, chosenText: opt.t,
          correctText: q.options[q.answer].t,
          shortWhy: opt.why || q.why,
          mcName: opt.mc && B.misconceptions[opt.mc] ? B.misconceptions[opt.mc].name : '',
          mcFix: opt.mc && B.misconceptions[opt.mc] ? B.misconceptions[opt.mc].fix : '',
          lang: (window.I18N && I18N.lang && I18N.lang()) || 'en',
        };
        const { status, data } = await callQuizAi(payload, session.access_token);
        if (status === 200 && data && data.ok) {
          resultBox.className = 'qz-ai-result ok';
          resultBox.innerHTML = '';
          resultBox.appendChild(el('div', 'qz-ai-text', data.explanation));
          resultBox.appendChild(el('div', 'qz-ai-credits', T('qz_ai_credits_left', { n: data.credits_left })));
          btn.remove();
          track('quiz_ai_ok', q.id, data.credits_left);
        } else if (status === 402) {
          resultBox.className = 'qz-ai-result err';
          resultBox.textContent = T('qz_ai_insufficient', { need: (data && data.need) || 15, have: (data && data.have) || 0 });
          btn.disabled = false; btn.textContent = '🤖 ' + T('qz_ai_btn');
        } else if (status === 429) {
          resultBox.className = 'qz-ai-result err';
          resultBox.textContent = T('qz_ai_rate_limited');
          btn.disabled = false; btn.textContent = '🤖 ' + T('qz_ai_btn');
        } else if (status === 503 || (data && data.error === 'ai_not_configured')) {
          resultBox.className = 'qz-ai-result err';
          resultBox.textContent = T('qz_ai_not_configured');
          btn.disabled = false; btn.textContent = '🤖 ' + T('qz_ai_btn');
        } else {
          resultBox.className = 'qz-ai-result err';
          resultBox.textContent = T('qz_ai_error');
          btn.disabled = false; btn.textContent = '🤖 ' + T('qz_ai_btn');
        }
      } catch (e) {
        resultBox.hidden = false;
        resultBox.className = 'qz-ai-result err';
        resultBox.textContent = T('qz_ai_error');
        btn.disabled = false; btn.textContent = '🤖 ' + T('qz_ai_btn');
      }
    });
    return wrap;
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

    // 较上次（先取上一次记录再写入本次；样本不同仅作趋势参考）
    const prev = HIST.attempts[HIST.attempts.length - 1];
    HIST.attempts.push({ t: Date.now(), s: score, n: N });
    if (HIST.attempts.length > 20) HIST.attempts = HIST.attempts.slice(-20);
    saveHist();
    const dEl = $('qzDelta');
    if (dEl) {
      if (prev) {
        const d = score - prev.s;
        dEl.hidden = false;
        dEl.className = 'qz-delta ' + (d > 0 ? 'up' : d < 0 ? 'down' : '');
        dEl.textContent = d > 0 ? T('qz_delta_up', { d }) : d < 0 ? T('qz_delta_down', { d: -d }) : T('qz_delta_flat');
      } else dEl.hidden = true;
    }

    // 按主题正确率（仅统计本次抽样作答的题目，非整题库）
    const bars = $('qzBars');
    bars.innerHTML = '';
    const dom = {};
    Q.forEach((q, i) => {
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
    $('qzStart').addEventListener('click', async () => {
      const btn = $('qzStart');
      btn.disabled = true;
      try {
        await loadBank();
      } catch (e) {
        btn.disabled = false;
        const meta = document.querySelector('.qz-meta');
        if (meta) { meta.textContent = T('qz_bank_load_err'); meta.style.color = 'var(--hot)'; }
        return;
      }
      btn.disabled = false;
      Q = sampleQuestions();
      N = Q.length;
      track('quiz_start', B.version, N);
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
      Q = sampleQuestions(); N = Q.length;
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
    // 首屏进度（有历史才显示）；题库预热完成后用在库题目重算待复习数
    renderIntroProgress();
    // 题库预热：进页即后台拉取，点击「开始」通常零等待；失败静默（点击时再报错）
    loadBank().then(renderIntroProgress).catch(() => { });
  }

  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', bind) : bind();
})();
