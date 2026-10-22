/**
 * 会话 + GitHub OAuth 辅助
 * - 会话 token 为随机值，DB 中仅存其 sha-256 摘要（sessions.id）
 * - 会话 cookie：of_session（HttpOnly; SameSite=Lax; Path=/; 生产 HTTPS 下 Secure）
 * - OAuth state cookie：of_oauth_state
 * - 过期会话：请求时惰性删除 + 登录时用户级清理 + 每日 Cron 全局清理
 */
import type { Context } from 'hono';
import type { Env, GithubTokenResponse, GithubUser, SessionRow, UserRow, Variables } from './types';
import { first, run } from './db';

export const SESSION_COOKIE = 'of_session';
export const OAUTH_STATE_COOKIE = 'of_oauth_state';

/** 会话有效期：30 天 */
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
/** OAuth state 有效期：10 分钟 */
const OAUTH_STATE_TTL_SECONDS = 60 * 10;

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;

// ── 工具 ────────────────────────────────────────────────────────

function bytesToHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** 生成随机 token（32 字节 → 64 位十六进制） */
export function generateToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** sha-256 十六进制摘要 */
export async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return bytesToHex(digest);
}

/** 请求是否经 HTTPS 到达（Cloudflare 终止 TLS 后 c.req.url 为 https） */
function isSecureRequest(c: AppContext): boolean {
  try {
    return new URL(c.req.url).protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Cookie 是否加 Secure：
 * - COOKIE_SECURE=true / false 显式覆盖（反向代理终止 TLS 或本地联调时使用）；
 * - 未设置时按请求协议自动判断，生产 HTTPS 下始终为 true。
 */
function cookieSecure(c: AppContext): boolean {
  const override = c.env.COOKIE_SECURE?.trim().toLowerCase();
  if (override === 'true') return true;
  if (override === 'false') return false;
  return isSecureRequest(c);
}

// ── Cookie 读写 ─────────────────────────────────────────────────

/** 从 Cookie 头解析单个 cookie 值 */
export function readCookie(c: AppContext, name: string): string | null {
  const header = c.req.header('Cookie');
  if (!header) return null;
  for (const part of header.split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const key = part.slice(0, idx).trim();
    if (key === name) return decodeURIComponent(part.slice(idx + 1).trim());
  }
  return null;
}

/** 构造 Set-Cookie 字符串 */
export function buildSetCookie(
  name: string,
  value: string,
  opts: { maxAge?: number; secure?: boolean; path?: string } = {}
): string {
  const parts = [`${name}=${encodeURIComponent(value)}`];
  parts.push(`Path=${opts.path ?? '/'}`);
  parts.push('HttpOnly');
  parts.push('SameSite=Lax');
  if (opts.secure) parts.push('Secure');
  if (typeof opts.maxAge === 'number') parts.push(`Max-Age=${opts.maxAge}`);
  return parts.join('; ');
}

/** 设置会话 cookie */
export function setSessionCookie(c: AppContext, token: string): void {
  c.header(
    'Set-Cookie',
    buildSetCookie(SESSION_COOKIE, token, {
      maxAge: SESSION_TTL_SECONDS,
      secure: cookieSecure(c),
    }),
    { append: true }
  );
}

/** 清除会话 cookie */
export function clearSessionCookie(c: AppContext): void {
  c.header(
    'Set-Cookie',
    buildSetCookie(SESSION_COOKIE, '', { maxAge: 0, secure: cookieSecure(c) }),
    { append: true }
  );
}

/** 设置 OAuth state cookie */
export function setOAuthStateCookie(c: AppContext, state: string): void {
  c.header(
    'Set-Cookie',
    buildSetCookie(OAUTH_STATE_COOKIE, state, {
      maxAge: OAUTH_STATE_TTL_SECONDS,
      secure: cookieSecure(c),
    }),
    { append: true }
  );
}

/** 清除 OAuth state cookie */
export function clearOAuthStateCookie(c: AppContext): void {
  c.header(
    'Set-Cookie',
    buildSetCookie(OAUTH_STATE_COOKIE, '', { maxAge: 0, secure: cookieSecure(c) }),
    { append: true }
  );
}

// ── 会话 ────────────────────────────────────────────────────────

/** 清理全部过期会话，返回删除条数（供每日 Cron 调用） */
export async function cleanupExpiredSessions(
  db: D1Database,
  now: Date = new Date()
): Promise<number> {
  const result = await run(db, 'DELETE FROM sessions WHERE expires_at <= ?', [
    now.toISOString(),
  ]);
  return result.meta.changes ?? 0;
}

/** 清理指定用户的过期会话（登录前调用，避免单用户历史会话堆积） */
export async function cleanupExpiredSessionsForUser(
  db: D1Database,
  userId: string,
  now: Date = new Date()
): Promise<number> {
  const result = await run(
    db,
    'DELETE FROM sessions WHERE user_id = ? AND expires_at <= ?',
    [userId, now.toISOString()]
  );
  return result.meta.changes ?? 0;
}

/** 创建会话：随机 token 的 sha-256 存入 sessions，返回原始 token（只此一次可见） */
export async function createSession(db: D1Database, userId: string): Promise<string> {
  await cleanupExpiredSessionsForUser(db, userId);
  const token = generateToken();
  const tokenHash = await sha256Hex(token);
  const expiresAt = new Date(Date.now() + SESSION_TTL_SECONDS * 1000).toISOString();
  await run(
    db,
    'INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)',
    [tokenHash, userId, expiresAt]
  );
  return token;
}

/** 由请求 cookie 取当前登录用户（过期/无效返回 null） */
export async function getSessionUser(c: AppContext): Promise<UserRow | null> {
  const token = readCookie(c, SESSION_COOKIE);
  if (!token) return null;
  const tokenHash = await sha256Hex(token);
  const session = await first<SessionRow>(
    c.env.DB,
    'SELECT * FROM sessions WHERE id = ?',
    [tokenHash]
  );
  if (!session) return null;
  const expiresAt = Date.parse(session.expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await clearSession(c.env.DB, tokenHash);
    return null;
  }
  const user = await first<UserRow>(c.env.DB, 'SELECT * FROM users WHERE id = ?', [
    session.user_id,
  ]);
  return user;
}

/** 删除会话（按 token 或按已算好的 hash） */
export async function clearSession(db: D1Database, tokenOrHash: string): Promise<void> {
  await run(db, 'DELETE FROM sessions WHERE id = ?', [tokenOrHash]);
}

/** 由原始 token 删除会话 */
export async function destroySessionByToken(db: D1Database, token: string): Promise<void> {
  const tokenHash = await sha256Hex(token);
  await clearSession(db, tokenHash);
}

/** 删除指定用户的全部会话（登出全端） */
export async function clearUserSessions(db: D1Database, userId: string): Promise<void> {
  await run(db, 'DELETE FROM sessions WHERE user_id = ?', [userId]);
}

// ── GitHub OAuth ────────────────────────────────────────────────

/** 构造 GitHub 授权页 URL */
export function buildGithubAuthorizeUrl(env: Env, state: string, redirect: string): string {
  const params = new URLSearchParams({
    client_id: env.GITHUB_CLIENT_ID,
    redirect_uri: redirect,
    scope: 'read:user user:email',
    state,
  });
  return `https://github.com/login/oauth/authorize?${params.toString()}`;
}

/** 用 code 换 access token */
export async function exchangeGithubCode(env: Env, code: string): Promise<string | null> {
  const res = await fetch('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'User-Agent': 'opensource-factory',
    },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
    }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as GithubTokenResponse;
  return data.access_token ?? null;
}

/** 取 GitHub 用户信息 */
export async function fetchGithubUser(token: string): Promise<GithubUser | null> {
  const res = await fetch('https://api.github.com/user', {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'opensource-factory',
    },
  });
  if (!res.ok) return null;
  return (await res.json()) as GithubUser;
}

