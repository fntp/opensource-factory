import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Link2,
  Loader2,
  Send,
  Unlink,
} from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  createTelegramLinkCode,
  fetchTelegramBotStatus,
  formatLinkCodeRemaining,
  formatTelegramTime,
  unlinkTelegram,
  type TelegramLinkCode,
} from './telegram-bot-api'

export function TelegramBotPanel() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['telegram-bot-status'],
    queryFn: fetchTelegramBotStatus,
  })
  const [code, setCode] = useState<TelegramLinkCode | null>(null)
  const [busy, setBusy] = useState<'generate' | 'unlink' | null>(null)

  async function handleGenerate() {
    setBusy('generate')
    try {
      const result = await createTelegramLinkCode()
      setCode(result)
      toast.success('绑定码已生成，请在 Telegram 中发送绑定命令')
    } catch {
      toast.error('生成绑定码失败，请确认 Bot 已配置后重试')
    } finally {
      setBusy(null)
    }
  }

  async function handleUnlink() {
    setBusy('unlink')
    try {
      await unlinkTelegram()
      setCode(null)
      await queryClient.invalidateQueries({ queryKey: ['telegram-bot-status'] })
      toast.success('已解绑 Telegram 会话')
    } catch {
      toast.error('解绑失败，请稍后重试')
    } finally {
      setBusy(null)
    }
  }

  async function handleCopy(value: string) {
    try {
      await navigator.clipboard.writeText(value)
      toast.success('已复制到剪贴板')
    } catch {
      toast.error('复制失败，请手动选择文本复制')
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className='flex items-center gap-2 py-6 text-sm text-muted-foreground'>
          <Loader2 className='size-4 animate-spin' />
          正在加载 Telegram Bot 状态…
        </CardContent>
      </Card>
    )
  }

  const status = data
  if (!status) return null

  return (
    <Card>
      <CardHeader>
        <div className='flex flex-wrap items-center gap-2'>
          <CardTitle className='flex items-center gap-2'>
            <Send className='size-4' />
            Telegram 查询 Bot
          </CardTitle>
          <Badge variant={status.configured ? 'default' : 'secondary'}>
            {status.configured ? '已配置' : '未配置'}
          </Badge>
          {status.linked ? (
            <Badge variant='outline' className='gap-1'>
              <CheckCircle2 className='size-3' />
              已绑定
            </Badge>
          ) : null}
        </div>
        <CardDescription>
          在 Telegram 里直接查询收藏、今日推荐与热榜，无需打开控制台。与每日推送共用同一个 Bot。
        </CardDescription>
      </CardHeader>

      <CardContent className='space-y-5'>
        {!status.configured ? (
          <Alert>
            <AlertCircle />
            <AlertDescription>
              尚未配置 Telegram Bot。请先在边缘服务设置 <code>TELEGRAM_BOT_TOKEN</code> 与{' '}
              <code>TELEGRAM_WEBHOOK_SECRET</code>，并将 webhook 指向{' '}
              <code>{status.webhookPath}</code>。
            </AlertDescription>
          </Alert>
        ) : null}

        {status.linked && status.link ? (
          <div className='space-y-4'>
            <div className='rounded-lg border p-4'>
              <div className='flex flex-wrap items-center justify-between gap-3'>
                <div className='space-y-1'>
                  <p className='text-sm font-medium'>
                    {status.link.username
                      ? `@${status.link.username}`
                      : `会话 ${status.link.chatId}`}
                  </p>
                  <p className='text-xs text-muted-foreground'>
                    GitHub 账号 @{status.link.login ?? '未知'} · 绑定于{' '}
                    {formatTelegramTime(status.link.linkedAt)}
                    {status.link.lastSeenAt
                      ? ` · 最近使用 ${formatTelegramTime(status.link.lastSeenAt)}`
                      : ''}
                  </p>
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={busy !== null}
                  onClick={handleUnlink}
                >
                  {busy === 'unlink' ? (
                    <Loader2 className='size-4 animate-spin' />
                  ) : (
                    <Unlink className='size-4' />
                  )}
                  解绑
                </Button>
              </div>
            </div>
            <p className='text-xs text-muted-foreground'>
              会话 ID 已脱敏：{status.link.chatId}。如需换一个 Telegram 账号，先解绑后重新生成绑定码。
            </p>
          </div>
        ) : (
          <div className='space-y-4'>
            <p className='text-sm text-muted-foreground'>
              生成一次性绑定码后，在 Telegram 中向 Bot 发送{' '}
              <code>/link &lt;6 位绑定码&gt;</code> 即可完成绑定。绑定码 10 分钟内有效。
            </p>
            <Button
              type='button'
              disabled={!status.configured || busy !== null}
              onClick={handleGenerate}
            >
              {busy === 'generate' ? (
                <Loader2 className='size-4 animate-spin' />
              ) : (
                <Link2 className='size-4' />
              )}
              生成绑定码
            </Button>

            {code ? (
              <div className='space-y-3 rounded-lg border bg-muted/30 p-4'>
                <div className='flex flex-wrap items-center gap-3'>
                  <span className='font-mono text-3xl tracking-[0.3em]'>{code.code}</span>
                  <Button
                    type='button'
                    variant='ghost'
                    size='sm'
                    onClick={() => handleCopy(code.command)}
                  >
                    <Copy className='size-4' />
                    复制命令
                  </Button>
                </div>
                <p className='text-sm'>
                  发送：<code>{code.command}</code>
                </p>
                <p className='text-xs text-muted-foreground'>
                  {formatLinkCodeRemaining(code.expiresAt)}
                  {code.botUsername ? ` · Bot @${code.botUsername}` : ''}
                </p>
                {code.deepLink ? (
                  <a
                    href={code.deepLink}
                    target='_blank'
                    rel='noreferrer'
                    className='inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline'
                  >
                    在 Telegram 中打开
                    <ExternalLink className='size-3.5' />
                  </a>
                ) : null}
              </div>
            ) : null}
          </div>
        )}

        <Separator />

        <div className='space-y-2'>
          <p className='text-sm font-medium'>可用命令</p>
          <ul className='grid gap-1.5 text-sm text-muted-foreground sm:grid-cols-2'>
            {status.commands.map((item) => (
              <li key={item.command}>
                <code>/{item.command}</code> — {item.description}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}
