/* 后端（server.py）返回的中文报错 → i18n（前端映射，避免改后端需重启）
 * 固定串精确匹配；带动态参数的用前缀匹配，保留其后的动态尾部（冷媒名/参数名等无需翻译） */
function trBackendMsg(msg) {
  if (!msg || !window.T) return msg;
  const EXACT = { '超出饱和范围（可能高于临界点）': 'err_sat_range', '冷凝压力必须高于蒸发压力': 'err_pc_gt_pe', '介质仅支持 water / meg30 / meg50': 'err_medium', '请检查输入是否超出物性有效范围': 'err_check_range' };
  if (EXACT[msg]) return window.T(EXACT[msg]);
  const m = msg.match(/^请提供恰好两个已知参数（当前 (\d+) 个）$/);
  if (m) return window.T('err_two_params', { n: m[1] });
  const PREFIX = [['未知冷媒: ', 'err_unknown_fluid'], ['缺少参数: ', 'err_missing_param'], ['不支持的参数: ', 'err_unsupported_param'], ['计算失败: ', 'err_calc_failed']];
  for (const [p, k] of PREFIX) if (msg.startsWith(p)) return window.T(k) + msg.slice(p.length);
  return msg;   // 未知报错原样透传
}

/* 后端 API 封装 + toast */
async function api(path, params) {
  const q = params ? '?' + new URLSearchParams(params) : '';
  let r;
  try {
    r = await fetch(path + q);
  } catch (e) {
    throw new Error(window.T ? window.T('err_no_service') : '无法连接本地计算服务，请确认已运行 server.py（start.bat）');
  }
  const j = await r.json();
  if (j.error) throw new Error(trBackendMsg(j.error) + (j.hint ? '｜' + trBackendMsg(j.hint) : ''));
  return j;
}

function toast(msg, isErr) {
  let box = document.getElementById('toastBox');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toastBox';
    document.body.appendChild(box);
  }
  const t = document.createElement('div');
  t.className = 'toast' + (isErr ? ' err' : '');
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .4s'; }, 3600);
  setTimeout(() => t.remove(), 4100);
}

const fmtN = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(d);

/* 读取主题 CSS 变量（Canvas 图表配色跟随主题） */
const cssv = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
