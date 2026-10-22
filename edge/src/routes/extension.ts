/**
 * 浏览器扩展收藏助手（M8-02）
 *
 * 会话登录态（admin 设置页）：
 *   GET    /api/extension/tokens       当前用户的扩展令牌列表（不含明文）
 *   POST   /api/extension/tokens       创建令牌（明文仅返回一次）
 *   DELETE /api/extension/tokens/:id   撤销令牌
 *
 * Bearer 令牌（Chrome / Edge 扩展）：
 *   GET  /api/extension/me             连接测试
 *   GET  /api/extension/check?id=...   查询是否已收藏
 *   POST /api/extension/bookmark       一键收藏当前仓库
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, ExtensionTokenRow, RepoRow, UserRow, Variables } from '../types';
import { all, first, run } from '../db';
import { sha256Hex } from '../security/crypto';
import {
  generateExtensionToken,
  generateTokenId,
  isExtensionTokenFormat,
  normalizeBookmarkPayload,
  normalizeTokenLabel,
  parseRepoFullName,
  parseRepoUrl,
  toTokenDto,
  tokenHint,
} from '../extension/helpers';

const extension = new Hono<{ Bindings: Env; Variables: Variables }>();

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;

interface ExtensionAuth {
  user: UserRow;
  token: ExtensionTokenRow;
}

/** 从 Authorization: Bearer ofx_… 解析扩展令牌；无效返回 null。 */
async function resolveExtensionAuth(c: AppContext): Promise<ExtensionAuth | null> {
  const header = (c.req.header('Authorization') ?? '').trim();
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match) return null;
  const token = (match[1] ?? '').trim();
  if (!isExtensionTokenFormat(token)) return null;

  const hash = await sha256Hex(token);
  const row = await first<ExtensionTokenRow>(
    c.env.DB,
    'SELECT * FROM extension_tokens WHERE token_hash = ? AND revoked_at IS NULL',
    [hash]
  );
  if (!row) return null;
  const user = await first<UserRow>(c.env.DB, 'SELECT * FROM users WHERE id = ?', [
    row.user_id,
  ]);
  if (!user) return null;

  // 最近使用时间按分钟节流，避免每个请求都写 D1。
  await run(
    c.env.DB,
    `UPDATE extension_tokens
        SET last_used_at = CURRENT_TIMESTAMP
      WHERE id = ?
        AND (last_used_at IS NULL OR last_used_at < datetime('now', '-1 minute'))`,
    [row.id]
  );
  return { user, token: row };
}

function bookmarkRepoFromRow(row: RepoRow) {
  const owner = row.owner ?? row.id.split('/')[0] ?? '';
  const name = row.name ?? row.id.split('/')[1] ?? row.id;
  return {
    id: row.id,
    fullName: owner ? `${owner}/${name}` : row.id,
    platform: row.platform,
    description: row.description,
    language: row.language,
    stars: row.stars ?? 0,
    forks: row.forks ?? 0,
    url: row.html_url,
  };
}

async function readJson(c: AppContext): Promise<unknown | null> {
  try {
    return await c.req.json();
  } catch {
    return null;
  }
}

// ── 会话登录态：令牌管理 ────────────────────────────────────────

extension.get('/tokens', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const rows = await all<ExtensionTokenRow>(
    c.env.DB,
    `SELECT * FROM extension_tokens
      WHERE user_id = ?
      ORDER BY created_at DESC
      LIMIT 100`,
    [user.id]
  );
  return c.json({ items: rows.map(toTokenDto) });
});

extension.post('/tokens', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = (await readJson(c)) as { label?: unknown } | null;
  if (body !== null && typeof body !== 'object') {
    return c.json({ error: 'invalid_body' }, 400);
  }

  const active = await first<{ n: number }>(
    c.env.DB,
    'SELECT COUNT(*) AS n FROM extension_tokens WHERE user_id = ? AND revoked_at IS NULL',
    [user.id]
  );
  if ((active?.n ?? 0) >= 20) {
    return c.json(
      { error: 'too_many_tokens', message: '每个用户最多保留 20 个有效扩展令牌' },
      400
    );
  }

  const token = generateExtensionToken();
  const tokenHash = await sha256Hex(token);
  const createdAt = new Date().toISOString();
  const row: ExtensionTokenRow = {
    id: generateTokenId(),
    user_id: user.id,
    label: normalizeTokenLabel(body?.label),
    token_hash: tokenHash,
    hint: tokenHint(token),
    created_at: createdAt,
    last_used_at: null,
    revoked_at: null,
  };

  await run(
    c.env.DB,
    `INSERT INTO extension_tokens
       (id, user_id, label, token_hash, hint, created_at, last_used_at, revoked_at)
     VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)`,
    [row.id, row.user_id, row.label, row.token_hash, row.hint, row.created_at]
  );

  // 明文令牌只在这里返回一次，服务端不保存。
  return c.json({ token, item: toTokenDto(row) }, 201);
});

