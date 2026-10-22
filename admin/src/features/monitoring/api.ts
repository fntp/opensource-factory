/**
 * 系统监控 API 与演示数据（REQ-202610-0941 / M5-03）。
 *
 * 管理后台只调用边缘 Worker 的 `/api/monitoring/overview`：
 * - Workers 指标来自 D1 `worker_metrics`（边缘自采集）；
 * - VPS 健康检查 / 资源 / 告警由边缘代理本地节点 `/api/monitoring/status`。
 */
import { apiFetch, fetchWithFallback } from '@/lib/api'

export type MonitoringStatus = 'ok' | 'warning' | 'critical' | 'unknown'

export interface MonitoringCheck {
  name: string
  ok: boolean
  detail: string
  severity: string
}

export interface MemoryResource {
  usedMb: number
  budgetMb: number
  warnMb: number
  criticalMb: number
  percent: number
  source: string
  systemTotalMb?: number
  systemAvailableMb?: number
}

export interface DiskResource {
  usedMb: number
  budgetMb: number
  warnMb: number
  criticalMb: number
  percent: number
  path: string
  filesystemTotalMb?: number
  filesystemFreeMb?: number
}

export interface LoadResource {
  one: number
  five: number
  fifteen: number
  running: number
  total: number
}

export interface LogFileItem {
  name: string
  sizeMb: number
  modifiedAt: string
  expired: boolean
}

export interface LogsResource {
  path: string
  exists: boolean
  files: number
  totalMb: number
  budgetMb: number
  retentionDays: number
  oldFiles: number
  items?: LogFileItem[]
}

export interface MonitoringResources {
  memory: MemoryResource
  disk: DiskResource
  load: LoadResource
  logs: LogsResource
  collectedAt?: string
}

export interface MonitoringAlert {
  id: string
  kind: string
  severity: string
  message: string
  details: Record<string, unknown>
  dedupeKey: string
  status: 'open' | 'acknowledged' | 'resolved'
  occurrences: number
  firstSeenAt: string | null
  lastSeenAt: string | null
  acknowledgedAt: string | null
  resolvedAt: string | null
}

export interface MonitoringRun {
  id: string
  status: string
  checks: MonitoringCheck[]
  resources: MonitoringResources
  findings: Array<Record<string, unknown>>
  createdAt: string
}

export interface VpsMonitoringStatus {
  status: MonitoringStatus
  checkedAt: string
  checks: MonitoringCheck[]
  resources: MonitoringResources
  findings?: Array<Record<string, unknown>>
  thresholds?: Record<string, number>
  alerts: MonitoringAlert[]
  latestRun: MonitoringRun | null
}

export interface WorkerMetricBucket {
  requests: number
  errors: number
  serverErrors: number
  errorRate: number
  avgMs: number
  maxMs: number
}

export interface WorkerDailyMetric extends WorkerMetricBucket {
  date: string
}

export interface WorkerRouteMetric extends WorkerMetricBucket {
  route: string
  method: string
}

export interface WorkerMetricsSummary {
  days: number
  from: string
  to: string
  totals: WorkerMetricBucket
  daily: WorkerDailyMetric[]
  routes: WorkerRouteMetric[]
}

export interface MonitoringOverview {
  status: MonitoringStatus
  generatedAt: string
  edge: { status: string; metrics: boolean }
  workers: WorkerMetricsSummary | null
  workersError: string | null
  vps: VpsMonitoringStatus | null
  vpsError: string | null
}

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86400_000).toISOString()
}

function mockDailyMetrics(): WorkerDailyMetric[] {
  const values = [
    { requests: 1480, errors: 9, serverErrors: 2, avgMs: 82.4, maxMs: 640 },
    { requests: 1620, errors: 12, serverErrors: 1, avgMs: 79.1, maxMs: 520 },
    { requests: 1555, errors: 7, serverErrors: 0, avgMs: 88.6, maxMs: 710 },
    { requests: 1710, errors: 18, serverErrors: 3, avgMs: 91.2, maxMs: 980 },
    { requests: 1664, errors: 6, serverErrors: 0, avgMs: 84.9, maxMs: 600 },
    { requests: 1592, errors: 8, serverErrors: 1, avgMs: 80.3, maxMs: 540 },
    { requests: 1736, errors: 11, serverErrors: 2, avgMs: 86.7, maxMs: 820 },
  ]
  return values.map((item, index) => ({
    date: isoDaysAgo(values.length - 1 - index).slice(0, 10),
    ...item,
    errorRate: Math.round((item.errors / item.requests) * 1000) / 10,
  }))
}

const MOCK_DAILY = mockDailyMetrics()

