#!/usr/bin/env node
/**
 * 仓库检索基准 / 查询计划核对（REQ-202610-0904）
 *
 * 用 Node 内置 node:sqlite 加载 edge/migrations 下的真实迁移，
 * 灌入确定性的 20k 仓库数据，然后：
 *   1. 对四类查询执行 EXPLAIN QUERY PLAN，断言命中复合索引且无临时排序；
 *   2. 每类查询跑 200 次，输出 P50 / P95，P95 >= 300ms 时退出码 1。
 *
 * 用法：
 *   node scripts/search-bench.mjs [--rows 20000] [--iters 200]
 *
 * 说明：D1 与本地 SQLite 同为 SQLite 引擎，本脚本验证 SQL 与索引设计；
 * 真实 D1 的远端复测步骤见 docs/guides/search-performance.md。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const HERE = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS_DIR = join(HERE, '..', 'migrations');
const P95_BUDGET_MS = 300;

function argValue(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  const value = Number.parseInt(process.argv[index + 1] ?? '', 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const TOTAL_ROWS = argValue('--rows', 20000);
const ITERATIONS = argValue('--iters', 200);
const USERS = 50;
const CATEGORIES = 12;
const TAGS = 30;
const PAGE_SIZE = 100;

/** 确定性伪随机，保证每次基准数据一致 */
function mulberry32(seed) {
  return function random() {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function loadMigrations(db) {
  const files = readdirSync(MIGRATIONS_DIR)
    .filter((name) => name.endsWith('.sql'))
    .sort();
  for (const file of files) {
    db.exec(readFileSync(join(MIGRATIONS_DIR, file), 'utf8'));
  }
  return files;
}

function seed(db) {
  const random = mulberry32(20261022);
  const languages = ['TypeScript', 'Python', 'Go', 'Rust', 'Java', 'C++', 'JavaScript'];
  const keywords = ['payment', 'gateway', 'framework', 'database', 'agent', 'ui', 'cli', 'infra'];

  const insertRepo = db.prepare(
    `INSERT INTO my_repositories
       (id, platform, name, description, html_url, stars, language, readme_summary,
        category_id, created_at, user_id, owner, forks, updated_at, synced_at)
     VALUES (?, 'github', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );
  const insertTag = db.prepare('INSERT INTO tags (name, count) VALUES (?, 0)');
  const insertRepoTag = db.prepare('INSERT INTO repo_tags (repo_id, tag_id) VALUES (?, ?)');
  const insertCategory = db.prepare('INSERT INTO categories (id, name) VALUES (?, ?)');

  db.exec('BEGIN');
  for (let i = 0; i < CATEGORIES; i += 1) {
    insertCategory.run(`c${String(i).padStart(2, '0')}`, `分类 ${i}`);
  }
  for (let i = 0; i < TAGS; i += 1) {
    insertTag.run(`tag-${String(i).padStart(2, '0')}`);
  }

  for (let i = 0; i < TOTAL_ROWS; i += 1) {
    const user = `u${String(i % USERS).padStart(3, '0')}`;
    const name = `repo-${i}-${keywords[i % keywords.length]}`;
    const description = `${keywords[i % keywords.length]} 项目 ${i} 的描述，用于检索基准`;
    const repoId = `${user}/${name}`;
    const categoryId = `c${String(i % CATEGORIES).padStart(2, '0')}`;
    const stars = Math.floor(random() * 100000);
    const updatedAt = `2026-${String((i % 12) + 1).padStart(2, '0')}-${String((i % 28) + 1).padStart(2, '0')}T00:00:00Z`;
    insertRepo.run(
      repoId,
      name,
      description,
      `https://github.com/${repoId}`,
      stars,
      languages[i % languages.length],
      description,
      categoryId,
      '2026-01-01T00:00:00Z',
      user,
      user,
      Math.floor(random() * 5000),
      updatedAt,
      updatedAt
    );
    insertRepoTag.run(repoId, (i % TAGS) + 1);
    insertRepoTag.run(repoId, ((i + 7) % TAGS) + 1);
  }
  db.exec('COMMIT');
  db.exec('ANALYZE');
}

const SELECT_COLUMNS = `
  r.id, r.platform, r.name,
  COALESCE(r.description, r.readme_summary) AS description,
  r.html_url, r.stars, r.language, r.category_id, r.created_at,
  r.user_id, r.owner, r.forks, r.updated_at, r.synced_at,
  cat.name AS category_name,
  (SELECT GROUP_CONCAT(t.name, ',')
     FROM repo_tags rt JOIN tags t ON t.id = rt.tag_id
    WHERE rt.repo_id = r.id) AS tag_names`;

function buildQuery(kind) {
  const where = ['r.user_id = ?'];
  const params = [];
  if (kind.includes('category')) {
    where.push('r.category_id = ?');
  }
  if (kind.includes('keyword')) {
    where.push("(r.name LIKE ? ESCAPE '\\' OR r.id LIKE ? ESCAPE '\\' OR r.description LIKE ? ESCAPE '\\')");
  }
  const sql = `SELECT ${SELECT_COLUMNS}
                 FROM my_repositories r
                 LEFT JOIN categories cat ON cat.id = r.category_id
                WHERE ${where.join(' AND ')}
                ORDER BY r.stars DESC, r.updated_at DESC
                LIMIT ? OFFSET ?`;
  return { sql, params, where };
}

function queryParams(kind, random) {
  const user = `u${String(Math.floor(random() * USERS)).padStart(3, '0')}`;
  const params = [user];
  if (kind.includes('category')) {
    params.push(`c${String(Math.floor(random() * CATEGORIES)).padStart(2, '0')}`);
  }
  if (kind.includes('keyword')) {
    const keyword = ['payment', 'framework', 'agent', 'cli'][Math.floor(random() * 4)];
    const like = `%${keyword}%`;
    params.push(like, like, like);
  }
  params.push(PAGE_SIZE, 0);
  return params;
}

function explain(db, kind) {
  const { sql } = buildQuery(kind);
  const params = queryParams(kind, mulberry32(7));
  return db
    .prepare(`EXPLAIN QUERY PLAN ${sql}`)
    .all(...params)
    .map((row) => row.detail)
    .join(' | ');
}

function percentile(sorted, p) {
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * p) - 1));
  return sorted[index];
}

