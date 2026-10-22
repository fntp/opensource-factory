import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { RefreshCw, X } from 'lucide-react'
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
  fetchCategories,
  MOCK_CATEGORIES,
  MOCK_TAGS,
} from '@/features/categories/api'
import { fetchRepos, MOCK_REPOS, type RepoItem } from './api'
import { RepoFilterBar } from './filter-bar'
import {
  buildReposQuery,
  countActiveFilters,
  DEFAULT_REPO_FILTERS,
  STAR_RANGE_OPTIONS,
  TIME_RANGE_OPTIONS,
  type RepoFilters,
} from './filters'
import { useDebouncedValue } from './use-debounced-value'

function formatDate(value: string | null): string {
  return value ? value.slice(0, 10) : '—'
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string
  onRemove: () => void
}) {
  return (
    <Badge variant='secondary' className='gap-1 font-normal'>
      {label}
      <button
        type='button'
        onClick={onRemove}
        className='rounded-sm opacity-60 hover:opacity-100'
        aria-label={`移除筛选：${label}`}
      >
        <X className='size-3' />
      </button>
    </Badge>
  )
}

export function Repos() {
  const [filters, setFilters] = useState<RepoFilters>(DEFAULT_REPO_FILTERS)
  const [keywordInput, setKeywordInput] = useState('')
  const keyword = useDebouncedValue(keywordInput, 300)
  const effectiveFilters = useMemo(
    () => ({ ...filters, keyword }),
    [filters, keyword]
  )
  const query = buildReposQuery(effectiveFilters)

  // query 是 effectiveFilters 的稳定序列化，已覆盖全部筛选字段
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const { data, isFetching } = useQuery({
    queryKey: ['repos', query],
    queryFn: () => fetchRepos(effectiveFilters),
    placeholderData: keepPreviousData,
  })

  // 全量仓库用于提取语言选项；与默认列表共用同一个缓存键。
  const { data: facetRepos } = useQuery({
    queryKey: ['repos', ''],
    queryFn: () => fetchRepos(DEFAULT_REPO_FILTERS),
    staleTime: 5 * 60 * 1000,
  })

  const { data: categoryData } = useQuery({
    queryKey: ['categories'],
    queryFn: fetchCategories,
  })

  const categories = categoryData?.categories ?? MOCK_CATEGORIES
  const tags = categoryData?.tags ?? MOCK_TAGS
  const repos = data ?? MOCK_REPOS
  const activeCount = countActiveFilters(effectiveFilters)

  const languages = useMemo(() => {
    const values = (facetRepos ?? MOCK_REPOS)
      .map((repo) => repo.language)
      .filter((value): value is string => Boolean(value))
    return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b))
  }, [facetRepos])

  const categoryName = categories.find(
    (category) => category.id === filters.categoryId
  )?.name
  const starRangeLabel = STAR_RANGE_OPTIONS.find(
    (option) => option.value === filters.starRange
  )?.label
  const timeRangeLabel = TIME_RANGE_OPTIONS.find(
    (option) => option.value === filters.timeRange
  )?.label

  const patchFilters = (patch: Partial<RepoFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }))
  }

  const resetFilters = () => {
    setFilters(DEFAULT_REPO_FILTERS)
    setKeywordInput('')
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
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>我的仓库</h2>
            <p className='text-sm text-muted-foreground'>
              已同步的 GitHub 仓库，支持按分类、标签、语言、Star
              与时间组合筛选和排序。
            </p>
          </div>
          <Button
            onClick={() => toast.success('已触发 GitHub 仓库同步（演示）')}
          >
            <RefreshCw />
            同步仓库
          </Button>
        </div>

        <Card>
          <CardHeader className='space-y-3'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <div>
                <CardTitle className='flex items-center gap-2'>
                  仓库列表
                  {DEMO_MODE && (
                    <Badge variant='outline' className='font-normal'>
                      演示数据
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  共 {repos.length} 个仓库
                  {activeCount > 0 ? '（已按筛选条件收窄）' : ''}
                  {isFetching ? ' · 加载中…' : ''}
                </CardDescription>
              </div>
            </div>

            <RepoFilterBar
              filters={effectiveFilters}
              keyword={keywordInput}
              categories={categories}
              tags={tags}
              languages={languages}
              onKeywordChange={setKeywordInput}
              onChange={patchFilters}
              onReset={resetFilters}
            />

            {activeCount > 0 && (
              <div className='flex flex-wrap items-center gap-1.5'>
                {filters.keyword.trim() && (
                  <FilterChip
                    label={`关键词：${filters.keyword.trim()}`}
                    onRemove={() => setKeywordInput('')}
                  />
                )}
                {filters.categoryId && categoryName && (
                  <FilterChip
                    label={`分类：${categoryName}`}
                    onRemove={() => patchFilters({ categoryId: '' })}
                  />
                )}
                {filters.tagNames.map((tag) => (
                  <FilterChip
                    key={`tag-${tag}`}
                    label={`标签：${tag}`}
                    onRemove={() =>
                      patchFilters({
                        tagNames: filters.tagNames.filter(
                          (item) => item !== tag
                        ),
                      })
                    }
                  />
                ))}
                {filters.languages.map((language) => (
                  <FilterChip
                    key={`language-${language}`}
                    label={`语言：${language}`}
                    onRemove={() =>
                      patchFilters({
                        languages: filters.languages.filter(
                          (item) => item !== language
                        ),
                      })
                    }
                  />
                ))}
                {filters.starRange !== 'all' && (
                  <FilterChip
                    label={`Star：${starRangeLabel}`}
                    onRemove={() => patchFilters({ starRange: 'all' })}
                  />
                )}
                {filters.timeRange !== 'all' && (
                  <FilterChip
                    label={`更新：${timeRangeLabel}`}
                    onRemove={() => patchFilters({ timeRange: 'all' })}
                  />
                )}
              </div>
            )}
          </CardHeader>

          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>仓库</TableHead>
                  <TableHead>分类</TableHead>
                  <TableHead>标签</TableHead>
                  <TableHead>语言</TableHead>
                  <TableHead className='text-end'>Stars</TableHead>
                  <TableHead className='text-end'>最近更新</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {repos.map((repo) => (
                  <RepoRow key={repo.id} repo={repo} />
                ))}
                {repos.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className='h-24 text-center text-muted-foreground'
                    >
                      <div className='space-y-2'>
                        <p>没有匹配的仓库，试试放宽筛选条件。</p>
                        <Button
                          variant='outline'
                          size='sm'
                          onClick={resetFilters}
                        >
                          清除全部筛选
                        </Button>
                      </div>
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

function RepoRow({ repo }: { repo: RepoItem }) {
  return (
    <TableRow>
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
          {repo.description ?? '—'}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant='secondary'>{repo.category ?? '未分类'}</Badge>
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
            <span className='text-sm text-muted-foreground'>—</span>
          )}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant='outline'>{repo.language ?? '—'}</Badge>
      </TableCell>
      <TableCell className='text-end'>{repo.stars.toLocaleString()}</TableCell>
      <TableCell className='text-end text-muted-foreground'>
        {formatDate(repo.updatedAt)}
      </TableCell>
    </TableRow>
  )
}
