import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  FileText,
  FolderTree,
  History,
  ListChecks,
  Loader2,
  Play,
  Sparkles,
  Tag,
  XCircle,
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { cn } from '@/lib/utils'
import {
  createAgentRun,
  downloadAgentDraft,
  fetchAgentDrafts,
  fetchAgentRun,
  fetchAgentRuns,
  fetchAgentTemplates,
  MOCK_AGENT_TEMPLATES,
  updateAgentDraftStatus,
  type AgentDraft,
  type AgentMode,
  type AgentTemplate,
  type AgentTemplateDefinition,
} from './api'
import {
  agentDraftStatusLabel,
  agentModeLabel,
  agentRunStatusLabel,
  agentStatCards,
  agentTemplateLabel,
  formatAgentCount,
  formatAgentThreshold,
  formatAgentTime,
} from './utils'

function TemplatePicker({
  items,
  value,
  onChange,
}: {
  items: AgentTemplateDefinition[]
  value: AgentTemplate
  onChange: (item: AgentTemplateDefinition) => void
}) {
  return (
    <div className='space-y-2'>
      {items.map((item) => (
        <button
          key={item.key}
          type='button'
          onClick={() => onChange(item)}
          className={cn(
            'w-full rounded-lg border p-3 text-left transition-colors',
            item.key === value ? 'border-primary bg-muted/60' : 'hover:bg-muted/40'
          )}
        >
          <div className='flex items-center gap-2'>
            <span className='text-sm font-medium'>{item.title}</span>
            {item.key === 'full' && <Badge variant='secondary'>推荐</Badge>}
          </div>
          <p className='mt-1 text-xs leading-relaxed text-muted-foreground'>
            {item.description}
          </p>
        </button>
      ))}
    </div>
  )
}

function RunHistory({
  runs,
  activeId,
  onSelect,
}: {
  runs: ReturnType<typeof useAgentRuns>['runs']
  activeId: string | null
  onSelect: (id: string) => void
}) {
  if (runs.length === 0) {
    return (
      <p className='py-6 text-center text-sm text-muted-foreground'>
        还没有执行记录，先运行一次工作流。
      </p>
    )
  }
  return (
    <div className='space-y-2'>
      {runs.map((run) => (
        <button
          key={run.id}
          type='button'
          onClick={() => onSelect(run.id)}
          className={cn(
            'w-full rounded-lg border p-3 text-left transition-colors',
            run.id === activeId ? 'border-primary bg-muted/60' : 'hover:bg-muted/40'
          )}
        >
          <div className='flex flex-wrap items-center gap-2'>
            <span className='text-sm font-medium'>{agentTemplateLabel(run.template)}</span>
            <Badge variant='outline'>{agentModeLabel(run.mode)}</Badge>
            <Badge variant={run.status === 'completed' ? 'secondary' : 'destructive'}>
              {agentRunStatusLabel(run.status)}
            </Badge>
            <span className='ms-auto inline-flex items-center gap-1 text-xs text-muted-foreground'>
              <Clock className='size-3' />
              {formatAgentTime(run.createdAt)}
            </span>
          </div>
          <p className='mt-1 text-xs text-muted-foreground'>
            {formatAgentCount(run.repoCount)} 个收藏 · 阈值{' '}
            {formatAgentThreshold(run.threshold)}
          </p>
        </button>
      ))}
    </div>
  )
}

// 仅为 RunHistory 的类型推导提供稳定的返回形状
function useAgentRuns() {
  const query = useQuery({ queryKey: ['agent', 'runs'], queryFn: fetchAgentRuns })
  return { query, runs: query.data?.items ?? [] }
}

