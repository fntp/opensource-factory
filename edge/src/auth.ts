/**
 * 会话 + GitHub OAuth 辅助
 * - 会话 token 为随机值，DB 中仅存其 sha-256 摘要（sessions.id）
 * - 会话 cookie：of_session（httpOnly; SameSite=Lax; 生产环境 Secure）
 * - OAuth state cookie：of_oauth_state
 */
import type { Context } from 'hono';
import type {
  Env,
  GithubEmail,
  GithubTokenResponse,
  GithubUser,
  SessionRow,
  UserRow,
  Variables,
} from './types';
import { first, run } from './db';

export const SESSION_COOKIE = 'of_session';
export const OAUTH_STATE_COOKIE = 'of_oauth_state';

/** 会话有效期：30 天 */
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
/** OAuth state 有效期：10 分钟 */
const OAUTH_STATE_TTL_SECONDS = 60 * 10;
/** GitHub 官方端点（本地联调可通过 GITHUB_OAUTH_BASE_URL / GITHUB_API_BASE_URL 覆盖） */
const DEFAULT_OAUTH_BASE_URL = 'https://github.com';
const DEFAULT_API_BASE_URL = 'https://api.github.com';

/** OAuth state cookie 载荷：state 与登录后的回跳目标 */
export interface OAuthStatePayload {
  state: string;
  redirect: string | null;
}

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

/** 是否生产环境（用于 cookie Secure 标记；wrangler dev 无 CF_PAGES 等标记时按开发处理） */
function isSecureRequest(c: AppContext): boolean {
  try {
    return new URL(c.req.url).protocol === 'https:';
  } catch {
    return false;
  }
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
      secure: isSecureRequest(c),
    }),
    { append: true }
  );
}

/** 清除会话 cookie */
export function clearSessionCookie(c: AppContext): void {
  c.header(
    'Set-Cookie',
    buildSetCookie(SESSION_COOKIE, '', { maxAge: 0, secure: isSecureRequest(c) }),
    { append: true }
  );
}

/** 设置 OAuth state cookie（同时保存回跳目标，回调地址保持干净以便 GitHub 精确匹配） */
export function setOAuthStateCookie(c: AppContext, state: string, redirect: string | null): void {
  const payload: OAuthStatePayload = { state, redirect };
  c.header(
    'Set-Cookie',
    buildSetCookie(OAUTH_STATE_COOKIE, JSON.stringify(payload), {
      maxAge: OAUTH_STATE_TTL_SECONDS,
      secure: isSecureRequest(c),
    }),
    { append: true }
  );
}

/** 读取 OAuth state cookie；兼容旧格式（cookie 值就是 state） */
export function readOAuthStateCookie(c: AppContext): OAuthStatePayload | null {
  const raw = readCookie(c, OAUTH_STATE_COOKIE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<OAuthStatePayload>;
    if (typeof parsed.state === 'string' && parsed.state) {
      return {
        state: parsed.state,
        redirect: typeof parsed.redirect === 'string' ? parsed.redirect : null,
      };
    }
  } catch {
    // 旧格式：cookie 值即 state
  }
  return { state: raw, redirect: null };
}

/** 清除 OAuth state cookie */
export function clearOAuthStateCookie(c: AppContext): void {
  c.header(
    'Set-Cookie',
    buildSetCookie(OAUTH_STATE_COOKIE, '', { maxAge: 0, secure: isSecureRequest(c) }),
    { append: true }
  );
}

// ── 会话 ────────────────────────────────────────────────────────

/** 创建会话：随机 token 的 sha-256 存入 sessions，返回原始 token（只此一次可见） */
export async function createSession(db: D1Database, userId: string): Promise<string> {
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
  if (new Date(session.expires_at).getTime() < Date.now()) {
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

// ── GitHub OAuth ────────────────────────────────────────────────

function trimTrailingSlash(url: string): string {
  return url.replace(/\/+$/, '');
}

/** OAuth 授权端点根地址（默认 https://github.com） */
export function githubOAuthBase(env: Env): string {
  return trimTrailingSlash(env.GITHUB_OAUTH_BASE_URL || DEFAULT_OAUTH_BASE_URL);
}

/** GitHub API 根地址（默认 https://api.github.com） */
export function githubApiBase(env: Env): string {
  return trimTrailingSlash(env.GITHUB_API_BASE_URL || DEFAULT_API_BASE_URL);
}

/** 本次请求对应的 OAuth 回调地址（authorize 与 token 交换必须完全一致） */
export function buildCallbackUrl(c: AppContext): string {
  const url = new URL(c.req.url);
  return new URL('/api/auth/github/callback', url.origin).toString();
}

/** 构造 GitHub 授权页 URL */
export function buildGithubAuthorizeUrl(env: Env, state: string, redirectUri: string): string {
  const params = new URLSearchParams({
    client_id: env.GITHUB_CLIENT_ID,
    redirect_uri: redirectUri,
    scope: 'read:user user:email',
    state,
  });
  return `${githubOAuthBase(env)}/login/oauth/authorize?${params.toString()}`;
}

/** 用 code 换 access token（redirect_uri 必须与 authorize 阶段一致） */
export async function exchangeGithubCode(
  env: Env,
  code: string,
  redirectUri: string
): Promise<string | null> {
  try {
    const res = await fetch(`${githubOAuthBase(env)}/login/oauth/access_token`, {
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
        redirect_uri: redirectUri,
      }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as GithubTokenResponse;
    if (data.error) return null;
    return data.access_token ?? null;
  } catch {
    return null;
  }
}

/** 取 GitHub 用户信息；email 为私有时回退 /user/emails 取主邮箱 */
export async function fetchGithubUser(env: Env, token: string): Promise<GithubUser | null> {
  try {
    const res = await fetch(`${githubApiBase(env)}/user`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'opensource-factory',
      },
    });
    if (!res.ok) return null;
    const user = (await res.json()) as GithubUser;
    if (!user.email) {
      user.email = await fetchGithubPrimaryEmail(env, token);
    }
    return user;
  } catch {
    return null;
  }
}

/** 从 /user/emails 取主邮箱（优先 primary + verified，其次任一 verified） */
export async function fetchGithubPrimaryEmail(env: Env, token: string): Promise<string | null> {
  try {
    const res = await fetch(`${githubApiBase(env)}/user/emails`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'opensource-factory',
      },
    });
    if (!res.ok) return null;
    const emails = (await res.json()) as GithubEmail[];
    if (!Array.isArray(emails)) return null;
    const preferred =
      emails.find((item) => item.primary && item.verified) ??
      emails.find((item) => item.verified) ??
      emails.find((item) => item.primary);
    return preferred?.email ?? null;
  } catch {
    return null;
  }
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
  if (!env.ALLOWED_ORIGIN) return fallback;
  try {
    const url = new URL(raw);
    const allowed = new URL(env.ALLOWED_ORIGIN);
    if (url.origin === allowed.origin) return raw;
  } catch {
    // 非法 URL，忽略
  }
  return fallback;
}
