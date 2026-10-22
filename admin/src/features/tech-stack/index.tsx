import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  Boxes,
  Code2,
  FolderGit2,
  Gauge,
  Network,
  RefreshCw,
} from 'lucide-react'
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
import { cn } from '@/lib/utils'
import { fetchTechStack, MOCK_TECH_STACK } from './api'
import { TechStackGraph } from './components/tech-stack-graph'
import {
  foldLanguages,
  formatCompactNumber,
  formatPercent,
  topLanguageFrameworkPairs,
} from './utils'

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function StatCard({
  title,
  icon,
  value,
  hint,
}: {
  title: string
  icon: ReactNode
  value: string
  hint: string
}) {
  return (
    <Card>
      <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
        <CardTitle className='text-sm font-medium'>{title}</CardTitle>
        <span className='text-muted-foreground' aria-hidden='true'>
          {icon}
        </span>
      </CardHeader>
      <CardContent>
        <div className='text-2xl font-bold'>{value}</div>
        <p className='mt-1 text-xs text-muted-foreground'>{hint}</p>
      </CardContent>
    </Card>
  )
}

export function TechStack() {
  const { data, isFetching, refetch } = useQuery({
    queryKey: ['tech-stack'],
    queryFn: fetchTechStack,
  })
  const stack = data ?? MOCK_TECH_STACK
  const { summary } = stack
  const languages = foldLanguages(stack.languages)
  const maxLanguageCount = Math.max(1, ...languages.map((item) => item.repoCount))
  const pairs = topLanguageFrameworkPairs(stack.graph, 4)

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>技术栈图谱</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4 flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>技术栈图谱</h2>
            <p className='text-sm text-muted-foreground'>
              从已收藏仓库的语言、标签与简介中聚合你的技术偏好。
            </p>
          </div>
          <div className='flex items-center gap-3'>
            <span className='text-xs text-muted-foreground'>
              更新于 {formatDateTime(stack.generatedAt)}
            </span>
            <Button
              variant='outline'
              size='sm'
              onClick={() => void refetch()}
              disabled={isFetching}
            >
              <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} />
              刷新
            </Button>
          </div>
        </div>

        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
          <StatCard
            title='收录仓库'
            icon={<FolderGit2 className='h-4 w-4' />}
            value={String(summary.totalRepos)}
            hint={`累计 ${formatCompactNumber(summary.totalStars)} Star`}
          />
          <StatCard
            title='主要语言'
            icon={<Code2 className='h-4 w-4' />}
            value={summary.topLanguage ?? '—'}
            hint={`${summary.languageCount} 种语言 · ${summary.withLanguage} 个仓库有语言信息`}
          />
          <StatCard
            title='常用框架'
            icon={<Boxes className='h-4 w-4' />}
            value={summary.topFramework ?? '—'}
            hint={`${summary.frameworkCount} 个框架 · ${summary.withFramework} 个仓库已识别`}
          />
          <StatCard
            title='识别覆盖率'
            icon={<Gauge className='h-4 w-4' />}
            value={formatPercent(summary.coverage)}
            hint='语言或框架至少可识别其一的仓库占比'
          />
        </div>

        {summary.totalRepos === 0 ? (
          <Card className='mt-4'>
            <CardContent className='flex flex-col items-center justify-center gap-3 py-16 text-center'>
              <Network className='h-10 w-10 text-muted-foreground' />
              <div>
                <p className='font-medium'>还没有可聚合的仓库</p>
                <p className='mt-1 text-sm text-muted-foreground'>
                  同步 GitHub 仓库并补充语言 / 标签后，这里会自动生成技术栈图谱。
                </p>
              </div>
              <Button asChild>
                <Link to='/repos'>去管理仓库</Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-12'>
            <Card className='lg:col-span-7'>
              <CardHeader>
                <CardTitle>语言 × 框架关系</CardTitle>
                <CardDescription>
                  内圈为语言，外圈为框架；连线越粗，表示该组合在仓库中越常见。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <TechStackGraph
                  nodes={stack.graph.nodes}
                  links={stack.graph.links}
                />
              </CardContent>
            </Card>

            <Card className='lg:col-span-5'>
              <CardHeader>
                <CardTitle>语言分布</CardTitle>
                <CardDescription>
                  按收录仓库数排序，占比以全部仓库为分母。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className='space-y-4' role='list' aria-label='语言分布'>
                  {languages.map((item) => (
                    <div key={item.name} role='listitem'>
                      <div className='mb-1.5 flex items-baseline justify-between gap-2'>
                        <span className='truncate text-sm font-medium'>
                          {item.name}
                        </span>
                        <span className='shrink-0 text-xs tabular-nums text-muted-foreground'>
                          {item.repoCount} 个仓库 · {formatPercent(item.share)}
                        </span>
                      </div>
                      <div
                        className='h-2.5 w-full overflow-hidden rounded-full bg-muted'
                        aria-hidden='true'
                      >
                        <div
                          className={cn(
                            'h-full rounded-full transition-all',
                            item.isOther
                              ? 'bg-muted-foreground/40'
                              : 'bg-[#2a78d6] dark:bg-[#3987e5]'
                          )}
                          style={{
                            width: `${Math.max(2, (item.repoCount / maxLanguageCount) * 100)}%`,
                          }}
                        />
                      </div>
                      {item.frameworks.length > 0 && (
                        <p className='mt-1 truncate text-xs text-muted-foreground'>
                          常用框架：{item.frameworks.slice(0, 4).join(' · ')}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
                <p className='mt-4 text-xs text-muted-foreground'>
                  条形长度按最高语言归一，右侧百分比为占全部仓库的真实比例。
                </p>
              </CardContent>
            </Card>

            <Card className='lg:col-span-8'>
              <CardHeader>
                <CardTitle>框架排行</CardTitle>
                <CardDescription>
                  由仓库标签与简介 / 摘要启发式识别，同一仓库同一框架只计一次。
                </CardDescription>
              </CardHeader>
              <CardContent className='px-0'>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className='ps-6'>框架</TableHead>
                      <TableHead>分类</TableHead>
                      <TableHead className='text-end'>仓库数</TableHead>
                      <TableHead>主要语言</TableHead>
                      <TableHead className='pe-6 text-end'>占比</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stack.frameworks.map((framework) => (
                      <TableRow key={framework.name}>
                        <TableCell className='ps-6 font-medium'>
                          {framework.name}
                        </TableCell>
                        <TableCell>
                          <Badge variant='outline'>{framework.category}</Badge>
                        </TableCell>
                        <TableCell className='text-end tabular-nums'>
                          {framework.repoCount}
                        </TableCell>
                        <TableCell className='text-xs text-muted-foreground'>
                          {framework.languages.slice(0, 3).join(' / ') || '—'}
                        </TableCell>
                        <TableCell className='pe-6 text-end tabular-nums'>
                          {formatPercent(framework.share)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card className='lg:col-span-4'>
              <CardHeader>
                <CardTitle>组合洞察</CardTitle>
                <CardDescription>
                  出现频率最高的语言与框架搭配。
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-4'>
                <div className='space-y-2'>
                  {pairs.length === 0 ? (
                    <p className='text-sm text-muted-foreground'>
                      暂无足够的语言与框架组合数据。
                    </p>
                  ) : (
                    pairs.map((pair) => (
                      <div
                        key={`${pair.language}-${pair.framework}`}
                        className='flex items-center justify-between gap-2 rounded-lg border px-3 py-2'
                      >
                        <span className='truncate text-sm'>
                          <span className='font-medium'>{pair.language}</span>
                          <span className='mx-1.5 text-muted-foreground'>×</span>
                          <span className='font-medium'>{pair.framework}</span>
                        </span>
                        <Badge variant='secondary' className='shrink-0 tabular-nums'>
                          {pair.weight} 个仓库
                        </Badge>
                      </div>
                    ))
                  )}
                </div>

                <div className='border-t pt-4'>
                  <div className='flex items-center justify-between text-sm'>
                    <span>识别覆盖率</span>
                    <span className='font-medium tabular-nums'>
                      {formatPercent(summary.coverage)}
                    </span>
                  </div>
                  <div
                    className='mt-2 h-2 w-full overflow-hidden rounded-full bg-muted'
                    aria-hidden='true'
                  >
                    <div
                      className='h-full rounded-full bg-[#eb6834] dark:bg-[#d95926]'
                      style={{ width: `${Math.max(0, Math.min(100, summary.coverage))}%` }}
                    />
                  </div>
                  <p className='mt-2 text-xs text-muted-foreground'>
                    框架识别依赖标签与仓库简介，补充标签可提升识别覆盖率。
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        <p className='mt-4 text-xs text-muted-foreground'>
          仅统计当前账号收藏的仓库；演示环境数据可能与实际账号不同。
        </p>
      </Main>
    </>
  )
}
