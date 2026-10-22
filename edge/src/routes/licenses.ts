/**
 * License 合规接口（M6-06）
 * GET /api/licenses/catalog   许可证目录与分级口径（公开）
 * GET /api/licenses/summary   我的仓库 / 热榜 / 全部的 License 与风险分布
 *   - scope=trending 公开；
 *   - scope=my / all 需要登录（my 仅统计当前用户仓库）。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { all } from '../db';
import {
  catalogPayload,
  summarizeLicenseRows,
  type LicenseRowFields,
} from '../license/compliance';

const licenses = new Hono<{ Bindings: Env; Variables: Variables }>();

type Scope = 'my' | 'trending' | 'all';

function parseScope(raw: string | undefined): Scope | null {
  const value = (raw ?? 'all').trim();
  return value === 'my' || value === 'trending' || value === 'all' ? value : null;
}

licenses.get('/catalog', (c) => c.json(catalogPayload()));

licenses.get('/summary', async (c) => {
  const scope = parseScope(c.req.query('scope'));
  if (!scope) {
    return c.json({ error: 'invalid_scope', message: 'scope 必须是 my / trending / all' }, 400);
  }

  const user = c.get('user');
  if (scope !== 'trending' && !user) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  const rows: LicenseRowFields[] = [];
  if (scope !== 'trending' && user) {
    rows.push(
      ...(await all<LicenseRowFields>(
        c.env.DB,
        `SELECT license_spdx, license_name, license_source
           FROM my_repositories
          WHERE user_id = ?`,
        [user.id]
      ))
    );
  }
  if (scope !== 'my') {
    rows.push(
      ...(await all<LicenseRowFields>(
        c.env.DB,
        `SELECT license_spdx, license_name, license_source
           FROM trending_repositories`
      ))
    );
  }

  return c.json({ scope, ...summarizeLicenseRows(rows) });
});

export default licenses;
