/**
 * Workers 请求指标（REQ-202610-0941 / M5-03）
 *
 * 不依赖 Cloudflare GraphQL Analytics：每个 `/api/*` 请求结束后，按
 * `(日期, 路由, 方法, 状态类)` 聚合写入 D1 `worker_metrics`，供管理后台查询
 * 请求量 / 错误率 / 平均延迟。写失败只记日志，绝不影响业务响应。
 */

export interface WorkerMetricRow {
  metric_date: string;
  route: string;
  method: string;
  status_class: string;
  requests: number;
  total_ms: number;
  max_ms: number;
}

export interface MetricBucket {
  requests: number;
  errors: number;
  serverErrors: number;
  errorRate: number;
  avgMs: number;
  maxMs: number;
}

export interface DailyMetric extends MetricBucket {
  date: string;
}

export interface RouteMetric extends MetricBucket {
  route: string;
  method: string;
}

export interface WorkerMetricsSummary {
  days: number;
  from: string;
  to: string;
  totals: MetricBucket;
  daily: DailyMetric[];
  routes: RouteMetric[];
}

const MAX_DAYS = 30;

/** UTC 日期（YYYY-MM-DD），与 D1 `date('now')` 口径一致。 */
export function metricDate(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** 把天数参数收敛到 1~30，默认 7 天。 */
export function parseMetricDays(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return 7;
  return Math.min(MAX_DAYS, Math.max(1, Math.trunc(parsed)));
}

/** HTTP 状态码 → 状态类。 */
export function statusClass(status: number): string {
  if (status >= 500) return '5xx';
  if (status >= 400) return '4xx';
  if (status >= 300) return '3xx';
  if (status >= 200) return '2xx';
  return '1xx';
}

/**
 * 路由归一化：去掉查询串、折叠数字 / UUID / 长十六进制 ID，避免指标基数爆炸。
 * 例如 `/api/repos/123/detail` → `/api/repos/:id/detail`。
 */
export function normalizeRoute(pathname: string): string {
  const raw = pathname || '/';
  const clean = raw.split('?')[0]?.split('#')[0] ?? '/';
  const segments = clean.split('/').filter(Boolean).slice(0, 5);
  const normalized = segments.map((segment) => {
    if (/^\d+$/.test(segment)) return ':id';
    if (/^[0-9a-f]{8}-[0-9a-f-]{20,}$/i.test(segment)) return ':id';
    if (/^[0-9a-f]{16,}$/i.test(segment)) return ':id';
    return segment;
  });
  return `/${normalized.join('/')}`;
}

/** 只统计业务 API，跳过预检与内部接口。 */
export function shouldRecordMetric(method: string, pathname: string): boolean {
  const upper = (method || '').toUpperCase();
  if (upper === 'OPTIONS' || upper === 'HEAD') return false;
  const path = pathname || '';
  return path.startsWith('/api/') && !path.startsWith('/api/internal/');
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

interface MutableBucket {
  requests: number;
  errors: number;
  serverErrors: number;
  totalMs: number;
  maxMs: number;
}

function addRow(bucket: MutableBucket, row: WorkerMetricRow): void {
  const requests = Number(row.requests) || 0;
  const errors = row.status_class === '4xx' || row.status_class === '5xx' ? requests : 0;
  const serverErrors = row.status_class === '5xx' ? requests : 0;
  bucket.requests += requests;
  bucket.errors += errors;
  bucket.serverErrors += serverErrors;
  bucket.totalMs += Number(row.total_ms) || 0;
  bucket.maxMs = Math.max(bucket.maxMs, Number(row.max_ms) || 0);
}

function toBucket(bucket: MutableBucket): MetricBucket {
  return {
    requests: bucket.requests,
    errors: bucket.errors,
    serverErrors: bucket.serverErrors,
    errorRate: bucket.requests ? round1((bucket.errors / bucket.requests) * 100) : 0,
    avgMs: bucket.requests ? round1(bucket.totalMs / bucket.requests) : 0,
    maxMs: bucket.maxMs,
  };
}

/** 把 D1 行汇总为总量 / 每日 / 路由三个维度（日期缺失补零）。 */
export function summarizeMetricRows(
  rows: WorkerMetricRow[],
  days: number = 7,
  now: Date = new Date()
): WorkerMetricsSummary {
  const span = parseMetricDays(days);
  const to = metricDate(now);
  const dates: string[] = [];
  for (let offset = span - 1; offset >= 0; offset -= 1) {
    const date = new Date(now.getTime() - offset * 86400_000);
    dates.push(metricDate(date));
  }

  const totals: MutableBucket = { requests: 0, errors: 0, serverErrors: 0, totalMs: 0, maxMs: 0 };
  const daily = new Map<string, MutableBucket>();
  const routes = new Map<string, MutableBucket & { route: string; method: string }>();
  for (const date of dates) {
    daily.set(date, { requests: 0, errors: 0, serverErrors: 0, totalMs: 0, maxMs: 0 });
  }

  for (const row of rows) {
    addRow(totals, row);
    const day = daily.get(row.metric_date);
    if (day) addRow(day, row);
    const key = `${row.method} ${row.route}`;
    const route = routes.get(key) ?? {
      route: row.route,
      method: row.method,
      requests: 0,
      errors: 0,
      serverErrors: 0,
      totalMs: 0,
      maxMs: 0,
    };
    addRow(route, row);
    routes.set(key, route);
  }

  return {
    days: span,
    from: dates[0] ?? to,
    to,
    totals: toBucket(totals),
    daily: dates.map((date) => ({ date, ...toBucket(daily.get(date)!) })),
    routes: [...routes.values()]
      .map((item) => ({
        route: item.route,
        method: item.method,
        ...toBucket(item),
      }))
      .sort((left, right) => right.requests - left.requests)
      .slice(0, 20),
  };
}

/** 写入一条请求指标（UPSERT 聚合）。 */
export async function recordRequestMetric(
  db: D1Database,
  entry: { route: string; method: string; status: number; durationMs: number; now?: Date }
): Promise<void> {
  const duration = Math.max(0, Math.round(Number(entry.durationMs) || 0));
  await db
    .prepare(
      `INSERT INTO worker_metrics (
         metric_date, route, method, status_class, requests, total_ms, max_ms, updated_at
       ) VALUES (?, ?, ?, ?, 1, ?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(metric_date, route, method, status_class) DO UPDATE SET
         requests = requests + 1,
         total_ms = total_ms + excluded.total_ms,
         max_ms = MAX(max_ms, excluded.max_ms),
         updated_at = CURRENT_TIMESTAMP`
    )
    .bind(
      metricDate(entry.now ?? new Date()),
      entry.route,
      (entry.method || 'GET').toUpperCase(),
      statusClass(entry.status),
      duration,
      duration
    )
    .run();
}

/** 读取最近 N 天的原始指标行。 */
export async function queryWorkerMetrics(
  db: D1Database,
  days: number = 7,
  now: Date = new Date()
): Promise<WorkerMetricRow[]> {
  const span = parseMetricDays(days);
  const from = metricDate(new Date(now.getTime() - (span - 1) * 86400_000));
  const result = await db
    .prepare(
      `SELECT metric_date, route, method, status_class, requests, total_ms, max_ms
         FROM worker_metrics
        WHERE metric_date >= ?
        ORDER BY metric_date ASC`
    )
    .bind(from)
    .all<WorkerMetricRow>();
  return result.results ?? [];
}

/** 查询并汇总最近 N 天指标。 */
export async function getWorkerMetricsSummary(
  db: D1Database,
  days: number = 7,
  now: Date = new Date()
): Promise<WorkerMetricsSummary> {
  const rows = await queryWorkerMetrics(db, days, now);
  return summarizeMetricRows(rows, days, now);
}

/** 合并 VPS 状态与 Workers 错误率，得到页面顶部整体状态。 */
export function combineStatus(
  vpsStatus: string | undefined,
  workers: WorkerMetricsSummary | null
): 'ok' | 'warning' | 'critical' | 'unknown' {
  if (vpsStatus === 'critical') return 'critical';
  if (vpsStatus === 'warning') return 'warning';
  if (workers && workers.totals.requests >= 20) {
    if (workers.totals.errorRate >= 30) return 'critical';
    if (workers.totals.errorRate >= 10) return 'warning';
  }
  if (vpsStatus === 'ok') return 'ok';
  return 'unknown';
}
