import { useState } from 'react'
import {
  ExternalLink,
  Flame,
  FolderGit2,
  GitMerge,
  Loader2,
  RefreshCw,
  Star,
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
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  dismissDuplicate,
  scanDuplicates,
  type DuplicateCluster,
  type DuplicateScanResponse,
  type DuplicateScope,
} from './api'
import {
  actionLabel,
  fieldLabel,
  formatConfidence,
  formatFieldValue,
  kindLabel,
  memberRoleLabel,
  modeLabel,
  scanSummary,
  scopeLabel,
  sourceLabel,
} from './utils'

const SCOPES: DuplicateScope[] = ['all', 'my', 'trending']

export function DuplicateDetection() {
  const [scope, setScope] = useState<DuplicateScope>('all')
  const [result, setResult] = useState<DuplicateScanResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [dismissing, setDismissing] = useState<Set<string>>(new Set())
  const [error, setError] = useState('')

  async function runScan(nextScope: DuplicateScope = scope) {
    setLoading(true)
    setError('')
    try {
      const response = await scanDuplicates({
        scope: nextScope,
        maxClusters: 50,
      })
      setResult(response)
    } catch {
      setError('扫描失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  async function handleDismiss(cluster: DuplicateCluster) {
    setDismissing((prev) => new Set(prev).add(cluster.id))
    setError('')
    try {
      await dismissDuplicate({
        clusterId: cluster.id,
        repoIds: cluster.members.map(
          (member) => `${member.source}:${member.repoId}`
        ),
      })
      setResult((prev) =>
        prev
          ? {
              ...prev,
              count: Math.max(0, prev.count - 1),
              dismissedCount: prev.dismissedCount + 1,
              clusters: prev.clusters.filter((item) => item.id !== cluster.id),
            }
          : prev
      )
    } catch {
      setError('忽略失败，请稍后重试')
    } finally {
      setDismissing((prev) => {
        const next = new Set(prev)
        next.delete(cluster.id)
        return next
      })
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
        <div className='mb-6 space-y-1'>
          <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
            <GitMerge className='size-6 text-sky-500' />
            重复检测
          </h2>
          <p className='text-sm text-muted-foreground'>
            跨「我的仓库」与「每日热榜」识别重复 /
            相似项目，给出保留项与合并字段建议。检测只读，不会自动修改仓库。
          </p>
        </div>

        <Card className='mb-6'>
          <CardContent className='space-y-4 pt-6'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-xs text-muted-foreground'>扫描范围：</span>
              {SCOPES.map((item) => (
                <Button
                  key={item}
                  type='button'
                  size='sm'
                  variant={scope === item ? 'default' : 'outline'}
                  onClick={() => {
                    setScope(item)
                    if (result) void runScan(item)
                  }}
                >
                  {scopeLabel(item)}
                </Button>
              ))}
              <Button
                type='button'
                className='ms-auto'
                onClick={() => void runScan()}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className='me-1 size-4 animate-spin' />
                ) : (
                  <RefreshCw className='me-1 size-4' />
                )}
                {result ? '重新扫描' : '开始扫描'}
              </Button>
            </div>
            <p className='text-xs text-muted-foreground'>
              名称 /
              简介规则先筛，疑似项再用本地向量余弦复核；置信度低于阈值的命中不会展示。
            </p>
            {error && <p className='text-sm text-destructive'>{error}</p>}
          </CardContent>
        </Card>

        {result && (
          <div className='mb-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
            <Badge variant='secondary'>{modeLabel(result.mode)}</Badge>
            <span>{scanSummary(result)}</span>
            <span>· {result.tookMs} ms</span>
            <span>· 比较 {result.compared.toLocaleString()} 对</span>
            {result.dismissedCount > 0 && (
              <Badge variant='outline'>已忽略 {result.dismissedCount} 组</Badge>
            )}
          </div>
        )}

        <div className='space-y-4'>
          {result?.clusters.map((cluster) => (
            <Card key={cluster.id}>
              <CardHeader>
                <div className='flex flex-wrap items-start justify-between gap-3'>
                  <div className='min-w-0 space-y-1'>
                    <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
                      {kindLabel(cluster.kind)}
                      <Badge>{formatConfidence(cluster.confidence)}</Badge>
                      <Badge variant='outline'>
                        {cluster.members.length} 个条目
                      </Badge>
                    </CardTitle>
                    <CardDescription>
                      {cluster.reasons.join(' · ') || '名称 / 简介规则命中'}
                    </CardDescription>
                  </div>
                  <Button
                    type='button'
                    size='sm'
                    variant='outline'
                    disabled={dismissing.has(cluster.id)}
                    onClick={() => void handleDismiss(cluster)}
                  >
                    {dismissing.has(cluster.id) ? (
                      <Loader2 className='me-1 size-3 animate-spin' />
                    ) : null}
                    忽略此组
                  </Button>
                </div>
              </CardHeader>
              <CardContent className='space-y-4'>
                <div className='space-y-2'>
                  {cluster.members.map((member) => (
                    <div
                      key={`${member.source}:${member.repoId}`}
                      className='rounded-lg border p-3'
                    >
                      <div className='flex flex-wrap items-center gap-2'>
                        <a
                          href={member.url}
                          target='_blank'
                          rel='noreferrer'
                          className='min-w-0 truncate font-medium hover:underline'
                        >
                          {member.fullName}
                          <ExternalLink className='ms-1 inline size-3' />
                        </a>
                        <Badge variant='outline'>
                          {member.source === 'my' ? (
                            <FolderGit2 className='me-1 size-3' />
                          ) : (
                            <Flame className='me-1 size-3' />
                          )}
                          {sourceLabel(member.source)}
                        </Badge>
                        <Badge
                          variant={
                            member.role === 'canonical'
                              ? 'default'
                              : 'secondary'
                          }
                        >
                          {memberRoleLabel(member.role)}
                        </Badge>
                        {member.language && (
                          <Badge variant='outline'>{member.language}</Badge>
                        )}
                        <span className='inline-flex items-center gap-1 text-xs text-muted-foreground'>
                          <Star className='size-3' />
                          {member.stars.toLocaleString()}
                        </span>
                      </div>
                      <p className='mt-1 line-clamp-2 text-sm text-muted-foreground'>
                        {member.description || '暂无项目简介'}
                      </p>
                      {member.techStack.length > 0 && (
                        <div className='mt-2 flex flex-wrap gap-1'>
                          {member.techStack.map((tech) => (
                            <Badge key={tech} variant='outline'>
                              {tech}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className='space-y-2 rounded-lg bg-muted/50 p-3'>
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <span className='text-sm font-medium'>
                      {actionLabel(cluster.suggestion.action)}
                    </span>
                    <span className='text-xs text-muted-foreground'>
                      保留 {cluster.suggestion.keep.repoId} · 合并{' '}
                      {cluster.suggestion.mergeTargets.length} 项
                    </span>
                  </div>
                  {cluster.suggestion.fields.length > 0 && (
                    <ul className='space-y-1 text-xs text-muted-foreground'>
                      {cluster.suggestion.fields.map((field, index) => (
                        <li key={`${field.field}-${index}`}>
                          <span className='font-medium text-foreground'>
                            {fieldLabel(field.field)}：
                          </span>
                          {formatFieldValue(field.value)}
                          <span className='ms-1'>
                            （来自 {field.from.repoId}，{field.reason}）
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className='text-xs text-muted-foreground'>
                    {cluster.suggestion.notes}
                  </p>
                </div>
              </CardContent>
            </Card>
          ))}

          {result && result.clusters.length === 0 && (
            <Card>
              <CardContent className='flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground'>
                <GitMerge className='size-6' />
                <p>没有发现达到阈值的重复项目，当前范围很干净。</p>
              </CardContent>
            </Card>
          )}
        </div>

        {!result && (
          <Card>
            <CardContent className='flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground'>
              <GitMerge className='size-6' />
              <p>选择范围后开始扫描，检测过程只读、可随时忽略误报。</p>
            </CardContent>
          </Card>
        )}
      </Main>
    </>
  )
}
