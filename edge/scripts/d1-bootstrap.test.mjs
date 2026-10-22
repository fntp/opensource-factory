import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  checkSchemaParity,
  extractJson,
  normalizeSql,
  parseD1Config,
  replaceDatabaseId,
  validateDatabaseId,
} from './d1-bootstrap.mjs';

const EDGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const UUID = '123e4567-e89b-12d3-a456-426614174000';

const SAMPLE_TOML = `name = "opensource-factory-api"
main = "src/index.ts"

[[d1_databases]]
binding = "DB"
database_name = "opensource-factory"
database_id = "REPLACE_WITH_D1_DATABASE_ID"

[vars]
ALLOWED_ORIGIN = "http://localhost:5173"
# database_id = "not-in-d1-section"
`;

test('validateDatabaseId 只接受 UUID，拒绝占位符与随意字符串', () => {
  assert.equal(validateDatabaseId(UUID), true);
  assert.equal(validateDatabaseId(UUID.toUpperCase()), true);
  assert.equal(validateDatabaseId('REPLACE_WITH_D1_DATABASE_ID'), false);
  assert.equal(validateDatabaseId('not-a-uuid'), false);
  assert.equal(validateDatabaseId(undefined), false);
});

test('parseD1Config 解析绑定名、库名与 database_id', () => {
  assert.deepEqual(parseD1Config(SAMPLE_TOML), {
    binding: 'DB',
    databaseName: 'opensource-factory',
    databaseId: 'REPLACE_WITH_D1_DATABASE_ID',
  });
});

test('replaceDatabaseId 只改写 D1 段，保留其余内容', () => {
  const updated = replaceDatabaseId(SAMPLE_TOML, UUID);
  assert.match(updated, new RegExp(`database_id = "${UUID}"`));
  assert.match(updated, /ALLOWED_ORIGIN = "http:\/\/localhost:5173"/);
  assert.match(updated, /# database_id = "not-in-d1-section"/);
  assert.equal(parseD1Config(updated).databaseId, UUID);
});

test('replaceDatabaseId 拒绝非法 id', () => {
  assert.throws(() => replaceDatabaseId(SAMPLE_TOML, 'REPLACE_WITH_D1_DATABASE_ID'), /合法 UUID/);
});

test('extractJson 兼容 wrangler 提示文本前后夹带', () => {
  const output = 'some warning\n[{"name":"opensource-factory","uuid":"x"}]\n';
  assert.deepEqual(extractJson(output), [{ name: 'opensource-factory', uuid: 'x' }]);
});

test('normalizeSql 忽略注释与空白差异', () => {
  const a = '-- 注释\nCREATE TABLE t (id TEXT);\n';
  const b = 'CREATE   TABLE t\n(id TEXT); -- 行尾注释';
  assert.equal(normalizeSql(a), normalizeSql(b));
});

test('checkSchemaParity 能发现结构差异', () => {
  assert.equal(checkSchemaParity('CREATE TABLE a (id TEXT);', '-- x\nCREATE TABLE a (id TEXT);'), true);
  assert.equal(checkSchemaParity('CREATE TABLE a (id TEXT);', 'CREATE TABLE b (id TEXT);'), false);
});

test('仓库迁移文件与 docs/assets/d1-schema.sql 保持同步', () => {
  const migration = readFileSync(join(EDGE_ROOT, 'migrations', '0001_init.sql'), 'utf8');
  const asset = readFileSync(join(EDGE_ROOT, '..', 'docs', 'assets', 'd1-schema.sql'), 'utf8');
  assert.equal(checkSchemaParity(migration, asset), true);
});
