#!/usr/bin/env node
/**
 * M2 验收 · 热榜与摘要端到端走查（零第三方依赖）
 *
 * 在独立的本地 D1（wrangler dev）里种入固定热榜数据集，用真实 HTTP 走查 M2 的对外链路：
 *   按日快照列表 / 日期 / 语言 / 趋势 → 详情摘要回退 → 一键收藏闭环
 *   → 摘要内部回写 → 快照内部 upsert → 保留策略状态 / 归档清理 → 旧数据回退
 * 然后对热榜列表做多轮请求采样，输出 P50 / P95，并断言 P95 < 300ms。
 *
 * M2-01/02/03（抓取、容错告警、README 清洗）是 VPS 侧能力，由 `vps/pytest` 覆盖；
 * 本脚本负责 edge 对外契约与 D1 数据链路，验收矩阵见 docs/planning/acceptance-m2.md。
 *
 * 用法（在 edge/ 下）：
 *   npm run test:m2
 *   node scripts/m2-acceptance.mjs --strict
 *   node scripts/m2-acceptance.mjs --report-md docs/planning/acceptance-m2-report.md --report-json docs/planning/acceptance-m2-report.json
 */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer as createNetServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const EDGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = resolve(EDGE_ROOT, '..');
const WRANGLER_BIN = join(EDGE_ROOT, 'node_modules', 'wrangler', 'bin', 'wrangler.js');
const DB_NAME = 'opensource-factory';
const ALLOWED_ORIGIN = 'http://localhost:5173';
const SESSION_TOKEN = 'e2e-m2-session-token';
const INTERNAL_TOKEN = 'e2e-m2-internal-token';
const USER_ID = '2001';
const PERF_SAMPLES = 100;
const PERF_BUDGET_MS = 300;

const argv = process.argv.slice(2);
const flags = new Set(argv.filter((arg) => arg.startsWith('--')));
const STRICT = flags.has('--strict');
const KEEP = flags.has('--keep');
const REPORT_MD = readOption('--report-md');
const REPORT_JSON = readOption('--report-json');

function readOption(name) {
  const index = argv.indexOf(name);
  if (index === -1) return null;
  return argv[index + 1] ?? null;
}

const delay = (ms) => new Promise((done) => setTimeout(done, ms));

function isoDate(offsetDays = 0) {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

const TODAY = isoDate(0);
const YESTERDAY = isoDate(-1);
const TWO_DAYS_AGO = isoDate(-2);
const THIRTY_DAYS_AGO = isoDate(-30);
const EXPIRED_DATE = isoDate(-120);

function getFreePort() {
  return new Promise((done, reject) => {
    const server = createNetServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close(() => done(port));
    });
  });
}

async function http(url, options = {}) {
  const headers = {};
  if (options.cookie) headers.Cookie = options.cookie;
  if (options.token) headers['X-Internal-Token'] = options.token;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const started = performance.now();
  const res = await fetch(url, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  return { status: res.status, text, json, durationMs: performance.now() - started };
}

function runWrangler(argsList, env) {
  return new Promise((done, reject) => {
    const child = spawn(process.execPath, [WRANGLER_BIN, ...argsList], {
      cwd: EDGE_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    child.stdout.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) done(output);
      else reject(new Error(`wrangler ${argsList.join(' ')} 失败（exit ${code}）：\n${output}`));
    });
  });
}

async function waitForHealth(workerUrl, child, getOutput, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`wrangler dev 提前退出（exit ${child.exitCode}）：\n${getOutput()}`);
    }
    try {
      const res = await fetch(`${workerUrl}/healthz`);
      if (res.ok) return;
    } catch {
      // 尚未就绪
    }
    await delay(500);
  }
  throw new Error(`等待 wrangler dev 就绪超时：\n${getOutput()}`);
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  try {
    if (process.platform !== 'win32') process.kill(-child.pid, 'SIGTERM');
    else child.kill('SIGTERM');
  } catch {
    child.kill('SIGTERM');
  }
  await Promise.race([once(child, 'exit'), delay(5_000)]);
  if (child.exitCode === null) {
    try {
      if (process.platform !== 'win32') process.kill(-child.pid, 'SIGKILL');
      else child.kill('SIGKILL');
    } catch {
      // 已退出
    }
  }
}