const MOCK_WORKER_TOTALS: WorkerMetricBucket = {
  requests: MOCK_DAILY.reduce((sum, item) => sum + item.requests, 0),
  errors: MOCK_DAILY.reduce((sum, item) => sum + item.errors, 0),
  serverErrors: MOCK_DAILY.reduce((sum, item) => sum + item.serverErrors, 0),
  errorRate:
    Math.round(
      (MOCK_DAILY.reduce((sum, item) => sum + item.errors, 0) /
        MOCK_DAILY.reduce((sum, item) => sum + item.requests, 0)) *
        1000
    ) / 10,
  avgMs: 84.9,
  maxMs: 980,
}

export const MOCK_MONITORING_OVERVIEW: MonitoringOverview = {
  status: 'warning',
  generatedAt: isoDaysAgo(0),
  edge: { status: 'ok', metrics: true },
  workersError: null,
  workers: {
    days: 7,
    from: MOCK_DAILY[0]?.date ?? '',
    to: MOCK_DAILY[MOCK_DAILY.length - 1]?.date ?? '',
    totals: MOCK_WORKER_TOTALS,
    daily: MOCK_DAILY,
    routes: [
      {
        route: '/api/repos',
        method: 'GET',
        requests: 4860,
        errors: 21,
        serverErrors: 4,
        errorRate: 0.4,
        avgMs: 74.2,
        maxMs: 620,
      },
      {
        route: '/api/trending',
        method: 'GET',
        requests: 3210,
        errors: 12,
        serverErrors: 2,
        errorRate: 0.4,
        avgMs: 88.6,
        maxMs: 710,
      },
      {
        route: '/api/recommendations',
        method: 'GET',
        requests: 2104,
        errors: 9,
        serverErrors: 1,
        errorRate: 0.4,
        avgMs: 96.3,
        maxMs: 980,
      },
      {
        route: '/api/search/semantic',
        method: 'POST',
        requests: 1183,
        errors: 5,
        serverErrors: 0,
        errorRate: 0.4,
        avgMs: 142.5,
        maxMs: 880,
      },
    ],
  },
  vpsError: null,
  vps: {
    status: 'warning',
    checkedAt: isoDaysAgo(0),
    checks: [
      { name: 'database', ok: true, detail: '数据库可读写', severity: 'info' },
      { name: 'runtime_home', ok: true, detail: '/opt/openfactory', severity: 'info' },
      { name: 'redis', ok: true, detail: '127.0.0.1:6379 可连接', severity: 'info' },
      { name: 'edge', ok: true, detail: 'https://example.workers.dev 健康', severity: 'info' },
      {
        name: 'model_budget',
        ok: true,
        detail: 'BAAI/bge-m3（int8）约 1.1G，预算 2.0G',
        severity: 'info',
      },
    ],
    resources: {
      memory: {
        usedMb: 3640,
        budgetMb: 4096,
        warnMb: 3584,
        criticalMb: 4096,
        percent: 88.9,
        source: 'cgroup',
        systemTotalMb: 4096,
        systemAvailableMb: 456,
      },
      disk: {
        usedMb: 9860,
        budgetMb: 15360,
        warnMb: 13312,
        criticalMb: 15360,
        percent: 64.2,
        path: '/opt/openfactory',
        filesystemTotalMb: 40960,
        filesystemFreeMb: 24100,
      },
      load: { one: 0.62, five: 0.58, fifteen: 0.51, running: 3, total: 8 },
      logs: {
        path: '/opt/openfactory/logs',
        exists: true,
        files: 12,
        totalMb: 86.4,
        budgetMb: 1024,
        retentionDays: 14,
        oldFiles: 1,
        items: [
          {
            name: 'vps-api.log',
            sizeMb: 42.1,
            modifiedAt: isoDaysAgo(0),
            expired: false,
          },
          {
            name: 'celery-worker.log',
            sizeMb: 31.6,
            modifiedAt: isoDaysAgo(0),
            expired: false,
          },
          {
            name: 'vps-api.log.1',
            sizeMb: 12.7,
            modifiedAt: isoDaysAgo(18),
            expired: true,
          },
        ],
      },
      collectedAt: isoDaysAgo(0),
    },
    findings: [
      {
        kind: 'memory',
        severity: 'warning',
        message: '内存占用 3640 MB 超过 3.5G 预警线',
      },
    ],
    thresholds: {
      memoryWarnMb: 3584,
      memoryCriticalMb: 4096,
      diskWarnMb: 13312,
      diskCriticalMb: 15360,
      logBudgetMb: 1024,
    },
    alerts: [
      {
        id: 'mock-alert-1',
        kind: 'memory',
        severity: 'warning',
        message: '内存占用 3640 MB 超过 3.5G 预警线',
        details: { usedMb: 3640, warnMb: 3584 },
        dedupeKey: 'monitoring:memory:project',
        status: 'open',
        occurrences: 3,
        firstSeenAt: isoDaysAgo(0.2),
        lastSeenAt: isoDaysAgo(0),
        acknowledgedAt: null,
        resolvedAt: null,
      },
      {
        id: 'mock-alert-2',
        kind: 'logs',
        severity: 'warning',
        message: '日志占用 1050 MB 超过预算 1024 MB',
        details: { totalMb: 1050, budgetMb: 1024 },
        dedupeKey: 'monitoring:logs:runtime',
        status: 'resolved',
        occurrences: 1,
        firstSeenAt: isoDaysAgo(2),
        lastSeenAt: isoDaysAgo(2),
        acknowledgedAt: null,
        resolvedAt: isoDaysAgo(1.9),
      },
    ],
    latestRun: {
      id: 'mock-run-1',
      status: 'warning',
      checks: [],
      resources: {
        memory: {
          usedMb: 3640,
          budgetMb: 4096,
          warnMb: 3584,
          criticalMb: 4096,
          percent: 88.9,
          source: 'cgroup',
        },
        disk: {
          usedMb: 9860,
          budgetMb: 15360,
          warnMb: 13312,
          criticalMb: 15360,
          percent: 64.2,
          path: '/opt/openfactory',
        },
        load: { one: 0.62, five: 0.58, fifteen: 0.51, running: 3, total: 8 },
        logs: {
          path: '/opt/openfactory/logs',
          exists: true,
          files: 12,
          totalMb: 86.4,
          budgetMb: 1024,
          retentionDays: 14,
          oldFiles: 1,
        },
      },
      findings: [],
      createdAt: isoDaysAgo(0),
    },
  },
}

