import { useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  FileText,
  HardDrive,
  Loader2,
  RefreshCw,
  Server,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { cn } from '@/lib/utils'
import {
  type MonitoringAlert,
  type MonitoringOverview,
  MOCK_MONITORING_OVERVIEW,
  acknowledgeMonitoringAlert,
  activeAlerts,
  checkLabel,
  fetchMonitoringOverview,
  formatMb,
  formatPercent,
  severityLabel,
  statusBadgeClass,
  statusLabel,
  triggerMonitoringCheck,
  usageBarClass,
} from './api'

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function StatusBadge({ status }: { status: MonitoringOverview['status'] }) {
  return (
    <Badge variant='outline' className={cn('gap-1', statusBadgeClass(status))}>
      {status === 'ok' ? (
        <CheckCircle2 className='size-3.5' />
      ) : status === 'critical' ? (
        <XCircle className='size-3.5' />
      ) : (
        <AlertTriangle className='size-3.5' />
      )}
      {statusLabel(status)}
    </Badge>
  )
}

function UsageBar({ percent }: { percent: number }) {
  const width = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0))
  return (
    <div className='h-2 w-full overflow-hidden rounded-full bg-muted'>
      <div
        className={cn('h-full rounded-full transition-all', usageBarClass(width))}
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function StatCard({
  title,
  icon,
  value,
  hint,
  percent,
  footer,
}: {
  title: string
  icon: ReactNode
  value: string
  hint: string
  percent?: number
  footer?: string
}) {
  return (
    <Card>
      <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
        <CardTitle className='text-sm font-medium'>{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent className='space-y-2'>
        <div className='text-2xl font-bold'>{value}</div>
        {percent !== undefined && <UsageBar percent={percent} />}
        <p className='text-xs text-muted-foreground'>{hint}</p>
        {footer && <p className='text-xs text-muted-foreground'>{footer}</p>}
      </CardContent>
    </Card>
  )
}

export function Monitoring() {
  const queryClient = useQueryClient()
  const [checking, setChecking] = useState(false)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['monitoring', 'overview'],
    queryFn: () => fetchMonitoringOverview(7),
    refetchInterval: 60_000,
  })

  const overview: MonitoringOverview = data ?? MOCK_MONITORING_OVERVIEW
  const vps = overview.vps
  const workers = overview.workers
  const alerts = activeAlerts(vps?.alerts ?? [])
  const memory = vps?.resources.memory
  const disk = vps?.resources.disk
  const logs = vps?.resources.logs

  async function handleCheck() {
    setChecking(true)
    try {
      await triggerMonitoringCheck()
      toast.success('已触发一轮监控检查')
      await queryClient.invalidateQueries({ queryKey: ['monitoring'] })
    } catch {
      toast.error('检查触发失败，请确认 VPS 节点已配置')
    } finally {
      setChecking(false)
    }
  }

  async function handleAck(alert: MonitoringAlert) {
    try {
      await acknowledgeMonitoringAlert(alert.id)
      toast.success('告警已确认')
      await queryClient.invalidateQueries({ queryKey: ['monitoring'] })
    } catch {
      toast.error('告警确认失败（演示模式）')
    }
  }

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>开源项目工厂</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4 flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Activity className='size-6 text-emerald-500' />
              系统监控
              <StatusBadge status={overview.status} />
            </h2>
            <p className='text-sm text-muted-foreground'>
              健康检查、4G / 15G 资源红线、日志治理与 Workers 请求分析。
              数据更新于 {formatDateTime(overview.generatedAt)}。
            </p>
          </div>
          <div className='flex gap-2'>
            <Button variant='outline' size='sm' onClick={handleCheck} disabled={checking}>
              {checking ? (
                <Loader2 className='size-4 animate-spin' />
              ) : (
                <RefreshCw className='size-4' />
              )}
              立即检查
            </Button>
            <Button
              variant='outline'
              size='sm'
              onClick={() => queryClient.invalidateQueries({ queryKey: ['monitoring'] })}
              disabled={isFetching}
            >
              <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} />
              刷新
            </Button>
          </div>
        </div>

        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
          <StatCard
            title='内存 / 4G'
            icon={<Cpu className='h-4 w-4 text-muted-foreground' />}
            value={memory ? `${formatMb(memory.usedMb)} / ${formatMb(memory.budgetMb)}` : '—'}
            hint={
              memory
                ? `使用率 ${formatPercent(memory.percent)}（来源：${memory.source}）`
                : 'VPS 节点未连接'
            }
            percent={memory?.percent}
            footer={memory ? `预警 ${formatMb(memory.warnMb)} · 红线 ${formatMb(memory.criticalMb)}` : undefined}
          />
          <StatCard
            title='磁盘 / 15G'
            icon={<HardDrive className='h-4 w-4 text-muted-foreground' />}
            value={disk ? `${formatMb(disk.usedMb)} / ${formatMb(disk.budgetMb)}` : '—'}
            hint={disk ? `使用率 ${formatPercent(disk.percent)} · ${disk.path || '运行目录'}` : 'VPS 节点未连接'}
            percent={disk?.percent}
            footer={disk ? `预警 ${formatMb(disk.warnMb)} · 红线 ${formatMb(disk.criticalMb)}` : undefined}
          />
          <StatCard
            title='请求量（7 天）'
            icon={<Activity className='h-4 w-4 text-muted-foreground' />}
            value={workers ? workers.totals.requests.toLocaleString('zh-CN') : '—'}
            hint={workers ? `日均 ${Math.round(workers.totals.requests / Math.max(1, workers.days)).toLocaleString('zh-CN')} 次` : 'Workers 指标不可用'}
            footer={workers ? `平均延迟 ${workers.totals.avgMs} ms · 峰值 ${workers.totals.maxMs} ms` : undefined}
          />
          <StatCard
            title='错误率（7 天）'
            icon={<AlertTriangle className='h-4 w-4 text-muted-foreground' />}
            value={workers ? formatPercent(workers.totals.errorRate) : '—'}
            hint={workers ? `错误 ${workers.totals.errors.toLocaleString('zh-CN')} 次，其中 5xx ${workers.totals.serverErrors} 次` : 'Workers 指标不可用'}
            footer={workers ? `区间 ${workers.from} ~ ${workers.to}` : undefined}
          />
        </div>

        <div className='mt-4 grid gap-4 lg:grid-cols-2'>
          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Server className='size-4 text-muted-foreground' />
                健康检查
              </CardTitle>
              <CardDescription>
                {vps
                  ? `最近检查：${formatDateTime(vps.checkedAt)}`
                  : overview.vpsError
                    ? `VPS 节点不可用：${overview.vpsError}`
                    : 'VPS 节点未配置'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading && !vps ? (
                <div className='flex items-center gap-2 text-sm text-muted-foreground'>
                  <Loader2 className='size-4 animate-spin' />
                  加载中…
                </div>
              ) : vps?.checks.length ? (
                <ul className='space-y-3'>
                  {vps.checks.map((check) => (
                    <li key={check.name} className='flex items-start gap-3'>
                      {check.ok ? (
                        <CheckCircle2 className='mt-0.5 size-4 shrink-0 text-emerald-500' />
                      ) : (
                        <XCircle className='mt-0.5 size-4 shrink-0 text-red-500' />
                      )}
                      <div className='min-w-0'>
                        <div className='flex items-center gap-2 text-sm font-medium'>
                          {checkLabel(check.name)}
                          {!check.ok && (
                            <Badge variant='outline' className='border-amber-500/40 text-amber-600'>
                              {severityLabel(check.severity)}
                            </Badge>
                          )}
                        </div>
                        <p className='truncate text-xs text-muted-foreground'>{check.detail}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className='text-sm text-muted-foreground'>暂无检查结果。</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <AlertTriangle className='size-4 text-muted-foreground' />
                活跃告警
                {alerts.length > 0 && (
                  <Badge variant='outline' className='border-amber-500/40 text-amber-600'>
                    {alerts.length}
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>条件恢复后自动标记为已解决；可人工确认。</CardDescription>
            </CardHeader>
            <CardContent>
              {alerts.length === 0 ? (
                <div className='flex items-center gap-2 text-sm text-muted-foreground'>
                  <CheckCircle2 className='size-4 text-emerald-500' />
                  当前没有活跃告警
                </div>
              ) : (
                <ul className='space-y-3'>
                  {alerts.map((alert) => (
                    <li
                      key={alert.id}
                      className='flex flex-wrap items-start justify-between gap-2 rounded-md border p-3'
                    >
                      <div className='min-w-0 flex-1'>
                        <div className='flex items-center gap-2'>
                          <Badge
                            variant='outline'
                            className={
                              alert.severity === 'critical'
                                ? 'border-red-500/40 text-red-600'
                                : 'border-amber-500/40 text-amber-600'
                            }
                          >
                            {severityLabel(alert.severity)}
                          </Badge>
                          <span className='text-xs text-muted-foreground'>
                            {alert.occurrences} 次 · {formatDateTime(alert.lastSeenAt)}
                          </span>
                        </div>
                        <p className='mt-1 text-sm'>{alert.message}</p>
                      </div>
                      {alert.status === 'open' && (
                        <Button size='sm' variant='outline' onClick={() => handleAck(alert)}>
                          确认
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle className='flex items-center gap-2'>
              <Activity className='size-4 text-muted-foreground' />
              Workers 请求指标
            </CardTitle>
            <CardDescription>
              D1 按日 / 路由聚合的请求量、错误率与延迟（最近 7 天）。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {workers ? (
              <div className='grid gap-6 lg:grid-cols-2'>
                <div>
                  <h4 className='mb-2 text-sm font-medium'>每日趋势</h4>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>日期</TableHead>
                        <TableHead className='text-right'>请求</TableHead>
                        <TableHead className='text-right'>错误率</TableHead>
                        <TableHead className='text-right'>平均延迟</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {workers.daily.map((item) => (
                        <TableRow key={item.date}>
                          <TableCell className='font-mono text-xs'>{item.date}</TableCell>
                          <TableCell className='text-right'>{item.requests.toLocaleString('zh-CN')}</TableCell>
                          <TableCell className='text-right'>{formatPercent(item.errorRate)}</TableCell>
                          <TableCell className='text-right'>{item.avgMs} ms</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <div>
                  <h4 className='mb-2 text-sm font-medium'>热门路由</h4>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>路由</TableHead>
                        <TableHead className='text-right'>请求</TableHead>
                        <TableHead className='text-right'>错误率</TableHead>
                        <TableHead className='text-right'>平均延迟</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {workers.routes.map((item) => (
                        <TableRow key={`${item.method} ${item.route}`}>
                          <TableCell className='max-w-56 truncate font-mono text-xs'>
                            {item.method} {item.route}
                          </TableCell>
                          <TableCell className='text-right'>{item.requests.toLocaleString('zh-CN')}</TableCell>
                          <TableCell className='text-right'>{formatPercent(item.errorRate)}</TableCell>
                          <TableCell className='text-right'>{item.avgMs} ms</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            ) : (
              <p className='text-sm text-muted-foreground'>
                {overview.workersError ? `Workers 指标不可用：${overview.workersError}` : '暂无 Workers 指标。'}
              </p>
            )}
          </CardContent>
        </Card>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle className='flex items-center gap-2'>
              <FileText className='size-4 text-muted-foreground' />
              日志治理
            </CardTitle>
            <CardDescription>
              {logs
                ? `${logs.path || '日志目录'} · 保留 ${logs.retentionDays} 天 · 预算 ${formatMb(logs.budgetMb)}`
                : 'VPS 节点未连接'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {logs ? (
              <div className='space-y-4'>
                <div className='grid gap-3 sm:grid-cols-3'>
                  <div className='rounded-md border p-3'>
                    <div className='text-xs text-muted-foreground'>当前占用</div>
                    <div className='text-lg font-semibold'>{formatMb(logs.totalMb)}</div>
                  </div>
                  <div className='rounded-md border p-3'>
                    <div className='text-xs text-muted-foreground'>文件数</div>
                    <div className='text-lg font-semibold'>{logs.files}</div>
                  </div>
                  <div className='rounded-md border p-3'>
                    <div className='text-xs text-muted-foreground'>超期文件</div>
                    <div className='text-lg font-semibold'>{logs.oldFiles}</div>
                  </div>
                </div>
                {logs.items && logs.items.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>文件</TableHead>
                        <TableHead className='text-right'>大小</TableHead>
                        <TableHead className='text-right'>修改时间</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {logs.items.slice(0, 8).map((item) => (
                        <TableRow key={item.name}>
                          <TableCell className='max-w-64 truncate font-mono text-xs'>
                            {item.name}
                            {item.expired && (
                              <Badge variant='outline' className='ml-2 border-amber-500/40 text-amber-600'>
                                超期
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className='text-right'>{formatMb(item.sizeMb)}</TableCell>
                          <TableCell className='text-right text-xs'>
                            {formatDateTime(item.modifiedAt)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            ) : (
              <p className='text-sm text-muted-foreground'>暂无日志统计。</p>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
