import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { DEMO_MODE } from '@/lib/api'
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
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { triggerSync } from '@/features/tasks/api'
import { fetchRepos, MOCK_REPOS } from './api'

export function Repos() {
  const { data } = useQuery({ queryKey: ['repos'], queryFn: fetchRepos })
  const repos = data ?? MOCK_REPOS
  const [keyword, setKeyword] = useState('')
  const navigate = useNavigate()

  const syncMutation = useMutation({
    mutationFn: triggerSync,
    onSuccess: (result) => {
      if (result.status === 'accepted') {
        toast.info('VPS 节点未配置，同步任务未入队')
        return
      }
      toast.success(
        result.taskId
          ? `同步任务已入队（${result.taskId.slice(0, 8)}）`
          : '同步任务已入队'
      )
      navigate({ to: '/tasks' })
    },
    onError: () => toast.error('触发同步失败，请检查 edge / VPS 配置'),
  })

  const handleSync = () => {
    if (DEMO_MODE) {
      toast.success('已触发 GitHub 仓库同步（演示）')
      return
    }
    syncMutation.mutate()
  }

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    if (!q) return repos
    return repos.filter(
      (r) =>
        r.fullName.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.language.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.tags.some((t) => t.toLowerCase().includes(q))
    )
  }, [repos, keyword])

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
          <Button onClick={handleSync} disabled={syncMutation.isPending}>
            <RefreshCw
              className={syncMutation.isPending ? 'animate-spin' : ''}
            />
            同步仓库
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>仓库列表</CardTitle>
            <CardDescription>共 {filtered.length} 个仓库</CardDescription>
            <Input
              placeholder='搜索仓库、语言、分类或标签…'
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              className='max-w-sm'
            />
          </CardHeader>
          <CardContent>
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
                        {repo.description}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant='secondary'>{repo.category}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className='flex flex-wrap gap-1'>
                        {repo.tags.map((tag) => (
                          <Badge key={tag} variant='outline'>
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className='text-end'>
                      {repo.stars.toLocaleString()}
                    </TableCell>
                    <TableCell className='text-end text-muted-foreground'>
                      {repo.updatedAt}
                    </TableCell>
                  </TableRow>
                ))}
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className='h-24 text-center text-muted-foreground'
                    >
                      没有匹配的仓库。
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
