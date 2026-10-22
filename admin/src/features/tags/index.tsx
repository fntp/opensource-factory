import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  GitMerge,
  Hash,
  Link2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search as SearchIcon,
  Tags as TagsIcon,
  Trash2,
} from 'lucide-react'
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ConfigDrawer } from '@/components/config-drawer'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import {
  createTag,
  deleteTag,
  fetchTags,
  mergeTags,
  MOCK_TAGS,
  recountTags,
  renameTag,
  type Tag,
} from './api'
import { TagMergeDialog } from './tag-merge-dialog'
import { TagNameDialog } from './tag-name-dialog'
import {
  filterTags,
  sortTags,
  summarizeTags,
  tagErrorMessage,
  type SortOrder,
  type TagSort,
} from './tags'

type NameDialogState = { mode: 'create' } | { mode: 'rename'; tag: Tag } | null

export function Tags() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['tags'],
    queryFn: () => fetchTags(),
  })

  // 演示模式：本地维护一份可变的标签集合，模拟全部 CRUD 操作
  const [demoTags, setDemoTags] = useState<Tag[] | null>(
    DEMO_MODE ? MOCK_TAGS : null
  )
  const tags = demoTags ?? data?.items ?? MOCK_TAGS

  const [keyword, setKeyword] = useState('')
  const [sort, setSort] = useState<TagSort>('count')
  const [order, setOrder] = useState<SortOrder>('desc')
  const [nameDialog, setNameDialog] = useState<NameDialogState>(null)
  const [mergeSource, setMergeSource] = useState<Tag | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Tag | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isRecounting, setIsRecounting] = useState(false)

  const visible = useMemo(
    () => sortTags(filterTags(tags, keyword), sort, order),
    [tags, keyword, sort, order]
  )
  const summary = useMemo(() => summarizeTags(tags), [tags])
  const mergeCandidates = useMemo(
    () => tags.filter((tag) => tag.id !== mergeSource?.id),
    [tags, mergeSource?.id]
  )

  async function refresh(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ['tags'] })
  }

  function updateDemo(updater: (list: Tag[]) => Tag[]): void {
    setDemoTags((current) => updater(current ?? MOCK_TAGS))
  }

  async function handleCreate(name: string): Promise<void> {
    if (DEMO_MODE) {
      const exists = tags.some(
        (tag) => tag.name.toLowerCase() === name.toLowerCase()
      )
      if (exists) {
        toast.error('已存在同名标签')
        return
      }
      const nextId = Math.max(0, ...tags.map((tag) => tag.id)) + 1
      updateDemo((list) => [...list, { id: nextId, name, count: 0 }])
      setNameDialog(null)
      toast.success('标签已创建（演示）')
      return
    }

    setIsSubmitting(true)
    try {
      await createTag(name)
      setNameDialog(null)
      await refresh()
      toast.success('标签已创建')
    } catch (err) {
      toast.error(tagErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleRename(name: string): Promise<void> {
    if (!nameDialog || nameDialog.mode !== 'rename') return
    const target = nameDialog.tag

    if (DEMO_MODE) {
      const exists = tags.some(
        (tag) =>
          tag.id !== target.id && tag.name.toLowerCase() === name.toLowerCase()
      )
      if (exists) {
        toast.error('已存在同名标签，可改用「合并」')
        return
      }
      updateDemo((list) =>
        list.map((tag) => (tag.id === target.id ? { ...tag, name } : tag))
      )
      setNameDialog(null)
      toast.success('标签已重命名（演示）')
      return
    }

    setIsSubmitting(true)
    try {
      await renameTag(target.id, name)
      setNameDialog(null)
      await refresh()
      toast.success('标签已重命名')
    } catch (err) {
      toast.error(tagErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleMerge(targetId: number): Promise<void> {
    if (!mergeSource) return
    const source = mergeSource

    if (DEMO_MODE) {
      updateDemo((list) =>
        list
          .map((tag) =>
            tag.id === targetId
              ? { ...tag, count: tag.count + source.count }
              : tag
          )
          .filter((tag) => tag.id !== source.id)
      )
      setMergeSource(null)
      toast.success(`已把「${source.name}」合并（演示）`)
      return
    }

    setIsSubmitting(true)
    try {
      const result = await mergeTags(source.id, targetId)
      setMergeSource(null)
      await refresh()
      const dedupeNote =
        result.deduplicated > 0 ? `，去重 ${result.deduplicated} 个` : ''
      toast.success(
        `已合并到「${result.target.name}」：迁移 ${result.moved} 个关联${dedupeNote}`
      )
    } catch (err) {
      toast.error(tagErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleDelete(): Promise<void> {
    if (!deleteTarget) return
    const target = deleteTarget

    if (DEMO_MODE) {
      updateDemo((list) => list.filter((tag) => tag.id !== target.id))
      setDeleteTarget(null)
      toast.success('标签已删除（演示）')
      return
    }

    setIsSubmitting(true)
    try {
      const result = await deleteTag(target.id)
      setDeleteTarget(null)
      await refresh()
      toast.success(
        result.detached > 0
          ? `标签已删除，解除 ${result.detached} 个仓库关联`
          : '标签已删除'
      )
    } catch (err) {
      toast.error(tagErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleRecount(): Promise<void> {
    if (DEMO_MODE) {
      toast.success('演示模式：标签计数已是最新')
      return
    }

    setIsRecounting(true)
    try {
      const result = await recountTags()
      await refresh()
      toast.success(
        result.mismatched > 0
          ? `已重算 ${result.total} 个标签，修复 ${result.mismatched} 个计数`
          : `已重算 ${result.total} 个标签，计数均正确`
      )
    } catch (err) {
      toast.error(tagErrorMessage(err))
    } finally {
      setIsRecounting(false)
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
        <div className='mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <TagsIcon className='size-6 text-emerald-600' />
              标签体系
            </h2>
            <p className='text-sm text-muted-foreground'>
              统一维护标签名称与引用计数，支持重命名、合并与删除；合并会把仓库关联迁移到目标标签。
            </p>
          </div>
          <div className='flex gap-2'>
            <Button
              variant='outline'
              disabled={isRecounting}
              onClick={() => void handleRecount()}
            >
              <RefreshCw
                className={isRecounting ? 'animate-spin' : undefined}
              />
              重算计数
            </Button>
            <Button onClick={() => setNameDialog({ mode: 'create' })}>
              <Plus />
              新建标签
            </Button>
          </div>
        </div>

        <div className='mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3'>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription className='flex items-center gap-2'>
                <TagsIcon className='size-4' />
                标签总数
              </CardDescription>
              <CardTitle className='text-3xl tabular-nums'>
                {summary.total}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription className='flex items-center gap-2'>
                <Link2 className='size-4' />
                已引用标签
              </CardDescription>
              <CardTitle className='text-3xl tabular-nums'>
                {summary.used}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader className='pb-2'>
              <CardDescription className='flex items-center gap-2'>
                <Hash className='size-4' />
                引用关联
              </CardDescription>
              <CardTitle className='text-3xl tabular-nums'>
                {summary.references}
              </CardTitle>
            </CardHeader>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>全部标签</CardTitle>
            <CardDescription>
              共 {tags.length} 个标签，当前展示 {visible.length} 个
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-4'>
            <div className='flex flex-col gap-2 sm:flex-row sm:items-center'>
              <div className='relative flex-1'>
                <SearchIcon className='pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
                <Input
                  value={keyword}
                  className='ps-8'
                  placeholder='搜索标签名称…'
                  onChange={(event) => setKeyword(event.target.value)}
                />
              </div>
              <Select
                value={sort}
                onValueChange={(value) => setSort(value as TagSort)}
              >
                <SelectTrigger className='w-full sm:w-[140px]'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='count'>按引用数</SelectItem>
                  <SelectItem value='name'>按名称</SelectItem>
                </SelectContent>
              </Select>
              <Button
                variant='outline'
                size='icon'
                aria-label={order === 'desc' ? '切换为升序' : '切换为降序'}
                onClick={() =>
                  setOrder((current) => (current === 'desc' ? 'asc' : 'desc'))
                }
              >
                {order === 'desc' ? <ArrowDown /> : <ArrowUp />}
              </Button>
            </div>

            <div className='rounded-md border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>标签</TableHead>
                    <TableHead className='text-right'>引用仓库</TableHead>
                    <TableHead className='w-[64px] text-right'>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visible.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} className='h-24 text-center'>
                        <div className='flex flex-col items-center gap-1 text-muted-foreground'>
                          <TagsIcon className='size-5' />
                          <span className='text-sm'>
                            {isLoading ? '加载中…' : '没有匹配的标签'}
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  ) : (
                    visible.map((tag) => (
                      <TableRow key={tag.id}>
                        <TableCell>
                          <div className='flex items-center gap-2'>
                            <Badge variant='outline' className='font-normal'>
                              {tag.name}
                            </Badge>
                            {tag.count === 0 && (
                              <span className='text-xs text-muted-foreground'>
                                未引用
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className='text-right font-medium tabular-nums'>
                          {tag.count}
                        </TableCell>
                        <TableCell className='text-right'>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant='ghost'
                                size='icon'
                                aria-label={`管理 ${tag.name}`}
                              >
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align='end'>
                              <DropdownMenuItem
                                onClick={() =>
                                  setNameDialog({ mode: 'rename', tag })
                                }
                              >
                                <Pencil />
                                重命名
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                disabled={tags.length < 2}
                                onClick={() => setMergeSource(tag)}
                              >
                                <GitMerge />
                                合并…
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant='destructive'
                                onClick={() => setDeleteTarget(tag)}
                              >
                                <Trash2 />
                                删除
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </Main>

      {nameDialog && (
        <TagNameDialog
          key={
            nameDialog.mode === 'rename'
              ? `rename-${nameDialog.tag.id}`
              : 'create'
          }
          open
          mode={nameDialog.mode}
          initialName={nameDialog.mode === 'rename' ? nameDialog.tag.name : ''}
          isSubmitting={isSubmitting}
          onOpenChange={(open) => {
            if (!open) setNameDialog(null)
          }}
          onSubmit={nameDialog.mode === 'rename' ? handleRename : handleCreate}
        />
      )}

      {mergeSource && (
        <TagMergeDialog
          key={mergeSource.id}
          open
          source={mergeSource}
          candidates={mergeCandidates}
          isSubmitting={isSubmitting}
          onOpenChange={(open) => {
            if (!open) setMergeSource(null)
          }}
          onSubmit={handleMerge}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        title='删除标签'
        desc={
          deleteTarget
            ? `确定删除「${deleteTarget.name}」吗？${
                deleteTarget.count > 0
                  ? `将从 ${deleteTarget.count} 个仓库解除关联，`
                  : ''
              }此操作不可撤销。`
            : ''
        }
        confirmText='删除'
        destructive
        isLoading={isSubmitting}
        handleConfirm={() => void handleDelete()}
      />
    </>
  )
}
