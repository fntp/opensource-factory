import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ExternalLink,
  Loader2,
  Sparkles,
  Tags,
  X,
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
import { DEMO_MODE } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  acceptTagSuggestions,
  dismissTagSuggestions,
  fetchTagSuggestions,
  generateTagSuggestions,
  type TagSuggestionFilter,
  type TagSuggestionItem,
} from './api'
import {
  categoryLabel,
  formatScore,
  groupSuggestionsByRepo,
  scoreTone,
  truncateSummary,
} from './utils'

const FILTER_OPTIONS: Array<{ value: TagSuggestionFilter; label: string }> = [
  { value: 'pending', label: '待确认' },
  { value: 'accepted', label: '已采纳' },
  { value: 'dismissed', label: '已忽略' },
  { value: 'all', label: '全部' },
]

function scoreBadgeClass(tone: 'high' | 'medium' | 'low'): string {
  if (tone === 'high') {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  }
  if (tone === 'medium') {
    return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'
  }
  return 'border-slate-500/30 bg-slate-500/10 text-slate-600 dark:text-slate-300'
}

export function TagSuggestions() {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<TagSuggestionFilter>('pending')
  const [generating, setGenerating] = useState(false)
  const [busyIds, setBusyIds] = useState<string[]>([])
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ['tag-suggestions', status],
    queryFn: () => fetchTagSuggestions(status),
  })

  const items = useMemo(
    () => (data?.items ?? []).filter((item) => !hiddenIds.has(item.id)),
    [data?.items, hiddenIds]
  )
  const groups = useMemo(() => groupSuggestionsByRepo(items), [items])
  const summary = data?.summary

  async function handleGenerate() {
    setGenerating(true)
    try {
      if (DEMO_MODE) {
        toast.success('演示模式：已模拟生成 6 条建议（真实环境会调用 VPS 规则引擎）')
        return
      }
      const result = await generateTagSuggestions({ limit: 200, perRepo: 6 })
      toast.success(
        `已扫描 ${result.scanned} 个仓库，生成 ${result.suggested} 个仓库的 ${result.saved} 条建议（${result.source === 'vps' ? 'VPS 规则引擎' : '本地兜底规则'}）`
      )
      await queryClient.invalidateQueries({ queryKey: ['tag-suggestions'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '生成建议失败')
    } finally {
      setGenerating(false)
    }
  }

  function markBusy(ids: string[], busy: boolean) {
    setBusyIds((current) =>
      busy ? [...current, ...ids] : current.filter((id) => !ids.includes(id))
    )
  }

  async function handleAccept(ids: string[]) {
    if (ids.length === 0) return
    markBusy(ids, true)
    try {
      if (DEMO_MODE) {
        setHiddenIds((current) => new Set([...current, ...ids]))
        toast.success(`演示模式：已模拟采纳 ${ids.length} 条建议`)
        return
      }
      const result = await acceptTagSuggestions({ ids })
      setHiddenIds((current) => new Set([...current, ...ids]))
      toast.success(`已采纳 ${result.accepted} 条，写入 ${result.tagsApplied} 个新标签`)
      await queryClient.invalidateQueries({ queryKey: ['tag-suggestions'] })
      await queryClient.invalidateQueries({ queryKey: ['repos'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '采纳失败')
    } finally {
      markBusy(ids, false)
    }
  }

  async function handleAcceptGroup(group: {
    repoId: string
    items: TagSuggestionItem[]
  }) {
    const ids = group.items.map((item) => item.id)
    if (ids.length === 0) return
    markBusy(ids, true)
    try {
      if (DEMO_MODE) {
        setHiddenIds((current) => new Set([...current, ...ids]))
        toast.success(`演示模式：已模拟采纳 ${group.repoId} 的 ${ids.length} 条建议`)
        return
      }
      const result = await acceptTagSuggestions({
        repoId: group.repoId,
        tags: group.items.map((item) => item.tagName),
      })
      setHiddenIds((current) => new Set([...current, ...ids]))
      toast.success(`已采纳 ${result.accepted} 条，写入 ${result.tagsApplied} 个新标签`)
      await queryClient.invalidateQueries({ queryKey: ['tag-suggestions'] })
      await queryClient.invalidateQueries({ queryKey: ['repos'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '批量采纳失败')
    } finally {
      markBusy(ids, false)
    }
  }

  async function handleDismiss(ids: string[]) {
    if (ids.length === 0) return
    markBusy(ids, true)
    try {
      if (DEMO_MODE) {
        setHiddenIds((current) => new Set([...current, ...ids]))
        toast.success(`演示模式：已忽略 ${ids.length} 条建议`)
        return
      }
      const result = await dismissTagSuggestions(ids)
      setHiddenIds((current) => new Set([...current, ...ids]))
      toast.success(`已忽略 ${result.dismissed} 条建议`)
      await queryClient.invalidateQueries({ queryKey: ['tag-suggestions'] })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '忽略失败')
    } finally {
      markBusy(ids, false)
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
        <div className='mb-4 flex flex-wrap items-center justify-between gap-3'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>打标建议</h2>
            <p className='text-sm text-muted-foreground'>
              基于仓库中文摘要生成可解释的标签建议，确认后写入标签体系。
            </p>
          </div>
          <Button onClick={handleGenerate} disabled={generating}>
            {generating ? <Loader2 className='animate-spin' /> : <Sparkles />}
            生成建议
          </Button>
        </div>

        <div className='mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>待确认建议</CardDescription>
              <CardTitle className='text-3xl'>{summary?.pending ?? 0}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>覆盖仓库</CardDescription>
              <CardTitle className='text-3xl'>{summary?.repos ?? 0}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>平均置信度</CardDescription>
              <CardTitle className='text-3xl'>
                {formatScore(summary?.avgScore ?? 0)}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription>已采纳</CardDescription>
              <CardTitle className='text-3xl'>{summary?.accepted ?? 0}</CardTitle>
            </CardHeader>
          </Card>
        </div>

        <Card>
          <CardHeader className='flex flex-wrap items-center justify-between gap-3'>
            <div>
              <CardTitle>建议列表</CardTitle>
              <CardDescription>
                {status === 'pending'
                  ? '按仓库分组展示，采纳后自动写入 tags / repo_tags。'
                  : `当前筛选：${FILTER_OPTIONS.find((option) => option.value === status)?.label}`}
              </CardDescription>
            </div>
            <Select
              value={status}
              onValueChange={(value) => setStatus(value as TagSuggestionFilter)}
            >
              <SelectTrigger className='w-[140px]' aria-label='筛选建议状态'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FILTER_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardHeader>
          <CardContent className='space-y-4'>
            {isLoading ? (
              <div className='flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground'>
                <Loader2 className='animate-spin' />
                正在加载建议…
              </div>
            ) : groups.length === 0 ? (
              <div className='flex flex-col items-center gap-2 py-12 text-center'>
                <Tags className='size-8 text-muted-foreground' />
                <p className='font-medium'>暂无建议</p>
                <p className='text-sm text-muted-foreground'>
                  {status === 'pending'
                    ? '点击右上角「生成建议」，从有摘要的仓库中提取标签。'
                    : '当前状态下没有记录。'}
                </p>
              </div>
            ) : (
              groups.map((group) => (
                <Card key={group.repoId} className='overflow-hidden'>
                  <CardHeader className='border-b bg-muted/30 pb-3'>
                    <div className='flex flex-wrap items-start justify-between gap-2'>
                      <div className='min-w-0'>
                        <CardTitle className='flex items-center gap-2 text-base'>
                          <a
                            href={group.repoUrl}
                            target='_blank'
                            rel='noreferrer'
                            className='truncate hover:underline'
                          >
                            {group.repoName}
                          </a>
                          <ExternalLink className='size-3.5 shrink-0 text-muted-foreground' />
                        </CardTitle>
                        <CardDescription className='mt-1 line-clamp-2'>
                          {truncateSummary(group.summary) || '暂无摘要'}
                        </CardDescription>
                      </div>
                      <div className='flex items-center gap-2'>
                        <Badge variant='outline'>
                          平均 {formatScore(group.avgScore)}
                        </Badge>
                        {status === 'pending' && (
                          <Button
                            size='sm'
                            variant='secondary'
                            onClick={() => handleAcceptGroup(group)}
                            disabled={group.items.some((item) => busyIds.includes(item.id))}
                          >
                            <Check />
                            全部采纳
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className='p-0'>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>标签</TableHead>
                          <TableHead>类别</TableHead>
                          <TableHead>置信度</TableHead>
                          <TableHead className='hidden md:table-cell'>依据</TableHead>
                          <TableHead className='text-end'>操作</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {group.items.map((item) => {
                          const busy = busyIds.includes(item.id)
                          return (
                            <TableRow key={item.id}>
                              <TableCell>
                                <Badge variant='outline' className='font-medium'>
                                  {item.tagName}
                                </Badge>
                              </TableCell>
                              <TableCell className='text-muted-foreground'>
                                {categoryLabel(item.category)}
                              </TableCell>
                              <TableCell>
                                <Badge
                                  variant='outline'
                                  className={cn(scoreBadgeClass(scoreTone(item.score)))}
                                >
                                  {formatScore(item.score)}
                                </Badge>
                              </TableCell>
                              <TableCell className='hidden max-w-[420px] md:table-cell'>
                                <p className='truncate text-sm'>{item.reason}</p>
                                <p className='truncate text-xs text-muted-foreground'>
                                  {item.evidence}
                                </p>
                              </TableCell>
                              <TableCell className='text-end'>
                                {item.status === 'pending' ? (
                                  <div className='flex justify-end gap-2'>
                                    <Button
                                      size='sm'
                                      variant='ghost'
                                      onClick={() => handleAccept([item.id])}
                                      disabled={busy}
                                    >
                                      {busy ? <Loader2 className='animate-spin' /> : <Check />}
                                      采纳
                                    </Button>
                                    <Button
                                      size='sm'
                                      variant='ghost'
                                      onClick={() => handleDismiss([item.id])}
                                      disabled={busy}
                                    >
                                      <X />
                                      忽略
                                    </Button>
                                  </div>
                                ) : (
                                  <Badge variant='secondary'>
                                    {item.status === 'accepted' ? '已采纳' : '已忽略'}
                                  </Badge>
                                )}
                              </TableCell>
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              ))
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
