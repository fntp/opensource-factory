#!/usr/bin/env node
/**
 * D1 数据库创建与迁移引导脚本（REQ-202610-0894）
 *
 * 用法：
 *   node scripts/d1-bootstrap.mjs local            # 本地迁移 + schema 校验 + 幂等复跑
 *   node scripts/d1-bootstrap.mjs remote           # 创建/复用远程 D1，替换 database_id，应用迁移
 *   node scripts/d1-bootstrap.mjs check            # 配置与 schema 副本一致性检查（占位符仅告警）
 *   node scripts/d1-bootstrap.mjs check --require-id  # 部署门禁：database_id 仍为占位符则失败
 *
 * 远程模式凭据（二选一，均不落盘、不回显）：
 *   - 环境变量 CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID
 *   - 或本机已执行 `wrangler login`
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const EDGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const CONFIG_PATH = join(EDGE_ROOT, 'wrangler.toml');
const MIGRATIONS_DIR = join(EDGE_ROOT, 'migrations');
const SCHEMA_ASSET_PATH = join(EDGE_ROOT, '..', 'docs', 'assets', 'd1-schema.sql');

const EXPECTED_TABLES = [
  'categories',
  'my_repositories',
  'recommendations',
  'repo_tags',
  'sessions',
  'tags',
  'trending_repositories',
  'users',
];

const EXPECTED_INDEXES = [
  'idx_my_repositories_category_id',
  'idx_my_repositories_user_id',
  'idx_recommendations_score',
  'idx_recommendations_user_id',
  'idx_repo_tags_tag_id',
  'idx_sessions_expires_at',
  'idx_sessions_user_id',
  'idx_trending_repositories_stars_today',
];

const PLACEHOLDER_ID = 'REPLACE_WITH_D1_DATABASE_ID';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** 从可能夹带提示文本的输出中提取第一个完整 JSON 值。 */
export function extractJson(text) {
  const trimmed = String(text ?? '').trim();
  if (!trimmed) throw new Error('wrangler 未返回 JSON 输出');
  try {
    return JSON.parse(trimmed);
  } catch {
    // 继续尝试截取
  }
  for (const [open, close] of [['[', ']'], ['{', '}']]) {
    const start = trimmed.indexOf(open);
    const end = trimmed.lastIndexOf(close);
    if (start !== -1 && end > start) {
      try {
        return JSON.parse(trimmed.slice(start, end + 1));
      } catch {
        // 尝试下一种括号
      }
    }
  }
  throw new Error(`无法解析 wrangler JSON 输出：${trimmed.slice(0, 200)}`);
}

/** 校验 database_id 是否为 D1 UUID（占位符单独判断）。 */
export function validateDatabaseId(id) {
  return typeof id === 'string' && UUID_RE.test(id);
}

