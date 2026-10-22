import { useQuery } from '@tanstack/react-query'
import { Flame } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { EmptyState, ErrorState, LoadingState } from '@/components/data-state'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { fetchTrending } from './api'

export function Trending() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['trending'],
    queryFn: fetchTrending,
  })
  const items = data ?? []
  const today = new Date().toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
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
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Flame className='size-6 text-orange-500' />
              每日热榜
            </h2>
            <p className='text-sm text-muted-foreground'>
              {today} · 来自 GitHub Trending 的热门项目
            </p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>今日热门</CardTitle>
            <CardDescription>
              {isPending || isError
                ? '按今日新增 Star 排序'
                : `共 ${items.length} 个项目，按今日新增 Star 排序。`}
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-6'>
            {isPending ? (
              <LoadingState label='正在加载热榜…' rows={6} />
            ) : isError ? (
              <ErrorState
                error={error}
                title='热榜加载失败'
                onRetry={() => void refetch()}
              />
            ) : items.length === 0 ? (
              <EmptyState
                icon={Flame}
                title='今日暂无热榜数据'
                description='热榜抓取任务运行后，这里会自动展示当天的热门项目。'
              />
            ) : (
              items.map((item, index) => (
                <div key={item.id} className='flex items-center gap-4'>
                  <div className='flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-medium'>
                    {index + 1}
                  </div>
                  <div className='min-w-0 flex-1'>
                    <a
                      href={item.url}
                      target='_blank'
                      rel='noreferrer'
                      className='text-sm font-medium hover:underline'
                    >
                      {item.owner}/{item.name}
                    </a>
                    <p className='truncate text-sm text-muted-foreground'>
                      {item.description ?? '暂无描述'}
                    </p>
                  </div>
                  {item.language ? (
                    <Badge variant='outline'>{item.language}</Badge>
                  ) : null}
                  <div className='w-20 shrink-0 text-end'>
                    <div className='text-sm font-medium'>
                      +{item.starsToday}
                    </div>
                    <div className='text-xs text-muted-foreground'>
                      今日 Star
                    </div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
