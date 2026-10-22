import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { categoryErrorMessage, type Category, type CategoryInput } from './api'
import { getParentOptions } from './tree'

const ROOT_VALUE = '__root__'

interface CategoryDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  mode: 'create' | 'edit'
  categories: Category[]
  category?: Category | null
  /** 新建子分类时预选的父级 */
  defaultParentId?: string | null
  onSubmit: (input: CategoryInput) => Promise<void>
}

/** 新建 / 编辑分类对话框 */
export function CategoryDialog({
  open,
  onOpenChange,
  mode,
  categories,
  category,
  defaultParentId = null,
  onSubmit,
}: CategoryDialogProps) {
  const [name, setName] = useState(mode === 'edit' ? (category?.name ?? '') : '')
  const [description, setDescription] = useState(
    mode === 'edit' ? (category?.description ?? '') : ''
  )
  const [parentId, setParentId] = useState<string>(
    mode === 'edit' ? (category?.parentId ?? ROOT_VALUE) : (defaultParentId ?? ROOT_VALUE)
  )
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const parentOptions = getParentOptions(
    categories,
    mode === 'edit' ? category?.id : undefined
  )

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedName = name.trim()
    const trimmedDescription = description.trim()

    if (!trimmedName) {
      setError('请输入分类名称')
      return
    }
    if (trimmedName.length > 100) {
      setError('分类名称不能超过 100 个字符')
      return
    }
    if (trimmedDescription.length > 500) {
      setError('分类描述不能超过 500 个字符')
      return
    }

    setIsSubmitting(true)
    setError(null)
    try {
      await onSubmit({
        name: trimmedName,
        description: trimmedDescription.length > 0 ? trimmedDescription : null,
        parentId: parentId === ROOT_VALUE ? null : parentId,
      })
      onOpenChange(false)
    } catch (err) {
      setError(categoryErrorMessage(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? '新建分类' : '编辑分类'}</DialogTitle>
          <DialogDescription>
            分类支持无限层级；父级可随时调整，系统会阻止把分类移动到自己的子分类下。
          </DialogDescription>
        </DialogHeader>

        <form className='space-y-4' onSubmit={handleSubmit}>
          <div className='space-y-2'>
            <Label htmlFor='category-name'>名称</Label>
            <Input
              id='category-name'
              value={name}
              maxLength={100}
              placeholder='例如：支付系统'
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className='space-y-2'>
            <Label htmlFor='category-description'>描述</Label>
            <Textarea
              id='category-description'
              value={description}
              maxLength={500}
              rows={3}
              placeholder='这个分类收什么项目？'
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <div className='space-y-2'>
            <Label>父分类</Label>
            <Select value={parentId} onValueChange={setParentId}>
              <SelectTrigger className='w-full'>
                <SelectValue placeholder='选择父分类' />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ROOT_VALUE}>无（顶级分类）</SelectItem>
                {parentOptions.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {`${'· '.repeat(option.depth)}${option.name}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {error && <p className='text-sm text-destructive'>{error}</p>}

          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              disabled={isSubmitting}
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button type='submit' disabled={isSubmitting}>
              {isSubmitting ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