function sqlQuote(value) {
  if (value === null || value === undefined) return 'NULL';
  return `'${String(value).replaceAll("'", "''")}'`;
}

/** 6 个热榜仓库：覆盖摘要回退三档（readme / description / tech）。 */
const REPOS = [
  {
    id: 'trend/alpha',
    name: 'alpha',
    language: 'Python',
    stars: 52_000,
    starsToday: 900,
    description: 'Alpha 项目：支付网关示例',
    techStack: 'Python,FastAPI',
    summary: 'Alpha 项目的中文摘要，介绍核心能力与适用场景。',
  },
  {
    id: 'trend/beta',
    name: 'beta',
    language: 'TypeScript',
    stars: 41_000,
    starsToday: 800,
    description: 'Beta 前端工具集',
    techStack: 'TypeScript,React',
    summary: null,
  },
  {
    id: 'trend/gamma',
    name: 'gamma',
    language: 'Go',
    stars: 33_000,
    starsToday: 700,
    description: null,
    techStack: 'Go',
    summary: null,
  },
  {
    id: 'trend/delta',
    name: 'delta',
    language: 'Rust',
    stars: 28_000,
    starsToday: 600,
    description: 'Delta 高性能运行时',
    techStack: 'Rust',
    summary: 'Delta 的中文摘要。',
  },
  {
    id: 'trend/epsilon',
    name: 'epsilon',
    language: 'Python',
    stars: 21_000,
    starsToday: 500,
    description: 'Epsilon 数据工具',
    techStack: 'Python,Pandas',
    summary: null,
  },
  {
    id: 'trend/zeta',
    name: 'zeta',
    language: 'TypeScript',
    stars: 18_000,
    starsToday: 400,
    description: 'Zeta 组件库',
    techStack: 'TypeScript,Vue',
    summary: null,
  },
];

/** 最新快照：排名 + 趋势（same / up / down / new）。 */
const LATEST_SNAPSHOTS = [
  { repo: 'trend/alpha', rank: 1, rankDelta: 0, isNew: 0, trend: 'same', appearances: 5 },
  { repo: 'trend/beta', rank: 2, rankDelta: 5, isNew: 0, trend: 'up', appearances: 3 },
  { repo: 'trend/gamma', rank: 3, rankDelta: -4, isNew: 0, trend: 'down', appearances: 4 },
  { repo: 'trend/delta', rank: 4, rankDelta: 0, isNew: 1, trend: 'new', appearances: 1 },
  { repo: 'trend/epsilon', rank: 5, rankDelta: 0, isNew: 0, trend: 'same', appearances: 2 },
  { repo: 'trend/zeta', rank: 6, rankDelta: 2, isNew: 0, trend: 'up', appearances: 2 },
];