extension.delete('/tokens/:id', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const result = await run(
    c.env.DB,
    `UPDATE extension_tokens
        SET revoked_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ? AND revoked_at IS NULL`,
    [id, user.id]
  );
  if ((result.meta.changes ?? 0) === 0) {
    return c.json({ error: 'not_found' }, 404);
  }
  return c.json({ ok: true });
});

// ── Bearer 令牌：扩展运行时 ─────────────────────────────────────

extension.get('/me', async (c) => {
  const auth = await resolveExtensionAuth(c);
  if (!auth) return c.json({ error: 'unauthorized' }, 401);
  return c.json({
    user: {
      id: auth.user.id,
      login: auth.user.login,
      name: auth.user.name,
      avatarUrl: auth.user.avatar_url,
    },
    token: toTokenDto(auth.token),
  });
});

extension.get('/check', async (c) => {
  const auth = await resolveExtensionAuth(c);
  if (!auth) return c.json({ error: 'unauthorized' }, 401);

  const raw = c.req.query('id') ?? '';
  const parsed = parseRepoUrl(raw) ?? parseRepoFullName(raw);
  if (!parsed) return c.json({ error: 'invalid_repo' }, 400);

  const row = await first<RepoRow>(
    c.env.DB,
    'SELECT * FROM my_repositories WHERE id = ?',
    [parsed.fullName]
  );
  if (!row) return c.json({ saved: false });
  if (row.user_id && row.user_id !== auth.user.id) {
    // 不泄露其他用户的收藏；收藏时会返回 409。
    return c.json({ saved: false });
  }
  return c.json({ saved: true, repo: bookmarkRepoFromRow(row) });
});

extension.post('/bookmark', async (c) => {
  const auth = await resolveExtensionAuth(c);
  if (!auth) return c.json({ error: 'unauthorized' }, 401);

  const body = await readJson(c);
  const normalized = normalizeBookmarkPayload(body);
  if (!normalized.ok) {
    return c.json({ error: normalized.error, message: '仓库信息不合法' }, 400);
  }
  const repo = normalized.repo;

  const existing = await first<{ user_id: string | null }>(
    c.env.DB,
    'SELECT user_id FROM my_repositories WHERE id = ?',
    [repo.id]
  );
  if (existing?.user_id && existing.user_id !== auth.user.id) {
    return c.json(
      {
        error: 'repo_owned_by_other_user',
        message: '该仓库已被其他用户收藏，当前实例不支持重复收藏同一仓库',
      },
      409
    );
  }

  await run(
    c.env.DB,
    `INSERT INTO my_repositories
       (id, platform, name, description, html_url, stars, language, user_id, owner, forks,
        created_at, updated_at, synced_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
     ON CONFLICT(id) DO UPDATE SET
       platform = excluded.platform,
       name = excluded.name,
       description = COALESCE(excluded.description, my_repositories.description),
       html_url = excluded.html_url,
       stars = excluded.stars,
       language = COALESCE(excluded.language, my_repositories.language),
       user_id = COALESCE(my_repositories.user_id, excluded.user_id),
       owner = excluded.owner,
       forks = excluded.forks,
       updated_at = CURRENT_TIMESTAMP,
       synced_at = CURRENT_TIMESTAMP`,
    [
      repo.id,
      repo.platform,
      repo.name,
      repo.description,
      repo.url,
      repo.stars,
      repo.language,
      auth.user.id,
      repo.owner,
      repo.forks,
    ]
  );

  return c.json({
    ok: true,
    created: !existing,
    repo: {
      id: repo.id,
      fullName: repo.fullName,
      platform: repo.platform,
      description: repo.description,
      language: repo.language,
      stars: repo.stars,
      forks: repo.forks,
      url: repo.url,
    },
  });
});

export default extension;
