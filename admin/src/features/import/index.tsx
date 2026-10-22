import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardPaste,
  Eye,
  FileJson,
  History,
  Loader2,
  Play,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
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
  executeImport,
  fetchImportHistory,
  importErrorMessage,
  previewImport,
} from './api'
import type {
  ImportFormat,
  ImportPreview,
  ImportResult,
  ImportStatus,
} from './types'
import {
  DEMO_IMPORT_CONTENT,
  FORMAT_OPTIONS,
  MAX_CONTENT_LENGTH,
  MAX_IMPORT_ENTRIES,
  STATUS_LABELS,
  formatDateTime,
  formatFileSize,
  formatLabel,
  issueReasonLabel,
} from './utils'

const STATUS_CLASS: Record<ImportStatus, string> = {
  new: 'bg-emerald-600 text-white hover:bg-emerald-600',
  update: 'bg-amber-500 text-white hover:bg-amber-500',
  conflict: 'bg-destructive text-white hover:bg-destructive',
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className='rounded-xl border bg-card p-4'>
      <div className='text-sm text-muted-foreground'>{label}</div>
      <div className='mt-1 text-2xl font-bold tabular-nums'>{value}</div>
    </div>
  )
}

export function DataImport() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [content, setContent] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [fileSize, setFileSize] = useState(0)
  const [format, setFormat] = useState<ImportFormat>('auto')
  const [useFolders, setUseFolders] = useState(true)
  const [createCategories, setCreateCategories] = useState(true)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)

  const { data: history } = useQuery({
    queryKey: ['import-history'],
    queryFn: fetchImportHistory,
  })

  const previewMutation = useMutation({
    mutationFn: previewImport,
    onSuccess: (data) => {
      setPreview(data)
      setResult(null)
      if (data.total === 0) {
        toast.warning('没有识别到可导入的仓库')
      } else {
        toast.success(`已解析 ${data.total} 个仓库，确认后即可执行导入`)
      }
    },
    onError: (error) => toast.error(importErrorMessage(error)),
  })

  const executeMutation = useMutation({
    mutationFn: executeImport,
    onSuccess: (data) => {
      setResult(data)
      setPreview(null)
      toast.success(
        `导入完成：新增 ${data.imported} 个，更新 ${data.updated} 个`
      )
      void queryClient.invalidateQueries({ queryKey: ['import-history'] })
    },
    onError: (error) => toast.error(importErrorMessage(error)),
  })

  const busy = previewMutation.isPending || executeMutation.isPending

  function resetPreview() {
    setPreview(null)
    setResult(null)
  }

  function handleContentChange(value: string) {
    setContent(value)
    setFileName(null)
    setFileSize(new Blob([value]).size)
    resetPreview()
  }

  async function handleFile(file: File | undefined) {
    if (!file) return
    if (file.size > MAX_CONTENT_LENGTH) {
      toast.error(`文件 ${formatFileSize(file.size)}，超过 2 MB 上限`)
      return
    }
    try {
      const text = await file.text()
      setContent(text)
      setFileName(file.name)
      setFileSize(file.size)
      resetPreview()
      toast.success(`已读取 ${file.name}`)
    } catch {
      toast.error('读取文件失败，请重试')
    }
  }

  function handleDemoFill() {
    setContent(DEMO_IMPORT_CONTENT)
    setFileName('示例数据.json')
    setFileSize(new Blob([DEMO_IMPORT_CONTENT]).size)
    setFormat('json')
    resetPreview()
  }

  function handleClear() {
    setContent('')
    setFileName(null)
    setFileSize(0)
    setFormat('auto')
    resetPreview()
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function handlePreview() {
    if (!content.trim()) {
      toast.error('请先选择文件或粘贴导入内容')
      return
    }
    previewMutation.mutate({ content, format, useFolders, createCategories })
  }

  function handleExecute() {
    if (!preview) {
      toast.error('请先预览并确认导入内容')
      return
    }
    executeMutation.mutate({ content, format, useFolders, createCategories })
  }

  const activeFormat = FORMAT_OPTIONS.find((option) => option.key === format)

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
        <div className='mb-4 flex flex-wrap items-start justify-between gap-4'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <Upload className='size-6 text-emerald-600' />
              数据导入
            </h2>
            <p className='text-sm text-muted-foreground'>
              从其他收藏工具迁移仓库：支持 JSON、CSV 与浏览器书签 HTML，先预览再写入。
            </p>
          </div>
          <Badge variant='outline' className='mt-1'>
            冲突自动跳过 · 不覆盖他人收藏
          </Badge>
        </div>

        <div className='grid grid-cols-2 gap-3 lg:grid-cols-5'>
          <StatCard label='待导入条目' value={preview?.total ?? 0} />
          <StatCard label='新增' value={preview?.new ?? 0} />
          <StatCard label='更新' value={preview?.update ?? 0} />
          <StatCard label='冲突' value={preview?.conflict ?? 0} />
          <StatCard label='无效 / 重复' value={(preview?.invalid ?? 0) + (preview?.duplicates ?? 0)} />
        </div>

        <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3'>
          <Card className='lg:col-span-2'>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <ClipboardPaste className='size-4' />
                导入内容
              </CardTitle>
              <CardDescription>
                选择导出文件，或直接粘贴 JSON / CSV / 书签 HTML 文本。
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-3'>
              <div className='flex flex-wrap items-center gap-2'>
                <input
                  ref={fileInputRef}
                  type='file'
                  className='hidden'
                  accept={activeFormat?.accept}
                  onChange={(event) => {
                    void handleFile(event.target.files?.[0])
                    event.target.value = ''
                  }}
                />
                <Button
                  type='button'
                  variant='outline'
                  onClick={() => fileInputRef.current?.click()}
                  disabled={busy}
                >
                  <Upload className='size-4' />
                  选择文件
                </Button>
                <Button
                  type='button'
                  variant='ghost'
                  onClick={handleDemoFill}
                  disabled={busy}
                >
                  <FileJson className='size-4' />
                  填入示例
                </Button>
                <Button
                  type='button'
                  variant='ghost'
                  onClick={handleClear}
                  disabled={busy || (!content && !fileName)}
                >
                  <Trash2 className='size-4' />
                  清空
                </Button>
                {fileName ? (
                  <span className='text-sm text-muted-foreground'>
                    {fileName} · {formatFileSize(fileSize)}
                  </span>
                ) : content ? (
                  <span className='text-sm text-muted-foreground'>
                    已粘贴 {formatFileSize(fileSize)}
                  </span>
                ) : null}
              </div>

              <Textarea
                value={content}
                onChange={(event) => handleContentChange(event.target.value)}
                placeholder={'粘贴 JSON / CSV / 书签 HTML，或点击「选择文件」\n\n示例：\n{"schema":"openfactory.knowledge.v1","repositories":[{"url":"https://github.com/ollama/ollama"}]}'}
                className='min-h-[260px] font-mono text-xs'
                spellCheck={false}
                disabled={busy}
              />

              <p className='text-xs text-muted-foreground'>
                单次内容 ≤ {formatFileSize(MAX_CONTENT_LENGTH)} · 最多{' '}
                {MAX_IMPORT_ENTRIES} 个仓库 · 仅识别 GitHub / Gitee 仓库链接
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>导入设置</CardTitle>
              <CardDescription>格式与写入策略</CardDescription>
            </CardHeader>
            <CardContent className='space-y-5'>
              <div className='space-y-2'>
                <Label>文件格式</Label>
                <Select
                  value={format}
                  onValueChange={(value) => {
                    setFormat(value as ImportFormat)
                    resetPreview()
                  }}
                  disabled={busy}
                >
                  <SelectTrigger className='w-full'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FORMAT_OPTIONS.map((option) => (
                      <SelectItem key={option.key} value={option.key}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className='text-xs text-muted-foreground'>
                  {activeFormat?.description}
                </p>
              </div>

              <div className='flex items-start justify-between gap-3'>
                <div className='space-y-1'>
                  <Label htmlFor='use-folders'>书签文件夹 → 分类</Label>
                  <p className='text-xs text-muted-foreground'>
                    仅对浏览器书签 HTML 生效，默认文件夹会被忽略
                  </p>
                </div>
                <Switch
                  id='use-folders'
                  checked={useFolders}
                  onCheckedChange={setUseFolders}
                  disabled={busy}
                />
              </div>

              <div className='flex items-start justify-between gap-3'>
                <div className='space-y-1'>
                  <Label htmlFor='create-categories'>自动新建分类</Label>
                  <p className='text-xs text-muted-foreground'>
                    不存在的分类将按导入内容创建；关闭时归入未分类
                  </p>
                </div>
                <Switch
                  id='create-categories'
                  checked={createCategories}
                  onCheckedChange={setCreateCategories}
                  disabled={busy}
                />
              </div>

              <div className='space-y-2 border-t pt-4'>
                <Button
                  type='button'
                  className='w-full'
                  onClick={handlePreview}
                  disabled={busy || !content.trim()}
                >
                  {previewMutation.isPending ? (
                    <Loader2 className='size-4 animate-spin' />
                  ) : (
                    <Eye className='size-4' />
                  )}
                  预览导入
                </Button>
                <Button
                  type='button'
                  variant='default'
                  className='w-full bg-emerald-600 hover:bg-emerald-700'
                  onClick={handleExecute}
                  disabled={busy || !preview || preview.total === 0}
                >
                  {executeMutation.isPending ? (
                    <Loader2 className='size-4 animate-spin' />
                  ) : (
                    <Play className='size-4' />
                  )}
                  执行导入
                </Button>
                <p className='text-xs text-muted-foreground'>
                  {preview
                    ? `将新增 ${preview.new} 个、更新 ${preview.update} 个，跳过 ${preview.conflict + preview.invalid} 个`
                    : '先预览确认统计，再执行写入'}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>

        {preview ? (
          <div className='mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3'>
            <Card className='lg:col-span-2'>
              <CardHeader>
                <CardTitle>预览结果</CardTitle>
                <CardDescription>
                  识别格式 {formatLabel(preview.format)} · 有效条目 {preview.total}{' '}
                  个{preview.duplicates > 0 ? ` · 文件内去重 ${preview.duplicates} 条` : ''}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {preview.truncated ? (
                  <Alert className='mb-3'>
                    <AlertTriangle className='size-4' />
                    <AlertTitle>内容已截断</AlertTitle>
                    <AlertDescription>
                      单次最多导入 {MAX_IMPORT_ENTRIES} 个仓库，超出部分未包含在本次预览中。
                    </AlertDescription>
                  </Alert>
                ) : null}
                {preview.sample.length === 0 ? (
                  <p className='py-6 text-center text-sm text-muted-foreground'>
                    没有可导入的仓库，请检查文件内容。
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>仓库</TableHead>
                        <TableHead>分类</TableHead>
                        <TableHead>标签</TableHead>
                        <TableHead className='text-right'>状态</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.sample.map((item) => (
                        <TableRow key={item.fullName}>
                          <TableCell>
                            <div className='font-medium'>{item.fullName}</div>
                            <div className='text-xs text-muted-foreground'>
                              {item.language ?? item.platform}
                            </div>
                          </TableCell>
                          <TableCell className='text-sm text-muted-foreground'>
                            {item.category ?? '-'}
                          </TableCell>
                          <TableCell>
                            <div className='flex flex-wrap gap-1'>
                              {item.tags.slice(0, 3).map((tag) => (
                                <Badge key={tag} variant='secondary'>
                                  {tag}
                                </Badge>
                              ))}
                              {item.tags.length > 3 ? (
                                <Badge variant='outline'>+{item.tags.length - 3}</Badge>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell className='text-right'>
                            <Badge className={STATUS_CLASS[item.status]}>
                              {STATUS_LABELS[item.status]}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                {preview.sample.length < preview.total ? (
                  <p className='mt-2 text-xs text-muted-foreground'>
                    仅展示前 {preview.sample.length} 条，其余将在执行时一并处理。
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='flex items-center gap-2'>
                  <AlertTriangle className='size-4 text-amber-500' />
                  跳过与无效条目
                </CardTitle>
                <CardDescription>
                  冲突 {preview.conflict} 个 · 无效 {preview.invalid} 个
                </CardDescription>
              </CardHeader>
              <CardContent>
                {preview.issues.length === 0 ? (
                  <p className='text-sm text-muted-foreground'>没有发现无效条目。</p>
                ) : (
                  <ul className='space-y-2'>
                    {preview.issues.slice(0, 12).map((issue, index) => (
                      <li
                        key={`${issue.row}-${issue.reason}-${index}`}
                        className='rounded-md border p-2 text-sm'
                      >
                        <div className='font-medium'>{issueReasonLabel(issue.reason)}</div>
                        <div className='truncate text-xs text-muted-foreground'>
                          第 {issue.row || '-'} 行 {issue.value}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <p className='mt-3 text-xs text-muted-foreground'>
                  他人已收藏的仓库会按冲突跳过，不会修改对方数据。
                </p>
              </CardContent>
            </Card>
          </div>
        ) : null}

        {result ? (
          <Alert className='mt-4 border-emerald-600/30'>
            <CheckCircle2 className='size-4 text-emerald-600' />
            <AlertTitle>导入完成</AlertTitle>
            <AlertDescription>
              新增 {result.imported} 个 · 更新 {result.updated} 个 · 跳过{' '}
              {result.skipped} 个 · 新建分类 {result.categoriesCreated} 个 · 新建标签{' '}
              {result.tagsCreated} 个。任务编号 {result.runId}
            </AlertDescription>
          </Alert>
        ) : null}

        <Card className='mt-4'>
          <CardHeader>
            <CardTitle className='flex items-center gap-2'>
              <History className='size-4' />
              最近导入
            </CardTitle>
            <CardDescription>仅显示当前账号的导入记录，最多 10 条。</CardDescription>
          </CardHeader>
          <CardContent>
            {!history || history.items.length === 0 ? (
              <p className='py-4 text-sm text-muted-foreground'>还没有导入记录。</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>时间</TableHead>
                    <TableHead>格式</TableHead>
                    <TableHead className='text-right'>总条目</TableHead>
                    <TableHead className='text-right'>新增</TableHead>
                    <TableHead className='text-right'>更新</TableHead>
                    <TableHead className='text-right'>冲突</TableHead>
                    <TableHead className='text-right'>无效</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.items.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell className='text-sm'>
                        {formatDateTime(run.createdAt)}
                      </TableCell>
                      <TableCell>
                        <Badge variant='outline'>{formatLabel(run.format)}</Badge>
                      </TableCell>
                      <TableCell className='text-right tabular-nums'>{run.total}</TableCell>
                      <TableCell className='text-right tabular-nums'>{run.imported}</TableCell>
                      <TableCell className='text-right tabular-nums'>{run.updated}</TableCell>
                      <TableCell className='text-right tabular-nums'>{run.conflicts}</TableCell>
                      <TableCell className='text-right tabular-nums'>{run.invalid}</TableCell>
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
