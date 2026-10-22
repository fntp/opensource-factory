import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Download,
  Loader2,
  LockKeyhole,
  ShieldCheck,
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
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ContentSection } from '../settings/components/content-section'
import {
  deleteAccount,
  downloadPersonalData,
  fetchPrivacyPolicy,
  saveBlob,
} from './api'
import { formatPolicyDate, retentionText } from './utils'

function privacyErrorMessage(error: unknown): string {
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return '登录状态已失效，请重新登录。'
    if (error.status === 400) return '确认文本不正确，请输入大写的 DELETE。'
    if (error.status === 429) return '操作过于频繁，请稍后再试。'
  }
  return '操作失败，请稍后重试。'
}

export function SettingsPrivacy() {
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [confirmation, setConfirmation] = useState('')

  const policyQuery = useQuery({
    queryKey: ['privacy-policy'],
    queryFn: fetchPrivacyPolicy,
  })
  const policy = policyQuery.data

  const exportMutation = useMutation({
    mutationFn: downloadPersonalData,
    onSuccess: ({ blob, fileName }) => {
      saveBlob(blob, fileName)
      toast.success('个人数据已开始下载')
    },
    onError: (error) => toast.error(privacyErrorMessage(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteAccount(confirmation),
    onSuccess: () => {
      toast.success('账号及个人数据已删除')
      setDeleteOpen(false)
      window.setTimeout(() => window.location.assign('/'), 600)
    },
    onError: (error) => toast.error(privacyErrorMessage(error)),
  })

  const canDelete = confirmation === 'DELETE' && !DEMO_MODE

  return (
    <ContentSection
      title='隐私与数据'
      desc='查看数据保留策略，导出个人数据，或删除账号及全部个人数据。'
    >
      <div className='space-y-6'>
        {DEMO_MODE && (
          <div className='rounded-md border border-dashed p-3 text-sm text-muted-foreground'>
            当前为演示模式，未连接后端；导出内容为示例文件，账号删除不可用。
          </div>
        )}

        {policyQuery.isLoading ? (
          <div className='flex items-center gap-2 py-8 text-sm text-muted-foreground'>
            <Loader2 className='animate-spin' />
            正在加载隐私策略…
          </div>
        ) : policy ? (
          <>
            <div className='flex flex-wrap items-center gap-2 text-sm text-muted-foreground'>
              <ShieldCheck className='size-4 text-primary' />
              <span>策略版本 {policy.version}</span>
              <span aria-hidden>·</span>
              <span>更新于 {formatPolicyDate(policy.updatedAt)}</span>
            </div>

            <Card>
              <CardHeader>
                <CardTitle className='text-base'>你的数据权利</CardTitle>
                <CardDescription>{policy.controller}</CardDescription>
              </CardHeader>
              <CardContent className='space-y-3'>
                {policy.rights.map((right) => (
                  <div key={right.key} className='rounded-lg border p-3'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <span className='text-sm font-medium'>{right.title}</span>
                      <code className='rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground'>
                        {right.endpoint}
                      </code>
                    </div>
                    <p className='mt-1 text-sm text-muted-foreground'>
                      {right.description}
                    </p>
                  </div>
                ))}
                <p className='text-xs text-muted-foreground'>{policy.contact}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-base'>数据保留策略</CardTitle>
                <CardDescription>
                  到期后由每日清理任务自动删除；账号删除时立即清除可识别个人数据。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className='overflow-x-auto rounded-lg border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>数据类别</TableHead>
                        <TableHead>存储位置</TableHead>
                        <TableHead>保留期</TableHead>
                        <TableHead>到期动作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {policy.retention.map((item) => (
                        <TableRow key={item.key}>
                          <TableCell className='min-w-28 align-top'>
                            <div className='font-medium'>{item.category}</div>
                            <div className='text-xs text-muted-foreground'>
                              {item.purpose}
                            </div>
                          </TableCell>
                          <TableCell className='min-w-40 align-top text-xs text-muted-foreground'>
                            {item.storage}
                          </TableCell>
                          <TableCell className='min-w-32 align-top'>
                            <Badge variant='outline'>{retentionText(item)}</Badge>
                            {item.note && (
                              <p className='mt-1 text-xs text-muted-foreground'>
                                {item.note}
                              </p>
                            )}
                          </TableCell>
                          <TableCell className='min-w-24 align-top text-xs text-muted-foreground'>
                            {item.action}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-base'>第三方处理与数据出境</CardTitle>
                <CardDescription>
                  除下列必要场景外，个人数据不会提供给第三方。
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-2'>
                {policy.outbound.map((item) => (
                  <div key={item.target} className='rounded-lg border p-3 text-sm'>
                    <div className='font-medium'>{item.target}</div>
                    <div className='text-muted-foreground'>{item.purpose}</div>
                    <div className='mt-1 text-xs text-muted-foreground'>
                      数据：{item.data}
                    </div>
                  </div>
                ))}
                {policy.notes.length > 0 && (
                  <ul className='list-disc space-y-1 ps-5 text-xs text-muted-foreground'>
                    {policy.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-base'>导出个人数据</CardTitle>
                <CardDescription>
                  下载 JSON 文件，包含账号资料、收藏、推荐、通知、偏好与审计记录；
                  不包含令牌明文或哈希。
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  variant='outline'
                  onClick={() => exportMutation.mutate()}
                  disabled={exportMutation.isPending}
                >
                  {exportMutation.isPending ? (
                    <Loader2 className='animate-spin' />
                  ) : (
                    <Download />
                  )}
                  下载我的数据
                </Button>
              </CardContent>
            </Card>

            <Card className='border-destructive/40'>
              <CardHeader>
                <CardTitle className='flex items-center gap-2 text-base text-destructive'>
                  <LockKeyhole className='size-4' />
                  危险操作
                </CardTitle>
                <CardDescription>
                  删除账号会立即清除边缘 D1 与 VPS 本地镜像中的个人数据，且不可恢复。
                </CardDescription>
              </CardHeader>
              <CardContent className='space-y-3'>
                <div className='space-y-2'>
                  <label
                    htmlFor='privacy-delete-confirmation'
                    className='text-sm font-medium'
                  >
                    输入 <code className='font-mono'>DELETE</code> 以确认
                  </label>
                  <Input
                    id='privacy-delete-confirmation'
                    value={confirmation}
                    autoComplete='off'
                    placeholder='DELETE'
                    onChange={(event) => setConfirmation(event.target.value)}
                    disabled={DEMO_MODE || deleteMutation.isPending}
                  />
                </div>
                <Button
                  variant='destructive'
                  disabled={!canDelete || deleteMutation.isPending}
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash2 />
                  删除账号
                </Button>
              </CardContent>
            </Card>
          </>
        ) : (
          <div className='rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground'>
            暂时无法加载隐私策略，请稍后重试。
          </div>
        )}

        <AlertDialog
          open={deleteOpen}
          onOpenChange={(open) => {
            setDeleteOpen(open)
            if (!open) setConfirmation('')
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认删除账号？</AlertDialogTitle>
              <AlertDialogDescription>
                此操作不可恢复。账号、收藏、推荐、通知、扩展令牌与推送偏好将被删除，
                共享的热榜与分类配置不受影响。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deleteMutation.isPending}>
                取消
              </AlertDialogCancel>
              <AlertDialogAction
                className='bg-destructive text-white hover:bg-destructive/90'
                disabled={deleteMutation.isPending}
                onClick={(event) => {
                  event.preventDefault()
                  deleteMutation.mutate()
                }}
              >
                {deleteMutation.isPending && (
                  <Loader2 className='animate-spin' />
                )}
                永久删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </ContentSection>
  )
}
