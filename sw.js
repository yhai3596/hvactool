/* HVAC 工具站 Service Worker(PWA)
 * 策略:
 *   - /api/*        永不缓存(实时计算)
 *   - HTML 导航     network-first(保证更新及时),失败回缓存,再回 index.html 离线壳
 *   - 静态资源      cache-first(css/js 带 ?v=N 版本化,天然失效;图标/manifest 同缓存)
 *   - 跨域请求      不拦截(supabase CDN 等走浏览器默认)
 * ⚠ 维护约定:全站 bump ?v=N 时,同步把下面 SW_VERSION 改成同号(旧缓存在 activate 时清除)。
 */
const SW_VERSION = 'v228';
const CACHE = 'hvac-' + SW_VERSION;

const PRECACHE = [
  'index.html',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'css/style.css?v=228',
  'css/site.css?v=228',
  'js/lib/config.js?v=228',
  'js/lib/i18n.js?v=228',
  'js/lib/shell.js?v=228',
  'js/lib/units.js?v=228',
  'js/lib/analytics.js?v=228',
  'js/lib/api.js?v=228',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith('hvac-') && k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;          // 跨域不拦
  if (url.pathname.startsWith('/api/')) return;        // 计算接口不缓存

  // HTML 导航:network-first
  if (req.mode === 'navigate' || url.pathname.endsWith('.html') || url.pathname === '/') {
    e.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then(hit => hit || caches.match('index.html')))
    );
    return;
  }

  // 静态资源:cache-first(?v=N 保证更新)
  e.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
      return res;
    }))
  );
});
