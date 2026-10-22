import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Archive,
  Download,
  FileJson,
  FileText,
  FolderTree,
  Loader2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
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
import { Switch } from '@/components/ui/switch'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { cn } from '@/lib/utils'
import {
  downloadKnowledgeExport,
  fetchExportSummary,
  MOCK_EXPORT_SUMMARY,
  saveBlob,
} from './api'
import type { ExportFormat, ExportGroupBy } from './types'
import {
  FORMAT_OPTIONS,
  fallbackFileName,
  formatCompactNumber,
  formatLabel,
} from './utils'

const FORMAT_ICONS = {
  markdown: FileText,
  json: FileJson,
  obsidian: Archive,
} as const

export function KnowledgeExport() {
  const { data } = useQuery({
    queryKey: ['export-summary'],
    queryFn: fetchExportSummary,
  })
  const summary = data ?? MOCK_EXPORT_SUMMARY
  const [format, setFormat] = useState<ExportFormat>('markdown')
  const [includeSummary, setIncludeSummary] = useState(true)
  const [groupBy, setGroupBy] = useState<ExportGroupBy>('category')
  const [downloading, setDownloading] = useState(false)

  const empty = summary.totalRepos === 0
  const previewName = fallbackFileName(format, summary.generatedAt)

  async function handleDownload() {
    if (empty || downloading) return
    setDownloading(true)
    try {
      const { blob, fileName } = await downloadKnowledgeExport({
        format,
        includeSummary,
        groupBy,
      })
      saveBlob(blob, fileName)
      toast.success(`已生成 ${fileName}`)
    } catch {
      toast.error('导出失败，请稍后重试')
    } finally {
      setDownloading(false)
    }
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
        <div className='mb-4 flex flex-wrap items-start justify-between gap-4'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Download className='size-6 text-emerald-600' />
              知识库导出
            </h2>
            <p className='text-sm text-muted-foreground'>
              把你的收藏导出为 Markdown、JSON 或 Obsidian Vault，随时备份与迁移。
            </p>
          </div>
          <Badge variant='outline' className='mt-1'>
            只读导出 · 不改动数据
          </Badge>
        </div>

        <div className='grid grid-cols-2 gap-3 lg:grid-cols-5'>
          <StatCard label='项目总数' value={String(summary.totalRepos)} />
          <StatCard label='含摘要' value={String(summary.withSummary)} />
          <StatCard label='分类' value={String(summary.categoryCount)} />
          <StatCard label='标签' value={String(summary.tagCount)} />
          <StatCard
            label='Star 总数'
            value={formatCompactNumber(summary.totalStars)}
          />
        </div>

        <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3'>
          <div className='space-y-3 lg:col-span-2'>
            {FORMAT_OPTIONS.map((option) => {
              const Icon = FORMAT_ICONS[option.key]
              const selected = format === option.key
              return (
                <button
                  key={option.key}
                  type='button'
                  aria-pressed={selected}
                  onClick={() => setFormat(option.key)}
                  className={cn(
                    'flex w-full items-start gap-4 rounded-xl border bg-card p-4 text-left transition-colors',
                    selected
                      ? 'border-primary ring-2 ring-primary/20'
                      : 'hover:border-muted-foreground/30'
                  )}
                >
                  <span
                    className={cn(
                      'flex size-10 shrink-0 items-center justify-center rounded-lg',
                      selected
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted text-muted-foreground'
                    )}
                  >
                    <Icon className='size-5' />
                  </span>
                  <span className='min-w-0 flex-1'>
                    <span className='flex items-center gap-2'>
                      <span className='font-semibold'>{option.label}</span>
                      <Badge variant='secondary'>{option.extension}</Badge>
                    </span>
                    <span className='mt-1 block text-sm text-muted-foreground'>
                      {option.description}
                    </span>
                    <span className='mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground'>
                      {option.bullets.map((bullet) => (
                        <span key={bullet}>· {bullet}</span>
                      ))}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>

          <Card className='h-fit'>
            <CardHeader>
              <CardTitle>导出设置</CardTitle>
              <CardDescription>生成前可调整内容范围与组织方式。</CardDescription>
            </CardHeader>
            <CardContent className='space-y-5'>
              <div className='flex items-start justify-between gap-4'>
                <div className='space-y-1'>
                  <label
                    htmlFor='include-summary'
                    className='text-sm font-medium'
                  >
                    包含 README 摘要
                  </label>
                  <p className='text-xs text-muted-foreground'>
                    摘要由 VPS 生成，关闭后文件更精简。
                  </p>
                </div>
                <Switch
                  id='include-summary'
                  checked={includeSummary}
                  onCheckedChange={setIncludeSummary}
                />
              </div>

              <div className='space-y-2'>
                <label className='text-sm font-medium'>组织方式</label>
                <Select
                  value={groupBy}
                  onValueChange={(value) =>
                    setGroupBy(value as ExportGroupBy)
                  }
                >
                  <SelectTrigger className='w-full'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='category'>按分类分组</SelectItem>
                    <SelectItem value='none'>平铺（不分组）</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className='rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground'>
                <div className='flex items-center gap-1.5 font-medium text-foreground'>
                  <FolderTree className='size-3.5' />
                  文件名
                </div>
                <code className='mt-1 block break-all'>{previewName}</code>
              </div>

              {empty && (
                <p className='rounded-lg border border-dashed p-3 text-sm text-muted-foreground'>
                  还没有收藏项目，先去同步仓库再来导出吧。
                </p>
              )}
            </CardContent>
            <CardFooter>
              <Button
                className='w-full'
                onClick={handleDownload}
                disabled={empty || downloading}
              >
                {downloading ? (
                  <Loader2 className='animate-spin' />
                ) : (
                  <Download />
                )}
                {downloading ? '正在生成…' : `导出 ${formatLabel(format)}`}
              </Button>
            </CardFooter>
          </Card>
        </div>

        <p className='mt-4 text-xs text-muted-foreground'>
          导出仅包含当前账号的收藏数据，不会写入或修改任何内容。统计生成于{' '}
          {new Date(summary.generatedAt).toLocaleString('zh-CN')}。
        </p>
      </Main>
    </>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className='py-4'>
      <CardContent className='px-4'>
        <div className='text-xs text-muted-foreground'>{label}</div>
        <div className='mt-1 text-2xl font-semibold tracking-tight'>{value}</div>
      </CardContent>
    </Card>
  )
}

