import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Flame, FolderGit2, FolderTree, Sparkles } from 'lucide-react'
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
import { fetchDashboardStats, MOCK_DASHBOARD_STATS } from './api'
import { Overview } from './components/overview'
import { RecentTrending } from './components/recent-trending'

export function Dashboard() {
  const { data } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: fetchDashboardStats,
  })
  const stats = data ?? MOCK_DASHBOARD_STATS

  return (
    <>
      {/* ===== 顶部栏 ===== */}
      <Header>
        <h1 className='me-auto text-lg font-semibold'>开源项目工厂</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      {/* ===== 主内容 ===== */}
      <Main>
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>仪表盘</h2>
            <p className='text-sm text-muted-foreground'>
              你的开源资产总览与今日动态。
            </p>
          </div>
          <Button asChild>
            <Link to='/repos'>管理我的仓库</Link>
          </Button>
        </div>

        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>已收录仓库</CardTitle>
              <FolderGit2 className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>{stats.totalRepos}</div>
              <p className='text-xs text-muted-foreground'>
                已同步的 GitHub 仓库
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>今日热榜</CardTitle>
              <Flame className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>{stats.trendingToday}</div>
              <p className='text-xs text-muted-foreground'>
                今日抓取的热门项目
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>待读推荐</CardTitle>
              <Sparkles className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>
                {stats.pendingRecommendations}
              </div>
              <p className='text-xs text-muted-foreground'>
                等待你查看的智能推荐
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
              <CardTitle className='text-sm font-medium'>分类数量</CardTitle>
              <FolderTree className='h-4 w-4 text-muted-foreground' />
            </CardHeader>
            <CardContent>
              <div className='text-2xl font-bold'>{stats.categoryCount}</div>
              <p className='text-xs text-muted-foreground'>
                资产分类与标签体系
              </p>
            </CardContent>
          </Card>
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-7'>
          <Card className='col-span-1 lg:col-span-4'>
            <CardHeader>
              <CardTitle>Star 增长趋势</CardTitle>
              <CardDescription>近 12 个月全部仓库累计 Star 数</CardDescription>
            </CardHeader>
            <CardContent className='ps-2'>
              <Overview />
            </CardContent>
          </Card>
          <Card className='col-span-1 lg:col-span-3'>
            <CardHeader>
              <CardTitle>今日热榜</CardTitle>
              <CardDescription>来自 GitHub Trending 的最新项目。</CardDescription>
            </CardHeader>
            <CardContent>
              <RecentTrending />
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}
