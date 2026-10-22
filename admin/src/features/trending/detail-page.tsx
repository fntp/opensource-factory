import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import {
  ArrowLeft,
  Bookmark,
  BookmarkCheck,
  ExternalLink,
  Flame,
  RefreshCw,
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
import { Skeleton } from '@/components/ui/skeleton'
import { ApiHttpError } from '@/lib/api'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  favoriteTrending,
  fetchTrendingDetail,
  unfavoriteTrending,
  type TrendingRepoDetail,
} from './api'
import { buildMetaItems, summarySourceLabel } from './detail'

interface TrendingDetailProps {
  owner: string
  name: string
}

function favoriteErrorMessage(error: unknown): string {
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return '登录后才能收藏，请先登录。'
    if (error.status === 409) return '该仓库已被其他账号收藏，无法重复收录。'
    if (error.status === 404) return '热榜中已找不到该项目。'
  }
  return '操作失败，请稍后重试。'
}

export function TrendingDetail({ owner, name }: TrendingDetailProps) {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['trending', owner, name],
    queryFn: () => fetchTrendingDetail(owner, name),
    retry: 1,
  })

  const favorite = useMutation({
    mutationFn: (detail: TrendingRepoDetail) =>
      detail.isFavorited
        ? unfavoriteTrending(owner, name)
        : favoriteTrending(owner, name),
    onSuccess: (result) => {
      queryClient.setQueryData<TrendingRepoDetail>(
        ['trending', owner, name],
        (old) => (old ? { ...old, isFavorited: result.favorited } : old)
      )
      queryClient.invalidateQueries({ queryKey: ['trending'] })
      queryClient.invalidateQueries({ queryKey: ['repos'] })
      toast.success(result.favorited ? '已收藏到我的仓库' : '已取消收藏')
    },
    onError: (error) => toast.error(favoriteErrorMessage(error)),
  })

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
        <div className='mb-4 flex items-center justify-between gap-3'>
          <Button variant='ghost' size='sm' asChild>
            <Link to='/trending'>
              <ArrowLeft />
              返回热榜
            </Link>
          </Button>
          {data && (
            <Button
              variant={data.isFavorited ? 'secondary' : 'default'}
              disabled={favorite.isPending}
              onClick={() => favorite.mutate(data)}
            >
              {data.isFavorited ? <BookmarkCheck /> : <Bookmark />}
              {data.isFavorited ? '已收藏（点击取消）' : '一键收藏'}
            </Button>
          )}
        </div>

        {isLoading && <DetailSkeleton />}

        {isError && (
          <Card>
            <CardContent className='flex h-48 flex-col items-center justify-center gap-3 text-center'>
              <p className='text-muted-foreground'>
                详情加载失败，可能是项目已下榜或网络异常。
              </p>
              <Button variant='outline' onClick={() => refetch()}>
                <RefreshCw />
                重新加载
              </Button>
            </CardContent>
          </Card>
        )}

        {data && (
          <div className='space-y-6'>
            <div>
              <div className='flex flex-wrap items-center gap-2'>
                <Flame className='size-6 text-orange-500' />
                <h2 className='text-2xl font-bold tracking-tight'>
                  {data.owner}/{data.name}
                </h2>
                <Badge variant='outline'>{data.language || '未知语言'}</Badge>
                <Badge variant='secondary'>{data.platform}</Badge>
              </div>
              <div className='mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
                <span>今日 +{data.starsToday.toLocaleString('zh-CN')} Star</span>
                <span>·</span>
                <span>共 {data.stars.toLocaleString('zh-CN')} Star</span>
                <span>·</span>
                <a
                  href={data.url}
                  target='_blank'
                  rel='noreferrer'
                  className='inline-flex items-center gap-1 hover:underline'
                >
                  打开 GitHub
                  <ExternalLink className='size-3.5' />
                </a>
              </div>
            </div>

            <Card>
              <CardHeader>
                <div className='flex items-center justify-between gap-2'>
                  <CardTitle>项目摘要</CardTitle>
                  <Badge variant='outline'>
                    {summarySourceLabel(data.summarySource)}
                  </Badge>
                </div>
                <CardDescription>
                  摘要优先使用本地模型生成；模型不可用时回退项目描述或技术栈提示。
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-4'>
                <p className='whitespace-pre-wrap text-sm leading-6'>
                  {data.summary || '暂无摘要，等待摘要任务生成。'}
                </p>
                {data.summarySource === 'readme' && data.description && (
                  <p className='border-t pt-3 text-sm text-muted-foreground'>
                    原始简介：{data.description}
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>元信息</CardTitle>
                <CardDescription>
                  抓取日期 {data.crawledAt || '—'} · 数据来自 GitHub Trending
                </CardDescription>
              </CardHeader>
              <CardContent>
                <dl className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
                  {buildMetaItems(data).map((item) => (
                    <div key={item.label} className='rounded-lg border p-3'>
                      <dt className='text-xs text-muted-foreground'>{item.label}</dt>
                      <dd className='mt-1 text-sm font-medium break-words'>
                        {item.value}
                      </dd>
                    </div>
                  ))}
                </dl>
                {data.techStack.length > 0 && (
                  <div className='mt-4 flex flex-wrap gap-1'>
                    {data.techStack.map((tech) => (
                      <Badge key={tech} variant='secondary'>
                        {tech}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <div className='flex flex-wrap gap-2'>
              <Button
                variant={data.isFavorited ? 'secondary' : 'default'}
                disabled={favorite.isPending}
                onClick={() => favorite.mutate(data)}
              >
                {data.isFavorited ? <BookmarkCheck /> : <Bookmark />}
                {data.isFavorited ? '取消收藏' : '一键收藏'}
              </Button>
              <Button variant='outline' asChild>
                <a href={data.url} target='_blank' rel='noreferrer'>
                  <ExternalLink />
                  查看仓库
                </a>
              </Button>
            </div>
          </div>
        )}
      </Main>
    </>
  )
}

export function TrendingDetailRoute() {
  const { owner, name } = useParams({
    from: '/_authenticated/trending/$owner/$name',
  })
  return <TrendingDetail owner={owner} name={name} />
}

function DetailSkeleton() {
  return (
    <div className='space-y-6'>
      <div className='space-y-2'>
        <Skeleton className='h-8 w-72' />
        <Skeleton className='h-4 w-96' />
      </div>
      <Skeleton className='h-40 w-full' />
      <Skeleton className='h-48 w-full' />
    </div>
  )
}
