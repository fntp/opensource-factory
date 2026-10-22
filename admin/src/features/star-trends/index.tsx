import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowDownRight,
  ArrowUpRight,
  ExternalLink,
  FolderGit2,
  Gauge,
  Languages,
  Layers,
  Lightbulb,
  Minus,
  RefreshCw,
  Snowflake,
  Sparkles,
  Star,
  TrendingUp,
  Trophy,
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
import {
  fetchStarTrends,
  mockStarTrends,
  type StarInsight,
  type StarMover,
  type StarTrendScope,
} from './api'
import { Sparkline } from './components/sparkline'
import { StarTrendChart } from './components/star-trend-chart'
import {
  formatCompactNumber,
  formatGrowthRate,
  formatPercent,
  formatSignedNumber,
  normalizeDays,
  periodLabel,
  trendMeta,
} from './utils'

const DAY_OPTIONS = [7, 30, 90] as const

const INSIGHT_ICONS: Record<StarInsight['kind'], ReactNode> = {
  growth: <Trophy className='h-4 w-4' />,
  language: <Languages className='h-4 w-4' />,
  new: <Sparkles className='h-4 w-4' />,
  concentration: <Layers className='h-4 w-4' />,
  cooling: <Snowflake className='h-4 w-4' />,
}

const TREND_BADGE_CLASS: Record<string, string> = {
  new: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300',
  up: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  down: 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
  steady: 'border-border bg-muted text-muted-foreground',
}

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
        <div className='text-2xl font-bold tabular-nums'>{value}</div>
        <p className='mt-1 text-xs text-muted-foreground'>{hint}</p>
      </CardContent>
    </Card>
  )
}

function TrendBadge({ trend }: { trend: string }) {
  const meta = trendMeta(trend)
  const Icon =
    trend === 'up'
      ? ArrowUpRight
      : trend === 'down'
        ? ArrowDownRight
        : trend === 'new'
          ? Sparkles
          : Minus
  return (
    <Badge
      variant='outline'
      className={cn('gap-1', TREND_BADGE_CLASS[meta.tone] ?? TREND_BADGE_CLASS.steady)}
    >
      <Icon aria-hidden='true' />
      {meta.label}
    </Badge>
  )
}

function RepoLink({ item }: { item: StarMover }) {
  return (
    <a
      href={item.url}
      target='_blank'
      rel='noreferrer'
      className='inline-flex items-center gap-1 font-medium hover:underline'
    >
      <span className='max-w-[22rem] truncate'>
        {item.owner}/{item.name}
      </span>
      <ExternalLink className='h-3 w-3 shrink-0 text-muted-foreground' aria-hidden='true' />
    </a>
  )
}

