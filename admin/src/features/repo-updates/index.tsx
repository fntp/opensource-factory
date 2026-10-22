import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BellRing,
  CheckCheck,
  ExternalLink,
  Inbox,
  Loader2,
  RefreshCw,
  X,
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
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { cn } from '@/lib/utils'
import {
  type RepoUpdateItem,
  type RepoUpdateStatusFilter,
  type RepoUpdateTypeFilter,
  type RepoUpdatesPayload,
  dismissRepoUpdate,
  fetchRepoUpdates,
  formatRepoUpdateBadge,
  markAllRepoUpdatesRead,
  markRepoUpdateRead,
  mockRepoUpdatesPayload,
  scanRepoUpdates,
} from './api'
import {
  REPO_UPDATE_STATUS_FILTERS,
  REPO_UPDATE_TYPE_FILTERS,
  emptyUpdateLabel,
  formatUpdateTime,
  updateStatCards,
  updateStatusFilterLabel,
  updateStatusLabel,
  updateTypeFilterLabel,
  updateTypeLabel,
} from './utils'

const PAGE_SIZE = 10

export function RepoUpdates() {
  const [status, setStatus] = useState<RepoUpdateStatusFilter>('all')
  const [type, setType] = useState<RepoUpdateTypeFilter>('all')
  const [page, setPage] = useState(0)
  const [scanning, setScanning] = useState(false)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['repo-updates', 'list', status, type, page],
    queryFn: () =>
      fetchRepoUpdates({
        status,
        type,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  })

  const payload: RepoUpdatesPayload =
    data ??
    mockRepoUpdatesPayload({
      status,
      type,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    })
  const items = payload.items
  const totalPages = Math.max(1, Math.ceil(payload.total / PAGE_SIZE))
  const unreadBadge = formatRepoUpdateBadge(payload.summary.unread)

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ['repo-updates'] })
  }

  async function handleScan() {
    setScanning(true)
    try {
      const result = await scanRepoUpdates()
      toast.success(
        result.note === 'no repositories to scan'
          ? '收藏库为空，暂无可扫描项目'
          : '已提交扫描任务，稍后刷新查看结果'
      )
    } catch {
      toast.success('已提交扫描任务（演示模式）')
    } finally {
      setScanning(false)
    }
  }

  async function handleRead(item: RepoUpdateItem) {
    if (item.status !== 'unread') return
    try {
      await markRepoUpdateRead(item.id)
      toast.success('已标记为已读')
      await refresh()
    } catch {
      toast.success('已标记为已读（演示模式）')
    }
  }

  async function handleDismiss(item: RepoUpdateItem) {
    try {
      await dismissRepoUpdate(item.id)
      toast.success('已忽略该提醒')
      await refresh()
    } catch {
      toast.success('已忽略该提醒（演示模式）')
    }
  }

  async function handleReadAll() {
    try {
      await markAllRepoUpdatesRead()
      toast.success('全部提醒已标记为已读')
      await refresh()
    } catch {
      toast.success('全部提醒已标记为已读（演示模式）')
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
              <BellRing className='size-6 text-violet-500' />
              更新提醒
              {unreadBadge && <Badge className='rounded-full'>{unreadBadge}</Badge>}
            </h2>
            <p className='text-sm text-muted-foreground'>
              每日扫描收藏项目的 GitHub Release；主版本跃迁或 breaking change 会标记为重大变更。
            </p>
          </div>
          <div className='flex gap-2'>
            <Button variant='outline' size='sm' onClick={handleScan} disabled={scanning}>
              {scanning ? (
                <Loader2 className='size-4 animate-spin' />
              ) : (
                <RefreshCw className='size-4' />
              )}
              立即扫描
            </Button>
            <Button
              variant='secondary'
              size='sm'
              onClick={handleReadAll}
              disabled={payload.summary.unread === 0}
            >
              <CheckCheck className='size-4' />
              全部已读
            </Button>
          </div>
        </div>

        <div className='mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
          {updateStatCards(payload.summary).map((card) => (
            <Card key={card.title}>
              <CardHeader className='pb-2'>
                <CardDescription>{card.title}</CardDescription>
                <CardTitle className='text-2xl tabular-nums'>{card.value}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className='text-xs text-muted-foreground'>{card.hint}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className='mb-4 flex flex-wrap items-center gap-2'>
          {REPO_UPDATE_STATUS_FILTERS.map((value) => (
            <Button
              key={value}
              size='sm'
              variant={status === value ? 'default' : 'outline'}
              onClick={() => {
                setStatus(value)
                setPage(0)
              }}
            >
              {updateStatusFilterLabel(value)}
            </Button>
          ))}
          <span className='mx-1 h-5 w-px bg-border' />
          {REPO_UPDATE_TYPE_FILTERS.map((value) => (
            <Button
              key={value}
              size='sm'
              variant={type === value ? 'secondary' : 'ghost'}
              onClick={() => {
                setType(value)
                setPage(0)
              }}
            >
              {updateTypeFilterLabel(value)}
            </Button>
          ))}
        </div>

        {isLoading ? (
          <Card>
            <CardContent className='flex h-40 items-center justify-center gap-2 text-muted-foreground'>
              <Loader2 className='size-4 animate-spin' />
              正在加载更新提醒…
            </CardContent>
          </Card>
        ) : items.length === 0 ? (
          <Card>
            <CardContent className='flex h-48 flex-col items-center justify-center gap-2 text-muted-foreground'>
              <Inbox className='size-8' />
              <p>{emptyUpdateLabel(status, type)}</p>
            </CardContent>
          </Card>
        ) : (
          <div className='space-y-3'>
            {items.map((item) => (
              <Card
                key={item.id}
                className={cn(
                  item.status === 'unread' && 'border-violet-200 dark:border-violet-900',
                  item.type === 'major' && 'border-s-4 border-s-amber-500'
                )}
              >
                <CardHeader className='pb-2'>
                  <div className='flex flex-wrap items-start justify-between gap-2'>
                    <div className='flex items-start gap-2'>
                      {item.status === 'unread' && (
                        <span
                          aria-label='未读'
                          className='mt-2 size-2 shrink-0 rounded-full bg-violet-500'
                        />
                      )}
                      <div>
                        <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
                          {item.url ? (
                            <a
                              href={item.url}
                              target='_blank'
                              rel='noreferrer'
                              className='hover:underline'
                            >
                              {item.title}
                            </a>
                          ) : (
                            item.title
                          )}
                          <Badge variant={item.type === 'major' ? 'destructive' : 'secondary'}>
                            {item.type === 'major' && <AlertTriangle className='size-3' />}
                            {updateTypeLabel(item.type)}
                          </Badge>
                          <Badge variant='outline'>{item.version}</Badge>
                          {item.status !== 'unread' && (
                            <Badge variant='outline'>{updateStatusLabel(item.status)}</Badge>
                          )}
                        </CardTitle>
                        <CardDescription className='mt-1'>
                          {item.summary || '暂无 Release 说明'}
                        </CardDescription>
                      </div>
                    </div>
                    <span className='text-xs text-muted-foreground'>
                      发现于 {formatUpdateTime(item.detectedAt)}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className='flex flex-wrap items-center justify-between gap-3'>
                  <div className='space-y-1 text-xs text-muted-foreground'>
                    <a
                      href={item.repoUrl}
                      target='_blank'
                      rel='noreferrer'
                      className='font-medium text-foreground hover:underline'
                    >
                      {item.repoName}
                    </a>
                    <p>上游发布：{formatUpdateTime(item.publishedAt)}</p>
                  </div>
                  <div className='flex gap-2'>
                    {item.url && (
                      <Button size='sm' variant='outline' asChild>
                        <a href={item.url} target='_blank' rel='noreferrer'>
                          <ExternalLink className='size-4' />
                          查看 Release
                        </a>
                      </Button>
                    )}
                    {item.status === 'unread' && (
                      <Button size='sm' variant='secondary' onClick={() => handleRead(item)}>
                        标记已读
                      </Button>
                    )}
                    {item.status !== 'dismissed' && (
                      <Button
                        size='sm'
                        variant='ghost'
                        aria-label={`忽略 ${item.title}`}
                        onClick={() => handleDismiss(item)}
                      >
                        <X className='size-4' />
                        忽略
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {payload.total > PAGE_SIZE && (
          <div className='mt-4 flex items-center justify-end gap-2'>
            <Button
              size='sm'
              variant='outline'
              disabled={page === 0}
              onClick={() => setPage((value) => Math.max(0, value - 1))}
            >
              上一页
            </Button>
            <span className='text-sm text-muted-foreground'>
              第 {page + 1} / {totalPages} 页
            </span>
            <Button
              size='sm'
              variant='outline'
              disabled={!payload.hasMore}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
            </Button>
          </div>
        )}
      </Main>
    </>
  )
}
