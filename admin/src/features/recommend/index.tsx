import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookmarkCheck,
  EyeOff,
  ExternalLink,
  Loader2,
  RefreshCw,
  Sparkles,
  Star,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  dismissRecommendation,
  fetchRecommendationStats,
  fetchRecommendations,
  saveRecommendation,
  trackRecommendationClick,
  type Recommendation,
  type RecommendationFilter,
} from './api'

const FILTERS: Array<{ value: RecommendationFilter; label: string }> = [
  { value: 'new', label: '待处理' },
  { value: 'saved', label: '已收藏' },
  { value: 'dismissed', label: '已忽略' },
]

const DISMISS_REASONS = [
  '不感兴趣',
  '技术栈不匹配',
  '已收藏类似项目',
  '其他',
]

type PendingAction = { id: string; kind: 'save' | 'dismiss' } | null

export function Recommend() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<RecommendationFilter>('new')
  const [pending, setPending] = useState<PendingAction>(null)
  const [dismissTarget, setDismissTarget] = useState<Recommendation | null>(null)
  const [dismissReason, setDismissReason] = useState(DISMISS_REASONS[0])

  const listQuery = useQuery({
    queryKey: ['recommendations', filter],
    queryFn: () => fetchRecommendations(filter),
  })
  const statsQuery = useQuery({
    queryKey: ['recommendations', 'stats'],
    queryFn: fetchRecommendationStats,
  })

  const items = listQuery.data ?? []
  const stats = statsQuery.data

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['recommendations'] }),
    ])
  }

  async function handleSave(item: Recommendation) {
    setPending({ id: item.id, kind: 'save' })
    try {
      await saveRecommendation(item.id)
      toast.success(`已收藏 ${item.owner}/${item.name}`)
      await refresh()
    } catch {
      toast.error('收藏失败，请稍后重试')
    } finally {
      setPending(null)
    }
  }

  async function handleDismiss() {
    if (!dismissTarget) return
    const target = dismissTarget
    setPending({ id: target.id, kind: 'dismiss' })
    try {
      await dismissRecommendation(target.id, dismissReason)
      toast.success('已忽略，后续推荐会参考你的反馈')
      setDismissTarget(null)
      await refresh()
    } catch {
      toast.error('忽略失败，请稍后重试')
    } finally {
      setPending(null)
    }
  }

  function handleOpen(item: Recommendation) {
    void trackRecommendationClick(item.id).catch(() => {
      // 点击反馈失败不影响正常跳转
    })
  }

  const pendingTargetId = pending?.id
  const isEmpty = !listQuery.isLoading && !listQuery.isError && items.length === 0

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
        <div className='mb-2 flex flex-wrap items-end justify-between gap-4'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Sparkles className='size-6 text-violet-500' />
              智能推荐
            </h2>
            <p className='text-sm text-muted-foreground'>
              基于你的收藏与阅读偏好，通过语义匹配为你推荐可能感兴趣的开源项目。
            </p>
          </div>
          {stats && (
            <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
              <Badge variant='secondary'>待处理 {stats.new}</Badge>
              <Badge variant='outline'>已收藏 {stats.saved}</Badge>
              <Badge variant='outline'>已忽略 {stats.dismissed}</Badge>
              <Badge variant='outline'>已点击 {stats.clicked}</Badge>
            </div>
          )}
        </div>

        <div className='mb-6 flex flex-wrap items-center gap-2'>
          {FILTERS.map((item) => (
            <Button
              key={item.value}
              type='button'
              size='sm'
              variant={filter === item.value ? 'default' : 'outline'}
              onClick={() => setFilter(item.value)}
            >
              {item.label}
            </Button>
          ))}
        </div>

        {listQuery.isLoading && (
          <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
            {Array.from({ length: 3 }).map((_, index) => (
              <Card key={index}>
                <CardHeader>
                  <Skeleton className='h-5 w-2/3' />
                  <Skeleton className='h-4 w-full' />
                  <Skeleton className='h-4 w-4/5' />
                </CardHeader>
                <CardContent className='space-y-3'>
                  <Skeleton className='h-4 w-full' />
                  <Skeleton className='h-8 w-40' />
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {listQuery.isError && (
          <Card>
            <CardContent className='flex h-40 flex-col items-center justify-center gap-3 text-muted-foreground'>
              <p>推荐加载失败，请检查网络后重试。</p>
              <Button
                size='sm'
                variant='outline'
                onClick={() => void listQuery.refetch()}
              >
                <RefreshCw className='me-1 size-4' />
                重新加载
              </Button>
            </CardContent>
          </Card>
        )}

        {!listQuery.isLoading && !listQuery.isError && (
          <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
            {items.map((item) => {
              const busy = pendingTargetId === item.id
              return (
                <Card key={item.id} className='flex flex-col'>
                  <CardHeader>
                    <div className='flex items-start justify-between gap-2'>
                      <div className='min-w-0'>
                        <CardTitle className='truncate text-base'>
                          <a
                            href={item.url}
                            target='_blank'
                            rel='noreferrer'
                            className='hover:underline'
                            onClick={() => handleOpen(item)}
                          >
                            {item.owner}/{item.name}
                          </a>
                        </CardTitle>
                        <CardDescription className='mt-1 line-clamp-3'>
                          {item.description || '暂无项目简介'}
                        </CardDescription>
                      </div>
                      {item.status === 'saved' ? (
                        <Badge className='shrink-0' variant='secondary'>
                          <BookmarkCheck className='me-1 size-3' />
                          已收藏
                        </Badge>
                      ) : item.status === 'dismissed' ? (
                        <Badge className='shrink-0' variant='outline'>
                          <EyeOff className='me-1 size-3' />
                          已忽略
                        </Badge>
                      ) : (
                        <Badge className='shrink-0'>
                          匹配度 {Math.round(item.score * 100)}%
                        </Badge>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className='flex flex-1 flex-col justify-between gap-4'>
                    <p className='text-sm text-muted-foreground'>{item.reason}</p>
                    <div className='space-y-3'>
                      <div className='flex flex-wrap items-center gap-1'>
                        {(item.basedOn ?? []).map((tag) => (
                          <Badge key={tag} variant='outline'>
                            {tag}
                          </Badge>
                        ))}
                        <span className='ms-auto inline-flex items-center gap-1 text-xs text-muted-foreground'>
                          {item.language && <>{item.language} · </>}
                          <Star className='size-3' />
                          {item.stars.toLocaleString()}
                        </span>
                      </div>
                      <div className='flex flex-wrap gap-2'>
                        <Button size='sm' variant='outline' asChild>
                          <a
                            href={item.url}
                            target='_blank'
                            rel='noreferrer'
                            onClick={() => handleOpen(item)}
                          >
                            查看仓库
                            <ExternalLink className='ms-1 size-3' />
                          </a>
                        </Button>
                        {item.status === 'new' && (
                          <>
                            <Button
                              size='sm'
                              variant='secondary'
                              disabled={busy}
                              onClick={() => void handleSave(item)}
                            >
                              {busy && pending?.kind === 'save' ? (
                                <Loader2 className='me-1 size-4 animate-spin' />
                              ) : (
                                <BookmarkCheck className='me-1 size-4' />
                              )}
                              加入收藏
                            </Button>
                            <Button
                              size='sm'
                              variant='ghost'
                              disabled={busy}
                              onClick={() => {
                                setDismissReason(DISMISS_REASONS[0])
                                setDismissTarget(item)
                              }}
                            >
                              <EyeOff className='me-1 size-4' />
                              忽略
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}

        {isEmpty && (
          <Card>
            <CardContent className='flex h-40 items-center justify-center text-muted-foreground'>
              {filter === 'new'
                ? '暂时没有新的推荐，明天再来看看吧。'
                : filter === 'saved'
                  ? '还没有收藏任何推荐，去「待处理」看看吧。'
                  : '还没有忽略任何推荐。'}
            </CardContent>
          </Card>
        )}
      </Main>

      <Dialog
        open={dismissTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDismissTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>忽略这条推荐</DialogTitle>
            <DialogDescription>
              选择一个原因，反馈会用于调整后续推荐结果。
            </DialogDescription>
          </DialogHeader>
          <div className='grid gap-2'>
            {DISMISS_REASONS.map((reason) => (
              <Button
                key={reason}
                type='button'
                variant={dismissReason === reason ? 'default' : 'outline'}
                className='justify-start'
                onClick={() => setDismissReason(reason)}
              >
                {reason}
              </Button>
            ))}
          </div>
          <DialogFooter>
            <Button
              type='button'
              variant='ghost'
              onClick={() => setDismissTarget(null)}
            >
              取消
            </Button>
            <Button
              type='button'
              variant='destructive'
              disabled={pending?.kind === 'dismiss'}
              onClick={() => void handleDismiss()}
            >
              {pending?.kind === 'dismiss' && (
                <Loader2 className='me-1 size-4 animate-spin' />
              )}
              确认忽略
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
