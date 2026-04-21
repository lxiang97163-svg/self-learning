const express = require('express');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3456;

const CACHE_DIR   = path.join(__dirname, '..', 'outputs', 'cache');
const REVIEW_DIR  = path.join(__dirname, '..', 'outputs', 'review');
const DATA_FILE   = path.join(CACHE_DIR, 'dashboard_latest.json');
const DATA_NAME   = path.basename(DATA_FILE);

app.use(express.static(path.join(__dirname, 'public')));

// ────────────────────────────────────────────────────────────────
// 工具：安全读文件
// ────────────────────────────────────────────────────────────────
function readFile(p) {
  try { return fs.readFileSync(p, 'utf8'); }
  catch (_) { return null; }
}

// ────────────────────────────────────────────────────────────────
// Markdown 解析：每日复盘表
// ────────────────────────────────────────────────────────────────
function parseReview(md) {
  const sec = (h2, h2next) => {
    const re = new RegExp(`## ${h2}[\\s\\S]*?(?=\\n## ${h2next}|\\n# |$)`, 'i');
    const m = md.match(re);
    return m ? m[0] : '';
  };

  // ── 元信息
  const datM  = md.match(/>\s*\*\*日期\*\*[：:]\s*(\S+)/);
  const volM  = md.match(/>\s*\*\*两市成交额\*\*[：:]\s*(\S+)/);
  const date  = datM ? datM[1] : '';
  const vol   = volM ? volM[1] : '';

  // ── 一、指数
  const idx = {};
  const idxSec = sec('一、指数复盘', '二、');
  const tableRows = [...idxSec.matchAll(/\|\s*([^|]+?)\s*\|\s*([^|\n]+?)\s*\|/g)];
  for (const [, k, v] of tableRows) {
    const key = k.trim().replace(/\s+/g, '');
    if (key && !key.startsWith('-')) idx[key] = v.trim();
  }

  // ── 3.2 情绪复盘
  const emo = {};
  const emoSec = md.match(/### 3\.2 情绪复盘表[\s\S]*?(?=\n### |\n## |$)/);
  if (emoSec) {
    for (const [, k, v] of [...emoSec[0].matchAll(/\|\s*([^|]+?)\s*\|\s*([^|\n]+?)\s*\|/g)]) {
      const key = k.trim().replace(/\s+/g, '');
      if (key && !key.startsWith('-')) emo[key] = v.trim();
    }
  }

  // ── 3.3 情绪日历（最近 5 行）
  const cal = [];
  const calSec = md.match(/### 3\.3 情绪日历[\s\S]*?(?=\n### |\n## |$)/);
  if (calSec) {
    const rows = [...calSec[0].matchAll(/\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|\n]+)/g)];
    for (const [, date, state, desc, trend] of rows.slice(-5)) {
      cal.push({ date: date.trim(), state: state.trim(), desc: desc.trim(), trend: trend.trim() });
    }
  }

  // ── 3.5 热力追踪（取前5活跃 + 退潮列表）
  const heat = { active: [], cooling: [] };
  const heatSec = md.match(/### 3\.5[\s\S]*?(?=\n### |\n## |$)/);
  if (heatSec) {
    const rows = [...heatSec[0].matchAll(/\|\s*([^|]+?)\s*\|\s*([\d—\s*/\-]+)\s*\|\s*([\d—\s*/\-]+)\s*\|\s*([\d—\s*/\-]+)\s*\|\s*([\d—\s*/\-]+)\s*\|\s*([\d—\s*/\-]+)\s*\|\s*([↑↓→]+)\s*\|\s*([^|\n]+)/g)];
    for (const [, name, , , , , today, trend, stage] of rows) {
      if (!name.trim() || name.includes('题材')) continue;
      const t = today.replace(/\*\*/g, '').trim();
      const n = parseInt(t) || 0;
      const obj = { name: name.trim(), today: n, trend: trend.trim(), stage: stage.trim() };
      if (stage.includes('发酵') || stage.includes('🔥')) heat.active.push(obj);
      else if (stage.includes('退潮') || stage.includes('低吸')) heat.cooling.push(obj);
    }
    heat.active = heat.active.slice(0, 5);
    heat.cooling = heat.cooling.slice(0, 8);
  }

  // ── 八、如果则执行（已触发/未触发分类）
  const ifThen = [];
  const secEight = sec('八、如果则执行', '九、');
  const thenRows = [...secEight.matchAll(/\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|\n]+)/g)];
  for (const [, cond, action, result, note] of thenRows.slice(0, 15)) {
    if (cond.includes('---') || cond.includes('如果') || cond.includes('条件')) continue;
    ifThen.push({
      cond: cond.trim(),
      action: action.trim(),
      result: result.trim(),
      note: note.trim(),
    });
  }

  // ── 十、仓位计划（四块打分）
  const score = {};
  const secTen = sec('十、仓位计划', '十一、');
  // 合计行：**合计** | **10** | **7/10** 或 总分 7/10
  const totalM = secTen.match(/合计[^|]*\|\s*\*?\*?[\d]+\*?\*?\s*\|\s*\*?\*?([\d.]+)\/10/) ||
                 secTen.match(/总分[：:]\s*([\d.]+)\s*\/\s*10/);
  if (totalM) score.total = parseFloat(totalM[1]);
  // 子维度行：| 指数 | 4 | 2/4 | ...
  const subRows = [...secTen.matchAll(/\|\s*([^|*\d-][^|]{1,8}?)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\/\d+\s*\|/g)];
  for (const [, k, , v] of subRows) {
    const key = k.trim().replace(/\*\*/g,'');
    if (key && !key.includes('维度') && !key.includes('---')) score[key] = parseFloat(v);
  }

  // ── 全文总结（最后出现的「本模块总结」或第十节末段）
  let summary = '';
  const sumMatches = [...md.matchAll(/>\s*(.*?(?:明日关注|操作关键词|建议仓位|总结)[^\n]*)/g)];
  if (sumMatches.length) summary = sumMatches[sumMatches.length - 1][1].trim();

  // ── 二、板块复盘（Top5 题材）
  const sectors = [];
  const secTwo = sec('二、板块与题材复盘', '三、');
  const sRows = [...secTwo.matchAll(/\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|\n]+)/g)];
  for (const [, name, d1, d2, stage, seal, , , expect] of sRows.slice(0, 10)) {
    if (!name.trim() || name.includes('---') || name.includes('板块')) continue;
    sectors.push({ name: name.trim(), dragon1: d1.trim(), dragon2: d2.trim(), stage: stage.trim(), seal: seal.trim(), expect: expect.trim() });
  }

  return { date, vol, idx, emo, cal, heat, ifThen, score, summary, sectors };
}

