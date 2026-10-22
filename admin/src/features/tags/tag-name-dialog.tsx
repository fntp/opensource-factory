import { useState } from 'react'
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
import { normalizeTagName, validateTagName } from './tags'

interface TagNameDialogProps {
  open: boolean
  mode: 'create' | 'rename'
  initialName?: string
  isSubmitting: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (name: string) => void | Promise<void>
}

/** 新建 / 重命名标签共用对话框 */
export function TagNameDialog({
  open,
  mode,
  initialName = '',
  isSubmitting,
  onOpenChange,
  onSubmit,
}: TagNameDialogProps) {
  const [name, setName] = useState(initialName)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ): Promise<void> {
    event.preventDefault()
    const validationError = validateTagName(name)
    if (validationError) {
      setError(validationError)
      return
    }
    setError(null)
    await onSubmit(normalizeTagName(name))
  }

  const title = mode === 'create' ? '新建标签' : '重命名标签'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mode === 'create'
              ? '标签用于跨分类组织仓库，名称在标签库内需保持唯一。'
              : '重命名只影响标签本身，不会改变仓库关联。'}
          </DialogDescription>
        </DialogHeader>

        <form id='tag-name-form' className='space-y-2' onSubmit={handleSubmit}>
          <Label htmlFor='tag-name'>标签名称</Label>
          <Input
            id='tag-name'
            value={name}
            autoFocus
            maxLength={60}
            placeholder='例如：LLM、TypeScript、大模型'
            onChange={(event) => {
              setName(event.target.value)
              if (error) setError(null)
            }}
          />
          <p className='text-xs text-muted-foreground'>
            1~50 个字符，支持中英文；不能包含逗号。
          </p>
          {error && <p className='text-sm text-destructive'>{error}</p>}
        </form>

        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={isSubmitting}
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button type='submit' form='tag-name-form' disabled={isSubmitting}>
            {isSubmitting ? '保存中…' : mode === 'create' ? '创建' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
