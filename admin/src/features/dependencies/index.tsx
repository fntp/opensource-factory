import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Boxes, RefreshCw } from 'lucide-react'
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
import {
  fetchDependencyAnalysis,
  MOCK_ANALYSIS,
  refreshDependencyAnalysis,
} from './api'
import {
  barWidth,
  ecosystemLabel,
  formatCount,
  formatGeneratedAt,
  formatPercent,
  kindLabel,
  statusLabel,
  statusVariant,
} from './utils'

export function Dependencies() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['dependency-analysis'],
    queryFn: () => fetchDependencyAnalysis(20),
  })
  const analysis = data ?? MOCK_ANALYSIS
  const { summary } = analysis

  const refresh = useMutation({
    mutationFn: refreshDependencyAnalysis,
    onSuccess: (result) => {
      if (result.status === 'unavailable') {
        toast.warning(result.message ?? 'VPS 节点不可达，稍后再试')
        return
      }
      toast.success(
        `扫描完成：${result.ok}/${result.scanned} 个仓库，${formatCount(
          result.dependencies
        )} 条依赖`
      )
      void queryClient.invalidateQueries({ queryKey: ['dependency-analysis'] })
    },
    onError: () => toast.error('刷新失败，请确认 VPS 节点与登录状态'),
  })

  const stats = [
    {
      title: '已分析项目',
      value: `${summary.analyzed}/${summary.repos}`,
      hint: `${summary.pending} 个待分析 · ${summary.noManifest} 个无清单`,
    },
    {
      title: '唯一依赖',
      value: formatCount(summary.uniqueDependencies),
      hint: `共 ${formatCount(summary.dependencyRows)} 条依赖记录`,
    },
    {
      title: '依赖生态',
      value: formatCount(summary.ecosystems),
      hint: 'npm / PyPI / Go / Cargo 等',
    },
    {
      title: '技术栈语言',
      value: formatCount(analysis.techStack.length),
      hint: `失败 ${summary.failed} 个仓库`,
    },
  ]

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
        <div className='mb-4 flex flex-wrap items-start justify-between gap-3'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Boxes className='size-6' />
              依赖分析
            </h2>
            <p className='text-sm text-muted-foreground'>
              项目依赖清单与个人技术栈关联：看清每个仓库用了什么、哪些依赖覆盖最多。
            </p>
            <p className='mt-1 text-xs text-muted-foreground/70'>
              生成于 {formatGeneratedAt(analysis.generatedAt)}
              {analysis.mode === 'local' && ' · 本地降级概览'}
            </p>
          </div>
          <Button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            <RefreshCw className={refresh.isPending ? 'animate-spin' : ''} />
            刷新分析
          </Button>
        </div>

        <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-4'>
          {stats.map((item) => (
            <Card key={item.title}>
              <CardHeader className='pb-2'>
                <CardDescription>{item.title}</CardDescription>
                <CardTitle className='text-3xl'>{item.value}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className='text-xs text-muted-foreground'>{item.hint}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className='mt-4 grid gap-4 lg:grid-cols-3'>
          <Card className='lg:col-span-2'>
            <CardHeader>
              <CardTitle>技术栈分布</CardTitle>
              <CardDescription>按收藏仓库的主要语言统计</CardDescription>
            </CardHeader>
            <CardContent className='space-y-4'>
              {analysis.techStack.map((item) => (
                <div key={item.language} className='space-y-1.5'>
                  <div className='flex items-center justify-between text-sm'>
                    <span className='font-medium'>{item.language}</span>
                    <span className='text-muted-foreground'>
                      {item.count} 个仓库 · {formatPercent(item.percent)}
                    </span>
                  </div>
                  <div className='h-2 overflow-hidden rounded-full bg-muted'>
                    <div
                      className='h-full rounded-full bg-primary transition-all'
                      style={{ width: barWidth(item.percent) }}
                    />
                  </div>
                </div>
              ))}
              {analysis.techStack.length === 0 && (
                <p className='py-8 text-center text-sm text-muted-foreground'>
                  暂无语言数据，先同步仓库或刷新分析。
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>生态构成</CardTitle>
              <CardDescription>依赖清单所属生态与覆盖仓库</CardDescription>
            </CardHeader>
            <CardContent className='flex flex-wrap gap-2'>
              {analysis.ecosystems.map((item) => (
                <Badge key={item.ecosystem} variant='outline' className='text-xs'>
                  {ecosystemLabel(item.ecosystem)} · {item.repos} 仓库 /{' '}
                  {formatCount(item.dependencies)} 依赖
                </Badge>
              ))}
              {analysis.ecosystems.length === 0 && (
                <p className='text-sm text-muted-foreground'>
                  尚未解析到依赖清单。
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle>热门依赖</CardTitle>
            <CardDescription>
              按仓库覆盖率排序，展示版本样例、语言分布与代表项目
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>依赖</TableHead>
                  <TableHead>生态 / 类型</TableHead>
                  <TableHead className='text-end'>覆盖仓库</TableHead>
                  <TableHead>版本样例</TableHead>
                  <TableHead>语言分布</TableHead>
                  <TableHead>代表项目</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {analysis.dependencies.map((item) => (
                  <TableRow key={`${item.ecosystem}:${item.name}`}>
                    <TableCell className='font-medium'>{item.name}</TableCell>
                    <TableCell>
                      <div className='flex flex-wrap gap-1'>
                        <Badge variant='secondary'>
                          {ecosystemLabel(item.ecosystem)}
                        </Badge>
                        <Badge variant='outline'>{kindLabel(item.kind)}</Badge>
                      </div>
                    </TableCell>
                    <TableCell className='text-end'>
                      {item.repoCount} 个 · {formatPercent(item.coverage)}
                    </TableCell>
                    <TableCell className='max-w-40 truncate text-muted-foreground'>
                      {item.versions.length > 0 ? item.versions.join(' / ') : '—'}
                    </TableCell>
                    <TableCell>
                      <div className='flex flex-wrap gap-1'>
                        {item.languages.map((language) => (
                          <Badge key={language.language} variant='outline'>
                            {language.language} ×{language.count}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className='max-w-48 truncate text-muted-foreground'>
                      {item.repos.map((repo) => repo.name).join('、') || '—'}
                    </TableCell>
                  </TableRow>
                ))}
                {analysis.dependencies.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className='h-24 text-center text-muted-foreground'
                    >
                      暂无依赖数据，点击「刷新分析」扫描仓库清单。
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle>仓库覆盖</CardTitle>
            <CardDescription>逐仓库的清单命中、依赖数量与扫描状态</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>仓库</TableHead>
                  <TableHead>语言</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>清单</TableHead>
                  <TableHead className='text-end'>依赖数</TableHead>
                  <TableHead>Top 依赖</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {analysis.repos.map((repo) => (
                  <TableRow key={repo.repoId}>
                    <TableCell className='font-medium'>{repo.name || repo.repoId}</TableCell>
                    <TableCell>{repo.language || '—'}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(repo.status)}>
                        {statusLabel(repo.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className='max-w-48 truncate text-muted-foreground'>
                      {repo.manifests.join(', ') || '—'}
                    </TableCell>
                    <TableCell className='text-end'>
                      {formatCount(repo.dependencyCount)}
                    </TableCell>
                    <TableCell className='max-w-56 truncate text-muted-foreground'>
                      {repo.topDependencies
                        .map((dep) => dep.name)
                        .join('、') || '—'}
                    </TableCell>
                  </TableRow>
                ))}
                {analysis.repos.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className='h-24 text-center text-muted-foreground'
                    >
                      暂无仓库数据。
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
