import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderGit2, RefreshCw, SearchX } from 'lucide-react'
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { EmptyState, ErrorState, LoadingState } from '@/components/data-state'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { apiErrorMessage } from '@/lib/api'
import { fetchRepos, triggerSync } from './api'

function formatDate(value: string | null): string {
  if (!value) return '—'
  const normalized = value.includes('T')
    ? value
    : `${value.replace(' ', 'T')}Z`
  const ts = Date.parse(normalized)
  return Number.isFinite(ts)
    ? new Date(ts).toLocaleDateString('zh-CN')
    : value
}

export function Repos() {
  const queryClient = useQueryClient()
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['repos'],
    queryFn: fetchRepos,
  })
  const [keyword, setKeyword] = useState('')

  const syncMutation = useMutation({
    mutationFn: triggerSync,
    onSuccess: (result) => {
      if (result.note === 'vps node not configured') {
        toast.warning('同步请求已接受，但 VPS 节点尚未配置，未实际执行')
      } else {
        toast.success(
          result.taskId
            ? `同步任务已排队（${result.taskId}）`
            : '同步任务已排队'
        )
      }
      void queryClient.invalidateQueries({ queryKey: ['repos'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] })
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, '触发同步失败，请稍后重试'))
    },
  })

  const repos = useMemo(() => data ?? [], [data])
  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    if (!q) return repos
    return repos.filter(
      (r) =>
        r.fullName.toLowerCase().includes(q) ||
        (r.description ?? '').toLowerCase().includes(q) ||
        (r.language ?? '').toLowerCase().includes(q) ||
        (r.category ?? '').toLowerCase().includes(q) ||
        r.tags.some((t) => t.toLowerCase().includes(q))
    )
  }, [repos, keyword])

  const syncButton = (
    <Button
      onClick={() => syncMutation.mutate()}
      disabled={syncMutation.isPending}
    >
      <RefreshCw
        className={syncMutation.isPending ? 'animate-spin' : undefined}
      />
      {syncMutation.isPending ? '正在触发…' : '同步仓库'}
    </Button>
  )

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
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>我的仓库</h2>
            <p className='text-sm text-muted-foreground'>
              已同步的 GitHub 仓库，支持按分类、标签与关键词快速查找。
            </p>
          </div>
          {syncButton}
        </div>

        <Card>
          <CardHeader>
            <CardTitle>仓库列表</CardTitle>
            <CardDescription>
              {isPending || isError
                ? '仓库数据'
                : `共 ${repos.length} 个仓库${keyword ? `，匹配 ${filtered.length} 个` : ''}`}
            </CardDescription>
            <Input
              placeholder='搜索仓库、语言、分类或标签…'
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              className='max-w-sm'
              disabled={isPending || isError}
            />
          </CardHeader>
          <CardContent>
            {isPending ? (
              <LoadingState label='正在加载仓库…' rows={5} />
            ) : isError ? (
              <ErrorState
                error={error}
                title='仓库加载失败'
                onRetry={() => void refetch()}
              />
            ) : repos.length === 0 ? (
              <EmptyState
                icon={FolderGit2}
                title='还没有同步任何仓库'
                description='同步你的 GitHub 仓库后，就可以在这里分类、打标签并获取推荐。'
                action={syncButton}
              />
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={SearchX}
                title='没有匹配的仓库'
                description={`没有找到与「${keyword.trim()}」相关的仓库，换个关键词试试。`}
                action={
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={() => setKeyword('')}
                  >
                    清除搜索
                  </Button>
                }
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>仓库</TableHead>
                    <TableHead>分类</TableHead>
                    <TableHead>标签</TableHead>
                    <TableHead className='text-end'>Stars</TableHead>
                    <TableHead className='text-end'>最近更新</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((repo) => (
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
                          {repo.description ?? '暂无描述'}
                        </div>
                      </TableCell>
                      <TableCell>
                        {repo.category ? (
                          <Badge variant='secondary'>{repo.category}</Badge>
                        ) : (
                          <span className='text-sm text-muted-foreground'>
                            未分类
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className='flex flex-wrap gap-1'>
                          {repo.tags.length > 0 ? (
                            repo.tags.map((tag) => (
                              <Badge key={tag} variant='outline'>
                                {tag}
                              </Badge>
                            ))
                          ) : (
                            <span className='text-sm text-muted-foreground'>
                              —
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className='text-end'>
                        {repo.stars.toLocaleString()}
                      </TableCell>
                      <TableCell className='text-end text-muted-foreground'>
                        {formatDate(repo.updatedAt)}
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
