import { useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowUpCircle,
  CheckCircle2,
  Cloud,
  Cpu,
  Gauge,
  HardDrive,
  Loader2,
  RefreshCw,
  RotateCcw,
  Server,
  Sparkles,
  Zap,
} from 'lucide-react'
import { toast } from 'sonner'
import { DEMO_MODE } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  applyModelUpgrade,
  fetchModelRouteHealth,
  fetchModelRoutes,
  MOCK_MODEL_ROUTE_HEALTH,
  resetAllModelRoutes,
  resetModelRoute,
  updateModelRoute,
  type ModelRouteStrategy,
  type ModelRouteTask,
} from './api'
import {
  STRATEGY_OPTIONS,
  bestUpgrade,
  budgetToneClass,
  embeddingDimensionHint,
  fallbackNames,
  formatBudgetPercent,
  formatCost,
  formatLatency,
  formatMb,
  formatQuality,
  modelOptions,
  providerBadgeVariant,
  providerLabel,
  strategyLabel,
} from './utils'

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div className='rounded-lg border bg-muted/20 p-2.5'>
      <div className='flex items-center gap-1.5 text-xs text-muted-foreground'>
        {icon}
        {label}
      </div>
      <p className='mt-1 text-sm font-semibold tabular-nums'>{value}</p>
    </div>
  )
}