/** 以 GitHub 用户 upsert users 表并返回行 */
export async function upsertGithubUser(db: D1Database, gh: GithubUser): Promise<UserRow> {
  const id = String(gh.id);
  await run(
    db,
    `INSERT INTO users (id, login, name, email, avatar_url)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       login = excluded.login,
       name = excluded.name,
       email = COALESCE(excluded.email, users.email),
       avatar_url = excluded.avatar_url`,
    [id, gh.login, gh.name ?? null, gh.email ?? null, gh.avatar_url ?? null]
  );
  const user = await first<UserRow>(db, 'SELECT * FROM users WHERE id = ?', [id]);
  if (!user) throw new Error('failed to upsert user');
  return user;
}

// ── redirect 校验 ───────────────────────────────────────────────

/**
 * 校验 OAuth 完成后的跳转目标：
 * - 允许以 `/` 开头的同站路径；
 * - 允许 origin 等于 ALLOWED_ORIGIN 的绝对 URL；
 * - 否则回退到 ALLOWED_ORIGIN。
 */
export function resolveRedirectTarget(env: Env, raw: string | null): string {
  const fallback = env.ALLOWED_ORIGIN || '/';
  if (!raw) return fallback;
  if (raw.startsWith('/') && !raw.startsWith('//')) return raw;
  try {
    const url = new URL(raw);
    const allowed = new URL(env.ALLOWED_ORIGIN);
    if (url.origin === allowed.origin) return raw;
  } catch {
    // 非法 URL，忽略
  }
  return fallback;
}
