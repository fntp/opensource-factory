import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronRight, Flame, RefreshCw } from 'lucide-react'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { LicenseBadge } from '@/features/licenses/license-badge'
import {
  fetchTrending,
  fetchTrendingDates,
  fetchTrendingLanguages,
} from './api'
import { formatSnapshotDate, trendBadge, trendToneClass } from './trend'

const ALL_LANGUAGES = 'all'

export function Trending() {
  const [date, setDate] = useState('')
  const [language, setLanguage] = useState('')

  const datesQuery = useQuery({
    queryKey: ['trending-dates'],
    queryFn: fetchTrendingDates,
  })
  const dates = datesQuery.data?.dates ?? []
  const selectedDate = date || datesQuery.data?.latest || ''

  const languagesQuery = useQuery({
    queryKey: ['trending-languages', selectedDate],
    queryFn: () => fetchTrendingLanguages(selectedDate || undefined),
    enabled: Boolean(selectedDate),
  })
  const languages = languagesQuery.data?.languages ?? []

  const trendingQuery = useQuery({
    queryKey: ['trending', selectedDate, language],
    queryFn: () =>
      fetchTrending({
        date: selectedDate || undefined,
        language: language || undefined,
        limit: 100,
      }),
  })
  const items = trendingQuery.data ?? []

  const handleDateChange = (value: string) => {
    setDate(value)
    setLanguage('')
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
        <div className='mb-4 flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Flame className='size-6 text-orange-500' />
              每日热榜
            </h2>
            <p className='text-sm text-muted-foreground'>
              {formatSnapshotDate(selectedDate)} · 来自 GitHub Trending
              的热门项目
            </p>
          </div>

          <div className='flex flex-wrap items-center gap-2'>
            <Select value={selectedDate} onValueChange={handleDateChange}>
              <SelectTrigger className='w-[150px]' aria-label='选择快照日期'>
                <SelectValue placeholder='选择日期' />
              </SelectTrigger>
              <SelectContent>
                {dates.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={language || ALL_LANGUAGES}
              onValueChange={(value) =>
                setLanguage(value === ALL_LANGUAGES ? '' : value)
              }
            >
              <SelectTrigger className='w-[150px]' aria-label='选择语言'>
                <SelectValue placeholder='全部语言' />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_LANGUAGES}>全部语言</SelectItem>
                {languages.map((item) => (
                  <SelectItem key={item.language} value={item.language}>
                    {item.language}（{item.count}）
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button
              variant='outline'
              size='icon'
              aria-label='刷新热榜'
              onClick={() => {
                void datesQuery.refetch()
                void languagesQuery.refetch()
                void trendingQuery.refetch()
              }}
            >
              <RefreshCw
                className={
                  trendingQuery.isFetching ? 'animate-spin' : undefined
                }
              />
            </Button>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>榜单</CardTitle>
            <CardDescription>
              {trendingQuery.isLoading
                ? '正在加载热榜…'
                : `共 ${items.length} 个项目${language ? ` · ${language}` : ''}，按今日新增 Star 排名。`}
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-1'>
            {trendingQuery.isLoading ? (
              <div className='space-y-4 py-2'>
                {Array.from({ length: 6 }).map((_, index) => (
                  <div key={index} className='flex items-center gap-4'>
                    <Skeleton className='size-8 rounded-full' />
                    <div className='flex-1 space-y-2'>
                      <Skeleton className='h-4 w-48' />
                      <Skeleton className='h-3 w-full max-w-md' />
                    </div>
                    <Skeleton className='h-6 w-16' />
                  </div>
                ))}
              </div>
            ) : trendingQuery.isError ? (
              <div className='flex flex-col items-center gap-3 py-12 text-sm text-muted-foreground'>
                <p>热榜加载失败，请稍后重试。</p>
                <Button
                  variant='outline'
                  onClick={() => trendingQuery.refetch()}
                >
                  重新加载
                </Button>
              </div>
            ) : items.length === 0 ? (
              <div className='py-12 text-center text-sm text-muted-foreground'>
                该日期{language ? ` / ${language}` : ''}
                暂无热榜数据，换一个日期或语言试试。
              </div>
            ) : (
              items.map((item) => {
                const badge = trendBadge(item.trend, item.rankChange)
                return (
                  <div
                    key={`${item.snapshotDate}-${item.id}`}
                    className='flex items-start gap-3 border-b py-3 last:border-b-0 sm:items-center sm:gap-4'
                  >
                    <div
                      className={`flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-medium ${
                        item.rank <= 3
                          ? 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300'
                          : ''
                      }`}
                    >
                      {item.rank}
                    </div>
                    <div className='min-w-0 flex-1'>
                      <div className='flex flex-wrap items-center gap-2'>
                        <a
                          href={item.url}
                          target='_blank'
                          rel='noreferrer'
                          className='text-sm font-medium hover:underline'
                        >
                          {item.owner}/{item.name}
                        </a>
                        <Badge
                          variant='outline'
                          className={trendToneClass(badge.tone)}
                        >
                          {badge.label}
                        </Badge>
                      </div>
                      <p className='line-clamp-2 text-sm text-muted-foreground sm:truncate'>
                        {item.description}
                      </p>
                    </div>
                    <div className='hidden sm:block'>
                      <LicenseBadge license={item.license} />
                    </div>
                    <Badge variant='outline' className='hidden md:inline-flex'>
                      {item.language || '未知'}
                    </Badge>
                    <div className='w-16 shrink-0 text-end sm:w-20'>
                      <div className='text-sm font-medium'>
                        +{item.starsToday}
                      </div>
                      <div className='text-xs text-muted-foreground'>
                        今日 Star
                      </div>
                    </div>
                    <div className='hidden w-20 shrink-0 text-end sm:block'>
                      <div className='text-sm font-medium'>
                        {item.stars.toLocaleString()}
                      </div>
                      <div className='text-xs text-muted-foreground'>
                        总 Star
                      </div>
                    </div>
                    <Button
                      variant='ghost'
                      size='sm'
                      className='shrink-0 px-2 sm:px-3'
                      asChild
                    >
                      <Link
                        to='/trending/$owner/$name'
                        params={{ owner: item.owner, name: item.name }}
                      >
                        <span className='hidden sm:inline'>详情</span>
                        <ChevronRight />
                      </Link>
                    </Button>
                  </div>
                )
              })
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
