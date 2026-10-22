import { useEffect, useRef, useState } from 'react'
import {
  ExternalLink,
  Flame,
  FolderGit2,
  Loader2,
  MessageSquareText,
  RotateCcw,
  Send,
  Sparkles,
  Star,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  chatWithFallback,
  type ChatIntent,
  type ChatMode,
  type ChatResultItem,
  type ChatScopeInput,
  type ChatMessage,
} from './api'
import {
  chatModeLabel,
  chatScopeLabel,
  collectShownIds,
  formatChatTime,
  historyForRequest,
  intentLabel,
  isChatContentValid,
  normalizeChatContent,
} from './chat-utils'
import { scopeLabel } from './utils'

const SCOPES: ChatScopeInput[] = ['auto', 'my', 'trending', 'all']

const EXAMPLES = [
  '我的收藏里有哪些支付相关项目？',
  '热榜里有哪些 AI 相关项目？',
  '推荐一些 Rust 写的工具',
]

interface ChatEntry {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  items?: ChatResultItem[]
  suggestions?: string[]
  meta?: {
    mode: ChatMode
    intent: ChatIntent
    scope: 'my' | 'trending' | 'all'
    language: string
    total: number
    tookMs: number
    turn: number
    fallback?: boolean
  }
}

function entryId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function timestamp(): number {
  return Date.now()
}

const WELCOME: ChatEntry = {
  id: 'welcome',
  role: 'assistant',
  content:
    '你好，我是开源资产问答助手。你可以直接问「我的收藏里有哪些支付相关项目？」，再追问「那 Rust 的呢？」「还有吗？」「只看热榜」。',
  createdAt: Date.now(),
  suggestions: EXAMPLES,
}

