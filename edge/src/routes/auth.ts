/**
 * 认证路由
 * GET  /api/auth/github/login    302 → GitHub 授权页（设置 of_oauth_state cookie）
 * GET  /api/auth/github/callback 校验 state → 换 token → upsert 用户 → 建会话 → 跳转
 * GET  /api/auth/me              当前登录用户（AuthUser）或 401
 * POST /api/auth/logout          清除当前会话；{ all: true } / ?all=true 时清除该用户全部会话，204
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import {
  buildGithubAuthorizeUrl,
  clearOAuthStateCookie,
  clearSessionCookie,
  clearUserSessions,
  createSession,
  destroySessionByToken,
  exchangeGithubCode,
  fetchGithubUser,
  generateToken,
  OAUTH_STATE_COOKIE,
  readCookie,
  resolveRedirectTarget,
  SESSION_COOKIE,
  setOAuthStateCookie,
  setSessionCookie,
  upsertGithubUser,
} from '../auth';

const auth = new Hono<{ Bindings: Env; Variables: Variables }>();

// 认证响应一律不缓存，避免登录态 / 重定向被中间层缓存
auth.use('*', async (c, next) => {
  c.header('Cache-Control', 'no-store');
  await next();
});

// ── 登录：跳转 GitHub ───────────────────────────────────────────
auth.get('/github/login', (c) => {
  if (!c.env.GITHUB_CLIENT_ID) {
    return c.json({ error: 'github_oauth_not_configured' }, 501);
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
    return c.json({ error: 'github_oauth_not_configured' }, 501);
  }

  const url = new URL(c.req.url);
  const code = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const stateCookie = readCookie(c, OAUTH_STATE_COOKIE);
  clearOAuthStateCookie(c);

  // 校验 state（防 CSRF）
  if (!code || !state || !stateCookie || state !== stateCookie) {
    return c.json({ error: 'invalid_oauth_state' }, 400);
  }

  const token = await exchangeGithubCode(c.env, code);
  if (!token) return c.json({ error: 'github_token_exchange_failed' }, 502);

  const ghUser = await fetchGithubUser(token);
  if (!ghUser) return c.json({ error: 'github_user_fetch_failed' }, 502);

  const user = await upsertGithubUser(c.env.DB, ghUser);
  const sessionToken = await createSession(c.env.DB, user.id);
  setSessionCookie(c, sessionToken);

  const target = resolveRedirectTarget(c.env, url.searchParams.get('redirect'));
  return c.redirect(target, 302);
});

// ── 当前用户 ────────────────────────────────────────────────────
auth.get('/me', (c) => {
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

// ── 登出（支持全端）────────────────────────────────────────────
auth.post('/logout', async (c) => {
  const user = c.get('user');
  const cookie = readCookie(c, SESSION_COOKIE);
  const url = new URL(c.req.url);

  // 全端登出：JSON body { all: true }，或 ?all=true / ?scope=all
  let all = url.searchParams.get('all') === 'true' || url.searchParams.get('scope') === 'all';
  if (!all) {
    try {
      const body = await c.req.json<{ all?: unknown }>();
      all = body?.all === true;
    } catch {
      // 空 body / 非 JSON：按单会话登出处理
    }
  }

  if (all && user) {
    await clearUserSessions(c.env.DB, user.id);
  } else if (cookie) {
    await destroySessionByToken(c.env.DB, cookie);
  }

  clearSessionCookie(c);
  return c.body(null, 204);
});

export default auth;
