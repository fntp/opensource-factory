/**
 * 认证路由
 * GET  /api/auth/github/login    302 → GitHub 授权页（设置 of_oauth_state cookie）
 * GET  /api/auth/github/callback 校验 state → 换 token → upsert 用户 → 建会话 → 跳转
 * GET  /api/auth/me              当前登录用户（AuthUser）或 401
 * POST /api/auth/logout          清除会话，204
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, Variables } from '../types';
import {
  buildGithubAuthorizeUrl,
  clearOAuthStateCookie,
  clearSession,
  clearSessionCookie,
  createSession,
  exchangeGithubCode,
  fetchGithubUser,
  generateToken,
  OAUTH_STATE_COOKIE,
  readCookie,
  resolveRedirectTarget,
  setOAuthStateCookie,
  setSessionCookie,
  sha256Hex,
  upsertGithubUser,
} from '../auth';

const auth = new Hono<{ Bindings: Env; Variables: Variables }>();

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;

/**
 * OAuth 失败时的统一出口：
 * - 浏览器导航（Accept 含 text/html）且配置了 ALLOWED_ORIGIN → 302 回 admin 登录页并带 error 参数；
 * - 其余客户端保持 JSON 错误响应，便于脚本 / 测试断言状态码。
 */
function authFailure(c: AppContext, code: string, status: 400 | 501 | 502) {
  const origin = (c.env.ALLOWED_ORIGIN || '').trim();
  const acceptsHtml = (c.req.header('Accept') ?? '').includes('text/html');
  if (origin && acceptsHtml) {
    const url = new URL('/sign-in', origin);
    url.searchParams.set('error', code);
    return c.redirect(url.toString(), 302);
  }
  return c.json({ error: code }, status);
}

// ── 登录：跳转 GitHub ───────────────────────────────────────────
auth.get('/github/login', (c) => {
  if (!c.env.GITHUB_CLIENT_ID) {
    return authFailure(c, 'github_oauth_not_configured', 501);
  }
  const state = generateToken();
  setOAuthStateCookie(c, state);

  const url = new URL(c.req.url);
  const redirect = url.searchParams.get('redirect');
  // 把原始 redirect 参数附到回跳地址上，callback 时再校验
  const callbackUrl = new URL('/api/auth/github/callback', url.origin);
  if (redirect) callbackUrl.searchParams.set('redirect', redirect);

  const authorizeUrl = buildGithubAuthorizeUrl(
    c.env,
    state,
    callbackUrl.toString()
  );
  return c.redirect(authorizeUrl, 302);
});

// ── 回调：code → session ────────────────────────────────────────
auth.get('/github/callback', async (c) => {
  if (!c.env.GITHUB_CLIENT_ID || !c.env.GITHUB_CLIENT_SECRET) {
    return authFailure(c, 'github_oauth_not_configured', 501);
  }

  const url = new URL(c.req.url);
  const oauthError = url.searchParams.get('error');
  if (oauthError) {
    clearOAuthStateCookie(c);
    return authFailure(
      c,
      oauthError === 'access_denied' ? 'oauth_denied' : 'github_oauth_failed',
      400
    );
  }

  const code = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const stateCookie = readCookie(c, OAUTH_STATE_COOKIE);
  clearOAuthStateCookie(c);

  // 校验 state（防 CSRF）
  if (!code || !state || !stateCookie || state !== stateCookie) {
    return authFailure(c, 'invalid_oauth_state', 400);
  }

  const token = await exchangeGithubCode(c.env, code);
  if (!token) return authFailure(c, 'github_token_exchange_failed', 502);

  const ghUser = await fetchGithubUser(token);
  if (!ghUser) return authFailure(c, 'github_user_fetch_failed', 502);

  const user = await upsertGithubUser(c.env.DB, ghUser);
  const sessionToken = await createSession(c.env.DB, user.id);
  setSessionCookie(c, sessionToken);

  const target = resolveRedirectTarget(c.env, url.searchParams.get('redirect'));
  return c.redirect(target, 302);
});

// ── 当前用户 ────────────────────────────────────────────────────
auth.get('/me', (c) => {
  c.header('Cache-Control', 'no-store');
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  return c.json({
    id: user.id,
    login: user.login,
    name: user.name,
    email: user.email,
    avatarUrl: user.avatar_url,
  });
});

// ── 登出 ────────────────────────────────────────────────────────
auth.post('/logout', async (c) => {
  const cookie = readCookie(c, 'of_session');
  if (cookie) {
    const tokenHash = await sha256Hex(cookie);
    await clearSession(c.env.DB, tokenHash);
  }
  clearSessionCookie(c);
  return c.body(null, 204);
});

export default auth;
