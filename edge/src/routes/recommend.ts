/**
 * 推荐路由
 * GET /api/recommendations  当前用户的推荐（含全局推荐 user_id IS NULL），按 score 降序
 */
import { Hono } from 'hono';
import type { Env, Recommendation, RecommendationRow, Variables } from '../types';
import { all } from '../db';

const recommend = new Hono<{ Bindings: Env; Variables: Variables }>();

/** 解析 based_on（JSON 数组字符串）为 string[]，容错处理 */
function parseBasedOn(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return parsed.map((v) => String(v));
    return [];
  } catch {
    // 兼容逗号分隔的旧格式
    return raw.split(',').map((s) => s.trim()).filter(Boolean);
  }
}

export function toRecommendation(row: RecommendationRow): Recommendation {
  return {
    id: row.id,
    owner: row.owner ?? null,
    name: row.name ?? null,
    description: row.description ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    score: row.score ?? 0,
    reason: row.reason ?? null,
    basedOn: parseBasedOn(row.based_on),
    url: row.url ?? null,
  };
}

recommend.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const raw = Number.parseInt(c.req.query('limit') ?? '', 10);
  const limit = Number.isFinite(raw) && raw > 0 ? Math.min(raw, 100) : 50;

  const rows = await all<RecommendationRow>(
    c.env.DB,
    `SELECT * FROM recommendations
      WHERE user_id = ? OR user_id IS NULL
      ORDER BY score DESC
      LIMIT ?`,
    [user.id, limit]
  );

  return c.json(rows.map(toRecommendation));
});

export default recommend;
