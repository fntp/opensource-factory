import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  RefreshCw,
  RotateCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { DEMO_MODE } from '@/lib/api'
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
import {
  fetchTasks,
  formatTaskTime,
  isTaskActive,
  taskDuration,
  taskProgressPercent,
  taskResultSummary,
  taskStatusLabel,
  taskTypeLabel,
  triggerSync,
  type SyncTask,
} from './api'

const ACTIVE_REFRESH_MS = 3000

function statusBadgeVariant(status: string) {
  if (status === 'failure') return 'destructive' as const
  if (status === 'success') return 'default' as const
  if (status === 'progress' || status === 'started') return 'secondary' as const
  return 'outline' as const
}

function ProgressBar({ task }: { task: SyncTask }) {
  const percent = taskProgressPercent(task)
  const barClass =
    task.status === 'failure'
      ? 'bg-destructive'
      : task.status === 'success'
        ? 'bg-emerald-600'
        : 'bg-primary'
  return (
    <div className='flex min-w-36 items-center gap-2'>
      <div className='h-2 flex-1 overflow-hidden rounded-full bg-muted'>
        <div
          className={`h-full rounded-full transition-all ${barClass}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className='w-9 text-right text-xs text-muted-foreground tabular-nums'>
        {percent}%
      </span>
    </div>
  )
}

export function Tasks() {
  const queryClient = useQueryClient()
  const { data, isFetching, refetch } = useQuery({
    queryKey: ['sync-tasks'],
    queryFn: fetchTasks,
    refetchInterval: (query) => {
      const tasks = query.state.data
      return tasks?.some((task) => isTaskActive(task.status))
        ? ACTIVE_REFRESH_MS
        : false
    },
  })

  const tasks = data ?? []
  const activeCount = tasks.filter((task) => isTaskActive(task.status)).length
  const successCount = tasks.filter((task) => task.status === 'success').length
  const failedCount = tasks.filter((task) => task.status === 'failure').length

  const syncMutation = useMutation({
    mutationFn: triggerSync,
    onSuccess: (result) => {
      if (result.status === 'accepted') {
        toast.info('VPS 节点未配置，同步任务未入队')
        return
      }
      toast.success(
        result.taskId
          ? `同步任务已入队（${result.taskId.slice(0, 8)}）`
          : '同步任务已入队'
      )
      queryClient.invalidateQueries({ queryKey: ['sync-tasks'] })
    },
    onError: () => toast.error('触发同步失败，请检查 edge / VPS 配置'),
  })

  const handleSync = () => {
    if (DEMO_MODE) {
      toast.success('已触发 GitHub 仓库同步（演示）')
      return
    }
    syncMutation.mutate()
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
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>同步任务</h2>
            <p className='text-sm text-muted-foreground'>
              查看仓库同步的实时进度、结果与历史记录。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RotateCw className={isFetching ? 'animate-spin' : ''} />
              刷新
            </Button>
            <Button onClick={handleSync} disabled={syncMutation.isPending}>
              <RefreshCw
                className={syncMutation.isPending ? 'animate-spin' : ''}
              />
              立即同步
            </Button>
          </div>
        </div>

        <div className='grid gap-4 sm:grid-cols-3'>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>运行中</CardTitle>
              <Clock className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>{activeCount}</div>
              <p className='text-xs text-muted-foreground'>
                每 {ACTIVE_REFRESH_MS / 1000} 秒自动刷新
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>已完成</CardTitle>
              <CheckCircle2 className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>{successCount}</div>
              <p className='text-xs text-muted-foreground'>最近 20 条任务</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>失败</CardTitle>
              <AlertTriangle className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>{failedCount}</div>
              <p className='text-xs text-muted-foreground'>
                失败任务会保留已同步部分
              </p>
            </CardContent>
          </Card>
        </div>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle>任务列表</CardTitle>
            <CardDescription>
              共 {tasks.length} 条任务，展示最近 20 条。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任务</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>进度</TableHead>
                  <TableHead>结果</TableHead>
                  <TableHead className='text-end'>耗时</TableHead>
                  <TableHead className='text-end'>开始时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((task) => (
                  <TableRow key={task.taskId}>
                    <TableCell>
                      <div className='font-medium'>
                        {taskTypeLabel(task.type)}
                      </div>
                      <div className='font-mono text-xs text-muted-foreground'>
                        {task.taskId.slice(0, 12)}
                        {task.stale ? ' · 状态未刷新' : ''}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusBadgeVariant(task.status)}>
                        {taskStatusLabel(task.status)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <ProgressBar task={task} />
                    </TableCell>
                    <TableCell className='max-w-72'>
                      <span className='line-clamp-2 text-sm text-muted-foreground'>
                        {taskResultSummary(task)}
                      </span>
                    </TableCell>
                    <TableCell className='text-end text-muted-foreground'>
                      {taskDuration(task)}
                    </TableCell>
                    <TableCell className='text-end text-muted-foreground'>
                      {formatTaskTime(task.createdAt)}
                    </TableCell>
                  </TableRow>
                ))}
                {tasks.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className='h-24 text-center text-muted-foreground'
                    >
                      暂无同步任务，点击「立即同步」开始。
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
