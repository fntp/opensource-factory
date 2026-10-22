/**
 * 内部 License 回写接口（M6-06）
 * POST /api/internal/licenses
 * VPS License 补全任务把识别结果批量写回 D1。
 * 仅限内部调用（配置 INTERNAL_TOKEN 时校验 X-Internal-Token）。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { run } from '../db';

const internalLicenses = new Hono<{ Bindings: Env; Variables: Variables }>();

interface LicenseItem {
  repoId?: unknown;
  spdxId?: unknown;
  name?: unknown;
  source?: unknown;
  checkedAt?: unknown;
}

type Scope = 'my' | 'trending';

function parseScope(value: unknown): Scope | null {
  return value === 'my' || value === 'trending' ? value : null;
}

function optionalString(value: unknown, maxLength: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, maxLength) : null;
}

internalLicenses.post('/', async (c) => {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (expected) {
    const provided = c.req.header('X-Internal-Token') ?? '';
    if (provided !== expected) {
      return c.json({ error: 'unauthorized' }, 401);
    }
  }

  let body: { scope?: unknown; items?: LicenseItem[] } | null = null;
  try {
    body = await c.req.json<{ scope?: unknown; items?: LicenseItem[] }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.items)) {
    return c.json({ error: 'invalid_body', message: 'items 必须是数组' }, 400);
  }

  const scope = parseScope(body.scope);
  if (!scope) {
    return c.json({ error: 'invalid_scope', message: 'scope 必须是 my / trending' }, 400);
  }

  const table = scope === 'my' ? 'my_repositories' : 'trending_repositories';
  const items = body.items.slice(0, 500);
  let updated = 0;
  let skipped = 0;

  for (const item of items) {
    const repoId = optionalString(item.repoId, 255);
    if (!repoId) {
      skipped += 1;
      continue;
    }
    const spdxId = optionalString(item.spdxId, 64);
    const name = optionalString(item.name, 255);
    const source = optionalString(item.source, 16) ?? 'none';
    const checkedAt = optionalString(item.checkedAt, 40);

    const result = await run(
      c.env.DB,
      `UPDATE ${table}
          SET license_spdx = ?, license_name = ?, license_source = ?,
              license_checked_at = COALESCE(?, CURRENT_TIMESTAMP)
        WHERE id = ?`,
      [spdxId, name, source, checkedAt, repoId]
    );
    if ((result.meta.changes ?? 0) > 0) {
      updated += 1;
    } else {
      skipped += 1;
    }
  }

  return c.json({ scope, total: items.length, updated, skipped });
});

export default internalLicenses;
