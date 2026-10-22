import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  FolderPlus,
  FolderTree,
  MoreHorizontal,
  Pencil,
  Plus,
  Tags,
  Trash2,
} from 'lucide-react'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ConfigDrawer } from '@/components/config-drawer'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { DEMO_MODE } from '@/lib/api'
import {
  categoryErrorMessage,
  createCategory,
  deleteCategory,
  fetchCategories,
  MOCK_CATEGORIES,
  MOCK_TAGS,
  moveCategory,
  updateCategory,
  type Category,
  type CategoryInput,
} from './api'
import { CategoryDialog } from './category-dialog'
import {
  applyCategoryMove,
  buildCategoryTree,
  flattenVisibleTree,
  getReorderTarget,
  getSiblingPosition,
} from './tree'

type DialogState =
  | { mode: 'create'; parentId: string | null }
  | { mode: 'edit'; category: Category }

export function Categories() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['categories'],
    queryFn: fetchCategories,
  })

  const [demoCategories, setDemoCategories] = useState<Category[] | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [dialogState, setDialogState] = useState<DialogState | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Category | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const categories = demoCategories ?? data?.categories ?? MOCK_CATEGORIES
  const tags = data?.tags ?? MOCK_TAGS

  const tree = useMemo(() => buildCategoryTree(categories), [categories])
  const rows = useMemo(
    () => flattenVisibleTree(tree, (id) => collapsed.has(id)),
    [tree, collapsed]
  )

  async function refresh(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ['categories'] })
  }

  function updateDemo(updater: (list: Category[]) => Category[]): void {
    setDemoCategories(updater(categories))
  }

  function toggleCollapsed(id: string): void {
    setCollapsed((previous) => {
      const next = new Set(previous)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  async function handleCreate(input: CategoryInput): Promise<void> {
    if (DEMO_MODE) {
      const siblings = categories.filter(
        (category) => category.parentId === input.parentId
      )
      updateDemo((list) => [
        ...list,
        {
          id: `demo-${Date.now()}`,
          name: input.name,
          parentId: input.parentId,
          description: input.description,
          sortOrder: siblings.length,
          count: 0,
        },
      ])
      toast.success('已新建分类（演示模式）')
      return
    }

    await createCategory(input)
    await refresh()
    toast.success('已新建分类')
  }

  async function handleUpdate(id: string, input: CategoryInput): Promise<void> {
    const previousParentId =
      categories.find((category) => category.id === id)?.parentId ?? null

    if (DEMO_MODE) {
      updateDemo((list) => {
        const updated = list.map((category) =>
          category.id === id
            ? {
                ...category,
                name: input.name,
                description: input.description,
                parentId: input.parentId,
              }
            : category
        )
        return previousParentId === input.parentId
          ? updated
          : applyCategoryMove(updated, id, { parentId: input.parentId, beforeId: null })
      })
      toast.success('已保存分类（演示模式）')
      return
    }

    await updateCategory(id, input)
    await refresh()
    toast.success('已保存分类')
  }

  async function handleMove(id: string, direction: 'up' | 'down'): Promise<void> {
    const target = getReorderTarget(categories, id, direction)
    if (!target) return

    if (DEMO_MODE) {
      updateDemo((list) => applyCategoryMove(list, id, target))
      toast.success('已调整顺序（演示模式）')
      return
    }

    try {
      await moveCategory(id, target)
      await refresh()
      toast.success('已调整顺序')
    } catch (err) {
      toast.error(categoryErrorMessage(err))
    }
  }

  async function handleDelete(): Promise<void> {
    if (!deleteTarget) return

    if (DEMO_MODE) {
      const childCount = categories.filter(
        (category) => category.parentId === deleteTarget.id
      ).length
      if (childCount > 0) {
        toast.error('该分类下还有子分类，请先删除或移动子分类')
        return
      }
      if (deleteTarget.count > 0) {
        toast.error('该分类仍被仓库引用，请先调整仓库分类')
        return
      }
      updateDemo((list) => list.filter((category) => category.id !== deleteTarget.id))
      setDeleteTarget(null)
      toast.success('已删除分类（演示模式）')
      return
    }

    setIsDeleting(true)
    try {
      await deleteCategory(deleteTarget.id)
      await refresh()
      setDeleteTarget(null)
      toast.success('已删除分类')
    } catch (err) {
      toast.error(categoryErrorMessage(err))
    } finally {
      setIsDeleting(false)
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
        <div className='mb-2 flex items-center justify-between space-y-2'>
          <div>
            <h2 className='flex items-center gap-2 text-2xl font-bold tracking-tight'>
              <FolderTree className='size-6 text-emerald-600' />
              分类与标签
            </h2>
            <p className='text-sm text-muted-foreground'>
              用分类树与标签体系组织你的开源资产，支持无限层级、排序与移动。
            </p>
          </div>
          <Button onClick={() => setDialogState({ mode: 'create', parentId: null })}>
            <Plus />
            新建分类
          </Button>
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-3'>
          <Card className='lg:col-span-2'>
            <CardHeader>
              <CardTitle>分类树</CardTitle>
              <CardDescription>
                共 {categories.length} 个分类 · 数字为直接关联的仓库数
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-1'>
              {rows.length === 0 && (
                <p className='py-8 text-center text-sm text-muted-foreground'>
                  还没有分类，点击右上角「新建分类」开始。
                </p>
              )}

              {rows.map(({ node, depth }) => {
                const hasChildren = node.children.length > 0
                const isCollapsed = collapsed.has(node.id)
                const position = getSiblingPosition(categories, node.id)

                return (
                  <div
                    key={node.id}
                    className='group flex items-center gap-2 rounded-md py-1.5 pe-2 hover:bg-accent/50'
                    style={{ paddingLeft: `${depth * 24 + 8}px` }}
                  >
                    <Button
                      variant='ghost'
                      size='icon'
                      className='size-6'
                      aria-label={isCollapsed ? '展开子分类' : '收起子分类'}
                      disabled={!hasChildren}
                      onClick={() => toggleCollapsed(node.id)}
                    >
                      {hasChildren ? (
                        isCollapsed ? (
                          <ChevronRight className='size-4' />
                        ) : (
                          <ChevronDown className='size-4' />
                        )
                      ) : (
                        <span className='size-4' />
                      )}
                    </Button>

                    <FolderTree className='size-4 shrink-0 text-emerald-600' />

                    <div className='min-w-0 flex-1'>
                      <div className='truncate text-sm font-medium'>{node.name}</div>
                      {node.description && (
                        <div className='truncate text-xs text-muted-foreground'>
                          {node.description}
                        </div>
                      )}
                    </div>

                    <Badge variant='secondary'>{node.count}</Badge>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant='ghost'
                          size='icon'
                          className='size-8 opacity-60 group-hover:opacity-100'
                          aria-label={`操作：${node.name}`}
                        >
                          <MoreHorizontal className='size-4' />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align='end'>
                        <DropdownMenuItem
                          onClick={() =>
                            setDialogState({ mode: 'create', parentId: node.id })
                          }
                        >
                          <FolderPlus />
                          新建子分类
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => setDialogState({ mode: 'edit', category: node })}
                        >
                          <Pencil />
                          编辑
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          disabled={position.index <= 0}
                          onClick={() => handleMove(node.id, 'up')}
                        >
                          <ArrowUp />
                          上移
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={
                            position.index < 0 || position.index >= position.total - 1
                          }
                          onClick={() => handleMove(node.id, 'down')}
                        >
                          <ArrowDown />
                          下移
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          variant='destructive'
                          onClick={() => setDeleteTarget(node)}
                        >
                          <Trash2 />
                          删除
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                )
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Tags className='size-4' />
                标签
              </CardTitle>
              <CardDescription>共 {tags.length} 个标签</CardDescription>
            </CardHeader>
            <CardContent>
              <div className='flex flex-wrap gap-2'>
                {tags.map((tag) => (
                  <Badge key={tag.name} variant='outline'>
                    {tag.name} · {tag.count}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </Main>

      {dialogState && (
        <CategoryDialog
          open
          onOpenChange={(open) => {
            if (!open) setDialogState(null)
          }}
          mode={dialogState.mode}
          categories={categories}
          category={dialogState.mode === 'edit' ? dialogState.category : null}
          defaultParentId={dialogState.mode === 'create' ? dialogState.parentId : null}
          onSubmit={(input) =>
            dialogState.mode === 'edit'
              ? handleUpdate(dialogState.category.id, input)
              : handleCreate(input)
          }
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        title='删除分类'
        desc={
          deleteTarget
            ? `确定删除「${deleteTarget.name}」吗？此操作不可撤销。`
            : ''
        }
        confirmText='删除'
        destructive
        isLoading={isDeleting}
        handleConfirm={handleDelete}
      />
    </>
  )
}
