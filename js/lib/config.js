/* 站点配置 */
const SITE_CONFIG = {
  SUPABASE_URL: 'https://lnzepjubgtdclvmridxw.supabase.co',
  SUPABASE_KEY: 'sb_publishable_m4cNAyw4SzOdv-eogmOsDg_kHicDMEf',
  AUTH_REQUIRED: true,           // false = 关闭登录门禁（纯本地使用）
  NAV: [
    { href: 'index.html', key: 'home', label: '首页' },
    { href: 'sim.html', key: 'sim', label: '系统仿真' },
    { href: 'refprops.html', key: 'refprops', label: '冷媒物性' },
    { href: 'phcalc.html', key: 'phcalc', label: '压焓计算' },
    { href: 'psychro.html', key: 'psychro', label: '湿空气' },
    { href: 'hydronic.html', key: 'hydronic', label: '水力计算' },
    { href: 'duct.html', key: 'duct', label: '风管设计' },
    { href: 'energy.html', key: 'energy', label: '能耗电费' },
    { href: 'units.html', key: 'units', label: '单位换算' },
    { href: 'quiz.html', key: 'quiz', label: '考证小测' },
  ],
};
