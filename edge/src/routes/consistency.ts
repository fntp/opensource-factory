/**
 * 内部数据一致性巡检：D1 只读快照
 *
 * GET /api/internal/consistency/snapshot?table=<name>&limit=&offset=
 * - 仅服务端调用（X-Internal-Token），用于 VPS 对账工具拉取 D1 主数据；
 * - 表名与列名均为白名单，不接受任意 SQL；
 * - 主键升序稳定排序，分页返回，避免一次性拉全表。
 */
import { Hono } from 'hono';
import type { Env } from '../types';

interface SnapshotTable {
  key: string;
  columns: readonly string[];
}

/** 允许对账的表与列（新增列时同步维护；顺序即返回列顺序） */
export const SNAPSHOT_TABLES: Record<string, SnapshotTable> = {
  my_repositories: {
    key: 'id',
    columns: [
      'id',
      'platform',
      'name',
      'description',
      'html_url',
      'stars',
      'language',
      'readme_summary',
      'category_id',
      'created_at',
      'user_id',
      'owner',
      'forks',
      'updated_at',
      'synced_at',
    ],
  },
  categories: {
    key: 'id',
    columns: ['id', 'name', 'parent_id', 'description', 'sort_order'],
  },
  trending_repositories: {
    key: 'id',
    columns: [
      'id',
      'platform',
      'name',
      'html_url',
      'stars_today',
      'description',
      'tech_stack',
      'crawled_at',
      'owner',
      'language',
      'stars',
    ],
  },
  users: {
    key: 'id',
    columns: ['id', 'login', 'name', 'email', 'avatar_url', 'created_at'],
  },
  recommendations: {
    key: 'id',
    columns: [
      'id',
      'user_id',
      'owner',
      'name',
      'description',
      'language',
      'stars',
      'score',
      'reason',
      'based_on',
      'url',
      'status',
      'created_at',
    ],
  },
};

const DEFAULT_LIMIT = 500;
const MAX_LIMIT = 1000;

const consistency = new Hono<{ Bindings: Env }>();

/** 常量时间比较，避免通过响应时间推断令牌前缀 */
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

/** 校验内部令牌：未配置时关闭接口，配置后必须精确匹配 */
function authorize(env: Env, provided: string | undefined): 401 | 503 | null {
  const expected = env.INTERNAL_TOKEN?.trim();
  if (!expected) return 503;
  if (!provided || !safeEqual(provided, expected)) return 401;
  return null;
}

consistency.get('/snapshot', async (c) => {
  const authError = authorize(c.env, c.req.header('X-Internal-Token'));
  if (authError === 503) {
    return c.json({ error: 'not_configured', message: 'INTERNAL_TOKEN 未配置，巡检接口已关闭' }, 503);
  }
  if (authError === 401) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  const table = c.req.query('table')?.trim() ?? '';
  const spec = SNAPSHOT_TABLES[table];
  if (!spec) {
    return c.json(
      { error: 'unknown_table', allowed: Object.keys(SNAPSHOT_TABLES) },
      400
    );
  }

  const rawLimit = c.req.query('limit');
  const rawOffset = c.req.query('offset');
  const limit = rawLimit === undefined ? DEFAULT_LIMIT : Number(rawLimit);
  const offset = rawOffset === undefined ? 0 : Number(rawOffset);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    return c.json({ error: 'invalid_limit', message: `limit 需为 1~${MAX_LIMIT} 的整数` }, 400);
  }
  if (!Number.isInteger(offset) || offset < 0) {
    return c.json({ error: 'invalid_offset', message: 'offset 需为非负整数' }, 400);
  }

  const totalRow = await c.env.DB.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first<{
    n: number;
  }>();
  const total = totalRow?.n ?? 0;
  const result = await c.env.DB.prepare(
    `SELECT ${spec.columns.join(', ')} FROM ${table}
      ORDER BY ${spec.key} ASC
      LIMIT ? OFFSET ?`
  )
    .bind(limit, offset)
    .all<Record<string, unknown>>();
  const rows = result.results ?? [];

  return c.json({
    table,
    key: spec.key,
    columns: spec.columns,
    rows,
    offset,
    limit,
    total,
    hasMore: offset + rows.length < total,
    generatedAt: new Date().toISOString(),
  });
});

export default consistency;