// ────────────────────────────────────────────────────────────────
// Markdown 解析：速查卡
// ────────────────────────────────────────────────────────────────
function parseSpeedcard(md) {
  // 元信息
  const dateM  = md.match(/速查卡\s+(\d{4}-\d{2}-\d{2})/);
  const capM   = md.match(/仓位天花板[：:]\s*([^\s|]+)/);
  const emoM   = md.match(/情绪定性[：:]\s*([^，,|$\n]+)/);
  const scoreM = md.match(/四块拼图\s+([\d.]+)\/10/);

  // 第零步信号表（4行，第1行为表头，第2行为分隔线，第3-6行为信号）
  const step0 = [];
  const s0Sec = md.match(/第零步[\s\S]*?(?=\n## |\n---)/);
  if (s0Sec) {
    const rows = [...s0Sec[0].matchAll(/^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|\n]+)/gm)];
    for (const [, signal, ok, fail] of rows) {
      const s = signal.replace(/\*\*/g,'').trim();
      if (!s || s.includes('---') || s === '信号') continue;
      step0.push({ signal: s, ok: ok.replace(/\*\*/g,'').trim(), fail: fail.replace(/\*\*/g,'').trim() });
    }
  }

  // 第一优先 链条（票池表）
  const p1 = parseChain(md, header => header.includes('第一优先'));
  const p2 = parseChain(md, header => header.includes('第二优先'));

  // B模式备用候选（取每个候选的标题 + stocks）
  const bCandidates = [];
  const bSec = md.match(/##\s*🔀\s*B\s*模式[\s\S]*?(?=\n## |$)/);
  if (bSec) {
    const blocks = [...bSec[0].matchAll(/###\s*候选[一二两\d]+[：:]\s*([^\n]+)([\s\S]*?)(?=\n###\s*候选|\n## |$)/g)];
    for (const [, title, block] of blocks) {
      const stocks = [];
      for (const [, rank, name, code, suf] of [...block.matchAll(/\|\s*(\d+)\s*\|\s*\*\*([^*]+)\*\*\s*\(\s*`?(\d+)\.(SZ|SH)`?\s*\)/g)]) {
        stocks.push({ rank: parseInt(rank), name: name.trim(), ts_code: `${code}.${suf}` });
      }
      const switchBlock = block.match(/>\s*\*\*切换确认[\s\S]*?(?=\n>?\s*$|\n###)/);
      bCandidates.push({ title: title.trim(), stocks, switchText: switchBlock ? switchBlock[0].replace(/>/g, '').trim() : '' });
    }
  }

  // 空仓条件
  const noTrade = [];
  const ntSec = md.match(/##\s*(?:❌\s*)?(?:不做|今日不[交操]作)[\s\S]*?(?=\n---|\n## |$)/);
  if (ntSec) {
    for (const [, item] of [...ntSec[0].matchAll(/[-•]\s*([^\n]+)/g)]) {
      noTrade.push(item.trim());
    }
  }

  // 如果则执行（支持：八、如果则执行 / ## ⚡ 如果则执行 两种写法）
  const ifThen = [];
  const itSec = md.match(/(?:(?:八|8)[、.]\s*|##\s*⚡\s*)如果则执行[\s\S]*?(?=\n##|\n---|$)/);
  if (itSec) {
    // 优先尝试 4 列格式；如无有效行则回退到 2 列格式（| 如果 | 则 |）
    const rows4 = [...itSec[0].matchAll(/\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+)/gm)];
    const valid4 = rows4.filter(([, c]) => c.trim() && !c.includes('---') && !c.includes('如果') && !c.includes('条件'));
    if (valid4.length > 0) {
      for (const [, cond, action, result, note] of valid4.slice(0, 15)) {
        ifThen.push({ cond: cond.trim(), action: action.trim(), result: result.trim(), note: note.trim() });
      }
    } else {
      const rows2 = [...itSec[0].matchAll(/\|\s*([^|\n]+?)\s*\|\s*([^|\n]+)/gm)];
      for (const [, cond, action] of rows2.slice(0, 15)) {
        if (!cond.trim() || cond.includes('---') || cond.includes('如果') || cond.includes('条件')) continue;
        ifThen.push({ cond: cond.trim(), action: action.trim(), result: '', note: '' });
      }
    }
  }

  return {
    date: dateM ? dateM[1] : '',
    cap: capM ? capM[1] : '',
    emotion: emoM ? emoM[1].trim() : '',
    score: scoreM ? parseFloat(scoreM[1]) : null,
    step0, p1, p2, bCandidates, noTrade, ifThen,
  };
}

function parseChain(md, matcher) {
  const sections = [...md.matchAll(/(?:^|\n)###\s*✅\s*([^\n]+)\n([\s\S]*?)(?=\n### |\n## |\n---\n|$)/g)];
  const sec = sections.find(([, header]) => {
    const clean = header.trim();
    return typeof matcher === 'function' ? matcher(clean) : clean.includes(String(matcher));
  });
  if (!sec) return { title: typeof matcher === 'string' ? matcher : '', stocks: [], health: [] };
  const title = sec[1].trim();
  const block = sec[2];

  // 只取「票池表」部分：遇到「完整链」或「####」即截止
  const poolEndIdx = Math.min(
    block.includes('完整链') ? block.indexOf('完整链') : Infinity,
    block.includes('\n####') ? block.indexOf('\n####') : Infinity,
  );
  const poolBlock = poolEndIdx < Infinity ? block.slice(0, poolEndIdx) : block;

  // 票池表格：格式 | **名字**(code.SZ) | 角色 | 条件 | 否决 |
  const stocks = [];
  for (const [, name, code, suf, role, cond, deny] of [...poolBlock.matchAll(/\|\s*\*\*([^*]+)\*\*\s*\(\s*`?(\d+)\.(SZ|SH)`?\s*\)\s*\|\s*([^|]*?)\s*\|\s*([^|]+)\s*\|\s*([^|\n]+)/g)]) {
    stocks.push({ name: name.trim(), ts_code: `${code}.${suf}`, role: role.trim(), cond: cond.trim(), deny: deny.trim() });
  }

  // 健康度验证
  const health = [];
  const healthSec = block.match(/⚠️[\s\S]*?健康度验证[\s\S]*?(?=\n####|\n>?\s*\n[^>]|$)/);
  if (healthSec) {
    for (const [, name, thr] of [...healthSec[0].matchAll(/龙[一二三四五\d]*\*\*([^*]+)\*\*竞价涨幅\s*>\s*([+-]?[\d.]+)%/g)]) {
      health.push({ name: name.trim(), threshold: parseFloat(thr) });
    }
  }
  return { title, stocks, health };
}

// ────────────────────────────────────────────────────────────────
// API: /api/dates  ── 可用日期列表（有 速查_D.md 的日期）
// ────────────────────────────────────────────────────────────────
app.get('/api/dates', (req, res) => {
  try {
    const files = fs.readdirSync(REVIEW_DIR);
    const dates = files
      .filter(f => /^速查_\d{4}-\d{2}-\d{2}\.md$/.test(f))
      .map(f => f.replace('速查_', '').replace('.md', ''))
      .sort()
      .reverse();   // 最新在前
    res.json({ dates });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ────────────────────────────────────────────────────────────────
// API: /api/review?date=YYYY-MM-DD  ── 返回复盘表解析 JSON
// ────────────────────────────────────────────────────────────────
app.get('/api/review', (req, res) => {
  const date = req.query.date;
  if (!date) return res.status(400).json({ error: '缺少 date 参数' });

  // 速查 D 对应的复盘表是 D-1 交易日；这里按文件名扫描自动找上一个可用的
  const files = fs.readdirSync(REVIEW_DIR);
  const reviewFiles = files
    .filter(f => /^每日复盘表_\d{4}-\d{2}-\d{2}\.md$/.test(f))
    .map(f => f.replace('每日复盘表_', '').replace('.md', ''))
    .sort();

  // 找小于 date 的最新复盘日期
  const prevDates = reviewFiles.filter(d => d < date);
  const targetDate = prevDates.length ? prevDates[prevDates.length - 1] : reviewFiles[reviewFiles.length - 1];
  if (!targetDate) return res.status(404).json({ error: '找不到复盘表' });

  const md = readFile(path.join(REVIEW_DIR, `每日复盘表_${targetDate}.md`));
  if (!md) return res.status(404).json({ error: `复盘表 ${targetDate} 不存在` });

  try {
    res.json({ review_date: targetDate, ...parseReview(md) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ────────────────────────────────────────────────────────────────
// API: /api/speedcard?date=YYYY-MM-DD  ── 返回速查解析 JSON
// ────────────────────────────────────────────────────────────────
app.get('/api/speedcard', (req, res) => {
  const date = req.query.date;
  if (!date) return res.status(400).json({ error: '缺少 date 参数' });

  const md = readFile(path.join(REVIEW_DIR, `速查_${date}.md`));
  if (!md) return res.status(404).json({ error: `速查 ${date} 不存在` });

  try {
    res.json(parseSpeedcard(md));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ────────────────────────────────────────────────────────────────
// API: /api/snapshot?date=YYYYMMDD  ── 历史竞价快照
// ────────────────────────────────────────────────────────────────
app.get('/api/snapshot', (req, res) => {
  const date = req.query.date;   // YYYYMMDD
  if (!date) return res.status(400).json({ error: '缺少 date 参数' });

  const snapFile = path.join(CACHE_DIR, `dashboard_${date}.json`);
  const raw = readFile(snapFile);
  if (!raw) {
    return res.status(404).json({
      error: `无 ${date} 的竞价快照`,
      detail: `请确认存在 ${path.basename(snapFile)}（该交易日需运行 speedcard_monitor.py，写入当日最后一轮仪表盘 JSON）`,
    });
  }

  try { res.json(JSON.parse(raw)); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

// ────────────────────────────────────────────────────────────────
// 原有 REST 轮询接口（保留）
// ────────────────────────────────────────────────────────────────
app.get('/api/data', (req, res) => {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.setHeader('Pragma', 'no-cache');
  try {
    const raw = fs.readFileSync(DATA_FILE, 'utf8');
    res.json(JSON.parse(raw));
  } catch (e) {
    res.status(503).json({
      error: '数据尚未就绪，请先启动 speedcard_monitor.py 脚本',
      detail: e.message,
    });
  }
});

// ────────────────────────────────────────────────────────────────
// SSE 实时推送接口
// ────────────────────────────────────────────────────────────────
app.get('/api/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  const push = (raw) => { res.write(`data: ${raw}\n\n`); };

  try { push(fs.readFileSync(DATA_FILE, 'utf8')); }
  catch (e) { push(JSON.stringify({ error: '数据尚未就绪', detail: e.message })); }

  let watcher = null;
  let debounceTimer = null;
  const debouncedPush = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      try { push(fs.readFileSync(DATA_FILE, 'utf8')); } catch (_) {}
    }, 100);
  };
  // Linux 上对目录 fs.watch 时 filename 经常为 null，若严格比对 DATA_NAME 会永远不推送
  try {
    if (fs.existsSync(DATA_FILE)) {
      watcher = fs.watch(DATA_FILE, debouncedPush);
    } else {
      watcher = fs.watch(CACHE_DIR, (event, filename) => {
        if (filename != null && filename !== DATA_NAME) return;
        debouncedPush();
      });
    }
  } catch (e) {
    console.warn('[SSE] 监听失败，回退为目录 watch:', e.message);
    try {
      watcher = fs.watch(CACHE_DIR, (event, filename) => {
        if (filename != null && filename !== DATA_NAME) return;
        debouncedPush();
      });
    } catch (e2) { console.warn('[SSE] 无法监听目录:', e2.message); }
  }

  const heartbeat = setInterval(() => { res.write(': ping\n\n'); }, 20000);

  req.on('close', () => {
    clearInterval(heartbeat);
    clearTimeout(debounceTimer);
    if (watcher) { try { watcher.close(); } catch (_) {} }
  });
});

app.listen(PORT, () => {
  console.log('\n盯盘仪表盘已启动（三Tab版）');
  console.log(`访问：http://localhost:${PORT}`);
  console.log(`复盘目录：${REVIEW_DIR}`);
  console.log(`缓存目录：${CACHE_DIR}\n`);
});
