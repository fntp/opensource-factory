import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpDown,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
  Sparkles,
  TrendingUp,
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
import {
  applyRerank,
  fetchRerankPreview,
  type RerankResult,
} from './api'
import {
  WEIGHT_PRESETS,
  formatGeneratedAt,
  formatPercent,
  formatRankShift,
  rankShiftClass,
  signalPercent,
  topSignals,
  weightSummary,
} from './utils'

const DEFAULT_PRESET = 'balanced'

export function RerankWorkbench() {
  const [presetValue, setPresetValue] = useState(DEFAULT_PRESET)
  const queryClient = useQueryClient()
  const preset = WEIGHT_PRESETS.find((item) => item.value === presetValue) ?? WEIGHT_PRESETS[0]
  const params = {
    topK: 20,
    poolSize: 100,
    mmrLambda: preset.mmrLambda,
    weights: preset.weights,
  }

  const { data, isPending, isFetching, error } = useQuery({
    queryKey: ['rerank-preview', presetValue, params],
    queryFn: () => fetchRerankPreview(params),
  })

  const apply = useMutation({
    mutationFn: () => applyRerank(params),
    onSuccess: (result) => {
      if (!result.applied) {
        toast.warning('没有可应用的推荐，先生成每日推荐后再试')
        return
      }
      toast.success(`已应用精排：${result.items.length} 条推荐已更新`)
      void queryClient.invalidateQueries({ queryKey: ['rerank-preview'] })
      void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
    },
    onError: () => toast.error('应用精排失败，请确认登录状态与 VPS 节点'),
  })

  const result: RerankResult | undefined = data
  const metrics = result?.metrics

  const stats = [
    {
      title: '精排候选',
      value: metrics ? `${metrics.selected}/${metrics.total}` : '—',
      hint: '入选 / 参与精排的推荐数',
    },
    {
      title: '名次上升',
      value: metrics ? String(metrics.movedUp) : '—',
      hint: metrics ? `下降 ${metrics.movedDown} · 不变 ${metrics.unchanged}` : '精排前后对比',
    },
    {
      title: '平均名次变化',
      value: metrics ? metrics.avgRankShift.toFixed(2) : '—',
      hint: '绝对值越小说明排序越稳定',
    },
    {
      title: '多样性',
      value: metrics
        ? `${formatPercent(metrics.diversityBefore)} → ${formatPercent(metrics.diversityAfter)}`
        : '—',
      hint: metrics ? `语言覆盖率 ${formatPercent(metrics.languageCoverage)}` : 'Top 列表两两差异度',
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
              <Sparkles className='size-6 text-violet-500' />
              精排工作台
            </h2>
            <p className='text-sm text-muted-foreground'>
              在粗排之后综合相关性、画像亲和、时效、动量、人气与健康度重新排序，
              并用 MMR 控制列表多样性。
            </p>
            <p className='mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground/70'>
              <span>生成于 {result ? formatGeneratedAt(result.generatedAt) : '—'}</span>
              {result && (
                <Badge variant={result.mode === 'vps' ? 'secondary' : 'outline'}>
                  {result.mode === 'vps' ? 'VPS 六路信号' : '本地降级'}
                </Badge>
              )}
              {result && <span>{weightSummary(result.weights)}</span>}
            </p>
          </div>
          <div className='flex flex-wrap items-center gap-2'>
            <Select value={presetValue} onValueChange={setPresetValue}>
              <SelectTrigger className='w-[180px]' aria-label='选择精排权重预设'>
                <SelectValue placeholder='选择权重预设' />
              </SelectTrigger>
              <SelectContent>
                {WEIGHT_PRESETS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant='outline'
              onClick={() => queryClient.invalidateQueries({ queryKey: ['rerank-preview'] })}
              disabled={isFetching}
            >
              <RefreshCw className={isFetching ? 'animate-spin' : ''} />
              重新精排
            </Button>
            <Button onClick={() => apply.mutate()} disabled={apply.isPending || !result?.items.length}>
              <CheckCircle2 />
              应用精排
            </Button>
          </div>
        </div>

        <p className='mb-4 text-xs text-muted-foreground'>{preset.description}</p>

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

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle className='flex items-center gap-2'>
              <ArrowUpDown className='size-5' />
              精排前后对比
            </CardTitle>
            <CardDescription>
              展示名次变化、六路信号贡献与推荐理由；「应用精排」会把精排分与名次写回推荐表。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isPending ? (
              <p className='py-10 text-center text-sm text-muted-foreground'>正在计算精排结果…</p>
            ) : error ? (
              <p className='py-10 text-center text-sm text-rose-600'>
                精排预览失败，请确认登录状态与 VPS 节点。
              </p>
            ) : !result?.items.length ? (
              <p className='py-10 text-center text-sm text-muted-foreground'>
                暂无可精排的推荐，先生成每日推荐后再试。
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className='w-24'>名次</TableHead>
                    <TableHead>项目</TableHead>
                    <TableHead className='text-end'>粗排 / 精排</TableHead>
                    <TableHead>主要信号</TableHead>
                    <TableHead>推荐理由</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.items.map((item) => (
                    <TableRow key={item.repoId}>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <span className='text-muted-foreground'>{item.rankBefore}</span>
                          <TrendingUp className='size-3 text-muted-foreground' />
                          <span className='font-semibold'>{item.rankAfter}</span>
                          <span className={`text-xs ${rankShiftClass(item)}`}>
                            {formatRankShift(item)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='space-y-1'>
                          <a
                            href={item.htmlUrl}
                            target='_blank'
                            rel='noreferrer'
                            className='flex items-center gap-1 font-medium hover:underline'
                          >
                            {item.name || item.repoId}
                            <ExternalLink className='size-3' />
                          </a>
                          <div className='flex items-center gap-2 text-xs text-muted-foreground'>
                            <span>{item.repoId}</span>
                            {item.language && <Badge variant='outline'>{item.language}</Badge>}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className='text-end'>
                        <div className='text-sm text-muted-foreground'>{formatPercent(item.baseScore)}</div>
                        <div className='font-semibold'>{formatPercent(item.rerankScore)}</div>
                      </TableCell>
                      <TableCell>
                        <div className='space-y-1.5'>
                          {topSignals(item, 3).map((signal) => (
                            <div key={signal.key} className='space-y-1'>
                              <div className='flex items-center justify-between gap-3 text-xs'>
                                <span>{signal.label}</span>
                                <span className='text-muted-foreground'>
                                  {formatPercent(signal.value)}
                                </span>
                              </div>
                              <div className='h-1.5 w-32 overflow-hidden rounded-full bg-muted'>
                                <div
                                  className='h-full rounded-full bg-primary'
                                  style={{ width: `${signalPercent(signal.value)}%` }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='flex max-w-md flex-wrap gap-1'>
                          {item.reasons.map((reason) => (
                            <Badge key={reason} variant='secondary' className='text-xs font-normal'>
                              {reason}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
