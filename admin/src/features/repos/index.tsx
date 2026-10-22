import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
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
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { LicenseBadge } from '@/features/licenses/license-badge'
import { fetchRepos, MOCK_REPOS, refreshRepoHealth } from './api'
import {
  HEALTH_LABELS,
  healthBadgeClass,
  healthForRepo,
  normalizeHealthStatus,
  summarizeRepoHealth,
  type HealthStatus,
} from './health'

const HEALTH_FILTERS: Array<{ value: 'all' | HealthStatus; label: string }> = [
  { value: 'all', label: '全部健康度' },
  ...(Object.entries(HEALTH_LABELS) as Array<[HealthStatus, string]>).map(
    ([value, label]) => ({ value, label })
  ),
]

export function Repos() {
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ['repos'], queryFn: fetchRepos })
  const repos = data ?? MOCK_REPOS
  const [keyword, setKeyword] = useState('')
  const [healthFilter, setHealthFilter] = useState<'all' | HealthStatus>('all')

  const refreshHealth = useMutation({
    mutationFn: refreshRepoHealth,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['repos'] })
      toast.success(
        result.status === 'accepted'
          ? '已提交刷新请求（VPS 未配置，将按计划自动同步）'
          : '已触发项目健康度刷新'
      )
    },
    onError: () => {
      toast.error('刷新失败：演示模式或 VPS 节点暂不可用')
    },
  })

  const healthSummary = useMemo(
    () =>
      summarizeRepoHealth(
        repos.map((repo) => ({ health: healthForRepo(repo) }))
      ),
    [repos]
  )

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    return repos.filter((r) => {
      if (
        healthFilter !== 'all' &&
        normalizeHealthStatus(healthForRepo(r).status) !== healthFilter
      ) {
        return false
      }
      if (!q) return true
      return (
        r.fullName.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        (r.summary ?? '').toLowerCase().includes(q) ||
        r.language.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.tags.some((t) => t.toLowerCase().includes(q))
      )
    })
  }, [repos, keyword, healthFilter])

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
        <div className='mb-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>我的仓库</h2>
            <p className='text-sm text-muted-foreground'>
              已同步的 GitHub 仓库，支持按分类、标签与关键词快速查找。
            </p>
          </div>
          <div className='flex flex-wrap items-center gap-2'>
            <Button
              variant='outline'
              onClick={() => refreshHealth.mutate()}
              disabled={refreshHealth.isPending}
            >
              <RefreshCw
                className={refreshHealth.isPending ? 'animate-spin' : undefined}
              />
              刷新健康度
            </Button>
            <Button
              onClick={() => toast.success('已触发 GitHub 仓库同步（演示）')}
            >
              <RefreshCw />
              同步仓库
            </Button>
          </div>
        </div>

        <div className='mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>平均健康分</CardDescription>
              <CardTitle className='text-2xl'>
                {healthSummary.averageScore}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>活跃仓库</CardDescription>
              <CardTitle className='text-2xl text-emerald-600 dark:text-emerald-400'>
                {healthSummary.active}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>需关注</CardDescription>
              <CardTitle className='text-2xl text-amber-600 dark:text-amber-400'>
                {healthSummary.attention}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>停滞 / 已归档</CardDescription>
              <CardTitle className='text-2xl text-rose-600 dark:text-rose-400'>
                {healthSummary.stale + healthSummary.archived}
              </CardTitle>
            </CardHeader>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>仓库列表</CardTitle>
            <CardDescription>
              共 {filtered.length} 个仓库
              {healthSummary.unknown > 0
                ? ` · ${healthSummary.unknown} 个健康度待刷新`
                : ''}
            </CardDescription>
            <div className='flex flex-wrap items-center gap-2'>
              <Input
                placeholder='搜索仓库、语言、分类或标签…'
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className='max-w-sm'
              />
              <Select
                value={healthFilter}
                onValueChange={(value) =>
                  setHealthFilter(value as 'all' | HealthStatus)
                }
              >
                <SelectTrigger className='w-[150px]' aria-label='按健康度筛选'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HEALTH_FILTERS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <div className='hidden md:block'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>仓库</TableHead>
                    <TableHead>健康度</TableHead>
                    <TableHead>分类</TableHead>
                    <TableHead>License</TableHead>
                    <TableHead>标签</TableHead>
                    <TableHead className='text-end'>Stars</TableHead>
                    <TableHead className='text-end'>最近更新</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((repo) => {
                    const health = healthForRepo(repo)
                    return (
                      <TableRow key={repo.id}>
                        <TableCell>
                          <a
                            href={repo.url}
                            target='_blank'
                            rel='noreferrer'
                            className='font-medium hover:underline'
                          >
                            {repo.fullName}
                          </a>
                          <div className='max-w-100 truncate text-sm text-muted-foreground'>
                            {repo.description}
                          </div>
                          {repo.summary && (
                            <div className='max-w-100 truncate text-xs text-muted-foreground/70'>
                              摘要：{repo.summary}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant='outline'
                            className={healthBadgeClass(health.status)}
                            title={health.reasons.join('；')}
                          >
                            {health.label} · {health.score}
                          </Badge>
                          <div className='mt-1 text-xs text-muted-foreground'>
                            {health.daysSincePush !== null
                              ? `${health.daysSincePush} 天前提交`
                              : '暂无提交时间'}
                            {health.openIssues > 0
                              ? ` · ${health.openIssues} open issues`
                              : ''}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant='secondary'>{repo.category}</Badge>
                        </TableCell>
                        <TableCell>
                          <LicenseBadge license={repo.license} />
                        </TableCell>
                        <TableCell>
                          <div className='flex flex-wrap gap-1'>
                            {repo.tags.map((tag) => (
                              <Badge key={tag} variant='outline'>
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        </TableCell>
                        <TableCell className='text-end'>
                          {repo.stars.toLocaleString()}
                        </TableCell>
                        <TableCell className='text-end text-muted-foreground'>
                          {repo.updatedAt}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                  {filtered.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={7}
                        className='h-24 text-center text-muted-foreground'
                      >
                        没有匹配的仓库。
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <div className='space-y-3 md:hidden'>
              {filtered.map((repo) => {
                const health = healthForRepo(repo)
                return (
                  <article
                    key={repo.id}
                    className='rounded-lg border bg-card p-3'
                  >
                    <div className='flex items-start justify-between gap-2'>
                      <a
                        href={repo.url}
                        target='_blank'
                        rel='noreferrer'
                        className='min-w-0 text-sm font-medium break-all hover:underline'
                      >
                        {repo.fullName}
                      </a>
                      <span className='shrink-0 text-xs text-muted-foreground'>
                        {repo.stars.toLocaleString()} stars
                      </span>
                    </div>
                    <p className='mt-1 line-clamp-2 text-sm text-muted-foreground'>
                      {repo.description}
                    </p>
                    <div className='mt-2 flex flex-wrap items-center gap-1.5'>
                      <Badge variant='secondary'>{repo.category}</Badge>
                      <Badge
                        variant='outline'
                        className={healthBadgeClass(health.status)}
                        title={health.reasons.join('；')}
                      >
                        {health.label} · {health.score}
                      </Badge>
                      <LicenseBadge license={repo.license} />
                    </div>
                    {repo.tags.length > 0 && (
                      <div className='mt-2 flex flex-wrap gap-1'>
                        {repo.tags.slice(0, 4).map((tag) => (
                          <Badge key={tag} variant='outline'>
                            {tag}
                          </Badge>
                        ))}
                        {repo.tags.length > 4 && (
                          <span className='self-center text-xs text-muted-foreground'>
                            +{repo.tags.length - 4}
                          </span>
                        )}
                      </div>
                    )}
                    <div className='mt-2 flex items-center justify-between text-xs text-muted-foreground'>
                      <span>{repo.updatedAt}</span>
                      <span>
                        {health.daysSincePush !== null
                          ? `${health.daysSincePush} 天前提交`
                          : '暂无提交时间'}
                      </span>
                    </div>
                  </article>
                )
              })}
              {filtered.length === 0 && (
                <div className='rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground'>
                  没有匹配的仓库。
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
