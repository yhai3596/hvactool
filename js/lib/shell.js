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
  nav.innerHTML =
    `<a class="brand" href="index.html">HVAC TOOLS · 暖通工具站</a>` +
    SITE_CONFIG.NAV.map(n =>
      `<a class="nav-link${n.key === page ? ' on' : ''}" href="${n.href}">${n.label}</a>`).join('') +
    `<span class="spacer"></span>` +
    `<span id="unitSlot"></span>` +
    (document.body.dataset.fixedTheme ? '' :
      `<span class="theme-seg">${THEMES.map(([k, l]) => `<button data-t="${k}">${l}</button>`).join('')}</span>`) +
    `<span class="user-chip" id="userChip"></span>`;
  const app = document.getElementById('app') || document.body;
  app.insertBefore(nav, app.firstChild);

  nav.querySelectorAll('.theme-seg button').forEach(b => {
    b.onclick = () => { localStorage.setItem('hvac-theme', b.dataset.t); shellApplyTheme(b.dataset.t); };
  });
  if (document.body.dataset.units && window.Units) {
    Units.mount(document.getElementById('unitSlot'));
    Units.initDefaults();
  }
}

function shellSetChip(html) {
  const c = document.getElementById('userChip');
  if (c) c.innerHTML = html;
}

async function shellInitAuth() {
  const page = document.body.dataset.page || '';
  const isPublic = page === 'home' || page === 'login';

  if (!window.supabase) {
    shellSetChip('<span class="offline-badge">离线模式 · 登录不可用</span>');
    return;
  }
  sbClient = window.supabase.createClient(SITE_CONFIG.SUPABASE_URL, SITE_CONFIG.SUPABASE_KEY);
  try {
    const { data: { session } } = await sbClient.auth.getSession();
    sbUser = session ? session.user : null;
  } catch (e) {
    shellSetChip('<span class="offline-badge">认证服务不可达</span>');
    return;
  }

  if (sbUser) {
    shellSetChip(`<b>${sbUser.email || '已登录'}</b><button class="chip-btn" id="logoutBtn">退出</button>`);
    document.getElementById('logoutBtn').addEventListener('click', async () => {
      await sbClient.auth.signOut();
      location.href = 'index.html';
    });
  } else {
    shellSetChip(`<a class="chip-btn" style="text-decoration:none" href="login.html">登录 / 注册</a>`);
    if (SITE_CONFIG.AUTH_REQUIRED && !isPublic) {
      location.href = 'login.html?next=' + encodeURIComponent(location.pathname.split('/').pop());
    }
  }
}

function shellRenderFooter() {
  const app = document.getElementById('app') || document.body;
  if (document.getElementById('siteFooter')) return;
  const f = document.createElement('footer');
  f.id = 'siteFooter';
  f.innerHTML =
    `<span class="cr">© 版权 Alan 所有 · 欢迎交流联系！</span>` +
    `<span class="wx">关注 Alan 的公众号：<b>Alan 的 AI 世界</b></span>`;
  app.appendChild(f);
}

document.addEventListener('DOMContentLoaded', () => {
  shellInitTheme();
  shellRenderNav();
  shellRenderFooter();
  shellInitAuth();
});