function EmptyState({ scope }: { scope: StarTrendScope }) {
  const isMy = scope === 'my'
  return (
    <Card className='mt-4'>
      <CardContent className='flex flex-col items-center justify-center gap-3 py-16 text-center'>
        {isMy ? (
          <FolderGit2 className='h-10 w-10 text-muted-foreground' />
        ) : (
          <TrendingUp className='h-10 w-10 text-muted-foreground' />
        )}
        <div>
          <p className='font-medium'>
            {isMy ? '收藏库里还没有可用的 Star 历史' : '等待热榜快照积累'}
          </p>
          <p className='mt-1 text-sm text-muted-foreground'>
            {isMy
              ? '收藏仓库并出现在每日热榜后，这里会展示它们的 Star 增长趋势。'
              : '每日热榜任务运行后，这里会自动生成 Star 增长趋势与洞察。'}
          </p>
        </div>
        <Button asChild>
          <Link to={isMy ? '/repos' : '/trending'}>
            {isMy ? '去管理仓库' : '查看热榜'}
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}

export function StarTrends() {
  const [scope, setScope] = useState<StarTrendScope>('trending')
  const [days, setDays] = useState(30)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['star-trends', days, scope],
    queryFn: () => fetchStarTrends(days, scope),
  })

  const trends = data ?? mockStarTrends(days, scope)
  const { summary, period } = trends
  const isEmpty = summary.trackedRepos === 0 && trends.series.length === 0
  const maxLanguageGain = Math.max(
    1,
    ...trends.languages.map((item) => Math.abs(item.starGain))
  )

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>Star 趋势</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4 flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Star 趋势与洞察</h2>
            <p className='text-sm text-muted-foreground'>
              基于每日热榜快照，回答「谁涨得最快、哪个语言在升温」。
            </p>
          </div>
          <div className='flex flex-wrap items-center gap-3'>
            <div
              className='flex items-center gap-1 rounded-lg border p-0.5'
              role='group'
              aria-label='统计范围'
            >
              <Button
                size='sm'
                variant={scope === 'trending' ? 'default' : 'ghost'}
                onClick={() => setScope('trending')}
                aria-pressed={scope === 'trending'}
              >
                热榜洞察
              </Button>
              <Button
                size='sm'
                variant={scope === 'my' ? 'default' : 'ghost'}
                onClick={() => setScope('my')}
                aria-pressed={scope === 'my'}
              >
                我的收藏
              </Button>
            </div>
            <div
              className='flex items-center gap-1 rounded-lg border p-0.5'
              role='group'
              aria-label='统计窗口'
            >
              {DAY_OPTIONS.map((option) => (
                <Button
                  key={option}
                  size='sm'
                  variant={days === option ? 'default' : 'ghost'}
                  onClick={() => setDays(normalizeDays(option))}
                  aria-pressed={days === option}
                >
                  {option} 天
                </Button>
              ))}
            </div>
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
            title='追踪仓库'
            icon={<FolderGit2 className='h-4 w-4' />}
            value={String(summary.trackedRepos)}
            hint={
              scope === 'my'
                ? `收藏 ${summary.portfolioRepos ?? 0} 个 · 快照覆盖 ${formatPercent(summary.coverage ?? 0)}`
                : '窗口内出现在热榜快照中的仓库数'
            }
          />
          <StatCard
            title='最新总 Star'
            icon={<Star className='h-4 w-4' />}
            value={formatCompactNumber(summary.totalStars)}
            hint={
              scope === 'my'
                ? '收藏仓库当前 Star 合计'
                : '窗口内最后一天快照的 Star 合计'
            }
          />
          <StatCard
            title='区间净增'
            icon={<TrendingUp className='h-4 w-4' />}
            value={formatSignedNumber(summary.starGain)}
            hint={`${periodLabel(period.startDate, period.endDate)} · ${period.snapshotDays} 个快照日`}
          />
          <StatCard
            title='日均净增'
            icon={<Gauge className='h-4 w-4' />}
            value={formatSignedNumber(summary.averageDailyGain)}
            hint={`上升 ${summary.risingRepos} · 回落 ${summary.fallingRepos} · 新上榜 ${summary.newEntries}`}
          />
        </div>

        {isEmpty ? (
          <EmptyState scope={scope} />
        ) : (
          <>
            <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-12'>
              <Card className='lg:col-span-8'>
                <CardHeader>
                  <CardTitle>每日 Star 净增</CardTitle>
                  <CardDescription>
                    按快照 star_delta 汇总；曲线只覆盖有快照的日期，不补零。
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <StarTrendChart series={trends.series} />
                </CardContent>
              </Card>

              <Card className='lg:col-span-4'>
                <CardHeader>
                  <CardTitle className='flex items-center gap-2'>
                    <Lightbulb className='h-4 w-4' />
                    关键洞察
                  </CardTitle>
                  <CardDescription>由确定性规则生成，不依赖模型。</CardDescription>
                </CardHeader>
                <CardContent>
                  {trends.insights.length === 0 ? (
                    <p className='text-sm text-muted-foreground'>
                      暂无足够数据生成洞察。
                    </p>
                  ) : (
                    <div className='space-y-3' role='list' aria-label='关键洞察'>
                      {trends.insights.map((insight) => (
                        <div
                          key={`${insight.kind}-${insight.title}`}
                          role='listitem'
                          className='flex gap-3 rounded-lg border p-3'
                        >
                          <span className='mt-0.5 text-muted-foreground' aria-hidden='true'>
                            {INSIGHT_ICONS[insight.kind]}
                          </span>
                          <div>
                            <p className='text-sm font-medium'>{insight.title}</p>
                            <p className='mt-0.5 text-xs leading-relaxed text-muted-foreground'>
                              {insight.description}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-12'>
              <Card className='lg:col-span-8'>
                <CardHeader>
                  <CardTitle>Top Movers</CardTitle>
                  <CardDescription>
                    按区间净增排序；增长率 = 净增 ÷ 期初 Star（单日快照用 star_delta 估算）。
                  </CardDescription>
                </CardHeader>
                <CardContent className='px-0'>
                  {trends.topMovers.length === 0 ? (
                    <p className='px-6 pb-4 text-sm text-muted-foreground'>
                      窗口内暂无仓库增长数据。
                    </p>
                  ) : (
                    <div className='overflow-x-auto'>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className='ps-6 text-center'>#</TableHead>
                            <TableHead>仓库</TableHead>
                            <TableHead>语言</TableHead>
                            <TableHead className='text-end'>总 Star</TableHead>
                            <TableHead className='text-end'>区间净增</TableHead>
                            <TableHead className='text-end'>增长率</TableHead>
                            <TableHead className='text-end'>上榜</TableHead>
                            <TableHead>趋势</TableHead>
                            <TableHead className='pe-6 text-end'>走势</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {trends.topMovers.map((item, index) => (
                            <TableRow key={item.repoId}>
                              <TableCell className='ps-6 text-center tabular-nums text-muted-foreground'>
                                {index + 1}
                              </TableCell>
                              <TableCell>
                                <RepoLink item={item} />
                              </TableCell>
                              <TableCell>
                                {item.language ? (
                                  <Badge variant='outline'>{item.language}</Badge>
                                ) : (
                                  '—'
                                )}
                              </TableCell>
                              <TableCell className='text-end tabular-nums'>
                                {formatCompactNumber(item.stars)}
                              </TableCell>
                              <TableCell
                                className={cn(
                                  'text-end tabular-nums',
                                  item.gain > 0
                                    ? 'text-emerald-600 dark:text-emerald-400'
                                    : item.gain < 0
                                      ? 'text-rose-600 dark:text-rose-400'
                                      : 'text-muted-foreground'
                                )}
                              >
                                {formatSignedNumber(item.gain)}
                              </TableCell>
                              <TableCell className='text-end tabular-nums'>
                                {formatGrowthRate(item.growthRate)}
                              </TableCell>
                              <TableCell className='text-end tabular-nums'>
                                {item.appearances} 天
                              </TableCell>
                              <TableCell>
                                <TrendBadge trend={item.trend} />
                              </TableCell>
                              <TableCell className='pe-6 text-end'>
                                <Sparkline
                                  values={item.sparkline}
                                  label={`${item.owner}/${item.name} 最近 ${item.sparkline.length} 次快照的 Star 走势`}
                                />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className='space-y-4 lg:col-span-4'>
                <Card>
                  <CardHeader>
                    <CardTitle>语言贡献</CardTitle>
                    <CardDescription>
                      按 Star 增量排序，占比以正增量总和为分母。
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {trends.languages.length === 0 ? (
                      <p className='text-sm text-muted-foreground'>
                        暂无语言增量数据。
                      </p>
                    ) : (
                      <div className='space-y-3' role='list' aria-label='语言贡献'>
                        {trends.languages.map((item) => (
                          <div key={item.language} role='listitem'>
                            <div className='mb-1 flex items-baseline justify-between gap-2'>
                              <span className='truncate text-sm font-medium'>
                                {item.language}
                              </span>
                              <span className='shrink-0 text-xs tabular-nums text-muted-foreground'>
                                {formatSignedNumber(item.starGain)} · {formatPercent(item.share)}
                              </span>
                            </div>
                            <div
                              className='h-2 w-full overflow-hidden rounded-full bg-muted'
                              aria-hidden='true'
                            >
                              <div
                                className='h-full rounded-full bg-[#2a78d6] dark:bg-[#3987e5]'
                                style={{
                                  width: `${Math.max(
                                    2,
                                    (Math.abs(item.starGain) / maxLanguageGain) * 100
                                  )}%`,
                                }}
                              />
                            </div>
                            <p className='mt-1 truncate text-xs text-muted-foreground'>
                              {item.repoCount} 个仓库
                              {item.topRepo ? ` · 代表项目 ${item.topRepo}` : ''}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>新上榜</CardTitle>
                    <CardDescription>窗口内首次出现在热榜快照的项目。</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {trends.newEntries.length === 0 ? (
                      <p className='text-sm text-muted-foreground'>
                        窗口内没有新上榜项目。
                      </p>
                    ) : (
                      <div className='space-y-3' role='list' aria-label='新上榜项目'>
                        {trends.newEntries.map((item) => (
                          <div
                            key={item.repoId}
                            role='listitem'
                            className='rounded-lg border p-3'
                          >
                            <RepoLink item={item} />
                            <div className='mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                              <Badge
                                variant='outline'
                                className={TREND_BADGE_CLASS.new}
                              >
                                新上榜
                              </Badge>
                              {item.language && <span>{item.language}</span>}
                              <span className='tabular-nums'>
                                {formatSignedNumber(item.gain)} Star
                              </span>
                              <span>首次出现 {item.firstDate}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </div>
          </>
        )}

        {scope === 'my' && (
          <p className='mt-4 text-xs text-muted-foreground'>
            仅统计收藏仓库中上过热榜的项目，快照覆盖率{' '}
            {formatPercent(summary.coverage ?? 0)}（{summary.trackedRepos} /{' '}
            {summary.portfolioRepos ?? 0}）。未上榜仓库暂无历史快照，因此不绘制曲线。
          </p>
        )}
        <p className='mt-2 text-xs text-muted-foreground'>
          数据来源：trending_snapshots 每日快照。区间净增取首末快照差，日序列取
          star_delta 合计；更新于 {formatDateTime(trends.generatedAt)}。
        </p>
      </Main>
    </>
  )
}
