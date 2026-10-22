/**
 * OpenFactory 边缘 API — Hono 应用入口
 * 中间件：CORS（精确回显 ALLOWED_ORIGIN，允许 credentials）+ 请求日志
 * 路由：/api/auth、/api/repos、/api/trending、/api/recommendations、
 *       /api/notifications、/api/push-preferences、/api/categories、
 *       /api/dashboard、/api/sync、/api/internal/trending、/api/search、/api/similar、
 *       /api/tech-stack

 *       /api/category-suggestions
 */
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { secureHeaders } from 'hono/secure-headers';
import type { Env, Variables } from './types';
import { getSessionUser } from './auth';
import authRoutes from './routes/auth';
import reposRoutes from './routes/repos';
import trendingRoutes from './routes/trending';
import recommendRoutes from './routes/recommend';
import notificationRoutes, {
  internalNotifications,
} from './routes/notifications';
import pushPreferenceRoutes, {
  internalPushPreferences,
} from './routes/push-preferences';
import categoriesRoutes from './routes/categories';
import dashboardRoutes from './routes/dashboard';
import syncRoutes from './routes/sync';
import internalTrendingRoutes from './routes/internal-trending';
import searchRoutes from './routes/search';
import similarRoutes from './routes/similar';
import duplicatesRoutes from './routes/duplicates';
import techStackRoutes from './routes/tech-stack';
import tagSuggestionRoutes from './routes/tag-suggestions';

import categorySuggestionsRoutes from './routes/category-suggestions';
import agentRoutes from './routes/agent';
import internalVectorsRoutes from './routes/internal-vectors';
import internalRecommendationsRoutes from './routes/internal-recommendations';
import internalSecurityRoutes from './routes/internal-security';
import monitoringRoutes, { internalAnalytics } from './routes/monitoring';
import reportsRoutes, { internalReports, generateReportsForAllUsers } from './routes/reports';
import {
  cleanupSecurityData,
  clientIpFromHeaders,
  consumeRateLimit,
  policyFor,
  rateLimitBucket,
  rateLimitIdentity,
} from './security/rate-limit.ts';
import { recordSecurityEvent } from './security/login-guard.ts';
import { normalizeRoute, recordRequestMetric, shouldRecordMetric } from './monitoring/metrics';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// 安全响应头（M5-08）：nosniff / frame / referrer / HSTS 等基线
app.use('*', secureHeaders());

// 请求日志
app.use('*', logger());

// CORS：必须精确回显 ALLOWED_ORIGIN 且带 credentials（前端 fetch 使用 credentials: 'include'）
app.use('*', async (c, next) => {
  const origin = c.env.ALLOWED_ORIGIN || '';
  return cors({
    origin,
    credentials: true,
    allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowHeaders: ['Content-Type', 'Authorization'],
    maxAge: 86400,
  })(c, next);
});

// 健康检查
app.get('/healthz', (c) => c.json({ status: 'ok' }));

// 会话解析 + 接口限流（M5-05）
// 限流按 用户 id / 匿名 IP 哈希分桶；D1 异常时 fail-open，不阻塞业务。
let securityRequestCounter = 0;

app.use('/api/*', async (c, next) => {
  const user = await getSessionUser(c);
  c.set('user', user);

  const policy = policyFor(c.req.method, new URL(c.req.url).pathname, c.env);
  if (!policy) {
    await next();
    return;
  }

  const ip = clientIpFromHeaders(c.req.header('CF-Connecting-IP'), c.req.header('X-Forwarded-For'));
  try {
    const identity = await rateLimitIdentity(policy.scope, user?.id, ip);
    const decision = await consumeRateLimit(
      c.env.DB,
      rateLimitBucket(policy.scope, identity),
      policy.limit,
      policy.windowSeconds,
      Date.now()
    );
    c.header('X-RateLimit-Limit', String(decision.limit));
    c.header('X-RateLimit-Remaining', String(decision.remaining));
    c.header('X-RateLimit-Reset', String(Math.floor(decision.resetAt / 1000)));
    if (!decision.allowed) {
      c.header('Retry-After', String(decision.retryAfterSeconds));
      if (policy.scope === 'auth') {
        await recordSecurityEvent(
          c.env.DB,
          'rate_limited',
          identity,
          policy.scope,
          new Date().toISOString()
        );
      }
      return c.json(
        {
          error: 'rate_limited',
          scope: policy.scope,
          retryAfterSeconds: decision.retryAfterSeconds,
        },
        429
      );
    }
  } catch (err) {
    // D1 限流不可用时放行，保证可用性优先
    console.error('rate limiter unavailable:', err);
  }

  securityRequestCounter += 1;
  if (securityRequestCounter % 200 === 0) {
    try {
      c.executionCtx.waitUntil(cleanupSecurityData(c.env.DB, Date.now()));
    } catch {
      // 本地 / 测试环境没有 executionCtx，忽略
    }
  }

  await next();
});