/** 拉取统一监控视图；接口不可用时回退到内置演示数据。 */
export function fetchMonitoringOverview(days = 7): Promise<MonitoringOverview> {
  return fetchWithFallback<MonitoringOverview>(
    `/api/monitoring/overview?days=${days}`,
    MOCK_MONITORING_OVERVIEW
  )
}

/** 触发一轮 VPS 检查（演示模式下失败由页面兜底）。 */
export function triggerMonitoringCheck(): Promise<unknown> {
  return apiFetch('/api/monitoring/check', { method: 'POST' })
}

/** 确认告警。 */
export function acknowledgeMonitoringAlert(id: string): Promise<MonitoringAlert> {
  return apiFetch<MonitoringAlert>(`/api/monitoring/alerts/${id}/ack`, {
    method: 'POST',
  })
}

/** 字节 / MB 格式化：大于 1024 MB 显示 GB。 */
export function formatMb(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (Math.abs(value) >= 1024) return `${(value / 1024).toFixed(1)} GB`
  return `${Math.round(value)} MB`
}

/** 百分比格式化。 */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(digits)}%`
}

/** 整体状态中文文案。 */
export function statusLabel(status: MonitoringStatus): string {
  if (status === 'ok') return '正常'
  if (status === 'warning') return '预警'
  if (status === 'critical') return '严重'
  return '未知'
}

/** 告警级别中文文案。 */
export function severityLabel(severity: string): string {
  if (severity === 'critical') return '严重'
  if (severity === 'warning') return '预警'
  return '提示'
}

/** 状态对应的徽章样式。 */
export function statusBadgeClass(status: MonitoringStatus): string {
  if (status === 'ok') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600'
  if (status === 'warning') return 'border-amber-500/40 bg-amber-500/10 text-amber-600'
  if (status === 'critical') return 'border-red-500/40 bg-red-500/10 text-red-600'
  return 'border-muted-foreground/30 bg-muted text-muted-foreground'
}

/** 资源使用率对应的进度条颜色。 */
export function usageBarClass(percent: number): string {
  if (percent >= 100) return 'bg-red-500'
  if (percent >= 87.5) return 'bg-amber-500'
  return 'bg-emerald-500'
}

/** 活跃告警（open / acknowledged）。 */
export function activeAlerts(alerts: MonitoringAlert[]): MonitoringAlert[] {
  return alerts.filter((alert) => alert.status !== 'resolved')
}

/** 检查项中文名称。 */
export function checkLabel(name: string): string {
  const labels: Record<string, string> = {
    database: '数据库',
    runtime_home: '运行目录',
    redis: 'Redis',
    edge: 'Edge Worker',
    model_budget: '模型预算',
  }
  return labels[name] ?? name
}
