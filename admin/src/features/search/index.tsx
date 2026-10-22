import { useState } from 'react'
import {
  ExternalLink,
  Flame,
  FolderGit2,
  Loader2,
  Search as SearchIcon,
  Sparkles,
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
import { Input } from '@/components/ui/input'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { searchRepositories, type SearchResponse } from './api'
import {
  formatScore,
  isQueryValid,
  modeLabel,
  normalizeQuery,
  scopeLabel,
  type SearchScope,
} from './utils'

const EXAMPLES = [
  '支持多租户的 NestJS 管理后台模板',
  '轻量级 Python 任务调度工具',
  '带实时协作的 React 富文本编辑器',
]

const SCOPES: SearchScope[] = ['all', 'my', 'trending']

export function SemanticSearch() {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<SearchScope>('all')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function runSearch(rawQuery: string, nextScope: SearchScope = scope) {
    const normalized = normalizeQuery(rawQuery)
    if (!isQueryValid(normalized)) {
      setError('请输入 1~200 个字符的检索内容')
      return
    }
    setQuery(normalized)
    setLoading(true)
    setError('')
    try {
      const response = await searchRepositories({
        query: normalized,
        topK: 10,
        scope: nextScope,
      })
      setResult(response)
    } catch {
      setError('检索失败，请稍后重试')
    } finally {
      setLoading(false)
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
            <Sparkles className='size-6 text-violet-500' />
            语义搜索
          </h2>
          <p className='text-sm text-muted-foreground'>
            用自然语言描述你需要的项目，跨「我的仓库」与「每日热榜」做语义匹配。
          </p>
        </div>

        <Card className='mb-6'>
          <CardContent className='space-y-4 pt-6'>
            <form
              className='flex flex-col gap-2 sm:flex-row'
              onSubmit={(event) => {
                event.preventDefault()
                void runSearch(query)
              }}
            >
              <Input
                value={query}
                maxLength={200}
                placeholder='例如：支持多租户的 NestJS 管理后台模板'
                onChange={(event) => setQuery(event.target.value)}
                aria-label='语义搜索查询'
              />
              <Button type='submit' disabled={loading}>
                {loading ? (
                  <Loader2 className='me-1 size-4 animate-spin' />
                ) : (
                  <SearchIcon className='me-1 size-4' />
                )}
                搜索
              </Button>
            </form>

            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-xs text-muted-foreground'>范围：</span>
              {SCOPES.map((item) => (
                <Button
                  key={item}
                  type='button'
                  size='sm'
                  variant={scope === item ? 'default' : 'outline'}
                  onClick={() => {
                    setScope(item)
                    if (result) void runSearch(query, item)
                  }}
                >
                  {scopeLabel(item)}
                </Button>
              ))}
            </div>

            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-xs text-muted-foreground'>试试：</span>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type='button'
                  className='rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground'
                  onClick={() => void runSearch(example)}
                >
                  {example}
                </button>
              ))}
            </div>

            {error && <p className='text-sm text-destructive'>{error}</p>}
          </CardContent>
        </Card>

        {result && (
          <div className='mb-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
            <Badge variant='secondary'>{modeLabel(result.mode)}</Badge>
            <span>
              共 {result.count} 条结果 · {result.tookMs} ms
              {result.model ? ` · ${result.model}` : ''}
              {result.dim ? ` · ${result.dim} 维` : ''}
            </span>
          </div>
        )}

        <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
          {result?.items.map((item) => (
            <Card key={`${item.source}:${item.id}`} className='flex flex-col'>
              <CardHeader>
                <div className='flex items-start justify-between gap-2'>
                  <div className='min-w-0'>
                    <CardTitle className='truncate text-base'>
                      <a
                        href={item.url}
                        target='_blank'
                        rel='noreferrer'
                        className='hover:underline'
                      >
                        {item.fullName}
                      </a>
                    </CardTitle>
                    <CardDescription className='mt-1 line-clamp-3'>
                      {item.description || '暂无项目简介'}
                    </CardDescription>
                  </div>
                  <Badge className='shrink-0'>{formatScore(item.score)}</Badge>
                </div>
              </CardHeader>
              <CardContent className='flex flex-1 flex-col justify-between gap-4'>
                <p className='text-sm text-muted-foreground'>{item.reason}</p>
                <div className='space-y-3'>
                  <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                    <Badge variant='outline'>
                      {item.source === 'my' ? (
                        <FolderGit2 className='me-1 size-3' />
                      ) : (
                        <Flame className='me-1 size-3' />
                      )}
                      {item.source === 'my' ? '我的仓库' : '热榜'}
                    </Badge>
                    {item.language && (
                      <Badge variant='outline'>{item.language}</Badge>
                    )}
                    <span className='inline-flex items-center gap-1'>
                      <Star className='size-3' />
                      {item.stars.toLocaleString()}
                    </span>
                    {item.starsToday > 0 && (
                      <span className='inline-flex items-center gap-1'>
                        <Flame className='size-3' />
                        今日 +{item.starsToday}
                      </span>
                    )}
                  </div>
                  <Button size='sm' variant='outline' asChild>
                    <a href={item.url} target='_blank' rel='noreferrer'>
                      查看仓库
                      <ExternalLink className='ms-1 size-3' />
                    </a>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}

          {result && result.items.length === 0 && (
            <Card className='md:col-span-2 xl:col-span-3'>
              <CardContent className='flex h-40 items-center justify-center text-muted-foreground'>
                没有找到语义相近的项目，换个描述试试吧。
              </CardContent>
            </Card>
          )}
        </div>

        {!result && (
          <Card>
            <CardContent className='flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground'>
              <SearchIcon className='size-6' />
              <p>输入自然语言描述开始检索，支持中文与英文。</p>
            </CardContent>
          </Card>
        )}
      </Main>
    </>
  )
}