// Workers 请求指标（M5-03）：请求结束后异步聚合写入 D1，失败不影响响应
app.use('/api/*', async (c, next) => {
  const started = Date.now();
  await next();
  const path = new URL(c.req.url).pathname;
  if (!shouldRecordMetric(c.req.method, path)) return;
  const task = recordRequestMetric(c.env.DB, {
    route: normalizeRoute(path),
    method: c.req.method,
    status: c.res.status,
    durationMs: Date.now() - started,
  }).catch((err) => console.error('worker metrics write failed:', err));
  try {
    c.executionCtx.waitUntil(task);
  } catch {
    // 非 Worker 运行时（本地脚本 / 测试）没有 executionCtx，直接执行即可
    void task;
  }
});

// 业务路由
app.route('/api/auth', authRoutes);
app.route('/api/repos', reposRoutes);
app.route('/api/trending', trendingRoutes);
app.route('/api/recommendations', recommendRoutes);
app.route('/api/notifications', notificationRoutes);
app.route('/api/internal/notifications', internalNotifications);
app.route('/api/push-preferences', pushPreferenceRoutes);
app.route('/api/internal/push-preferences', internalPushPreferences);
app.route('/api/categories', categoriesRoutes);
app.route('/api/dashboard', dashboardRoutes);
app.route('/api/sync', syncRoutes);
app.route('/api/internal/trending', internalTrendingRoutes);
app.route('/api/search', searchRoutes);
app.route('/api/similar', similarRoutes);
app.route('/api/duplicates', duplicatesRoutes);
app.route('/api/tech-stack', techStackRoutes);
app.route('/api/tag-suggestions', tagSuggestionRoutes);

app.route('/api/category-suggestions', categorySuggestionsRoutes);
app.route('/api/agent', agentRoutes);
app.route('/api/internal/vectors', internalVectorsRoutes);
app.route('/api/internal/recommendations', internalRecommendationsRoutes);
app.route('/api/internal/security', internalSecurityRoutes);
app.route('/api/monitoring', monitoringRoutes);
app.route('/api/internal/analytics', internalAnalytics);
app.route('/api/reports', reportsRoutes);
app.route('/api/internal/reports', internalReports);

// 404
app.notFound((c) =>
  c.json({ error: 'not_found', path: new URL(c.req.url).pathname }, 404)
);

// 500
app.onError((err, c) => {
  console.error('unhandled error:', err);
  return c.json({ error: 'internal_error' }, 500);
});

// ── 精选报告定时生成（M7-03）────────────────────────────────────
// Cron 表达式为 UTC：周日 23:30 UTC = 周一 07:30 Asia/Shanghai（汇总上一个自然周）；
// 每月 1 日 23:40 UTC = 2 日 07:40 Asia/Shanghai（汇总上一个自然月）。
export const WEEKLY_REPORT_CRON = '30 23 * * 0';
export const MONTHLY_REPORT_CRON = '40 23 1 * *';

export default {
  fetch(request: Request, env: Env, ctx: ExecutionContext): Response | Promise<Response> {
    return app.fetch(request, env, ctx);
  },
  async scheduled(
    controller: ScheduledController,
    env: Env,
    ctx: ExecutionContext
  ): Promise<void> {
    const kind = controller.cron === MONTHLY_REPORT_CRON ? 'monthly' : 'weekly';
    ctx.waitUntil(generateReportsForAllUsers(env.DB, kind, 'previous'));
  },
} satisfies ExportedHandler<Env>;
