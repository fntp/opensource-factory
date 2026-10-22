/**
 * 数据保留与隐私路由（REQ-202610-0983 / M9-06）
 *
 * GET    /api/privacy/policy             公开：保留策略、数据主体权利、出网点
 * GET    /api/privacy/export             登录态：导出当前用户全部个人数据（JSON 附件）
 * DELETE /api/privacy/account            登录态：删除账号及个人数据（需 confirmation=DELETE）
 * POST   /api/internal/privacy/cleanup   内部令牌：手动触发 D1 保留清理
 *
 * 安全约定：
 * - 导出不返回会话 token 哈希、扩展令牌哈希或任何密钥；
 * - 删除按 user_id 逐表清理，并在同一 D1 batch 内写入 privacy_events 审计；
 * - 删除后 best-effort 通知 VPS 清理本地镜像，失败不影响边缘删除结果。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, UserRow, Variables } from '../types';
import { all, first } from '../db';
import { clearSessionCookie, sha256Hex } from '../auth';
import { requireInternalToken } from '../security/internal-token';
import { cleanupExpiredData } from '../privacy/cleanup';
import {
  buildPersonalDataExport,
  personalDataFileName,
  type PersonalDataSections,
} from '../privacy/export';
import {
  buildPrivacyPolicy,
  isAccountDeletionConfirmed,
  PRIVACY_POLICY_VERSION,
  privacyEventId,
} from '../privacy/policy';

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;

const privacy = new Hono<{ Bindings: Env; Variables: Variables }>();

// ── 公开策略 ────────────────────────────────────────────────────
privacy.get('/policy', (c) => c.json(buildPrivacyPolicy()));

// ── 个人数据导出 ────────────────────────────────────────────────
async function loadPersonalData(
  c: AppContext,
  user: UserRow,
  actorHash: string
): Promise<PersonalDataSections> {
  const db = c.env.DB;
  const [
    repositories,
    categories,
    tags,
    recommendations,
    notifications,
    repoUpdates,
    pushPreferences,
    tagSuggestions,
    categorySuggestions,
    curatedReports,
    recommendationFeedback,
    duplicateDismissals,
    extensionTokens,
    telegramLink,
    sessions,
    privacyEvents,
  ] = await Promise.all([
    all(db, 'SELECT * FROM my_repositories WHERE user_id = ? ORDER BY created_at ASC', [user.id]),
    all(db, 'SELECT * FROM categories ORDER BY sort_order ASC, name ASC'),
    all(db, 'SELECT * FROM tags ORDER BY name ASC'),
    all(db, 'SELECT * FROM recommendations WHERE user_id = ? ORDER BY created_at DESC', [user.id]),
    all(db, 'SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC', [user.id]),
    all(db, 'SELECT * FROM repo_updates WHERE user_id = ? ORDER BY created_at DESC', [user.id]),
    first(db, 'SELECT * FROM push_preferences WHERE user_id = ?', [user.id]),
    all(db, 'SELECT * FROM tag_suggestions WHERE user_id = ? ORDER BY updated_at DESC', [user.id]),
    all(db, 'SELECT * FROM category_suggestions WHERE user_id = ? ORDER BY updated_at DESC', [user.id]),
    all(db, 'SELECT * FROM curated_reports WHERE user_id = ? ORDER BY generated_at DESC', [user.id]),
    all(db, 'SELECT * FROM recommendation_feedback WHERE user_id = ? ORDER BY created_at DESC', [user.id]),
    all(db, 'SELECT * FROM duplicate_dismissals WHERE user_id = ? ORDER BY created_at DESC', [user.id]),
    all(
      db,
      `SELECT id, label, hint, created_at, last_used_at, revoked_at
         FROM extension_tokens WHERE user_id = ? ORDER BY created_at DESC`,
      [user.id]
    ),
    first(
      db,
      'SELECT chat_id, username, linked_at, last_seen_at FROM telegram_links WHERE user_id = ?',
      [user.id]
    ),
    all(db, 'SELECT created_at, expires_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC', [
      user.id,
    ]),
    all(
      db,
      `SELECT id, event_type, detail, created_at
         FROM privacy_events WHERE actor_hash = ? ORDER BY created_at DESC`,
      [actorHash]
    ),
  ]);

  return {
    repositories,
    categories,
    tags,
    recommendations,
    notifications,
    repoUpdates,
    pushPreferences,
    tagSuggestions,
    categorySuggestions,
    curatedReports,
    recommendationFeedback,
    duplicateDismissals,
    extensionTokens,
    telegramLink,
    sessions,
    privacyEvents,
  };
}

privacy.get('/export', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const actorHash = await sha256Hex(user.id);
  const generatedAt = new Date().toISOString();
  const data = await loadPersonalData(c, user, actorHash);
  const document = buildPersonalDataExport(user, data, generatedAt);

  try {
    await c.env.DB.prepare(
      `INSERT INTO privacy_events (id, event_type, actor_hash, detail, created_at)
       VALUES (?, 'export', ?, ?, ?)`
    )
      .bind(
        privacyEventId(),
        actorHash,
        JSON.stringify({ policyVersion: PRIVACY_POLICY_VERSION, counts: document.counts }),
        generatedAt
      )
      .run();
  } catch (err) {
    // 审计写入失败不阻塞数据主体导出
    console.error('privacy export audit write failed:', err);
  }

  return new Response(JSON.stringify(document, null, 2), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Disposition': `attachment; filename="${personalDataFileName(generatedAt)}"`,
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  });
});

// ── 删除账号（数据主体删除权）──────────────────────────────────
privacy.delete('/account', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: unknown = null;
  try {
    body = await c.req.json();
  } catch {
    body = null;
  }
  if (!isAccountDeletionConfirmed(body)) {
    return c.json({ error: 'confirmation_required', hint: '请求体需包含 "confirmation":"DELETE"' }, 400);
  }

  const actorHash = await sha256Hex(user.id);
  const deletedAt = new Date().toISOString();
  const db = c.env.DB;

  const statements = [
    'DELETE FROM repo_tags WHERE repo_id IN (SELECT id FROM my_repositories WHERE user_id = ?)',
    'DELETE FROM my_repositories WHERE user_id = ?',
    'DELETE FROM sessions WHERE user_id = ?',
    'DELETE FROM recommendations WHERE user_id = ?',
    'DELETE FROM recommendation_feedback WHERE user_id = ?',
    'DELETE FROM notifications WHERE user_id = ?',
    'DELETE FROM repo_updates WHERE user_id = ?',
    'DELETE FROM push_preferences WHERE user_id = ?',
    'DELETE FROM tag_suggestions WHERE user_id = ?',
    'DELETE FROM category_suggestions WHERE user_id = ?',
    'DELETE FROM curated_reports WHERE user_id = ?',
    'DELETE FROM duplicate_dismissals WHERE user_id = ?',
    'DELETE FROM extension_tokens WHERE user_id = ?',
    'DELETE FROM telegram_links WHERE user_id = ?',
    'DELETE FROM telegram_link_codes WHERE user_id = ?',
  ].map((sql) => db.prepare(sql).bind(user.id));

  statements.push(
    db
      .prepare(
        `INSERT INTO privacy_events (id, event_type, actor_hash, detail, created_at)
         VALUES (?, 'delete', ?, ?, ?)`
      )
      .bind(
        privacyEventId(),
        actorHash,
        JSON.stringify({ policyVersion: PRIVACY_POLICY_VERSION, tables: 15 }),
        deletedAt
      )
  );
  statements.push(db.prepare('DELETE FROM users WHERE id = ?').bind(user.id));

  await db.batch(statements);
  clearSessionCookie(c);

  // best-effort：清理 VPS 本地镜像中的用户关联数据
  const vpsUrl = c.env.VPS_NODE_URL?.trim();
  if (vpsUrl) {
    const task = fetch(`${vpsUrl.replace(/\/+$/, '')}/api/privacy/purge-user`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': c.env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({ userId: user.id, login: user.login }),
      signal: AbortSignal.timeout(5000),
    }).catch((err) => console.error('vps privacy purge failed:', err));
    try {
      c.executionCtx.waitUntil(task);
    } catch {
      void task;
    }
  }

  return c.json({ status: 'deleted', deletedAt, policyVersion: PRIVACY_POLICY_VERSION });
});

// ── 内部：手动触发保留清理 ─────────────────────────────────────
export const internalPrivacy = new Hono<{ Bindings: Env; Variables: Variables }>();

internalPrivacy.post('/cleanup', async (c) => {
  const denied = await requireInternalToken(c);
  if (denied) return denied;
  const result = await cleanupExpiredData(c.env.DB, new Date(), c.env);
  return c.json(result);
});

export default privacy;
