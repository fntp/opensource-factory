import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronRight, Flame } from 'lucide-react'
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
import { fetchTrending, MOCK_TRENDING_REPOS } from './api'

export function Trending() {
  const { data } = useQuery({ queryKey: ['trending'], queryFn: fetchTrending })
  const items = data ?? MOCK_TRENDING_REPOS
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
              共 {items.length} 个项目，按今日新增 Star 排序。
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-6'>
            {items.map((item, index) => (
              <div key={item.id} className='flex items-center gap-4'>
                <div className='flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-medium'>
                  {index + 1}
                </div>
                <div className='min-w-0 flex-1'>
                  <Link
                    to='/trending/$owner/$name'
                    params={{ owner: item.owner, name: item.name }}
                    className='text-sm font-medium hover:underline'
                  >
                    {item.owner}/{item.name}
                  </Link>
                  <p className='truncate text-sm text-muted-foreground'>
                    {item.description}
                  </p>
                </div>
                <Badge variant='outline'>{item.language}</Badge>
                <div className='w-20 shrink-0 text-end'>
                  <div className='text-sm font-medium'>+{item.starsToday}</div>
                  <div className='text-xs text-muted-foreground'>今日 Star</div>
                </div>
                <Button variant='ghost' size='sm' asChild>
                  <Link
                    to='/trending/$owner/$name'
                    params={{ owner: item.owner, name: item.name }}
                  >
                    详情
                    <ChevronRight />
                  </Link>
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
