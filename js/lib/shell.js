/* 站点壳：主题 + 导航注入 + 单位开关 + Supabase 认证门禁
 * <body data-page="xxx">          页面标识（home/login 免登录）
 * <body data-units="1">           显示公制/美制双开关
 * <body data-fixed-theme="dark">  页面锁定主题（仿真场景专用）
 * supabase-js CDN 加载失败 → 离线模式（不阻断工具使用）。 */
let sbClient = null;
let sbUser = null;

const THEMES = [['dark', '深色'], ['light', '浅色'], ['contrast', '高对比']];

function shellApplyTheme(t) {
  document.documentElement.dataset.theme = t;
  document.querySelectorAll('.theme-seg button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
  window.dispatchEvent(new CustomEvent('hvac-theme-change', { detail: t }));
}

function shellInitTheme() {
  const fixed = document.body.dataset.fixedTheme;
  shellApplyTheme(fixed || localStorage.getItem('hvac-theme') || 'dark');
}

function shellRenderNav() {
  const page = document.body.dataset.page || '';
  const nav = document.createElement('nav');
  nav.id = 'siteNav';
  const cur = window.I18N ? I18N.lang() : 'en';
  const LANGS = (window.I18N && I18N.langs) || [{ code: 'en', label: 'EN' }];
  const langCtrl = LANGS.length > 2
    ? `<select class="lang-select" id="langSel">${LANGS.map(l => `<option value="${l.code}"${cur === l.code ? ' selected' : ''}>${l.label}</option>`).join('')}</select>`
    : `<span class="lang-seg">${LANGS.map(l => `<button data-l="${l.code}"${cur === l.code ? ' class="on"' : ''}>${l.label}</button>`).join('')}</span>`;
  nav.innerHTML =
    `<a class="brand" data-i18n="brand" href="index.html">HVAC TOOLS</a>` +
    SITE_CONFIG.NAV.map(n =>
      `<a class="nav-link${n.key === page ? ' on' : ''}" data-i18n="nav_${n.key}" href="${n.href}">${n.label}</a>`).join('') +
    `<span class="spacer"></span>` +
    langCtrl +
    `<span id="unitSlot"></span>` +
    (document.body.dataset.fixedTheme ? '' :
      `<span class="theme-seg">${THEMES.map(([k]) => `<button data-t="${k}" data-i18n="th_${k}"></button>`).join('')}</span>`) +
    `<span class="user-chip" id="userChip"></span>`;
  const app = document.getElementById('app') || document.body;
  app.insertBefore(nav, app.firstChild);

  nav.querySelectorAll('.theme-seg button').forEach(b => {
    b.onclick = () => { localStorage.setItem('hvac-theme', b.dataset.t); shellApplyTheme(b.dataset.t); };
  });
  nav.querySelectorAll('.lang-seg button').forEach(b => {
    b.onclick = () => window.I18N && I18N.setLang(b.dataset.l);
  });
  const langSel = nav.querySelector('#langSel');
  if (langSel) langSel.onchange = () => window.I18N && I18N.setLang(langSel.value);
  if (document.body.dataset.units && window.Units) {
    Units.mount(document.getElementById('unitSlot'));
    Units.initDefaults();
  }
  if (window.I18N) I18N.apply(nav);
}

function shellSetChip(html) {
  const c = document.getElementById('userChip');
  if (c) c.innerHTML = html;
}

async function shellInitAuth() {
  const page = document.body.dataset.page || '';
  const isPublic = page === 'home' || page === 'login';

  if (!window.supabase) {
    shellSetChip('<span class="offline-badge">' + T('offline') + '</span>');
    return;
  }
  sbClient = window.supabase.createClient(SITE_CONFIG.SUPABASE_URL, SITE_CONFIG.SUPABASE_KEY);
  try {
    const { data: { session } } = await sbClient.auth.getSession();
    sbUser = session ? session.user : null;
  } catch (e) {
    shellSetChip('<span class="offline-badge">' + T('auth_unreachable') + '</span>');
    return;
  }

  if (sbUser) {
    // 结算积分（惰性：按日历天数补扣每日 30）
    let credits = null;
    try { const r = await sbClient.rpc('settle_credits'); if (r.data && r.data[0]) credits = r.data[0].credits; } catch (_) {}
    const low = credits !== null && credits <= 0;
    shellSetChip(
      `<span class="credit-chip${low ? ' low' : ''}" id="creditChip">⚡ ${credits === null ? '—' : credits}</span>` +
      `<button class="chip-btn" id="inviteBtn">🎟 ${T('invites_btn')}</button>` +
      `<b>${sbUser.email || ''}</b>` +
      `<button class="chip-btn" id="logoutBtn">${T('logout')}</button>`);
    document.getElementById('logoutBtn').addEventListener('click', async () => {
      await sbClient.auth.signOut();
      location.href = 'index.html';
    });
    document.getElementById('inviteBtn').addEventListener('click', shellShowInvites);
    document.getElementById('creditChip').addEventListener('click', shellShowCredits);
  } else {
    shellSetChip(`<a class="chip-btn" style="text-decoration:none" href="login.html">${T('login_register')}</a>`);
    if (SITE_CONFIG.AUTH_REQUIRED && !isPublic) {
      location.href = 'login.html?next=' + encodeURIComponent(location.pathname.split('/').pop());
    }
  }
}

async function shellShowInvites() {
  if (!sbClient) return;
  document.getElementById('inviteModal')?.remove();
  const box = document.createElement('div');
  box.id = 'inviteModal';
  box.className = 'invite-overlay';
  box.innerHTML =
    `<div class="invite-panel">
       <div class="invite-head">${T('inv_title')}<span class="invite-close" id="invClose">✕</span></div>
       <div class="invite-body" id="invBody">${T('inv_loading')}</div>
       <div class="invite-foot">${T('inv_foot')}</div>
     </div>`;
  document.body.appendChild(box);
  box.addEventListener('click', e => { if (e.target === box || e.target.id === 'invClose') box.remove(); });

  const { data, error } = await sbClient.rpc('get_my_invites');
  const body = document.getElementById('invBody');
  if (error) { body.textContent = T('inv_load_fail') + error.message; return; }
  if (!data || !data.length) {
    body.innerHTML = `<div style="color:var(--text-dim);font-size:12px;line-height:1.7">${T('inv_empty')}</div>`;
    return;
  }
  body.innerHTML = data.map(r =>
    `<div class="inv-row${r.used ? ' used' : ''}">
       <code>${r.code}</code>
       <span class="inv-st">${r.used ? T('inv_used') : T('inv_unused')}</span>
       <button class="inv-copy" data-c="${r.code}"${r.used ? ' disabled' : ''}>${T('inv_copy')}</button>
     </div>`).join('');
  body.querySelectorAll('.inv-copy').forEach(b => b.addEventListener('click', () => {
    navigator.clipboard?.writeText(b.dataset.c).then(() => { b.textContent = T('inv_copied'); setTimeout(() => b.textContent = T('inv_copy'), 1200); });
  }));
}

async function shellShowCredits() {
  if (!sbClient) return;
  document.getElementById('inviteModal')?.remove();
  const box = document.createElement('div');
  box.id = 'inviteModal';
  box.className = 'invite-overlay';
  box.innerHTML =
    `<div class="invite-panel">
       <div class="invite-head">${T('cred_title')}<span class="invite-close" id="invClose">✕</span></div>
       <div class="invite-body" id="credBody">${T('inv_loading')}</div>
       <div class="invite-foot">${T('cred_foot')}</div>
     </div>`;
  document.body.appendChild(box);
  box.addEventListener('click', e => { if (e.target === box || e.target.id === 'invClose') box.remove(); });

  const cur = await sbClient.rpc('settle_credits');
  const credits = (cur.data && cur.data[0]) ? cur.data[0].credits : '—';
  const logRes = await sbClient.from('credit_log').select('delta,reason,balance_after,created_at').order('created_at', { ascending: false }).limit(60);
  const log = logRes.data || [];
  const zh = window.I18N && I18N.lang() === 'zh';
  const RN = { 'signup': T('reason_signup'), 'signup(backfill)': T('reason_backfill'), 'invite_reward': T('reason_invite') };
  const rn = r => RN[r] || (r.startsWith('daily') ? (T('reason_daily') + ' · ' + (r.match(/\((\d+)d\)/)?.[1] || 1) + (zh ? ' 天' : 'd')) : r);
  const est = typeof credits === 'number' ? Math.max(0, Math.floor(credits / 30)) : '—';
  const body = document.getElementById('credBody');
  body.innerHTML =
    `<div class="cred-now${(typeof credits === 'number' && credits <= 0) ? ' low' : ''}">⚡ ${credits} <small>${T('cred_days', { d: est })}</small></div>` +
    (log.length
      ? '<div class="cred-log">' + log.map(l =>
        `<div class="cl-row"><span>${rn(l.reason)}</span><span class="cl-d ${l.delta < 0 ? 'minus' : 'plus'}">${l.delta > 0 ? '+' : ''}${l.delta}</span><span class="cl-b">${l.balance_after}</span></div>`).join('') + '</div>'
      : `<div style="color:var(--text-dim);font-size:12px">${T('cred_empty')}</div>`);
}

function shellRenderFooter() {
  const app = document.getElementById('app') || document.body;
  if (document.getElementById('siteFooter')) return;
  const f = document.createElement('footer');
  f.id = 'siteFooter';
  f.innerHTML =
    `<span class="cr">${T('footer_cr')}</span>` +
    `<span class="wx">${T('footer_wx')}<b>${T('footer_wx_name')}</b></span>`;
  app.appendChild(f);
}

document.addEventListener('DOMContentLoaded', () => {
  shellInitTheme();
  shellRenderNav();
  shellRenderFooter();
  if (window.I18N) I18N.apply();   // 渲染全页 data-i18n（页面正文）
  shellInitAuth();
});
