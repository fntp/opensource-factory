/**
 * OpenFactory 边缘 API — Hono 应用入口
 * 中间件：CORS（精确回显 ALLOWED_ORIGIN，允许 credentials）+ 请求日志
 * 路由：/api/auth、/api/repos、/api/trending、/api/recommendations、
 *       /api/notifications、/api/categories、/api/dashboard、/api/sync、
 *       /api/internal/trending、/api/search
 */
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import type { Env, Variables } from './types';
import { getSessionUser } from './auth';
import authRoutes from './routes/auth';
import reposRoutes from './routes/repos';
import trendingRoutes from './routes/trending';
import recommendRoutes from './routes/recommend';
import notificationRoutes, {
  internalNotifications,
} from './routes/notifications';
import categoriesRoutes from './routes/categories';
import dashboardRoutes from './routes/dashboard';
import syncRoutes from './routes/sync';
import internalTrendingRoutes from './routes/internal-trending';
import searchRoutes from './routes/search';
import internalVectorsRoutes from './routes/internal-vectors';
import internalRecommendationsRoutes from './routes/internal-recommendations';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

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

// 在每个请求上解析会话用户，挂到 c.var.user（未登录为 null）
app.use('/api/*', async (c, next) => {
  c.set('user', await getSessionUser(c));
  await next();
});

// 业务路由
app.route('/api/auth', authRoutes);
app.route('/api/repos', reposRoutes);
app.route('/api/trending', trendingRoutes);
app.route('/api/recommendations', recommendRoutes);
app.route('/api/notifications', notificationRoutes);
app.route('/api/internal/notifications', internalNotifications);
app.route('/api/categories', categoriesRoutes);
app.route('/api/dashboard', dashboardRoutes);
app.route('/api/sync', syncRoutes);
app.route('/api/internal/trending', internalTrendingRoutes);
app.route('/api/search', searchRoutes);
app.route('/api/internal/vectors', internalVectorsRoutes);
app.route('/api/internal/recommendations', internalRecommendationsRoutes);

// 404
app.notFound((c) =>
  c.json({ error: 'not_found', path: new URL(c.req.url).pathname }, 404)
);

// 500
app.onError((err, c) => {
  console.error('unhandled error:', err);
  return c.json({ error: 'internal_error' }, 500);
});

export default app;