function DraftList({
  drafts,
  onStatusChange,
  busyId,
}: {
  drafts: AgentDraft[]
  onStatusChange: (id: string, status: 'applied' | 'discarded') => void
  busyId: string | null
}) {
  if (drafts.length === 0) {
    return (
      <p className='py-6 text-center text-sm text-muted-foreground'>
        还没有草稿，运行「收藏草稿」或「整理 + 草稿」模板即可生成。
      </p>
    )
  }
  return (
    <div className='space-y-2'>
      {drafts.map((draft) => (
        <div key={draft.id} className='rounded-lg border p-3'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='text-sm font-medium'>{draft.title}</span>
            <Badge variant={draft.status === 'draft' ? 'outline' : 'secondary'}>
              {agentDraftStatusLabel(draft.status)}
            </Badge>
            <span className='ms-auto text-xs text-muted-foreground'>
              {formatAgentTime(draft.updatedAt)}
            </span>
          </div>
          <div className='mt-2 flex flex-wrap items-center gap-2'>
            <Button
              size='sm'
              variant='outline'
              onClick={() => downloadAgentDraft(draft)}
            >
              <Download className='size-3.5' />
              下载
            </Button>
            {draft.status === 'draft' && (
              <>
                <Button
                  size='sm'
                  variant='outline'
                  disabled={busyId === draft.id}
                  onClick={() => onStatusChange(draft.id, 'applied')}
                >
                  {busyId === draft.id ? (
                    <Loader2 className='size-3.5 animate-spin' />
                  ) : (
                    <CheckCircle2 className='size-3.5' />
                  )}
                  标记已采用
                </Button>
                <Button
                  size='sm'
                  variant='ghost'
                  disabled={busyId === draft.id}
                  onClick={() => onStatusChange(draft.id, 'discarded')}
                >
                  <XCircle className='size-3.5' />
                  丢弃
                </Button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export function AgentWorkflow() {
  const [template, setTemplate] = useState<AgentTemplate>('full')
  const [mode, setMode] = useState<AgentMode>('apply')
  const [threshold, setThreshold] = useState(0.75)
  const [focus, setFocus] = useState('')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [draftBusyId, setDraftBusyId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const templatesQuery = useQuery({
    queryKey: ['agent', 'templates'],
    queryFn: fetchAgentTemplates,
  })
  const templates = templatesQuery.data?.items ?? MOCK_AGENT_TEMPLATES
  const { query: runsQuery, runs } = useAgentRuns()
  const activeId =
    activeRunId && runs.some((run) => run.id === activeRunId)
      ? activeRunId
      : (runs[0]?.id ?? null)

  const detailQuery = useQuery({
    queryKey: ['agent', 'run', activeId],
    queryFn: () => fetchAgentRun(activeId as string),
    enabled: Boolean(activeId),
  })
  const detail = detailQuery.data ?? null

  const draftsQuery = useQuery({
    queryKey: ['agent', 'drafts'],
    queryFn: fetchAgentDrafts,
  })
  const drafts = draftsQuery.data?.items ?? []

  function handleTemplateChange(item: AgentTemplateDefinition) {
    setTemplate(item.key)
    setMode(item.defaultMode)
    setThreshold(item.defaultThreshold)
  }

  async function handleRun() {
    setCreating(true)
    try {
      const created = await createAgentRun({
        template,
        mode,
        threshold,
        focus: focus.trim() || null,
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['agent', 'runs'] }),
        queryClient.invalidateQueries({ queryKey: ['agent', 'drafts'] }),
      ])
      setActiveRunId(created.id)
      toast.success(`${agentTemplateLabel(template)}执行完成`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '执行 Agent 工作流失败')
    } finally {
      setCreating(false)
    }
  }

  async function handleCopy(draft: AgentDraft) {
    try {
      await navigator.clipboard.writeText(draft.content)
      toast.success('Markdown 已复制')
    } catch {
      toast.error('复制失败，请手动选择内容')
    }
  }

  async function handleDraftStatus(id: string, status: 'applied' | 'discarded') {
    setDraftBusyId(id)
    try {
      await updateAgentDraftStatus(id, status)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['agent', 'drafts'] }),
        queryClient.invalidateQueries({ queryKey: ['agent', 'run', activeId] }),
      ])
      toast.success(status === 'applied' ? '草稿已标记为已采用' : '草稿已丢弃')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新草稿状态失败')
    } finally {
      setDraftBusyId(null)
    }
  }

  const statCards = detail ? agentStatCards(detail.result.stats) : []

  return (
    <>
      <Header>
        <h1 className='me-auto text-lg font-semibold'>Agent 工作流</h1>
        <Search />
        <ThemeSwitch />
        <ConfigDrawer />
        <ProfileDropdown />
      </Header>

      <Main>
        <div className='mb-4'>
          <div className='flex flex-wrap items-center gap-2'>
            <h2 className='text-2xl font-bold tracking-tight'>Agent 工作流</h2>
            <Badge variant='outline'>M7-09</Badge>
          </div>
          <p className='text-sm text-muted-foreground'>
            把标签建议、分类建议与报告能力串成一条可回放的工作流：先整理，再生成可编辑的收藏草稿。
          </p>
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-12'>
          <Card className='lg:col-span-4'>
            <CardHeader>
              <CardTitle className='flex items-center gap-2 text-base'>
                <Bot className='size-4' />
                新建执行
              </CardTitle>
              <CardDescription>选择模板与参数，预览或直接应用整理动作。</CardDescription>
            </CardHeader>
            <CardContent className='space-y-4'>
              <div className='space-y-2'>
                <Label>工作流模板</Label>
                <TemplatePicker
                  items={templates}
                  value={template}
                  onChange={handleTemplateChange}
                />
              </div>

              <div className='space-y-2'>
                <Label>执行模式</Label>
                <div className='inline-flex w-full rounded-lg border p-1'>
                  {(['preview', 'apply'] as AgentMode[]).map((item) => (
                    <Button
                      key={item}
                      size='sm'
                      variant={mode === item ? 'default' : 'ghost'}
                      className='flex-1'
                      onClick={() => setMode(item)}
                    >
                      {agentModeLabel(item)}
                    </Button>
                  ))}
                </div>
                <p className='text-xs text-muted-foreground'>
                  {mode === 'apply'
                    ? '达到阈值的建议会写入标签 / 分类。'
                    : '只生成计划与草稿，不改动现有数据。'}
                </p>
              </div>

              <div className='space-y-2'>
                <div className='flex items-center justify-between'>
                  <Label htmlFor='agent-threshold'>置信度阈值</Label>
                  <span className='text-sm font-medium tabular-nums'>
                    {formatAgentThreshold(threshold)}
                  </span>
                </div>
                <input
                  id='agent-threshold'
                  type='range'
                  min={0.5}
                  max={1}
                  step={0.05}
                  value={threshold}
                  onChange={(event) => setThreshold(Number(event.target.value))}
                  className='w-full accent-primary'
                />
              </div>

              <div className='space-y-2'>
                <Label htmlFor='agent-focus'>关注主题（可选）</Label>
                <Input
                  id='agent-focus'
                  value={focus}
                  maxLength={120}
                  placeholder='例如：AI Agent 工具'
                  onChange={(event) => setFocus(event.target.value)}
                />
                <p className='text-xs text-muted-foreground'>
                  会写进草稿标题，便于区分不同主题的产出。
                </p>
              </div>

              <Button className='w-full' onClick={() => void handleRun()} disabled={creating}>
                {creating ? <Loader2 className='size-4 animate-spin' /> : <Play className='size-4' />}
                执行工作流
              </Button>
            </CardContent>
          </Card>

          <div className='space-y-4 lg:col-span-8'>
            {detailQuery.isLoading ? (
              <Card>
                <CardContent className='flex items-center justify-center gap-2 py-16 text-muted-foreground'>
                  <Loader2 className='h-5 w-5 animate-spin' />
                  正在加载执行详情…
                </CardContent>
              </Card>
            ) : !detail ? (
              <Card>
                <CardContent className='flex flex-col items-center justify-center gap-3 py-16 text-center'>
                  <Sparkles className='h-10 w-10 text-muted-foreground' />
                  <div>
                    <p className='font-medium'>还没有执行记录</p>
                    <p className='mt-1 text-sm text-muted-foreground'>
                      在左侧选择模板并执行，计划和草稿会在这里展示。
                    </p>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <>
                <Card>
                  <CardHeader>
                    <div className='flex flex-wrap items-center gap-2'>
                      <CardTitle className='text-base'>
                        {agentTemplateLabel(detail.template)} · {agentModeLabel(detail.mode)}
                      </CardTitle>
                      <Badge variant={detail.status === 'completed' ? 'secondary' : 'destructive'}>
                        {agentRunStatusLabel(detail.status)}
                      </Badge>
                      <Badge variant='outline'>阈值 {formatAgentThreshold(detail.threshold)}</Badge>
                      <span className='ms-auto text-xs text-muted-foreground'>
                        {formatAgentTime(detail.createdAt)}
                      </span>
                    </div>
                    <CardDescription>
                      处理 {formatAgentCount(detail.repoCount)} 个收藏；结果来源：
                      {detail.result.source === 'vps' ? 'VPS 规划' : '本地规则兜底'}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className='space-y-4'>
                    <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
                      {statCards.map((card) => (
                        <div key={card.title} className='rounded-lg border bg-muted/30 p-3'>
                          <p className='text-xs text-muted-foreground'>{card.title}</p>
                          <p className='mt-1 text-xl font-bold tabular-nums'>{card.value}</p>
                          <p className='mt-1 text-xs text-muted-foreground'>{card.hint}</p>
                        </div>
                      ))}
                    </div>

                    <div>
                      <h3 className='mb-2 flex items-center gap-2 text-sm font-medium'>
                        <ListChecks className='size-4' />
                        执行计划
                      </h3>
                      <div className='space-y-2'>
                        {detail.plan.map((step) => (
                          <div
                            key={step.key}
                            className={cn(
                              'rounded-lg border p-3',
                              step.status === 'skipped' && 'opacity-60'
                            )}
                          >
                            <div className='flex flex-wrap items-center gap-2'>
                              <span className='text-sm font-medium'>{step.title}</span>
                              <Badge variant='outline'>{formatAgentCount(step.count)}</Badge>
                              <Badge variant={step.status === 'ready' ? 'secondary' : 'outline'}>
                                {step.status === 'ready' ? '就绪' : '跳过'}
                              </Badge>
                            </div>
                            <p className='mt-1 text-xs text-muted-foreground'>{step.detail}</p>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className='flex flex-wrap gap-4 text-sm'>
                      <span className='inline-flex items-center gap-1 text-muted-foreground'>
                        <Tag className='size-4' />
                        应用标签 {formatAgentCount(detail.result.appliedTags.length)} 条
                      </span>
                      <span className='inline-flex items-center gap-1 text-muted-foreground'>
                        <FolderTree className='size-4' />
                        应用分类 {formatAgentCount(detail.result.appliedCategories.length)} 条
                      </span>
                      <span className='inline-flex items-center gap-1 text-muted-foreground'>
                        <History className='size-4' />
                        待处理建议 {formatAgentCount(detail.result.pendingTags)} /{' '}
                        {formatAgentCount(detail.result.pendingCategories)}
                      </span>
                    </div>
                  </CardContent>
                </Card>

                {detail.draft && (
                  <Card>
                    <CardHeader>
                      <div className='flex flex-wrap items-center gap-2'>
                        <CardTitle className='flex items-center gap-2 text-base'>
                          <FileText className='size-4' />
                          {detail.draft.title}
                        </CardTitle>
                        <Badge variant='outline'>
                          {agentDraftStatusLabel(detail.draft.status)}
                        </Badge>
                        <div className='ms-auto flex items-center gap-2'>
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => void handleCopy(detail.draft as AgentDraft)}
                          >
                            <Copy className='size-3.5' />
                            复制
                          </Button>
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => downloadAgentDraft(detail.draft as AgentDraft)}
                          >
                            <Download className='size-3.5' />
                            下载
                          </Button>
                        </div>
                      </div>
                      <CardDescription>
                        {detail.draft.metadata.highlights.join('；')}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <pre className='max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/30 p-4 font-mono text-xs leading-relaxed'>
                        {detail.draft.content}
                      </pre>
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </div>
        </div>

        <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2'>
          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2 text-base'>
                <History className='size-4' />
                执行记录
              </CardTitle>
              <CardDescription>保留每次执行的计划与结果，可随时回放。</CardDescription>
            </CardHeader>
            <CardContent>
              {runsQuery.isLoading ? (
                <p className='py-6 text-center text-sm text-muted-foreground'>加载中…</p>
              ) : (
                <RunHistory runs={runs} activeId={activeId} onSelect={setActiveRunId} />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2 text-base'>
                <FileText className='size-4' />
                草稿箱
              </CardTitle>
              <CardDescription>生成后可编辑、下载，并标记采用或丢弃。</CardDescription>
            </CardHeader>
            <CardContent>
              {draftsQuery.isLoading ? (
                <p className='py-6 text-center text-sm text-muted-foreground'>加载中…</p>
              ) : (
                <DraftList
                  drafts={drafts}
                  busyId={draftBusyId}
                  onStatusChange={(id, status) => void handleDraftStatus(id, status)}
                />
              )}
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}