function snapshotValues(repo, date, rank, rankDelta, isNew, trend, appearances) {
  return `(${[
    sqlQuote(date),
    sqlQuote(repo.id),
    "'github'",
    sqlQuote(repo.id.split('/')[0]),
    sqlQuote(repo.name),
    sqlQuote(`https://github.com/${repo.id}`),
    sqlQuote(repo.description),
    sqlQuote(repo.language),
    sqlQuote(repo.techStack),
    repo.stars,
    repo.starsToday,
    rank,
    rank,
    0,
    rankDelta,
    appearances,
    isNew,
    sqlQuote(trend),
    "'[]'",
  ].join(', ')})`;
}

function buildSeedSql() {
  const lines = [
    'PRAGMA foreign_keys = OFF;',
    `INSERT INTO users (id, login, name, email) VALUES (${sqlQuote(USER_ID)}, 'm2-tester', 'M2 Tester', 'm2@example.com');`,
  ];

  for (const repo of REPOS) {
    lines.push(
      `INSERT INTO trending_repositories (id, platform, name, html_url, stars_today, description, tech_stack, crawled_at, owner, language, stars, readme_summary) VALUES (${[
        sqlQuote(repo.id),
        "'github'",
        sqlQuote(repo.name),
        sqlQuote(`https://github.com/${repo.id}`),
        repo.starsToday,
        sqlQuote(repo.description),
        sqlQuote(repo.techStack),
        sqlQuote(TODAY),
        sqlQuote(repo.id.split('/')[0]),
        sqlQuote(repo.language),
        repo.stars,
        sqlQuote(repo.summary),
      ].join(', ')});`
    );
  }

  const values = [];
  for (const item of LATEST_SNAPSHOTS) {
    const repo = REPOS.find((entry) => entry.id === item.repo);
    values.push(
      snapshotValues(repo, TODAY, item.rank, item.rankDelta, item.isNew, item.trend, item.appearances)
    );
  }
  // 昨日 3 条（用于趋势基线与 history）
  values.push(snapshotValues(REPOS[0], YESTERDAY, 3, 0, 0, 'same', 4));
  values.push(snapshotValues(REPOS[1], YESTERDAY, 4, 0, 0, 'same', 2));
  values.push(snapshotValues(REPOS[2], YESTERDAY, 1, 0, 0, 'same', 3));
  // 30 天前 1 条（history 三点曲线）
  values.push(snapshotValues(REPOS[0], THIRTY_DAYS_AGO, 2, 0, 0, 'same', 1));
  // 过期 2 条（保留策略清理对象）
  values.push(
    `(${[
      sqlQuote(EXPIRED_DATE),
      sqlQuote('old/one'),
      "'github'",
      "'old'",
      "'one'",
      "'https://github.com/old/one'",
      "'过期样例'",
      "'Go'",
      "'Go'",
      100,
      10,
      1,
      1,
      0,
      0,
      1,
      0,
      "'same'",
      "'[]'",
    ].join(', ')})`
  );
  values.push(
    `(${[
      sqlQuote(EXPIRED_DATE),
      sqlQuote('old/two'),
      "'github'",
      "'old'",
      "'two'",
      "'https://github.com/old/two'",
      "'过期样例二'",
      "'Rust'",
      "'Rust'",
      90,
      9,
      2,
      2,
      0,
      0,
      1,
      0,
      "'same'",
      "'[]'",
    ].join(', ')})`
  );

  lines.push(
    `INSERT INTO trending_snapshots (snapshot_date, repo_id, platform, owner, name, html_url, description, language, tech_stack, stars, stars_today, rank, language_rank, star_delta, rank_delta, appearances, is_new, trend, trending_pages) VALUES\n${values.join(',\n')};`
  );

  return `${lines.join('\n')}\n`;
}

const results = [];
const perf = [];

async function check(id, title, fn) {
  const started = performance.now();
  try {
    const outcome = await fn();
    const status = outcome?.status ?? 'PASS';
    const detail = outcome?.detail ?? '';
    results.push({ id, title, status, detail, durationMs: performance.now() - started });
    const icon = status === 'PASS' ? '✔' : status === 'GAP' ? '○' : status === 'SKIP' ? '–' : '✖';
    console.log(`  ${icon} [${status}] ${title}${detail ? ` — ${detail}` : ''}`);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    results.push({ id, title, status: 'FAIL', detail, durationMs: performance.now() - started });
    console.log(`  ✖ [FAIL] ${title} — ${detail}`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}：期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}`);
  }
}

function percentile(sorted, p) {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[index];
}

async function sample(workerUrl, path, cookie, samples = PERF_SAMPLES) {
  const durations = [];
  for (let i = 0; i < samples; i += 1) {
    const res = await http(`${workerUrl}${path}`, { cookie });
    assertEqual(res.status, 200, `性能采样 ${path} 应 200`);
    durations.push(res.durationMs);
  }
  durations.sort((a, b) => a - b);
  return {
    path,
    samples,
    p50: percentile(durations, 50),
    p95: percentile(durations, 95),
    max: durations[durations.length - 1],
  };
}

function formatMs(value) {
  return `${value.toFixed(1)}ms`;
}

function summarize() {
  const summary = { PASS: 0, GAP: 0, FAIL: 0, SKIP: 0 };
  for (const item of results) summary[item.status] = (summary[item.status] ?? 0) + 1;
  return summary;
}

