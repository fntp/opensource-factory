import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowLeft,
  Bookmark,
  BookmarkCheck,
  ExternalLink,
  Flame,
  RefreshCw,
  Scale,
  Sparkles,
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
import { LicenseBadge } from '@/features/licenses/license-badge'
import {
  formatLicenseCheckedAt,
  licenseSourceLabel,
} from '@/features/licenses/utils'
import {
  favoriteTrending,
  fetchSimilarRepos,
  fetchTrendingDetail,
  unfavoriteTrending,
  type SimilarRepoItem,
  type TrendingRepoDetail,
} from './api'
import { buildMetaItems, repoRouteParams, summarySourceLabel } from './detail'

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

  const similar = useQuery({
    queryKey: ['trending', owner, name, 'similar'],
    queryFn: () => fetchSimilarRepos('trending', `${owner}/${name}`, 6),
    retry: 1,
    staleTime: 5 * 60 * 1000,
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
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <CardTitle className='flex items-center gap-2'>
                    <Scale className='size-4 text-primary' />
                    License 合规提示
                  </CardTitle>
                  <LicenseBadge license={data.license} />
                </div>
                <CardDescription>
                  {data.license
                    ? `${data.license.categoryLabel} · ${data.license.riskLabel} · 来源：${licenseSourceLabel(data.license.source)} · 识别于 ${formatLicenseCheckedAt(data.license.checkedAt)}`
                    : '尚未识别 License，建议运行 License 补全任务后再评估使用方式。'}
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-4'>
                {data.license ? (
                  <>
                    <p className='text-sm leading-6'>{data.license.summary}</p>
                    <div className='grid gap-4 sm:grid-cols-2'>
                      <div>
                        <h4 className='mb-2 text-sm font-medium'>需要履行的义务</h4>
                        <ul className='space-y-1 text-sm text-muted-foreground'>
                          {data.license.obligations.length ? (
                            data.license.obligations.map((item) => (
                              <li key={item}>· {item}</li>
                            ))
                          ) : (
                            <li>无强制义务</li>
                          )}
                        </ul>
                      </div>
                      <div>
                        <h4 className='mb-2 flex items-center gap-1 text-sm font-medium'>
                          <AlertTriangle className='size-3.5 text-amber-500' />
                          风险提醒
                        </h4>
                        <ul className='space-y-1 text-sm text-muted-foreground'>
                          {data.license.warnings.length ? (
                            data.license.warnings.map((item) => (
                              <li key={item}>· {item}</li>
                            ))
                          ) : (
                            <li>暂无额外提醒</li>
                          )}
                        </ul>
                      </div>
                    </div>
                    <p className='border-t pt-3 text-xs text-muted-foreground'>
                      合规提示仅为工程辅助信息，不构成法律意见；商用或 SaaS
                      场景建议进行法务复核。
                    </p>
                  </>
                ) : (
                  <p className='text-sm leading-6 text-muted-foreground'>
                    无许可证不等于可以自由使用；复制、修改、分发或商用前需联系作者获取明确授权。
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

            <Card>
              <CardHeader>
                <CardTitle className='flex items-center gap-2'>
                  <Sparkles className='size-4 text-primary' />
                  看了又看
                </CardTitle>
                <CardDescription>
                  基于项目向量近邻推荐；向量不可用时回退同语言 / 技术栈匹配。
                </CardDescription>
              </CardHeader>
              <CardContent>
                {similar.isLoading && (
                  <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
                    {Array.from({ length: 3 }).map((_, index) => (
                      <Skeleton key={index} className='h-28 w-full' />
                    ))}
                  </div>
                )}
                {similar.isError && (
                  <p className='text-sm text-muted-foreground'>
                    相似推荐加载失败，请稍后重试。
                  </p>
                )}
                {!similar.isLoading &&
                  !similar.isError &&
                  (similar.data?.length ?? 0) === 0 && (
                    <p className='text-sm text-muted-foreground'>
                      暂无相似项目，向量索引可能尚未覆盖该项目。
                    </p>
                  )}
                {similar.data && similar.data.length > 0 && (
                  <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
                    {similar.data.map((item) => (
                      <SimilarRepoCard
                        key={`${item.source}:${item.id}`}
                        item={item}
                      />
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

function SimilarRepoCard({ item }: { item: SimilarRepoItem }) {
  const params = repoRouteParams(item.fullName)
  const body = (
    <div className='flex h-full flex-col gap-2 rounded-lg border p-3 transition-colors hover:bg-accent/50'>
      <div className='flex items-start justify-between gap-2'>
        <span className='text-sm font-medium break-all'>{item.fullName}</span>
        <Badge variant='outline'>{Math.round(item.score * 100)}%</Badge>
      </div>
      <p className='line-clamp-2 text-xs text-muted-foreground'>
        {item.description || '暂无简介'}
      </p>
      <p className='mt-auto text-xs text-muted-foreground'>{item.reason}</p>
      <div className='flex items-center gap-2 text-xs text-muted-foreground'>
        <span>{item.language || '未知语言'}</span>
        <span>·</span>
        <span>{item.stars.toLocaleString('zh-CN')} Star</span>
      </div>
    </div>
  )

  if (params) {
    return (
      <Link
        to='/trending/$owner/$name'
        params={params}
        className='block h-full'
      >
        {body}
      </Link>
    )
  }
  return (
    <a href={item.url} target='_blank' rel='noreferrer' className='block h-full'>
      {body}
    </a>
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
