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
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Tag } from './api'

interface TagMergeDialogProps {
  open: boolean
  source: Tag | null
  candidates: Tag[]
  isSubmitting: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (targetId: number) => void | Promise<void>
}

/** 标签合并对话框：源标签的仓库关联迁移到目标标签后，源标签被删除 */
export function TagMergeDialog({
  open,
  source,
  candidates,
  isSubmitting,
  onOpenChange,
  onSubmit,
}: TagMergeDialogProps) {
  const [targetId, setTargetId] = useState('')

  const target = candidates.find((tag) => String(tag.id) === targetId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>合并标签</DialogTitle>
          <DialogDescription>
            {`把「${source?.name ?? '—'}」的仓库关联迁移到目标标签，然后删除源标签。此操作不可撤销。`}
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-4'>
          <div className='rounded-md border bg-muted/40 p-3 text-sm'>
            <div className='flex items-center justify-between'>
              <span className='text-muted-foreground'>源标签</span>
              <span className='font-medium'>{source?.name ?? '—'}</span>
            </div>
            <div className='mt-1 flex items-center justify-between'>
              <span className='text-muted-foreground'>引用仓库</span>
              <span className='font-medium'>{source?.count ?? 0}</span>
            </div>
          </div>

          <div className='space-y-2'>
            <Label htmlFor='tag-merge-target'>合并到</Label>
            <Select value={targetId} onValueChange={setTargetId}>
              <SelectTrigger id='tag-merge-target' className='w-full'>
                <SelectValue placeholder='选择目标标签' />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((tag) => (
                  <SelectItem key={tag.id} value={String(tag.id)}>
                    {tag.name} · {tag.count}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {target && (
              <p className='text-xs text-muted-foreground'>
                合并后「{target.name}」预计引用{' '}
                {target.count + (source?.count ?? 0)}{' '}
                个仓库（重叠关联会自动去重）。
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={isSubmitting}
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            type='button'
            variant='destructive'
            disabled={isSubmitting || !targetId}
            onClick={() => {
              if (targetId) void onSubmit(Number(targetId))
            }}
          >
            {isSubmitting ? '合并中…' : '确认合并'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
