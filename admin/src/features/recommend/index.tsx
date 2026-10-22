import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
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
import { EmptyState, ErrorState, LoadingState } from '@/components/data-state'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { fetchRecommendations } from './api'

function scorePercent(score: number): number {
  const percent = score <= 1 ? score * 100 : score
  return Math.max(0, Math.min(100, Math.round(percent)))
}

export function Recommend() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['recommendations'],
    queryFn: fetchRecommendations,
  })
  const [dismissed, setDismissed] = useState<string[]>([])
  const items = (data ?? []).filter((item) => !dismissed.includes(item.id))

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
              <Sparkles className='size-6 text-violet-500' />
              智能推荐
            </h2>
            <p className='text-sm text-muted-foreground'>
              基于你的收藏与阅读偏好，通过语义匹配为你推荐可能感兴趣的开源项目。
            </p>
          </div>
        </div>

        {isPending ? (
          <Card>
            <CardContent className='pt-6'>
              <LoadingState label='正在加载推荐…' rows={4} />
            </CardContent>
          </Card>
        ) : isError ? (
          <Card>
            <CardContent className='pt-6'>
              <ErrorState
                error={error}
                title='推荐加载失败'
                onRetry={() => void refetch()}
              />
            </CardContent>
          </Card>
        ) : items.length === 0 ? (
          <Card>
            <CardContent className='pt-6'>
              <EmptyState
                icon={Sparkles}
                title='暂时没有新的推荐'
                description='每日推荐任务运行后，这里会展示与你收藏相关的项目。'
              />
            </CardContent>
          </Card>
        ) : (
          <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
            {items.map((item) => (
              <Card key={item.id} className='flex flex-col'>
                <CardHeader>
                  <div className='flex items-start justify-between gap-2'>
                    <div>
                      <CardTitle className='text-base'>
                        {item.url ? (
                          <a
                            href={item.url}
                            target='_blank'
                            rel='noreferrer'
                            className='hover:underline'
                          >
                            {item.owner ?? '未知'}/{item.name ?? '未命名'}
                          </a>
                        ) : (
                          `${item.owner ?? '未知'}/${item.name ?? '未命名'}`
                        )}
                      </CardTitle>
                      <CardDescription className='mt-1'>
                        {item.description ?? '暂无描述'}
                      </CardDescription>
                    </div>
                    <Badge className='shrink-0'>
                      匹配度 {scorePercent(item.score)}%
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className='flex flex-1 flex-col justify-between gap-4'>
                  <p className='text-sm text-muted-foreground'>
                    {item.reason ?? '暂无推荐理由'}
                  </p>
                  <div className='space-y-3'>
                    <div className='flex flex-wrap items-center gap-1'>
                      {item.basedOn.map((tag) => (
                        <Badge key={tag} variant='outline'>
                          {tag}
                        </Badge>
                      ))}
                      <span className='ms-auto text-xs text-muted-foreground'>
                        {item.language ?? '未知语言'} ·{' '}
                        {item.stars.toLocaleString()} stars
                      </span>
                    </div>
                    <div className='flex gap-2'>
                      {item.url ? (
                        <Button size='sm' asChild>
                          <a href={item.url} target='_blank' rel='noreferrer'>
                            查看仓库
                          </a>
                        </Button>
                      ) : null}
                      <Button
                        size='sm'
                        variant='ghost'
                        onClick={() =>
                          setDismissed((prev) => [...prev, item.id])
                        }
                      >
                        忽略
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </Main>
    </>
  )
}