function TaskRouteCard({
  task,
  busy,
  onApply,
  onReset,
  onUpgrade,
}: {
  task: ModelRouteTask
  busy: boolean
  onApply: (
    task: ModelRouteTask,
    strategy: ModelRouteStrategy,
    modelId: string
  ) => Promise<void>
  onReset: (task: ModelRouteTask) => Promise<void>
  onUpgrade: (task: ModelRouteTask) => Promise<void>
}) {
  const [strategy, setStrategy] = useState<ModelRouteStrategy>(task.strategy)
  const [modelId, setModelId] = useState(task.modelId)
  const options = modelOptions(task)
  const upgrade = bestUpgrade(task)
  const percent = formatBudgetPercent(task.residentMb, task.budgetMb)
  const dimensionHint = embeddingDimensionHint(task)

  function changeStrategy(value: string) {
    const next = value as ModelRouteStrategy
    setStrategy(next)
    if (next === 'manual' && !options.some((item) => item.id === modelId)) {
      setModelId(options[0]?.id ?? task.modelId)
    }
  }

  return (
    <Card className='flex flex-col'>
      <CardHeader className='pb-3'>
        <div className='flex flex-wrap items-start justify-between gap-2'>
          <div>
            <CardTitle className='flex items-center gap-2 text-base'>
              <Cpu className='size-4 text-muted-foreground' />
              {task.label}
            </CardTitle>
            <CardDescription className='mt-1'>
              {task.description}
            </CardDescription>
          </div>
          <div className='flex flex-wrap items-center gap-1.5'>
            <Badge variant='outline'>{strategyLabel(task.strategy)}</Badge>
            <Badge variant={providerBadgeVariant(task.provider)}>
              {providerLabel(task.provider)}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className='flex flex-1 flex-col gap-3'>
        <div className='rounded-lg border bg-muted/30 p-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='text-xs text-muted-foreground'>当前模型</span>
            <span className='text-xs text-muted-foreground tabular-nums'>
              预算占用 {percent}%
            </span>
          </div>
          <p className='mt-1 font-medium'>{task.modelName}</p>
          <p className='mt-1 text-xs text-muted-foreground'>{task.reason}</p>
          <div className='mt-2 h-1.5 overflow-hidden rounded-full bg-muted'>
            <div
              className={cn('h-full rounded-full', budgetToneClass(percent))}
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>

        <div className='grid grid-cols-2 gap-2 sm:grid-cols-4'>
          <Metric
            icon={<HardDrive className='size-3.5' />}
            label='驻留'
            value={formatMb(task.residentMb)}
          />
          <Metric
            icon={<Gauge className='size-3.5' />}
            label='质量'
            value={formatQuality(task.quality)}
          />
          <Metric
            icon={<Zap className='size-3.5' />}
            label='延迟'
            value={formatLatency(task.latencyMs)}
          />
          <Metric
            icon={<Cloud className='size-3.5' />}
            label='成本'
            value={formatCost(task.costPer1k)}
          />
        </div>

        <div className='grid gap-2 sm:grid-cols-2'>
          <div className='space-y-1.5'>
            <Label htmlFor={`${task.task}-strategy`}>路由策略</Label>
            <Select value={strategy} onValueChange={changeStrategy}>
              <SelectTrigger id={`${task.task}-strategy`} className='w-full'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STRATEGY_OPTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {strategy === 'manual' && (
            <div className='space-y-1.5'>
              <Label htmlFor={`${task.task}-model`}>指定模型</Label>
              <Select value={modelId} onValueChange={setModelId}>
                <SelectTrigger id={`${task.task}-model`} className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <div className='flex flex-wrap items-center gap-2'>
          <Button
            size='sm'
            onClick={() => void onApply(task, strategy, modelId)}
            disabled={busy}
          >
            {busy ? (
              <Loader2 className='size-4 animate-spin' />
            ) : (
              <CheckCircle2 className='size-4' />
            )}
            应用
          </Button>
          <Button
            size='sm'
            variant='outline'
            onClick={() => void onReset(task)}
            disabled={busy}
          >
            <RotateCcw className='size-4' />
            恢复默认
          </Button>
          {upgrade && (
            <Button
              size='sm'
              variant='secondary'
              onClick={() => void onUpgrade(task)}
              disabled={busy}
            >
              <ArrowUpCircle className='size-4' />
              升级至 {upgrade.modelName}
            </Button>
          )}
        </div>

        {task.upgrades.length > 0 && (
          <div className='space-y-1.5'>
            <p className='text-xs font-medium text-muted-foreground'>
              升级建议
            </p>
            {task.upgrades.slice(0, 4).map((item) => (
              <div
                key={item.modelId}
                className='flex flex-wrap items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs'
              >
                <Badge variant={item.eligible ? 'secondary' : 'outline'}>
                  {item.eligible ? '可升级' : '受预算限制'}
                </Badge>
                <span className='font-medium'>{item.modelName}</span>
                <span className='text-muted-foreground'>
                  质量 {item.quality} · {formatMb(item.residentMb)}
                </span>
                <span className='ms-auto text-muted-foreground'>
                  {item.reason}
                </span>
              </div>
            ))}
          </div>
        )}

        {dimensionHint && (
          <p className='rounded-md border border-amber-300/60 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-200'>
            {dimensionHint}
          </p>
        )}

        <p className='mt-auto text-xs text-muted-foreground'>
          回退链：{fallbackNames(task)}
        </p>
      </CardContent>
    </Card>
  )
}

export function ModelRouting() {
  const queryClient = useQueryClient()
  const [busyTask, setBusyTask] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)

  const overviewQuery = useQuery({
    queryKey: ['model-routes'],
    queryFn: fetchModelRoutes,
  })
  const healthQuery = useQuery({
    queryKey: ['model-routes', 'health'],
    queryFn: fetchModelRouteHealth,
  })

  const overview = overviewQuery.data
  const health = healthQuery.data ?? MOCK_MODEL_ROUTE_HEALTH

  async function refresh() {
    await Promise.all([overviewQuery.refetch(), healthQuery.refetch()])
  }

  async function handleApply(
    task: ModelRouteTask,
    strategy: ModelRouteStrategy,
    modelId: string
  ) {
    if (DEMO_MODE) {
      toast.info('演示模式：未连接 VPS，配置不会持久化')
      return
    }
    setBusyTask(task.task)
    try {
      await updateModelRoute(task.task, {
        strategy,
        modelId: strategy === 'manual' ? modelId : null,
      })
      await queryClient.invalidateQueries({ queryKey: ['model-routes'] })
      toast.success(`${task.label}路由已更新`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新路由失败')
    } finally {
      setBusyTask(null)
    }
  }

  async function handleReset(task: ModelRouteTask) {
    if (DEMO_MODE) {
      toast.info('演示模式：未连接 VPS，配置不会持久化')
      return
    }
    setBusyTask(task.task)
    try {
      await resetModelRoute(task.task)
      await queryClient.invalidateQueries({ queryKey: ['model-routes'] })
      toast.success(`${task.label}已恢复默认`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '恢复默认失败')
    } finally {
      setBusyTask(null)
    }
  }

  async function handleUpgrade(task: ModelRouteTask) {
    if (DEMO_MODE) {
      toast.info('演示模式：未连接 VPS，配置不会持久化')
      return
    }
    setBusyTask(task.task)
    try {
      const result = await applyModelUpgrade(task.task)
      await queryClient.invalidateQueries({ queryKey: ['model-routes'] })
      if (result.ok) toast.success(result.message)
      else toast.warning(result.message)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '应用升级失败')
    } finally {
      setBusyTask(null)
    }
  }

  async function handleResetAll() {
    if (DEMO_MODE) {
      toast.info('演示模式：未连接 VPS，配置不会持久化')
      return
    }
    setResetting(true)
    try {
      const result = await resetAllModelRoutes()
      await queryClient.invalidateQueries({ queryKey: ['model-routes'] })
      toast.success(result.message)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '全部恢复默认失败')
    } finally {
      setResetting(false)
    }
  }

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>模型路由</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4 flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>
              模型路由与升级
            </h2>
            <p className='text-sm text-muted-foreground'>
              按任务选择模型：预算、均衡、质量或人工指定；所有选择都必须落在推理内存预算内。
            </p>
          </div>
          <div className='flex flex-wrap items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => void refresh()}
              disabled={overviewQuery.isFetching || healthQuery.isFetching}
            >
              <RefreshCw
                className={cn(
                  'size-4',
                  (overviewQuery.isFetching || healthQuery.isFetching) &&
                    'animate-spin'
                )}
              />
              刷新
            </Button>
            <Button
              variant='outline'
              size='sm'
              onClick={() => void handleResetAll()}
              disabled={resetting}
            >
              {resetting ? (
                <Loader2 className='size-4 animate-spin' />
              ) : (
                <RotateCcw className='size-4' />
              )}
              全部恢复默认
            </Button>
          </div>
        </div>

        {DEMO_MODE && (
          <div className='mb-4 flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-500/40 dark:bg-amber-950/30 dark:text-amber-200'>
            <AlertTriangle className='mt-0.5 size-4 shrink-0' />
            演示模式：当前展示内置示例数据，配置操作不会写入后端。
          </div>
        )}

        {overviewQuery.isLoading && !overview ? (
          <Card>
            <CardContent className='flex items-center justify-center gap-2 py-16 text-muted-foreground'>
              <Loader2 className='size-5 animate-spin' />
              正在加载模型路由…
            </CardContent>
          </Card>
        ) : overview ? (
          <div className='space-y-4'>
            <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
              <Card>
                <CardHeader className='pb-2'>
                  <CardDescription>任务路由</CardDescription>
                  <CardTitle className='text-2xl tabular-nums'>
                    {overview.taskCount}
                  </CardTitle>
                </CardHeader>
                <CardContent className='text-xs text-muted-foreground'>
                  每个任务独立选择模型与策略
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardDescription>本地 / 云端模型</CardDescription>
                  <CardTitle className='text-2xl tabular-nums'>
                    {overview.localModelCount} / {overview.cloudModelCount}
                  </CardTitle>
                </CardHeader>
                <CardContent className='text-xs text-muted-foreground'>
                  另有 {overview.ruleModelCount} 个本地规则引擎
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardDescription>峰值驻留</CardDescription>
                  <CardTitle className='text-2xl tabular-nums'>
                    {formatMb(overview.peakResidentMb)}
                  </CardTitle>
                </CardHeader>
                <CardContent className='space-y-1.5'>
                  <div className='h-2 overflow-hidden rounded-full bg-muted'>
                    <div
                      className={cn(
                        'h-full rounded-full',
                        budgetToneClass(overview.budgetPercent)
                      )}
                      style={{
                        width: `${Math.min(100, overview.budgetPercent)}%`,
                      }}
                    />
                  </div>
                  <p className='text-xs text-muted-foreground'>
                    预算 {formatMb(overview.budgetMb)} · 占用{' '}
                    {overview.budgetPercent}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className='pb-2'>
                  <CardDescription>预算状态</CardDescription>
                  <CardTitle className='flex items-center gap-2 text-2xl'>
                    {overview.withinBudget ? (
                      <CheckCircle2 className='size-6 text-emerald-500' />
                    ) : (
                      <AlertTriangle className='size-6 text-red-500' />
                    )}
                    {overview.withinBudget ? '正常' : '超预算'}
                  </CardTitle>
                </CardHeader>
                <CardContent className='text-xs text-muted-foreground'>
                  所有任务结果均通过 resident_mb ≤ 预算校验
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className='pb-3'>
                <CardTitle className='flex items-center gap-2 text-base'>
                  <Server className='size-4 text-muted-foreground' />
                  模型通道
                </CardTitle>
                <CardDescription>
                  实时探测 Ollama；DeepSeek 只展示配置状态，不发起真实调用。
                </CardDescription>
              </CardHeader>
              <CardContent className='grid gap-3 sm:grid-cols-3'>
                <div className='rounded-lg border p-3'>
                  <div className='flex items-center justify-between gap-2'>
                    <span className='text-sm font-medium'>Ollama</span>
                    <Badge
                      variant={
                        health.ollama.reachable ? 'secondary' : 'outline'
                      }
                    >
                      {health.ollama.reachable ? '可达' : '不可达'}
                    </Badge>
                  </div>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {health.ollama.configured
                      ? health.ollama.reachable
                        ? `已加载 ${health.ollama.models.length} 个模型 · 峰值 ${formatMb(
                            health.ollama.peakResidentMb
                          )}`
                        : health.ollama.error || '未配置 OLLAMA_BASE_URL'
                      : '未配置 OLLAMA_BASE_URL'}
                  </p>
                </div>
                <div className='rounded-lg border p-3'>
                  <div className='flex items-center justify-between gap-2'>
                    <span className='text-sm font-medium'>DeepSeek</span>
                    <Badge
                      variant={
                        health.deepseek.configured ? 'default' : 'outline'
                      }
                    >
                      {health.deepseek.configured ? '已配置' : '未配置'}
                    </Badge>
                  </div>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {health.deepseek.configured
                      ? `模型 ${health.deepseek.model}`
                      : '配置 DEEPSEEK_API_KEY 后可启用云端路由'}
                  </p>
                </div>
                <div className='rounded-lg border p-3'>
                  <div className='flex items-center justify-between gap-2'>
                    <span className='text-sm font-medium'>规则引擎</span>
                    <Badge variant='outline'>
                      {health.rules.available ? '可用' : '不可用'}
                    </Badge>
                  </div>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    打标 / 分类 / 精排零模型驻留，始终可回退。
                  </p>
                </div>
              </CardContent>
            </Card>

            <div className='grid gap-4 lg:grid-cols-2'>
              {overview.tasks.map((task) => (
                <TaskRouteCard
                  key={`${task.task}-${task.strategy}-${task.modelId}`}
                  task={task}
                  busy={busyTask === task.task}
                  onApply={handleApply}
                  onReset={handleReset}
                  onUpgrade={handleUpgrade}
                />
              ))}
            </div>

            <p className='flex items-center gap-1.5 text-xs text-muted-foreground'>
              <Sparkles className='size-3.5' />
              路由配置为节点级，保存后对新任务生效；已有向量化单例需重启 VPS
              进程后切换模型。
            </p>
          </div>
        ) : null}
      </Main>
    </>
  )
}
