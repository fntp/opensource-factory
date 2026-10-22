import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import {
  Bell,
  CheckCheck,
  ExternalLink,
  Inbox,
  Loader2,
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
import {
  type NotificationFilter,
  type NotificationItem,
  type NotificationsPayload,
  dismissNotification,
  fetchNotifications,
  formatUnreadBadge,
  formatUnreadLabel,
  markAllNotificationsRead,
  markNotificationRead,
  mockNotificationsPayload,
} from './api'

const PAGE_SIZE = 10

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return formatDistanceToNow(date, { addSuffix: true, locale: zhCN })
}

function filterLabel(filter: NotificationFilter): string {
  if (filter === 'unread') return '未读'
  if (filter === 'read') return '已读'
  return '全部'
}

export function Notifications() {
  const [filter, setFilter] = useState<NotificationFilter>('all')
  const [page, setPage] = useState(0)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['notifications', 'list', filter, page],
    queryFn: () =>
      fetchNotifications({
        status: filter,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  })

  const payload: NotificationsPayload =
    data ?? mockNotificationsPayload({ status: filter, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
  const items = payload.items
  const totalPages = Math.max(1, Math.ceil(payload.total / PAGE_SIZE))

  function updateList(
    updater: (current: NotificationsPayload) => NotificationsPayload
  ) {
    queryClient.setQueriesData<NotificationsPayload>(
      { queryKey: ['notifications', 'list'] },
      (current) => (current ? updater(current) : current)
    )
    queryClient.setQueryData<{ unread: number }>(
      ['notifications', 'unread-count'],
      (current) => {
        const next = updater({
          items: [],
          total: 0,
          unread: current?.unread ?? payload.unread,
          limit: PAGE_SIZE,
          offset: 0,
          hasMore: false,
        })
        return { unread: next.unread }
      }
    )
  }

  async function handleRead(item: NotificationItem) {
    if (item.status !== 'unread') return
    updateList((current) => ({
      ...current,
      unread: Math.max(0, current.unread - 1),
      items: current.items.map((row) =>
        row.id === item.id
          ? { ...row, status: 'read', readAt: new Date().toISOString() }
          : row
      ),
    }))
    try {
      await markNotificationRead(item.id)
      toast.success('已标记为已读')
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
    } catch {
      toast.success('已标记为已读（演示模式）')
    }
  }

  async function handleReadAll() {
    updateList((current) => ({
      ...current,
      unread: 0,
      items: current.items.map((row) =>
        row.status === 'unread'
          ? { ...row, status: 'read', readAt: new Date().toISOString() }
          : row
      ),
    }))
    try {
      await markAllNotificationsRead()
      toast.success('全部通知已标记为已读')
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
    } catch {
      toast.success('全部通知已标记为已读（演示模式）')
    }
  }

  async function handleDismiss(item: NotificationItem) {
    updateList((current) => ({
      ...current,
      total: Math.max(0, current.total - 1),
      unread:
        item.status === 'unread'
          ? Math.max(0, current.unread - 1)
          : current.unread,
      items: current.items.filter((row) => row.id !== item.id),
    }))
    try {
      await dismissNotification(item.id)
      toast.success('已忽略该通知')
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
    } catch {
      toast.success('已忽略该通知（演示模式）')
    }
  }

  const unreadBadge = formatUnreadBadge(payload.unread)

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
              <Bell className='size-6 text-violet-500' />
              通知中心
              {unreadBadge && <Badge className='rounded-full'>{unreadBadge}</Badge>}
            </h2>
            <p className='text-sm text-muted-foreground'>
              每日评估通过的项目会进入这里；{formatUnreadLabel(payload.unread)}。
            </p>
          </div>
          <Button
            variant='outline'
            size='sm'
            onClick={handleReadAll}
            disabled={payload.unread === 0}
          >
            <CheckCheck className='size-4' />
            全部已读
          </Button>
        </div>

        <div className='mb-4 flex flex-wrap gap-2'>
          {(['all', 'unread', 'read'] as const).map((value) => (
            <Button
              key={value}
              size='sm'
              variant={filter === value ? 'default' : 'outline'}
              onClick={() => {
                setFilter(value)
                setPage(0)
              }}
            >
              {filterLabel(value)}
            </Button>
          ))}
        </div>

        {isLoading ? (
          <Card>
            <CardContent className='flex h-40 items-center justify-center gap-2 text-muted-foreground'>
              <Loader2 className='size-4 animate-spin' />
              正在加载通知…
            </CardContent>
          </Card>
        ) : items.length === 0 ? (
          <Card>
            <CardContent className='flex h-48 flex-col items-center justify-center gap-2 text-muted-foreground'>
              <Inbox className='size-8' />
              <p>暂时没有{filter === 'all' ? '' : filterLabel(filter)}通知。</p>
            </CardContent>
          </Card>
        ) : (
          <div className='space-y-3'>
            {items.map((item) => (
              <Card
                key={item.id}
                className={item.status === 'unread' ? 'border-violet-200 dark:border-violet-900' : undefined}
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
                          <Badge variant='secondary'>
                            {item.type === 'recommendation'
                              ? '推荐'
                              : item.type === 'repo_update'
                                ? '项目更新'
                                : '系统'}
                          </Badge>
                          {item.score !== null && (
                            <Badge>匹配度 {Math.round(item.score * 100)}%</Badge>
                          )}
                        </CardTitle>
                        <CardDescription className='mt-1'>
                          {item.body ?? '—'}
                        </CardDescription>
                      </div>
                    </div>
                    <span className='text-xs text-muted-foreground'>
                      {formatTime(item.createdAt)}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className='flex flex-wrap items-center justify-between gap-3'>
                  <div className='space-y-1'>
                    {item.reason && (
                      <p className='text-sm text-muted-foreground'>{item.reason}</p>
                    )}
                    <p className='text-xs text-muted-foreground'>
                      {[item.language, item.stars ? `${item.stars.toLocaleString()} stars` : null]
                        .filter(Boolean)
                        .join(' · ') || '—'}
                    </p>
                  </div>
                  <div className='flex gap-2'>
                    {item.url && (
                      <Button size='sm' variant='outline' asChild>
                        <a href={item.url} target='_blank' rel='noreferrer'>
                          <ExternalLink className='size-4' />
                          查看仓库
                        </a>
                      </Button>
                    )}
                    {item.status === 'unread' && (
                      <Button size='sm' variant='secondary' onClick={() => handleRead(item)}>
                        标记已读
                      </Button>
                    )}
                    <Button
                      size='sm'
                      variant='ghost'
                      aria-label={`忽略 ${item.title}`}
                      onClick={() => handleDismiss(item)}
                    >
                      <X className='size-4' />
                      忽略
                    </Button>
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
