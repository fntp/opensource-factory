import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { ApiHttpError, DEMO_MODE } from '@/lib/api'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ContentSection } from '../settings/components/content-section'
import {
  createExtensionToken,
  EXTENSION_INSTALL_STEPS,
  extensionApiBase,
  fetchExtensionTokens,
  formatTokenDate,
  revokeExtensionToken,
  tokenStatusLabel,
  tokenUsageLabel,
  type CreatedExtensionToken,
  type ExtensionToken,
} from './api'

const EXTENSION_REPO_URL =
  'https://github.com/fntp/opensource-factory/tree/main/extension'

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return '登录状态已失效，请重新登录。'
    if (error.status === 400)
      return '令牌数量已达上限（20 个），请先撤销不用的令牌。'
    if (error.status === 404) return '令牌不存在或已被撤销。'
  }
  return '操作失败，请稍后重试。'
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已复制到剪贴板')
  } catch {
    toast.error('复制失败，请手动选择文本')
  }
}

export function SettingsExtension() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [created, setCreated] = useState<CreatedExtensionToken | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<ExtensionToken | null>(null)

  const tokensQuery = useQuery({
    queryKey: ['extension-tokens'],
    queryFn: fetchExtensionTokens,
  })
  const tokens = tokensQuery.data ?? []

  const createMutation = useMutation({
    mutationFn: () => createExtensionToken(label.trim()),
    onSuccess: (result) => {
      setCreateOpen(false)
      setLabel('')
      setCreated(result)
      void queryClient.invalidateQueries({ queryKey: ['extension-tokens'] })
    },
    onError: (error) => toast.error(actionErrorMessage(error)),
  })

  const revokeMutation = useMutation({
    mutationFn: (id: string) => revokeExtensionToken(id),
    onSuccess: () => {
      toast.success('令牌已撤销')
      setRevokeTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['extension-tokens'] })
    },
    onError: (error) => toast.error(actionErrorMessage(error)),
  })

  return (
    <ContentSection
      title='浏览器扩展'
      desc='安装 OpenFactory 收藏助手，在 GitHub / Gitee 仓库页一键收藏到「我的仓库」。'
    >
      <div>
        <div className='space-y-6'>
          {DEMO_MODE && (
            <div className='rounded-md border border-dashed p-3 text-sm text-muted-foreground'>
              当前为演示模式，未连接后端；令牌的创建与撤销不可用。
            </div>
          )}

          <Card>
            <CardHeader>
              <CardTitle className='text-base'>安装扩展</CardTitle>
              <CardDescription>
                扩展为 Manifest V3 零构建版本，直接加载仓库中的 extension/
                目录即可。
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-4'>
              <ol className='space-y-2 text-sm text-muted-foreground'>
                {EXTENSION_INSTALL_STEPS.map((step, index) => (
                  <li key={step} className='flex gap-2'>
                    <span className='flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary'>
                      {index + 1}
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
              <Button variant='outline' size='sm' asChild>
                <a href={EXTENSION_REPO_URL} target='_blank' rel='noreferrer'>
                  查看扩展源码
                  <ExternalLink />
                </a>
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='text-base'>站点地址</CardTitle>
              <CardDescription>
                在扩展设置页的「API 地址」中填写该地址。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className='flex gap-2'>
                <Input
                  readOnly
                  value={extensionApiBase()}
                  className='font-mono text-xs'
                  aria-label='站点 API 地址'
                />
                <Button
                  variant='outline'
                  size='icon'
                  aria-label='复制站点地址'
                  onClick={() => void copyText(extensionApiBase())}
                >
                  <Copy />
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className='flex flex-row items-start justify-between gap-3 space-y-0'>
              <div className='space-y-1.5'>
                <CardTitle className='text-base'>扩展令牌</CardTitle>
                <CardDescription>
                  令牌只保存哈希，明文仅在创建时显示一次；最多保留 20
                  个有效令牌。
                </CardDescription>
              </div>
              <Button
                size='sm'
                onClick={() => setCreateOpen(true)}
                disabled={DEMO_MODE}
              >
                <Plus />
                创建令牌
              </Button>
            </CardHeader>
            <CardContent className='space-y-2'>
              {tokensQuery.isLoading ? (
                <div className='flex items-center gap-2 py-6 text-sm text-muted-foreground'>
                  <Loader2 className='animate-spin' />
                  正在加载令牌…
                </div>
              ) : tokens.length === 0 ? (
                <div className='rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground'>
                  还没有扩展令牌，点击「创建令牌」开始连接浏览器扩展。
                </div>
              ) : (
                tokens.map((token) => (
                  <div
                    key={token.id}
                    className='flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between'
                  >
                    <div className='min-w-0 space-y-1'>
                      <div className='flex flex-wrap items-center gap-2'>
                        <KeyRound className='size-4 text-muted-foreground' />
                        <span className='truncate text-sm font-medium'>
                          {token.label}
                        </span>
                        <Badge
                          variant={
                            token.status === 'active' ? 'secondary' : 'outline'
                          }
                        >
                          {tokenStatusLabel(token.status)}
                        </Badge>
                      </div>
                      <div className='flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground'>
                        <code className='font-mono'>{token.hint}</code>
                        <span>
                          创建于 {formatTokenDate(token.createdAt, '—')}
                        </span>
                        <span>{tokenUsageLabel(token)}</span>
                      </div>
                    </div>
                    {token.status === 'active' && (
                      <Button
                        variant='ghost'
                        size='sm'
                        className='self-start text-destructive hover:text-destructive sm:self-auto'
                        disabled={DEMO_MODE}
                        onClick={() => setRevokeTarget(token)}
                      >
                        <Trash2 />
                        撤销
                      </Button>
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <Dialog
          open={createOpen}
          onOpenChange={(open) => {
            setCreateOpen(open)
            if (!open) setLabel('')
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>创建扩展令牌</DialogTitle>
              <DialogDescription>
                给令牌起一个便于识别的名字，例如「工作电脑
                Chrome」。令牌只会显示一次。
              </DialogDescription>
            </DialogHeader>
            <Input
              value={label}
              maxLength={40}
              placeholder='工作电脑 Chrome'
              onChange={(event) => setLabel(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !createMutation.isPending) {
                  createMutation.mutate()
                }
              }}
            />
            <DialogFooter>
              <Button
                variant='outline'
                onClick={() => setCreateOpen(false)}
                disabled={createMutation.isPending}
              >
                取消
              </Button>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={createMutation.isPending}
              >
                {createMutation.isPending && (
                  <Loader2 className='animate-spin' />
                )}
                创建
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog
          open={Boolean(created)}
          onOpenChange={(open) => {
            if (!open) setCreated(null)
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>令牌已创建</DialogTitle>
              <DialogDescription>
                复制下面的令牌并粘贴到扩展设置页。关闭此窗口后将无法再次查看明文。
              </DialogDescription>
            </DialogHeader>
            <div className='flex gap-2'>
              <Input
                readOnly
                value={created?.token ?? ''}
                className='font-mono text-xs'
                onFocus={(event) => event.currentTarget.select()}
                aria-label='扩展令牌明文'
              />
              <Button
                variant='outline'
                size='icon'
                aria-label='复制令牌'
                onClick={() => void copyText(created?.token ?? '')}
              >
                <Copy />
              </Button>
            </div>
            <p className='text-xs text-muted-foreground'>
              提示：令牌等同于账号的收藏权限，请勿分享或提交到代码仓库。
            </p>
            <DialogFooter>
              <Button onClick={() => setCreated(null)}>我已保存</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <AlertDialog
          open={Boolean(revokeTarget)}
          onOpenChange={(open) => {
            if (!open) setRevokeTarget(null)
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>撤销这个令牌？</AlertDialogTitle>
              <AlertDialogDescription>
                撤销后，使用「{revokeTarget?.label}
                」的浏览器扩展将立即失效，需要重新创建令牌并配置。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={revokeMutation.isPending}>
                取消
              </AlertDialogCancel>
              <AlertDialogAction
                className='bg-destructive text-white hover:bg-destructive/90'
                disabled={revokeMutation.isPending}
                onClick={(event) => {
                  event.preventDefault()
                  if (revokeTarget) revokeMutation.mutate(revokeTarget.id)
                }}
              >
                {revokeMutation.isPending && (
                  <Loader2 className='animate-spin' />
                )}
                撤销令牌
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </ContentSection>
  )
}
