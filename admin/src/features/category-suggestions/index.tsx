import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ExternalLink,
  Loader2,
  RefreshCw,
  Sparkles,
  Tags,
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
  acceptCategorySuggestions,
  dismissCategorySuggestions,
  fetchCategorySuggestions,
  generateCategorySuggestions,
  type CategorySuggestionStatus,
} from './api'
import {
  businessLineLabel,
  formatScore,
  generateSummary,
  groupByRepo,
  scoreTier,
  sourceLabel,
  statusLabel,
  summaryText,
  type CategorySuggestionItem,
  type CategorySuggestionListResponse,
} from './utils'

const STATUS_TABS: Array<CategorySuggestionStatus | 'all'> = [
  'pending',
  'accepted',
  'dismissed',
  'all',
]

function tierClass(tier: 'high' | 'medium' | 'low'): string {
  if (tier === 'high')
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700'
  if (tier === 'medium')
    return 'border-amber-500/30 bg-amber-500/10 text-amber-700'
  return 'border-slate-500/30 bg-slate-500/10 text-slate-600'
}

function removeItems(
  data: CategorySuggestionListResponse,
  ids: string[]
): CategorySuggestionListResponse {
  const removed = new Set(ids)
  const items = data.items.filter((item) => !removed.has(item.id))
  const summary = {
    ...data.summary,
    total: Math.max(0, data.summary.total - removed.size),
    pending: Math.max(0, data.summary.pending - removed.size),
  }
  return { ...data, items, summary }
}

