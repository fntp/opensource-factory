/**
 * 安全状态内部路由（M5-05）
 *
 * - GET  /api/internal/security/status：限流 / 登录防护 / 双令牌状态（只输出指纹）
 * - POST /api/internal/security/cleanup：清理过期限流计数、登录审计与安全事件
 *
 * 仅内部调用：校验 X-Internal-Token（支持 current + previous 双令牌）。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { requireInternalToken, internalTokenStatus } from '../security/internal-token.ts';
import { cleanupSecurityData, rateLimitSettings } from '../security/rate-limit.ts';
import { loginGuardSettings } from '../security/login-guard.ts';

const router = new Hono<{ Bindings: Env; Variables: Variables }>();

router.use('*', async (c, next) => {
  const denied = await requireInternalToken(c);
  if (denied) return denied;
  await next();
});

router.get('/status', async (c) => {
  const rateLimit = rateLimitSettings(c.env);
  const loginGuard = loginGuardSettings(c.env);
  return c.json({
    rateLimit: {
      enabled: rateLimit.enabled,
      readPerMinute: rateLimit.readPerMinute,
      writePerMinute: rateLimit.writePerMinute,
      authPerMinute: rateLimit.authPerMinute,
      windowSeconds: rateLimit.windowSeconds,
    },
    loginGuard: {
      maxFailures: loginGuard.maxFailures,
      failureWindowSeconds: loginGuard.failureWindowSeconds,
      lockoutSeconds: loginGuard.lockoutSeconds,
    },
    internalToken: await internalTokenStatus(c.env),
    now: new Date().toISOString(),
  });
});

router.post('/cleanup', async (c) => {
  const result = await cleanupSecurityData(c.env.DB, Date.now());
  return c.json({ ok: true, deleted: result });
});

export default router;