export function ConversationalSearch() {
  const [messages, setMessages] = useState<ChatEntry[]>([WELCOME])
  const [scope, setScope] = useState<ChatScopeInput>('auto')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages, loading])

  async function send(raw: string) {
    const content = normalizeChatContent(raw)
    if (!isChatContentValid(content)) {
      setError('请输入 1~500 个字符的提问')
      return
    }
    if (loading) return

    const userEntry: ChatEntry = {
      id: entryId(),
      role: 'user',
      content,
      createdAt: timestamp(),
    }
    const nextMessages = [...messages, userEntry]
    const history: ChatMessage[] = historyForRequest(
      nextMessages.map((entry) => ({
        role: entry.role,
        content: entry.content,
      }))
    )
    const shownIds = collectShownIds(nextMessages)

    setMessages(nextMessages)
    setInput('')
    setError('')
    setLoading(true)
    try {
      const response = await chatWithFallback({
        messages: history,
        shownIds,
        topK: 8,
        scope,
      })
      setMessages((current) => [
        ...current,
        {
          id: entryId(),
          role: 'assistant',
          content: response.answer,
          createdAt: timestamp(),
          items: response.items,
          suggestions: response.suggestions,
          meta: {
            mode: response.mode,
            intent: response.intent,
            scope: response.scope,
            language: response.language,
            total: response.total,
            tookMs: response.tookMs,
            turn: response.turn,
            fallback: response.fallback,
          },
        },
      ])
    } catch {
      setError('问答检索失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setMessages([{ ...WELCOME, createdAt: timestamp() }])
    setScope('auto')
    setInput('')
    setError('')
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
        <div className='mb-6 flex flex-wrap items-start justify-between gap-3'>
          <div className='space-y-1'>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <MessageSquareText className='size-6 text-violet-500' />
              问答检索
            </h2>
            <p className='text-sm text-muted-foreground'>
              用连续追问找项目：系统会继承主题、语言与范围，并排除已经展示过的结果。
            </p>
          </div>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={reset}
            disabled={loading}
          >
            <RotateCcw className='me-1 size-4' />
            新对话
          </Button>
        </div>

        <Card className='mb-4'>
          <CardContent className='flex flex-wrap items-center gap-2 py-3'>
            <span className='text-xs text-muted-foreground'>范围：</span>
            {SCOPES.map((item) => (
              <Button
                key={item}
                type='button'
                size='sm'
                variant={scope === item ? 'default' : 'outline'}
                onClick={() => setScope(item)}
                disabled={loading}
              >
                {chatScopeLabel(item)}
              </Button>
            ))}
            <span className='ms-auto text-xs text-muted-foreground'>
              范围会在下一轮提问时生效
            </span>
          </CardContent>
        </Card>

        <Card className='mb-4'>
          <CardContent className='p-0'>
            <div
              ref={scrollRef}
              className='h-[52vh] min-h-[360px] space-y-4 overflow-y-auto p-4'
              aria-live='polite'
            >
              {messages.map((entry) => (
                <div
                  key={entry.id}
                  className={`flex ${entry.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[92%] space-y-3 rounded-2xl px-4 py-3 text-sm ${
                      entry.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted'
                    }`}
                  >
                    <div className='flex items-start gap-2'>
                      {entry.role === 'assistant' && (
                        <Sparkles className='mt-0.5 size-4 shrink-0 text-violet-500' />
                      )}
                      <p className='leading-relaxed whitespace-pre-line'>
                        {entry.content}
                      </p>
                    </div>

                    {entry.meta && (
                      <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                        <Badge variant='secondary'>
                          {chatModeLabel(entry.meta.mode)}
                        </Badge>
                        <Badge variant='outline'>
                          {intentLabel(entry.meta.intent)}
                        </Badge>
                        <span>{scopeLabel(entry.meta.scope)}</span>
                        {entry.meta.language && (
                          <span>· {entry.meta.language}</span>
                        )}
                        <span>
                          · 共 {entry.meta.total} 个 · {entry.meta.tookMs} ms
                        </span>
                        {entry.meta.fallback && (
                          <Badge variant='destructive'>演示 / 降级</Badge>
                        )}
                        <span className='ms-auto'>
                          {formatChatTime(entry.createdAt)}
                        </span>
                      </div>
                    )}

                    {entry.items && entry.items.length > 0 && (
                      <div className='grid gap-3 md:grid-cols-2'>
                        {entry.items.map((item) => (
                          <div
                            key={`${item.source}:${item.id}`}
                            className='rounded-xl border bg-background p-3'
                          >
                            <div className='flex items-start justify-between gap-2'>
                              <div className='min-w-0'>
                                <a
                                  href={item.url}
                                  target='_blank'
                                  rel='noreferrer'
                                  className='block truncate text-sm font-medium hover:underline'
                                >
                                  [{item.citation}] {item.fullName}
                                </a>
                                <p className='mt-1 line-clamp-2 text-xs text-muted-foreground'>
                                  {item.description || '暂无项目简介'}
                                </p>
                              </div>
                              <Badge variant='outline' className='shrink-0'>
                                {Math.round(
                                  Math.max(0, Math.min(1, item.score)) * 100
                                )}
                                %
                              </Badge>
                            </div>
                            <div className='mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                              <Badge variant='outline'>
                                {item.source === 'my' ? (
                                  <FolderGit2 className='me-1 size-3' />
                                ) : (
                                  <Flame className='me-1 size-3' />
                                )}
                                {item.source === 'my' ? '我的收藏' : '热榜'}
                              </Badge>
                              {item.language && (
                                <Badge variant='outline'>{item.language}</Badge>
                              )}
                              <span className='inline-flex items-center gap-1'>
                                <Star className='size-3' />
                                {item.stars.toLocaleString()}
                              </span>
                              <a
                                href={item.url}
                                target='_blank'
                                rel='noreferrer'
                                className='ms-auto inline-flex items-center gap-1 hover:underline'
                              >
                                查看
                                <ExternalLink className='size-3' />
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {entry.suggestions && entry.suggestions.length > 0 && (
                      <div className='flex flex-wrap gap-2'>
                        {entry.suggestions.map((suggestion) => (
                          <button
                            key={suggestion}
                            type='button'
                            className='rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50'
                            onClick={() => void send(suggestion)}
                            disabled={loading}
                          >
                            {suggestion}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className='flex justify-start'>
                  <div className='flex items-center gap-2 rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground'>
                    <Loader2 className='size-4 animate-spin' />
                    正在检索并整理答案…
                  </div>
                </div>
              )}
            </div>

            <form
              className='flex gap-2 border-t p-3'
              onSubmit={(event) => {
                event.preventDefault()
                void send(input)
              }}
            >
              <Input
                value={input}
                maxLength={500}
                placeholder='继续追问，例如：那 Rust 的呢？'
                onChange={(event) => setInput(event.target.value)}
                aria-label='问答检索提问'
                disabled={loading}
              />
              <Button type='submit' disabled={loading || !input.trim()}>
                {loading ? (
                  <Loader2 className='me-1 size-4 animate-spin' />
                ) : (
                  <Send className='me-1 size-4' />
                )}
                发送
              </Button>
            </form>
          </CardContent>
        </Card>

        {error && <p className='mb-3 text-sm text-destructive'>{error}</p>}

        <p className='text-xs text-muted-foreground'>
          提示：会话只保存在当前页面，刷新后重新开始；答案中的 [n]
          与项目卡片编号对应。
        </p>
      </Main>
    </>
  )
}
