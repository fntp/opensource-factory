/**
 * 认证路由
 * GET  /api/auth/github/login    302 → GitHub 授权页（设置 of_oauth_state cookie）
 * GET  /api/auth/github/callback 校验 state → 换 token → upsert 用户 → 建会话 → 跳转
 * GET  /api/auth/me              当前登录用户（AuthUser）或 401
 * POST /api/auth/logout          清除会话，204
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import {
  buildCallbackUrl,
  buildGithubAuthorizeUrl,
  clearOAuthStateCookie,
  clearSession,
  clearSessionCookie,
  createSession,
  exchangeGithubCode,
  fetchGithubUser,
  generateToken,
  readCookie,
  readOAuthStateCookie,
  resolveRedirectTarget,
  setOAuthStateCookie,
  setSessionCookie,
  sha256Hex,
  upsertGithubUser,
} from '../auth';

const auth = new Hono<{ Bindings: Env; Variables: Variables }>();

// ── 登录：跳转 GitHub ───────────────────────────────────────────
auth.get('/github/login', (c) => {
  if (!c.env.GITHUB_CLIENT_ID) {
    return c.json({ error: 'github_oauth_not_configured' }, 501);
  }
  const url = new URL(c.req.url);
  const rawRedirect = url.searchParams.get('redirect');
  // 限制回跳参数长度，避免撑爆 4KB cookie
  const redirect = rawRedirect && rawRedirect.length <= 512 ? rawRedirect : null;
  const state = generateToken();
  // 回跳目标存 state cookie；回调地址保持干净，保证 GitHub 精确匹配
  setOAuthStateCookie(c, state, redirect);

  const authorizeUrl = buildGithubAuthorizeUrl(c.env, state, buildCallbackUrl(c));
  return c.redirect(authorizeUrl, 302);
});

// ── 回调：code → session ────────────────────────────────────────
auth.get('/github/callback', async (c) => {
  if (!c.env.GITHUB_CLIENT_ID || !c.env.GITHUB_CLIENT_SECRET) {
    return c.json({ error: 'github_oauth_not_configured' }, 501);
  }

  const url = new URL(c.req.url);
  const oauthError = url.searchParams.get('error');
  const code = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const stateCookie = readOAuthStateCookie(c);
  clearOAuthStateCookie(c);

  // 用户在 GitHub 侧拒绝授权
  if (oauthError) {
    return c.json(
      {
        error: 'oauth_denied',
        detail: url.searchParams.get('error_description') ?? oauthError,
      },
      400
    );
  }

  // 校验 state（防 CSRF）
  if (!code || !state || !stateCookie || state !== stateCookie.state) {
    return c.json({ error: 'invalid_oauth_state' }, 400);
  }

  const token = await exchangeGithubCode(c.env, code, buildCallbackUrl(c));
  if (!token) return c.json({ error: 'github_token_exchange_failed' }, 502);

  const ghUser = await fetchGithubUser(c.env, token);
  if (!ghUser) return c.json({ error: 'github_user_fetch_failed' }, 502);

  const user = await upsertGithubUser(c.env.DB, ghUser);
  const sessionToken = await createSession(c.env.DB, user.id);
  setSessionCookie(c, sessionToken);

  const target = resolveRedirectTarget(c.env, stateCookie.redirect);
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
