/* 后端 API 封装 + toast */
async function api(path, params) {
  const q = params ? '?' + new URLSearchParams(params) : '';
  let r;
  try {
    r = await fetch(path + q);
  } catch (e) {
    throw new Error('无法连接本地计算服务，请确认已运行 server.py（start.bat）');
  }
  const j = await r.json();
  if (j.error) throw new Error(j.error + (j.hint ? '｜' + j.hint : ''));
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
