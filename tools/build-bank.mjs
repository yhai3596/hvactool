/* build-bank.mjs —— 题库校验 + 分片构建
 * 唯一编写源：js/quiz-bank.js（带注释，git 审阅友好）。本脚本负责：
 *   1) 结构校验：mc 引用存在、答案索引合法、每题 4 选项、id 唯一、错误项必须挂误区、题干重复检测
 *   2) 产物生成：bank/manifest.json（版本 + 板块清单 + 误区表 + qid→domain 索引）
 *               bank/<domain>.json（各板块题目分片，页面按需并行拉取）
 * ⚠ 维护约定：改 js/quiz-bank.js 后必须重跑 `node tools/build-bank.mjs`（产物需提交，服务器 git pull 部署）。
 */
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(ROOT, 'js', 'quiz-bank.js');
const OUT = path.join(ROOT, 'bank');

/* ---------- 载入编写源 ---------- */
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SRC, 'utf8'), sandbox, { filename: 'quiz-bank.js' });
const B = sandbox.window.QUIZ_BANK;
if (!B || !Array.isArray(B.questions)) {
  console.error('FATAL: window.QUIZ_BANK 未定义或缺 questions');
  process.exit(1);
}

/* ---------- 校验 ---------- */
const errs = [];
const warns = [];
const ids = new Set();
const stems = new Map();
const byDomain = {};

for (const q of B.questions) {
  if (!q.id) errs.push('题目缺 id: ' + JSON.stringify(q.text || '').slice(0, 60));
  if (ids.has(q.id)) errs.push(`重复 id: ${q.id}`);
  ids.add(q.id);
  if (!q.domain || !B.domains.includes(q.domain)) errs.push(`${q.id}: domain "${q.domain}" 不在 domains 列表`);
  (byDomain[q.domain] = byDomain[q.domain] || []).push(q);
  if (!Array.isArray(q.options) || q.options.length !== 4) errs.push(`${q.id}: 选项数 ${q.options?.length}（应为 4）`);
  if (!(Number.isInteger(q.answer) && q.answer >= 0 && q.answer < (q.options?.length || 0))) errs.push(`${q.id}: answer 索引非法`);
  if (!q.why) errs.push(`${q.id}: 缺整题解析 why`);
  if (!q.ref) warns.push(`${q.id}: 缺 ref 出处`);
  const stemKey = String(q.text || '').toLowerCase().replace(/\s+/g, ' ').trim();
  if (stems.has(stemKey)) errs.push(`${q.id}: 题干与 ${stems.get(stemKey)} 重复`);
  stems.set(stemKey, q.id);
  (q.options || []).forEach((o, i) => {
    if (!o.t) errs.push(`${q.id}: 选项 ${i} 缺文本`);
    if (i === q.answer) {
      if (o.mc) errs.push(`${q.id}: 正确项挂了误区 ${o.mc}`);
    } else {
      if (!o.mc) errs.push(`${q.id}: 错误项 ${i} 未挂误区（错因诊断是本产品核心，不允许留空）`);
      else if (!B.misconceptions[o.mc]) errs.push(`${q.id}: 误区 ${o.mc} 未在 misconceptions 定义`);
      if (!o.why) warns.push(`${q.id}: 错误项 ${i} 缺 why 即时解析`);
    }
  });
}
for (const [mcId, m] of Object.entries(B.misconceptions)) {
  for (const f of ['name', 'desc', 'fix']) if (!m[f]) errs.push(`误区 ${mcId} 缺字段 ${f}`);
  const used = B.questions.some(q => q.options.some(o => o.mc === mcId));
  if (!used) warns.push(`误区 ${mcId} 未被任何题目引用（孤儿节点）`);
}
for (const d of B.domains) if (!byDomain[d] || !byDomain[d].length) warns.push(`板块 ${d} 没有题目`);

if (warns.length) console.log('WARN:\n  ' + warns.join('\n  '));
if (errs.length) {
  console.error('校验失败（' + errs.length + ' 项）:\n  ' + errs.join('\n  '));
  process.exit(1);
}

/* ---------- 生成产物 ---------- */
fs.mkdirSync(OUT, { recursive: true });
const qidIndex = {};
const domainMeta = [];
for (const d of B.domains) {
  const qs = byDomain[d] || [];
  qs.forEach(q => { qidIndex[q.id] = d; });
  const file = d + '.json';
  fs.writeFileSync(path.join(OUT, file), JSON.stringify({ domain: d, questions: qs }), 'utf8');
  domainMeta.push({ key: d, file, count: qs.length });
}
const manifest = {
  version: B.version,
  builtAt: new Date().toISOString(),
  total: B.questions.length,
  domains: domainMeta,
  misconceptions: B.misconceptions,
  qidIndex,
};
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest), 'utf8');

console.log(`OK: ${B.questions.length} 题 / ${B.domains.length} 板块 / ${Object.keys(B.misconceptions).length} 误区节点`);
domainMeta.forEach(m => console.log(`  bank/${m.file}  ${m.count} 题  ${(fs.statSync(path.join(OUT, m.file)).size / 1024).toFixed(1)}KB`));
console.log(`  bank/manifest.json  ${(fs.statSync(path.join(OUT, 'manifest.json')).size / 1024).toFixed(1)}KB`);
