import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
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
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { LicenseBadge } from '@/features/licenses/license-badge'
import { fetchRepos, MOCK_REPOS } from './api'

export function Repos() {
  const { data } = useQuery({ queryKey: ['repos'], queryFn: fetchRepos })
  const repos = data ?? MOCK_REPOS
  const [keyword, setKeyword] = useState('')

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    if (!q) return repos
    return repos.filter(
      (r) =>
        r.fullName.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        (r.summary ?? '').toLowerCase().includes(q) ||
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
          <Button onClick={() => toast.success('已触发 GitHub 仓库同步（演示）')}>
            <RefreshCw />
            同步仓库
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>仓库列表</CardTitle>
            <CardDescription>
              共 {filtered.length} 个仓库
            </CardDescription>
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
                  <TableHead>License</TableHead>
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
                      {repo.summary && (
                        <div className='max-w-100 truncate text-xs text-muted-foreground/70'>
                          摘要：{repo.summary}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant='secondary'>{repo.category}</Badge>
                    </TableCell>
                    <TableCell>
                      <LicenseBadge license={repo.license} />
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
                      colSpan={6}
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