function buildMarkdown(meta) {
  const summary = summarize();
  const rows = results
    .map(
      (item) =>
        `| ${item.id} | ${item.title} | ${item.status} | ${item.detail.replaceAll('|', '\\|') || '—'} | ${formatMs(item.durationMs)} |`
    )
    .join('\n');
  const perfRows = perf
    .map(
      (item) =>
        `| \`${item.path}\` | ${item.samples} | ${formatMs(item.p50)} | ${formatMs(item.p95)} | ${formatMs(item.max)} | ${item.p95 < PERF_BUDGET_MS ? 'PASS' : 'FAIL'} |`
    )
    .join('\n');
  const gaps = results.filter((item) => item.status === 'GAP');
  return `# M2 验收报告（自动生成）

- 生成时间：${meta.finishedAt}
- 分支 / 提交：${meta.branch} / ${meta.commit}
- 运行环境：${meta.platform} · Node ${meta.nodeVersion}
- 数据规模：6 个热榜仓库 / 13 条快照（5 个日期，含 2 条过期）/ 1 个测试用户
- 判定口径：PASS 通过 · GAP 能力未集成（阻塞） · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
${rows}

## 性能抽样（预算 P95 < ${PERF_BUDGET_MS}ms）

| 场景 | 样本数 | P50 | P95 | Max | 结果 |
| --- | --- | --- | --- | --- | --- |
${perfRows}

## 汇总

- PASS：${summary.PASS}
- GAP：${summary.GAP}
- FAIL：${summary.FAIL}
- SKIP：${summary.SKIP}
- 结论：${summary.FAIL > 0 ? '存在失败项，验收不通过' : summary.GAP > 0 ? '已交付能力通过；存在未集成能力，整体验收待合并后复跑' : '全部通过'}

${gaps.length > 0 ? `## 未集成能力（GAP）\n\n${gaps.map((item) => `- ${item.id} ${item.title}：${item.detail || '能力未合入当前分支'}`).join('\n')}\n` : ''}`;
}

async function gitInfo() {
  const runGit = (args) =>
    new Promise((done) => {
      const child = spawn('git', args, { cwd: REPO_ROOT, stdio: ['ignore', 'pipe', 'ignore'] });
      let output = '';
      child.stdout.on('data', (chunk) => {
        output += chunk.toString();
      });
      child.on('exit', () => done(output.trim()));
    });
  return {
    branch: (await runGit(['rev-parse', '--abbrev-ref', 'HEAD'])) || 'unknown',
    commit: (await runGit(['rev-parse', '--short', 'HEAD'])) || 'unknown',
  };
}

