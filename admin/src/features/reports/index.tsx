import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays,
  Download,
  FileText,
  Loader2,
  RefreshCw,
  Sparkles,
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
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { cn } from '@/lib/utils'
import {
  downloadReportMarkdown,
  fetchReport,
  fetchReports,
  generateReport,
  type CuratedReport,
  type ReportKind,
  type ReportSection,
} from './api'
import {
  REPORT_KINDS,
  formatReportCount,
  formatReportGeneratedAt,
  formatReportPeriod,
  reportKindLabel,
  reportSourceLabel,
  reportStatCards,
  reportStatusLabel,
} from './utils'

function ReportSectionCard({ section }: { section: ReportSection }) {
  if (section.items.length === 0) return null

  return (
    <Card>
      <CardHeader className='pb-3'>
        <div className='flex items-center gap-2'>
          <CardTitle className='text-base'>{section.title}</CardTitle>
          <Badge variant='outline'>{section.items.length}</Badge>
        </div>
        <CardDescription>{section.description}</CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        {section.items.map((item) => (
          <div key={`${section.key}-${item.id}`} className='rounded-lg border p-3'>
            <div className='flex flex-wrap items-center gap-2'>
              <a
                href={item.url}
                target='_blank'
                rel='noreferrer'
                className='font-medium hover:underline'
              >
                {item.name}
              </a>
              <Badge variant='outline'>{reportSourceLabel(item.source)}</Badge>
              {item.language && <Badge variant='secondary'>{item.language}</Badge>}
              {item.category && <Badge variant='outline'>{item.category}</Badge>}
              <span className='ms-auto text-xs tabular-nums text-muted-foreground'>
                ⭐ {formatReportCount(item.stars)}
              </span>
              {item.starsDelta > 0 && (
                <span className='text-xs font-medium text-emerald-600 dark:text-emerald-400'>
                  +{formatReportCount(item.starsDelta)}
                </span>
              )}
            </div>
            {item.description && (
              <p className='mt-1 text-sm text-muted-foreground'>{item.description}</p>
            )}
            {item.reason && (
              <p className='mt-1 text-xs text-muted-foreground'>推荐理由：{item.reason}</p>
            )}
            {item.tags.length > 0 && (
              <div className='mt-2 flex flex-wrap gap-1'>
                {item.tags.slice(0, 4).map((tag) => (
                  <Badge key={tag} variant='outline'>
                    #{tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function ReportDetail({
  report,
  isFetching,
}: {
  report: CuratedReport
  isFetching: boolean
}) {
  const cards = reportStatCards(report.stats)

  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-center gap-2'>
            <CardTitle>{report.title}</CardTitle>
            <Badge variant='secondary'>{reportKindLabel(report.kind)}</Badge>
            <Badge variant={report.status === 'ready' ? 'default' : 'outline'}>
              {reportStatusLabel(report.status)}
            </Badge>
            {isFetching && (
              <span className='ms-auto text-xs text-muted-foreground'>加载中…</span>
            )}
          </div>
          <CardDescription className='flex flex-wrap items-center gap-x-4 gap-y-1'>
            <span className='inline-flex items-center gap-1'>
              <CalendarDays className='h-3.5 w-3.5' />
              {formatReportPeriod(report)}
            </span>
            <span>生成于 {formatReportGeneratedAt(report.generatedAt)}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className='text-sm leading-relaxed text-muted-foreground'>{report.summary}</p>
          <div className='mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
            {cards.map((card) => (
              <div key={card.title} className='rounded-lg border bg-muted/30 p-3'>
                <p className='text-xs text-muted-foreground'>{card.title}</p>
                <p className='mt-1 text-xl font-bold tabular-nums'>{card.value}</p>
                <p className='mt-1 text-xs text-muted-foreground'>{card.hint}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {report.status === 'empty' ? (
        <Card>
          <CardContent className='flex flex-col items-center justify-center gap-2 py-14 text-center'>
            <FileText className='h-10 w-10 text-muted-foreground' />
            <p className='font-medium'>这一期还没有可汇总的数据</p>
            <p className='text-sm text-muted-foreground'>
              同步收藏、生成推荐或积累热榜数据后，下一期报告会自动丰富起来。
            </p>
          </CardContent>
        </Card>
      ) : (
        report.sections.map((section) => (
          <ReportSectionCard key={section.key} section={section} />
        ))
      )}
    </div>
  )
}

export function Reports() {
  const [kind, setKind] = useState<ReportKind>('weekly')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const queryClient = useQueryClient()

  const listQuery = useQuery({
    queryKey: ['reports', 'list', kind],
    queryFn: () => fetchReports(kind),
  })
  const reports = listQuery.data?.items ?? []
  const activeId =
    selectedId && reports.some((report) => report.id === selectedId)
      ? selectedId
      : (reports[0]?.id ?? null)

  const detailQuery = useQuery({
    queryKey: ['reports', 'detail', activeId],
    queryFn: () => fetchReport(activeId as string),
    enabled: Boolean(activeId),
  })
  const report = detailQuery.data ?? null

  async function handleGenerate() {
    setGenerating(true)
    try {
      const created = await generateReport(kind)
      await queryClient.invalidateQueries({ queryKey: ['reports', 'list', kind] })
      setSelectedId(created.id)
      toast.success(`${reportKindLabel(kind)}已生成`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '生成报告失败')
    } finally {
      setGenerating(false)
    }
  }

  async function handleDownload() {
    if (!report) return
    setDownloading(true)
    try {
      await downloadReportMarkdown(report)
      toast.success('Markdown 已开始下载')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '下载报告失败')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>精选报告</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4 flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>精选报告</h2>
            <p className='text-sm text-muted-foreground'>
              每周 / 每月自动汇总收藏、推荐与热榜，沉淀一份可回看的开源资产报告。
            </p>
          </div>
          <div className='flex flex-wrap items-center gap-2'>
            <div className='inline-flex rounded-lg border p-1'>
              {REPORT_KINDS.map((item) => (
                <Button
                  key={item}
                  size='sm'
                  variant={kind === item ? 'default' : 'ghost'}
                  onClick={() => setKind(item)}
                >
                  {reportKindLabel(item)}
                </Button>
              ))}
            </div>
            <Button variant='outline' size='sm' onClick={() => void handleGenerate()} disabled={generating}>
              {generating ? (
                <Loader2 className='size-4 animate-spin' />
              ) : (
                <RefreshCw className='size-4' />
              )}
              立即生成
            </Button>
            <Button size='sm' onClick={() => void handleDownload()} disabled={!report || downloading}>
              {downloading ? (
                <Loader2 className='size-4 animate-spin' />
              ) : (
                <Download className='size-4' />
              )}
              下载 Markdown
            </Button>
          </div>
        </div>

        {listQuery.isLoading ? (
          <Card>
            <CardContent className='flex items-center justify-center gap-2 py-16 text-muted-foreground'>
              <Loader2 className='h-5 w-5 animate-spin' />
              正在加载报告…
            </CardContent>
          </Card>
        ) : reports.length === 0 ? (
          <Card>
            <CardContent className='flex flex-col items-center justify-center gap-3 py-16 text-center'>
              <Sparkles className='h-10 w-10 text-muted-foreground' />
              <div>
                <p className='font-medium'>还没有{reportKindLabel(kind)}</p>
                <p className='mt-1 text-sm text-muted-foreground'>
                  点击「立即生成」，我们会基于当前收藏、推荐与热榜数据生成一份报告。
                </p>
              </div>
              <Button onClick={() => void handleGenerate()} disabled={generating}>
                {generating ? <Loader2 className='size-4 animate-spin' /> : <Sparkles className='size-4' />}
                生成{reportKindLabel(kind)}
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className='grid grid-cols-1 gap-4 lg:grid-cols-12'>
            <Card className='lg:col-span-4'>
              <CardHeader>
                <CardTitle className='text-base'>报告归档</CardTitle>
                <CardDescription>按周期倒序排列，点击切换查看。</CardDescription>
              </CardHeader>
              <CardContent className='space-y-2'>
                {reports.map((item) => (
                  <button
                    key={item.id}
                    type='button'
                    onClick={() => setSelectedId(item.id)}
                    className={cn(
                      'w-full rounded-lg border p-3 text-left transition-colors',
                      item.id === activeId
                        ? 'border-primary bg-muted/60'
                        : 'hover:bg-muted/40'
                    )}
                  >
                    <div className='flex items-center justify-between gap-2'>
                      <span className='text-sm font-medium'>{item.title}</span>
                      <Badge variant={item.status === 'ready' ? 'secondary' : 'outline'}>
                        {reportStatusLabel(item.status)}
                      </Badge>
                    </div>
                    <p className='mt-1 text-xs text-muted-foreground'>
                      {formatReportPeriod(item)} · 生成于{' '}
                      {formatReportGeneratedAt(item.generatedAt)}
                    </p>
                  </button>
                ))}
              </CardContent>
            </Card>

            <div className='lg:col-span-8'>
              {report ? (
                <ReportDetail report={report} isFetching={detailQuery.isFetching} />
              ) : (
                <Card>
                  <CardContent className='flex items-center justify-center gap-2 py-16 text-muted-foreground'>
                    <Loader2 className='h-5 w-5 animate-spin' />
                    正在加载报告详情…
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        )}
      </Main>
    </>
  )
}
