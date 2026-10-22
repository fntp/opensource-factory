/**
 * 仪表盘统计路由
 * GET /api/dashboard/stats → {totalRepos, trendingToday, pendingRecommendations, categoryCount}
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { count } from '../db';

const dashboard = new Hono<{ Bindings: Env; Variables: Variables }>();

dashboard.get('/stats', async (c) => {
  const user = c.get('user');
  const db = c.env.DB;

  // 总仓库数：登录用户看自己的；未登录看全库（统计接口不强制登录）
  const totalRepos = user
    ? await count(db, 'SELECT COUNT(*) AS n FROM my_repositories WHERE user_id = ?', [user.id])
    : await count(db, 'SELECT COUNT(*) AS n FROM my_repositories');

  // 今日趋势条数（按 crawled_at = 今天）
  const trendingToday = await count(
    db,
    `SELECT COUNT(*) AS n FROM trending_repositories WHERE crawled_at = CURRENT_DATE`
  );

  // 待处理推荐：登录用户（含全局）；未登录看全局
  const pendingRecommendations = user
    ? await count(
        db,
        `SELECT COUNT(*) AS n FROM recommendations
          WHERE (user_id = ? OR user_id IS NULL) AND (status IS NULL OR status = 'new')`,
        [user.id]
      )
    : await count(
        db,
        `SELECT COUNT(*) AS n FROM recommendations
          WHERE user_id IS NULL AND (status IS NULL OR status = 'new')`
      );

  // 分类总数
  const categoryCount = await count(db, 'SELECT COUNT(*) AS n FROM categories');

  return c.json({ totalRepos, trendingToday, pendingRecommendations, categoryCount });
});

export default dashboard;