function benchmark(db, kind, random) {
  const { sql } = buildQuery(kind);
  const stmt = db.prepare(sql);
  for (let i = 0; i < 20; i += 1) {
    stmt.all(...queryParams(kind, random));
  }
  const samples = [];
  for (let i = 0; i < ITERATIONS; i += 1) {
    const params = queryParams(kind, random);
    const start = process.hrtime.bigint();
    stmt.all(...params);
    const elapsed = Number(process.hrtime.bigint() - start) / 1e6;
    samples.push(elapsed);
  }
  samples.sort((a, b) => a - b);
  return {
    p50: percentile(samples, 0.5),
    p95: percentile(samples, 0.95),
    max: samples[samples.length - 1],
  };
}

function main() {
  const db = new DatabaseSync(':memory:');
  const migrations = loadMigrations(db);
  seed(db);

  const cases = [
    { kind: 'list', label: '用户列表', expectIndex: 'idx_my_repositories_user_stars' },
    {
      kind: 'category',
      label: '分类筛选',
      expectIndex: 'idx_my_repositories_user_category_stars',
    },
    { kind: 'keyword', label: '关键字检索', expectIndex: 'idx_my_repositories_user_stars' },
    {
      kind: 'keyword+category',
      label: '关键字 + 分类',
      expectIndex: 'idx_my_repositories_user_category_stars',
    },
  ];

  console.log(`迁移：${migrations.join(', ')}`);
  console.log(`数据：${TOTAL_ROWS} 仓库 / ${USERS} 用户 / ${CATEGORIES} 分类 / ${TAGS} 标签`);
  console.log(`预算：P95 < ${P95_BUDGET_MS}ms（每类 ${ITERATIONS} 次）\n`);

  const failures = [];
  const random = mulberry32(42);
  console.log('查询计划：');
  for (const item of cases) {
    const plan = explain(db, item.kind);
    const usesIndex = plan.includes(item.expectIndex);
    const tempSort = plan.includes('USE TEMP B-TREE FOR ORDER BY');
    const fullScan = /SCAN (r|my_repositories)\b/.test(plan);
    console.log(`  ${item.label}: ${plan}`);
    if (!usesIndex) failures.push(`${item.label} 未命中索引 ${item.expectIndex}`);
    if (tempSort) failures.push(`${item.label} 出现临时排序（USE TEMP B-TREE FOR ORDER BY）`);
    if (fullScan) failures.push(`${item.label} 出现全表扫描`);
  }

  console.log('\n响应时间：');
  console.log('  查询              P50        P95        Max');
  for (const item of cases) {
    const result = benchmark(db, item.kind, random);
    console.log(
      `  ${item.label.padEnd(14)} ${result.p50.toFixed(2).padStart(7)}ms ${result.p95
        .toFixed(2)
        .padStart(7)}ms ${result.max.toFixed(2).padStart(7)}ms`
    );
    if (result.p95 >= P95_BUDGET_MS) {
      failures.push(`${item.label} P95 ${result.p95.toFixed(2)}ms 超出 ${P95_BUDGET_MS}ms`);
    }
  }

  if (failures.length > 0) {
    console.error('\n未通过：');
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exit(1);
  }
  console.log('\n通过：索引命中、无临时排序，P95 在预算内。');
}

main();