async function main() {
  if (!existsSync(WRANGLER_BIN)) {
    throw new Error('未找到 wrangler，请先在 edge/ 下执行 npm ci');
  }

  const persistDir = join(EDGE_ROOT, '.wrangler', `e2e-m2-${process.pid}`);
  rmSync(persistDir, { recursive: true, force: true });
  const tempDir = mkdtempSync(join(tmpdir(), 'm2-acceptance-'));

  const env = {
    ...process.env,
    CI: '1',
    WRANGLER_SEND_METRICS: 'false',
    NO_COLOR: '1',
    FORCE_COLOR: '0',
  };

  console.log('• 应用本地 D1 迁移（0001~0008）…');
  await runWrangler(
    ['d1', 'migrations', 'apply', DB_NAME, '--local', '--persist-to', persistDir],
    env
  );

  console.log('• 种入 M2 验收数据集…');
  const seedFile = join(tempDir, 'seed.sql');
  writeFileSync(seedFile, buildSeedSql(), 'utf8');
  await runWrangler(
    ['d1', 'execute', DB_NAME, '--local', '--persist-to', persistDir, '--file', seedFile],
    env
  );

  const sessionId = createHash('sha256').update(SESSION_TOKEN).digest('hex');
  await runWrangler(
    [
      'd1',
      'execute',
      DB_NAME,
      '--local',
      '--persist-to',
      persistDir,
      '--command',
      `INSERT INTO sessions (id, user_id, expires_at) VALUES ('${sessionId}', '${USER_ID}', '2099-01-01T00:00:00.000Z');`,
    ],
    env
  );

  const workerPort = await getFreePort();
  const inspectorPort = await getFreePort();
  const workerUrl = `http://127.0.0.1:${workerPort}`;

  let wranglerOutput = '';
  const wrangler = spawn(
    process.execPath,
    [
      WRANGLER_BIN,
      'dev',
      '--ip',
      '127.0.0.1',
      '--port',
      String(workerPort),
      '--inspector-port',
      String(inspectorPort),
      '--persist-to',
      persistDir,
      '--var',
      `ALLOWED_ORIGIN:${ALLOWED_ORIGIN}`,
      '--var',
      `INTERNAL_TOKEN:${INTERNAL_TOKEN}`,
    ],
    {
      cwd: EDGE_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: process.platform !== 'win32',
    }
  );
  wrangler.stdout.on('data', (chunk) => {
    wranglerOutput += chunk.toString();
  });
  wrangler.stderr.on('data', (chunk) => {
    wranglerOutput += chunk.toString();
  });

  const cookie = `of_session=${SESSION_TOKEN}`;
  const auth = { cookie };
  const internal = { token: INTERNAL_TOKEN };

  try {
    console.log('• 启动 wrangler dev（本地 D1）…');
    await waitForHealth(workerUrl, wrangler, () => wranglerOutput);

    // ── A 列表 / 日期 / 语言 / 趋势（M2-05 / M2-06）────────────────
    await check('M2-A01', '默认返回最近一天快照（6 条，按排名升序）', async () => {
      const res = await http(`${workerUrl}/api/trending`, auth);
      assertEqual(res.status, 200, '状态码');
      assert(Array.isArray(res.json), '响应应为数组');
      assertEqual(res.json.length, 6, '条数');
      assertEqual(res.json[0]?.id, 'trend/alpha', '第一名');
      assertEqual(res.json[0]?.rank, 1, '第一名 rank');
      assertEqual(res.json[0]?.snapshotDate, TODAY, '快照日期');
      return { detail: `6 条 · ${TODAY}` };
    });

    await check('M2-A02', '按日期筛选（昨日 3 条）', async () => {
      const res = await http(`${workerUrl}/api/trending?date=${YESTERDAY}`, auth);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.length, 3, '条数');
      assertEqual(res.json?.[0]?.snapshotDate, YESTERDAY, '快照日期');
      return { detail: `3 条 · ${YESTERDAY}` };
    });

    await check('M2-A03', '按语言筛选大小写不敏感（python → 2 条）', async () => {
      const res = await http(`${workerUrl}/api/trending?language=python`, auth);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.length, 2, '条数');
      assert(
        res.json.every((item) => String(item.language).toLowerCase() === 'python'),
        '应只返回 Python 仓库'
      );
      return { detail: '2 条 Python' };
    });

    await check('M2-A04', '趋势标注 new / up / down / same 完整', async () => {
      const res = await http(`${workerUrl}/api/trending`, auth);
      const byId = new Map((res.json ?? []).map((item) => [item.id, item]));
      assertEqual(byId.get('trend/delta')?.trend, 'new', 'delta trend');
      assertEqual(byId.get('trend/delta')?.rankChange, null, '新上榜 rankChange');
      assertEqual(byId.get('trend/beta')?.trend, 'up', 'beta trend');
      assertEqual(byId.get('trend/beta')?.rankChange, 5, 'beta rankChange');
      assertEqual(byId.get('trend/gamma')?.trend, 'down', 'gamma trend');
      assertEqual(byId.get('trend/gamma')?.rankChange, -4, 'gamma rankChange');
      assertEqual(byId.get('trend/alpha')?.trend, 'same', 'alpha trend');
      return { detail: 'new/up/down/same 均命中' };
    });

    await check('M2-A05', 'limit 生效（limit=2）且非法日期 400', async () => {
      const limited = await http(`${workerUrl}/api/trending?limit=2`, auth);
      assertEqual(limited.status, 200, 'limit 状态码');
      assertEqual(limited.json?.length, 2, 'limit 条数');
      const bad = await http(`${workerUrl}/api/trending?date=2026-02-31`, auth);
      assertEqual(bad.status, 400, '非法日期状态码');
      assertEqual(bad.json?.field, 'date', '错误字段');
      return { detail: 'limit=2 · 2026-02-31 → 400' };
    });

    await check('M2-A06', '显式日期无数据返回空数组（不静默回退）', async () => {
      const res = await http(`${workerUrl}/api/trending?date=1900-01-01`, auth);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.length, 0, '条数');
      return { detail: '[]' };
    });

    await check('M2-B01', '快照日期列表倒序且带计数', async () => {
      const res = await http(`${workerUrl}/api/trending/dates`, auth);
      assertEqual(res.status, 200, '状态码');
      assert(Array.isArray(res.json), '响应应为数组');
      assertEqual(res.json.length, 4, '日期数');
      assertEqual(res.json[0]?.date, TODAY, '最新日期');
      assertEqual(res.json[0]?.count, 6, '最新日期条数');
      return { detail: '4 个日期 · 最新 6 条' };
    });

    await check('M2-B02', '语言分布按日期统计', async () => {
      const res = await http(`${workerUrl}/api/trending/languages?date=${TODAY}`, auth);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.date, TODAY, '统计日期');
      const counts = new Map((res.json?.languages ?? []).map((item) => [item.language, item.count]));
      assertEqual(counts.get('Python'), 2, 'Python');
      assertEqual(counts.get('TypeScript'), 2, 'TypeScript');
      assertEqual(counts.get('Go'), 1, 'Go');
      return { detail: 'Python 2 / TypeScript 2 / Go 1 / Rust 1' };
    });

    await check('M2-B03', '单仓库历史返回三点曲线（升序）', async () => {
      const res = await http(`${workerUrl}/api/trending/history?repoId=trend/alpha&days=30`, auth);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.length, 3, '快照点数');
      const dates = res.json.map((item) => item.snapshotDate);
      assertEqual(dates[0], THIRTY_DAYS_AGO, '最早日期');
      assertEqual(dates[2], TODAY, '最新日期');
      return { detail: `${dates.join(' → ')}` };
    });

    // ── C 详情 / 收藏（M2-07）────────────────────────────────────
    await check('M2-C01', '详情优先返回 README 中文摘要', async () => {
      const res = await http(`${workerUrl}/api/trending/trend/alpha`, auth);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.summarySource, 'readme', '摘要来源');
      assert(String(res.json?.summary ?? '').includes('中文摘要'), '摘要内容');
      assertEqual(res.json?.owner, 'trend', 'owner');
      assertEqual(res.json?.isFavorited, false, '收藏态');
      return { detail: 'readme · 未收藏' };
    });

    await check('M2-C02', '摘要回退 description / tech', async () => {
      const beta = await http(`${workerUrl}/api/trending/trend/beta`, auth);
      assertEqual(beta.json?.summarySource, 'description', 'beta 来源');
      assertEqual(beta.json?.summary, 'Beta 前端工具集', 'beta 摘要');
      const gamma = await http(`${workerUrl}/api/trending/trend/gamma`, auth);
      assertEqual(gamma.json?.summarySource, 'tech', 'gamma 来源');
      assert(String(gamma.json?.summary ?? '').includes('Go'), 'gamma 摘要');
      return { detail: 'description → tech' };
    });

    await check('M2-C03', '不存在的仓库详情 404', async () => {
      const res = await http(`${workerUrl}/api/trending/trend/missing`, auth);
      assertEqual(res.status, 404, '状态码');
      return { detail: '404 not_found' };
    });

    await check('M2-C04', '未登录收藏返回 401', async () => {
      const res = await http(`${workerUrl}/api/trending/trend/alpha/favorite`, { method: 'POST' });
      assertEqual(res.status, 401, '状态码');
      return { detail: '401 unauthorized' };
    });

    await check('M2-C05', '一键收藏幂等写入 my_repositories', async () => {
      const first = await http(`${workerUrl}/api/trending/trend/alpha/favorite`, {
        ...auth,
        method: 'POST',
      });
      assertEqual(first.status, 200, '首次状态码');
      assertEqual(first.json?.favorited, true, '首次 favorited');
      assertEqual(first.json?.created, true, '首次 created');
      const second = await http(`${workerUrl}/api/trending/trend/alpha/favorite`, {
        ...auth,
        method: 'POST',
      });
      assertEqual(second.status, 200, '重复状态码');
      assertEqual(second.json?.created, false, '重复 created');
      const detail = await http(`${workerUrl}/api/trending/trend/alpha`, auth);
      assertEqual(detail.json?.isFavorited, true, '详情收藏态');
      return { detail: 'created true → false，详情 isFavorited=true' };
    });

    await check('M2-C06', '取消收藏后详情恢复未收藏', async () => {
      const res = await http(`${workerUrl}/api/trending/trend/alpha/favorite`, {
        ...auth,
        method: 'DELETE',
      });
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.favorited, false, 'favorited');
      assertEqual(res.json?.removed, true, 'removed');
      const detail = await http(`${workerUrl}/api/trending/trend/alpha`, auth);
      assertEqual(detail.json?.isFavorited, false, '详情收藏态');
      return { detail: 'removed=true → 未收藏' };
    });

    // ── D 摘要回写（M2-04）──────────────────────────────────────
    await check('M2-D01', '摘要回写接口校验内部令牌', async () => {
      const res = await http(`${workerUrl}/api/trending/summaries`, {
        method: 'POST',
        body: { items: [{ repoId: 'trend/beta', summary: '未授权写入' }] },
      });
      assertEqual(res.status, 401, '状态码');
      const ok = await http(`${workerUrl}/api/trending/summaries`, {
        ...internal,
        method: 'POST',
        body: { items: [] },
      });
      assertEqual(ok.status, 200, '带令牌状态码');
      return { detail: '401 → 200' };
    });

    await check('M2-D02', '摘要批量回写后详情立即生效', async () => {
      const res = await http(`${workerUrl}/api/trending/summaries`, {
        ...internal,
        method: 'POST',
        body: {
          items: [
            { repoId: 'trend/beta', summary: 'Beta 的新中文摘要：批量回写验收。' },
            { repoId: 'trend/missing', summary: '不存在仓库应跳过' },
          ],
        },
      });
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.updated, 1, '更新数');
      assertEqual(res.json?.skipped, 1, '跳过数');
      const detail = await http(`${workerUrl}/api/trending/trend/beta`, auth);
      assertEqual(detail.json?.summarySource, 'readme', '回写后来源');
      assert(String(detail.json?.summary ?? '').includes('批量回写验收'), '回写后摘要');
      return { detail: 'updated 1 / skipped 1' };
    });

    // ── E 内部快照与保留策略（M2-05 / M2-08）────────────────────
    await check('M2-E01', '内部快照接口校验令牌', async () => {
      const res = await http(`${workerUrl}/api/internal/trending/snapshots`, {
        method: 'POST',
        body: { snapshotDate: TWO_DAYS_AGO, items: [] },
      });
      assertEqual(res.status, 401, '状态码');
      return { detail: '401 unauthorized' };
    });

    await check('M2-E02', '内部快照 upsert 幂等且可更新排名', async () => {
      const payload = {
        snapshotDate: TWO_DAYS_AGO,
        items: [
          {
            repoId: 'trend/newbie',
            platform: 'github',
            owner: 'trend',
            name: 'newbie',
            htmlUrl: 'https://github.com/trend/newbie',
            description: '新上榜样例',
            language: 'Python',
            techStack: 'Python',
            stars: 5000,
            starsToday: 320,
            rank: 3,
            languageRank: 1,
            starDelta: 120,
            rankDelta: 0,
            appearances: 1,
            isNew: true,
            trend: 'new',
            trendingPages: ['python'],
          },
        ],
      };
      const first = await http(`${workerUrl}/api/internal/trending/snapshots`, {
        ...internal,
        method: 'POST',
        body: payload,
      });
      assertEqual(first.status, 200, '首次状态码');
      assertEqual(first.json?.upserted, 1, '首次 upserted');
      payload.items[0].rank = 1;
      payload.items[0].starsToday = 999;
      const second = await http(`${workerUrl}/api/internal/trending/snapshots`, {
        ...internal,
        method: 'POST',
        body: payload,
      });
      assertEqual(second.status, 200, '重复状态码');
      const list = await http(`${workerUrl}/api/trending?date=${TWO_DAYS_AGO}`, auth);
      assertEqual(list.json?.length, 1, '该日条数');
      assertEqual(list.json?.[0]?.rank, 1, '更新后排名');
      assertEqual(list.json?.[0]?.starsToday, 999, '更新后今日 Star');
      return { detail: 'upsert 1 → 更新 rank=1' };
    });

    await check('M2-E03', '保留策略状态统计（总数 / 最早 / 最新）', async () => {
      const res = await http(`${workerUrl}/api/internal/trending/retention`, internal);
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.total, 13, '快照总数');
      assertEqual(res.json?.oldest, EXPIRED_DATE, '最早日期');
      assertEqual(res.json?.newest, TODAY, '最新日期');
      return { detail: `total=13 · ${EXPIRED_DATE} → ${TODAY}` };
    });

    await check('M2-E04', '保留清理 dryRun 只统计不删除', async () => {
      const dry = await http(`${workerUrl}/api/internal/trending/retention/cleanup`, {
        ...internal,
        method: 'POST',
        body: { beforeDate: isoDate(-90), dryRun: true },
      });
      assertEqual(dry.status, 200, '状态码');
      assertEqual(dry.json?.deleted, 2, 'dryRun 命中数');
      const status = await http(`${workerUrl}/api/internal/trending/retention`, internal);
      assertEqual(status.json?.total, 13, 'dryRun 后总数');
      return { detail: '命中 2 · 未删除' };
    });

    await check('M2-E05', '保留清理实际删除过期快照', async () => {
      const res = await http(`${workerUrl}/api/internal/trending/retention/cleanup`, {
        ...internal,
        method: 'POST',
        body: { beforeDate: isoDate(-90) },
      });
      assertEqual(res.status, 200, '状态码');
      assertEqual(res.json?.deleted, 2, '删除数');
      const status = await http(`${workerUrl}/api/internal/trending/retention`, internal);
      assertEqual(status.json?.total, 11, '清理后总数');
      assertEqual(status.json?.oldest, THIRTY_DAYS_AGO, '清理后最早日期');
      return { detail: '删除 2 · 剩余 11' };
    });

    // ── F 旧数据回退 + 性能 ─────────────────────────────────────
    await check('M2-F01', '无任何快照时回退 trending_repositories', async () => {
      const cleanup = await http(`${workerUrl}/api/internal/trending/retention/cleanup`, {
        ...internal,
        method: 'POST',
        body: { beforeDate: isoDate(1) },
      });
      assertEqual(cleanup.status, 200, '清空状态码');
      const res = await http(`${workerUrl}/api/trending`, auth);
      assertEqual(res.status, 200, '回退状态码');
      assertEqual(res.json?.length, 6, '回退条数');
      assertEqual(res.json?.[0]?.id, 'trend/alpha', '按今日 Star 排序');
      assertEqual(res.json?.[0]?.rank, 1, '回退排名');
      return { detail: `删除 ${cleanup.json?.deleted} 条后回退 6 条` };
    });

    console.log('• 性能抽样…');
    const sampleResult = await sample(workerUrl, '/api/trending?limit=100', cookie);
    perf.push({ ...sampleResult, label: '热榜列表 limit=100' });
    console.log(
      `  · 热榜列表：P50 ${formatMs(sampleResult.p50)} / P95 ${formatMs(sampleResult.p95)} / Max ${formatMs(sampleResult.max)}`
    );
    results.push({
      id: 'M2-P01',
      title: `性能抽样 P95 < ${PERF_BUDGET_MS}ms`,
      status: sampleResult.p95 < PERF_BUDGET_MS ? 'PASS' : 'FAIL',
      detail: `P50 ${formatMs(sampleResult.p50)} / P95 ${formatMs(sampleResult.p95)}`,
      durationMs: sampleResult.p95,
    });

    const summary = summarize();
    console.log(
      `\n汇总：PASS ${summary.PASS} · GAP ${summary.GAP} · FAIL ${summary.FAIL} · SKIP ${summary.SKIP}`
    );

    const git = await gitInfo();
    const meta = {
      ...git,
      finishedAt: new Date().toISOString(),
      platform: `${process.platform} ${process.arch}`,
      nodeVersion: process.version,
    };
    if (REPORT_MD) {
      const target = resolve(REPO_ROOT, REPORT_MD);
      writeFileSync(target, buildMarkdown(meta), 'utf8');
      console.log(`• 已写入 Markdown 报告：${target}`);
    }
    if (REPORT_JSON) {
      const target = resolve(REPO_ROOT, REPORT_JSON);
      writeFileSync(target, JSON.stringify({ meta, results, perf }, null, 2), 'utf8');
      console.log(`• 已写入 JSON 报告：${target}`);
    }

    if (summary.FAIL > 0 || (STRICT && summary.GAP > 0)) {
      process.exitCode = 1;
    }
  } finally {
    await stopChild(wrangler);
    if (!KEEP) rmSync(persistDir, { recursive: true, force: true });
    else console.log(`• 保留本地 D1 目录：${persistDir}`);
    rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(`\n✖ ${err instanceof Error ? err.message : String(err)}`);
  process.exitCode = 1;
});