/** 解析 wrangler.toml 的 [[d1_databases]] 段（仓库只有一个 D1 绑定）。 */
export function parseD1Config(toml) {
  const section = String(toml).match(/\[\[d1_databases\]\]([\s\S]*?)(?=\n\[|$)/);
  if (!section) throw new Error('wrangler.toml 缺少 [[d1_databases]] 配置段');
  const body = section[1];
  const pick = (key) => {
    const match = body.match(new RegExp(`^\\s*${key}\\s*=\\s*"([^"]*)"`, 'm'));
    return match ? match[1] : '';
  };
  return {
    binding: pick('binding'),
    databaseName: pick('database_name'),
    databaseId: pick('database_id'),
  };
}

/** 仅替换 D1 配置段内的 database_id，保留其余内容与注释不变。 */
export function replaceDatabaseId(toml, databaseId) {
  if (!validateDatabaseId(databaseId)) throw new Error(`database_id 不是合法 UUID：${databaseId}`);
  const sectionRe = /(\[\[d1_databases\]\][\s\S]*?)(?=\n\[|$)/;
  const section = String(toml).match(sectionRe);
  if (!section) throw new Error('wrangler.toml 缺少 [[d1_databases]] 配置段');
  const idRe = /^(\s*database_id\s*=\s*)"[^"]*"/m;
  if (!idRe.test(section[1])) throw new Error('[[d1_databases]] 段缺少 database_id');
  const updatedSection = section[1].replace(idRe, `$1"${databaseId}"`);
  return String(toml).replace(sectionRe, updatedSection);
}

/** SQL 归一化：去掉行注释与空白，用于迁移文件与数据资产副本的一致性比对。 */
export function normalizeSql(sql) {
  return String(sql)
    .split('\n')
    .map((line) => line.replace(/--.*$/, ''))
    .join('\n')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 校验迁移文件与 docs/assets/d1-schema.sql 是否一致。 */
export function checkSchemaParity(migrationSql, assetSql) {
  return normalizeSql(migrationSql) === normalizeSql(assetSql);
}

function wranglerBin() {
  const local = join(EDGE_ROOT, 'node_modules', '.bin', 'wrangler');
  if (existsSync(local)) return { command: local, prefix: [] };
  return { command: 'npx', prefix: ['--no-install', 'wrangler'] };
}

function runWrangler(args, { allowFailure = false } = {}) {
  const { command, prefix } = wranglerBin();
  const result = spawnSync(command, [...prefix, ...args], {
    cwd: EDGE_ROOT,
    encoding: 'utf8',
    env: process.env,
  });
  if (result.error) throw result.error;
  if (result.status !== 0 && !allowFailure) {
    const detail = (result.stderr || result.stdout || '').trim().split('\n').slice(-8).join('\n');
    throw new Error(`wrangler ${args.join(' ')} 失败（exit ${result.status}）：\n${detail}`);
  }
  return { status: result.status, stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
}

function listDatabases() {
  const { stdout } = runWrangler(['d1', 'list', '--json']);
  const parsed = extractJson(stdout);
  if (!Array.isArray(parsed)) throw new Error('wrangler d1 list --json 返回的不是数组');
  return parsed;
}

function resolveRemoteDatabase(databaseName) {
  let databases = listDatabases();
  let db = databases.find((item) => item.name === databaseName);
  if (!db) {
    console.log(`未找到数据库 ${databaseName}，正在创建…`);
    runWrangler(['d1', 'create', databaseName]);
    databases = listDatabases();
    db = databases.find((item) => item.name === databaseName);
  }
  if (!db) throw new Error(`数据库 ${databaseName} 创建后仍未在账号中找到`);
  const id = db.uuid ?? db.id;
  if (!validateDatabaseId(id)) throw new Error(`数据库 ${databaseName} 返回的 id 非法：${id}`);
  return { id, name: db.name };
}

function patchConfig(databaseId) {
  const toml = readFileSync(CONFIG_PATH, 'utf8');
  const current = parseD1Config(toml);
  if (current.databaseId === databaseId) {
    console.log(`wrangler.toml database_id 已是 ${databaseId}，无需改写`);
    return false;
  }
  const next = replaceDatabaseId(toml, databaseId);
  const tmp = `${CONFIG_PATH}.tmp-${process.pid}`;
  writeFileSync(tmp, next, 'utf8');
  renameSync(tmp, CONFIG_PATH);
  console.log(`已更新 wrangler.toml：database_id ${current.databaseId} → ${databaseId}`);
  return true;
}

function querySchema(scope, databaseName) {
  const sql =
    "SELECT type, name FROM sqlite_master WHERE type IN ('table','index') " +
    "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name NOT LIKE 'd1_%' " +
    'ORDER BY type, name';
  const args = ['d1', 'execute', databaseName, scope, '--json', '--command', sql];
  const { stdout } = runWrangler(args);
  const parsed = extractJson(stdout);
  const rows = Array.isArray(parsed) ? parsed.flatMap((entry) => entry.results ?? []) : [];
  return rows;
}

function verifySchema(scope, databaseName) {
  const rows = querySchema(scope, databaseName);
  const tables = rows.filter((row) => row.type === 'table').map((row) => row.name).sort();
  const indexes = rows.filter((row) => row.type === 'index').map((row) => row.name).sort();
  const missingTables = EXPECTED_TABLES.filter((name) => !tables.includes(name));
  const missingIndexes = EXPECTED_INDEXES.filter((name) => !indexes.includes(name));
  if (missingTables.length || missingIndexes.length) {
    throw new Error(
      `schema 校验失败：缺少表 [${missingTables.join(', ') || '无'}]，缺少索引 [${missingIndexes.join(', ') || '无'}]`,
    );
  }
  console.log(`schema 校验通过：${tables.length} 张表 / ${indexes.length} 个索引`);
}

function migrationFiles() {
  return readdirSync(MIGRATIONS_DIR)
    .filter((name) => /^\d+_.*\.sql$/.test(name))
    .sort();
}

function countMigrationFiles() {
  return migrationFiles().length;
}

function readAllMigrations() {
  return migrationFiles()
    .map((name) => readFileSync(join(MIGRATIONS_DIR, name), 'utf8'))
    .join('\n');
}

function verifyMigrationCount(scope, databaseName) {
  const sql = 'SELECT COUNT(*) AS applied FROM d1_migrations';
  const { stdout } = runWrangler([
    'd1',
    'execute',
    databaseName,
    scope,
    '--json',
    '--command',
    sql,
  ]);
  const parsed = extractJson(stdout);
  const rows = Array.isArray(parsed) ? parsed.flatMap((entry) => entry.results ?? []) : [];
  const applied = Number(rows[0]?.applied ?? 0);
  const expected = countMigrationFiles();
  if (applied !== expected) {
    throw new Error(`迁移记录数不一致：d1_migrations=${applied}，迁移文件=${expected}`);
  }
  console.log(`迁移记录校验通过：已应用 ${applied} 个迁移`);
}

function runLocal() {
  const config = parseD1Config(readFileSync(CONFIG_PATH, 'utf8'));
  if (!config.databaseName) throw new Error('wrangler.toml 未配置 database_name');
  console.log('== D1 本地迁移 ==');
  runWrangler(['d1', 'migrations', 'apply', config.databaseName, '--local']);
  verifySchema('--local', config.databaseName);
  verifyMigrationCount('--local', config.databaseName);
  console.log('== 幂等复跑（应无待应用迁移）==');
  runWrangler(['d1', 'migrations', 'apply', config.databaseName, '--local']);
  verifyMigrationCount('--local', config.databaseName);
  console.log('本地 D1 迁移验证完成（.wrangler/state，未触碰远程）。');
}

function runRemote() {
  const toml = readFileSync(CONFIG_PATH, 'utf8');
  const config = parseD1Config(toml);
  if (!config.databaseName) throw new Error('wrangler.toml 未配置 database_name');
  console.log('== D1 远程数据库 ==');
  const { id } = resolveRemoteDatabase(config.databaseName);
  patchConfig(id);
  console.log('== 应用远程迁移 ==');
  runWrangler(['d1', 'migrations', 'apply', config.databaseName, '--remote']);
  verifySchema('--remote', config.databaseName);
  verifyMigrationCount('--remote', config.databaseName);
  console.log('远程 D1 迁移验证完成。');
}

function runCheck(requireId) {
  const toml = readFileSync(CONFIG_PATH, 'utf8');
  const config = parseD1Config(toml);
  if (config.binding !== 'DB') throw new Error(`D1 binding 应为 DB，实际为 ${config.binding || '空'}`);
  if (!config.databaseName) throw new Error('wrangler.toml 未配置 database_name');
  const placeholder = config.databaseId === PLACEHOLDER_ID;
  if (placeholder) {
    console.log('wrangler.toml：database_id 仍为占位符（本地可用，远程部署前需运行 db:bootstrap:remote）');
    if (requireId) throw new Error('database_id 仍为占位符，远程部署门禁未通过');
  } else if (!validateDatabaseId(config.databaseId)) {
    throw new Error(`database_id 格式非法：${config.databaseId}`);
  } else {
    console.log(`wrangler.toml：database_id 格式有效（${config.databaseId}）`);
  }
  const migrations = readAllMigrations();
  const asset = readFileSync(SCHEMA_ASSET_PATH, 'utf8');
  if (!checkSchemaParity(migrations, asset)) {
    throw new Error('docs/assets/d1-schema.sql 与 edge/migrations/*.sql 不一致');
  }
  console.log('schema 副本一致：edge/migrations/*.sql == docs/assets/d1-schema.sql');
}

function main() {
  const [, , command = 'local', ...rest] = process.argv;
  switch (command) {
    case 'local':
      runLocal();
      break;
    case 'remote':
      runRemote();
      break;
    case 'check':
      runCheck(rest.includes('--require-id'));
      break;
    case '-h':
    case '--help':
      console.log('用法：node scripts/d1-bootstrap.mjs <local|remote|check> [--require-id]');
      break;
    default:
      console.error(`未知命令：${command}`);
      console.error('用法：node scripts/d1-bootstrap.mjs <local|remote|check> [--require-id]');
      process.exit(2);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main();
  } catch (error) {
    console.error(`\n✗ ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
