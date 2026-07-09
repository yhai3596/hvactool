/* analytics.js —— 轻量埋点：页面浏览 / 停留时长 / 点击（仅按钮·链接·[data-track]）
 * 直连 events 表（PostgREST + RLS 仅允许 INSERT，user_id 一律 null，不采 PII）。
 * 停留时长用 visibilitychange 累计可见时间 + fetch(keepalive) 在隐藏/离开时上报。 */
(function () {
  if (typeof SITE_CONFIG === 'undefined') return;
  const URL = SITE_CONFIG.SUPABASE_URL, KEY = SITE_CONFIG.SUPABASE_KEY;
  if (!URL || !KEY) return;

  const page = (document.body && document.body.dataset.page) ||
    (location.pathname.split('/').pop() || 'index').replace(/\.html$/, '') || 'index';

  // 后台页不自埋（避免管理员自身操作污染统计）
  if (page === 'admin') return;

  let sid;
  try {
    sid = sessionStorage.getItem('hvac-sid');
    if (!sid) { sid = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)); sessionStorage.setItem('hvac-sid', sid); }
  } catch (_) { sid = 'nostore'; }

  function send(event_type, target, value) {
    try {
      fetch(URL + '/rest/v1/events', {
        method: 'POST',
        keepalive: true,
        headers: { 'apikey': KEY, 'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
        body: JSON.stringify([{ session_id: sid, user_id: null, page, event_type, target: target || null, value: value ?? null }]),
      }).catch(() => {});
    } catch (_) { /* 静默 */ }
  }

  // 1) 页面浏览
  send('view', page, null);

  // 2) 停留时长（累计可见毫秒，隐藏/离开时上报并清零，避免重复计）
  let visStart = document.visibilityState === 'visible' ? Date.now() : 0;
  let dwell = 0;
  function accumulate() { if (visStart) { dwell += Date.now() - visStart; visStart = 0; } }
  function flushDwell() { accumulate(); if (dwell >= 1000) { send('dwell', page, Math.round(dwell)); dwell = 0; } }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushDwell();
    else if (!visStart) visStart = Date.now();
  });
  window.addEventListener('pagehide', flushDwell);

  // 3) 点击（仅有意义的交互元素；绝不读取 input 的值）
  document.addEventListener('click', e => {
    const el = e.target.closest && e.target.closest('button, a, [data-track]');
    if (!el) return;
    let label = el.getAttribute('data-track') || el.getAttribute('aria-label') ||
      (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40) ||
      el.id || el.tagName.toLowerCase();
    send('click', label, null);
  }, true);
})();