export function CategorySuggestions() {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<CategorySuggestionStatus | 'all'>(
    'pending'
  )
  const [actingId, setActingId] = useState('')

  const query = useQuery({
    queryKey: ['category-suggestions', status],
    queryFn: () => fetchCategorySuggestions(status),
  })

  const generate = useMutation({
    mutationFn: () => generateCategorySuggestions({ limit: 200 }),
    onSuccess: (result) => {
      toast.success(generateSummary(result), {
        description: `来源：${sourceLabel(result.source)}`,
      })
      void queryClient.invalidateQueries({ queryKey: ['category-suggestions'] })
    },
    onError: () => toast.error('生成失败，请稍后重试'),
  })

  const accept = useMutation({
    mutationFn: (ids: string[]) => acceptCategorySuggestions(ids),
    onSuccess: (result, ids) => {
      toast.success(`已采纳 ${result.accepted} 条建议`, {
        description:
          result.categoriesCreated > 0
            ? `同时新建 ${result.categoriesCreated} 个分类`
            : undefined,
      })
      queryClient.setQueryData<CategorySuggestionListResponse>(
        ['category-suggestions', status],
        (prev) => (prev ? removeItems(prev, ids) : prev)
      )
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      void queryClient.invalidateQueries({ queryKey: ['repos'] })
    },
    onError: () => toast.error('采纳失败，请稍后重试'),
    onSettled: () => setActingId(''),
  })

  const dismiss = useMutation({
    mutationFn: (ids: string[]) => dismissCategorySuggestions(ids),
    onSuccess: (_result, ids) => {
      toast.success(`已忽略 ${ids.length} 条建议`)
      queryClient.setQueryData<CategorySuggestionListResponse>(
        ['category-suggestions', status],
        (prev) => (prev ? removeItems(prev, ids) : prev)
      )
    },
    onError: () => toast.error('忽略失败，请稍后重试'),
    onSettled: () => setActingId(''),
  })

  function handleAccept(item: CategorySuggestionItem) {
    setActingId(item.id)
    accept.mutate([item.id])
  }

  function handleDismiss(item: CategorySuggestionItem) {
    setActingId(item.id)
    dismiss.mutate([item.id])
  }

  const data = query.data
  const groups = data ? groupByRepo(data.items) : []
  const busy = generate.isPending || accept.isPending || dismiss.isPending

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
        <div className='mb-6 space-y-1'>
          <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
            <Tags className='size-6 text-violet-500' />
            分类建议
          </h2>
          <p className='text-sm text-muted-foreground'>
            按业务线自动分析仓库的名称、标签、简介与 README
            摘要，给出可解释的分类建议。采纳后写回仓库分类，忽略的建议不会被重复生成。
          </p>
        </div>

        {data && (
          <div className='mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4'>
            <Card>
              <CardHeader className='pb-2'>
                <CardDescription>待确认</CardDescription>
                <CardTitle className='text-2xl'>
                  {data.summary.pending}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className='pb-2'>
                <CardDescription>已采纳</CardDescription>
                <CardTitle className='text-2xl'>
                  {data.summary.accepted}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className='pb-2'>
                <CardDescription>覆盖仓库</CardDescription>
                <CardTitle className='text-2xl'>{data.summary.repos}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className='pb-2'>
                <CardDescription>平均置信度</CardDescription>
                <CardTitle className='text-2xl'>
                  {formatScore(data.summary.avgScore)}
                </CardTitle>
              </CardHeader>
            </Card>
          </div>
        )}

        <Card className='mb-6'>
          <CardContent className='space-y-3 pt-6'>
            <div className='flex flex-wrap items-center gap-2'>
              {STATUS_TABS.map((item) => (
                <Button
                  key={item}
                  type='button'
                  size='sm'
                  variant={status === item ? 'default' : 'outline'}
                  onClick={() => setStatus(item)}
                >
                  {statusLabel(item)}
                  {item === 'pending' && data
                    ? ` (${data.summary.pending})`
                    : ''}
                </Button>
              ))}
              <Button
                type='button'
                className='ms-auto'
                onClick={() => generate.mutate()}
                disabled={busy}
              >
                {generate.isPending ? (
                  <Loader2 className='me-1 size-4 animate-spin' />
                ) : (
                  <Sparkles className='me-1 size-4' />
                )}
                生成建议
              </Button>
            </div>
            <p className='text-xs text-muted-foreground'>
              规则引擎按「名称 &gt; 标签 / 简介 &gt;
              摘要」加权，语言仅作弱信号；置信度低于 55% 的命中不会入库。
            </p>
            {data && (
              <p className='text-xs text-muted-foreground'>
                {summaryText(data.summary)}
              </p>
            )}
          </CardContent>
        </Card>

        {query.isLoading && (
          <div className='flex items-center gap-2 py-10 text-sm text-muted-foreground'>
            <Loader2 className='size-4 animate-spin' />
            正在加载分类建议…
          </div>
        )}

        {query.isError && (
          <Card className='border-destructive/40'>
            <CardContent className='py-6 text-sm text-destructive'>
              加载失败，请稍后重试。
              <Button
                type='button'
                size='sm'
                variant='outline'
                className='ms-3'
                onClick={() => void query.refetch()}
              >
                <RefreshCw className='me-1 size-3' />
                重试
              </Button>
            </CardContent>
          </Card>
        )}

        {!query.isLoading && data && groups.length === 0 && (
          <Card>
            <CardContent className='flex flex-col items-center gap-2 py-12 text-center'>
              <Tags className='size-8 text-muted-foreground' />
              <p className='text-sm text-muted-foreground'>
                当前筛选下没有建议。点击「生成建议」扫描你的仓库。
              </p>
            </CardContent>
          </Card>
        )}

        <div className='space-y-4'>
          {groups.map((group) => (
            <Card key={group.repoId}>
              <CardHeader className='pb-3'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <CardTitle className='flex min-w-0 items-center gap-2 text-base'>
                    <a
                      href={group.repoUrl}
                      target='_blank'
                      rel='noreferrer'
                      className='truncate hover:underline'
                    >
                      {group.repoName}
                    </a>
                    <ExternalLink className='size-3.5 shrink-0 text-muted-foreground' />
                  </CardTitle>
                  <Badge variant='outline'>{group.items.length} 条建议</Badge>
                </div>
                {group.items[0]?.currentCategory && (
                  <CardDescription>
                    当前分类：{group.items[0].currentCategory}
                  </CardDescription>
                )}
              </CardHeader>
              <CardContent className='space-y-3'>
                {group.items.map((item) => {
                  const tier = scoreTier(item.score)
                  return (
                    <div
                      key={item.id}
                      className='rounded-lg border p-3 transition-colors hover:bg-muted/40'
                    >
                      <div className='flex flex-wrap items-start justify-between gap-3'>
                        <div className='min-w-0 space-y-1'>
                          <div className='flex flex-wrap items-center gap-2'>
                            <span className='font-medium'>
                              {item.categoryName}
                            </span>
                            <Badge variant='secondary'>
                              {businessLineLabel(item.businessLine)}
                            </Badge>
                            <span
                              className={`rounded-md border px-1.5 py-0.5 text-xs font-medium ${tierClass(tier)}`}
                            >
                              {formatScore(item.score)}
                            </span>
                            {item.status !== 'pending' && (
                              <Badge variant='outline'>
                                {statusLabel(item.status)}
                              </Badge>
                            )}
                          </div>
                          {item.reason && (
                            <p className='text-sm text-muted-foreground'>
                              {item.reason}
                            </p>
                          )}
                          {item.evidence && (
                            <p className='line-clamp-2 text-xs text-muted-foreground'>
                              依据：{item.evidence}
                            </p>
                          )}
                        </div>
                        {item.status === 'pending' && (
                          <div className='flex shrink-0 items-center gap-2'>
                            <Button
                              type='button'
                              size='sm'
                              disabled={busy}
                              onClick={() => handleAccept(item)}
                            >
                              {actingId === item.id && accept.isPending ? (
                                <Loader2 className='me-1 size-3 animate-spin' />
                              ) : (
                                <Check className='me-1 size-3' />
                              )}
                              采纳
                            </Button>
                            <Button
                              type='button'
                              size='sm'
                              variant='outline'
                              disabled={busy}
                              onClick={() => handleDismiss(item)}
                            >
                              {actingId === item.id && dismiss.isPending ? (
                                <Loader2 className='me-1 size-3 animate-spin' />
                              ) : (
                                <X className='me-1 size-3' />
                              )}
                              忽略
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          ))}
        </div>
      </Main>
    </>
  )
}
