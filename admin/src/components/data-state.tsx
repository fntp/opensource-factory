import {
  AlertTriangle,
  Inbox,
  Loader2,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react'
import { apiErrorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface LoadingStateProps {
  label?: string
  /** 骨架行数 */
  rows?: number
  className?: string
}

/** 列表 / 卡片的加载骨架 */
export function LoadingState({
  label = '加载中…',
  rows = 3,
  className,
}: LoadingStateProps) {
  return (
    <div
      className={cn('space-y-3', className)}
      role='status'
      aria-live='polite'
    >
      <div className='flex items-center gap-2 text-sm text-muted-foreground'>
        <Loader2 className='size-4 animate-spin' />
        {label}
      </div>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className='h-10 animate-pulse rounded-md bg-muted'
          aria-hidden='true'
        />
      ))}
    </div>
  )
}

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}

/** 空数据态（与「搜索无结果」区分使用） */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 py-12 text-center',
        className
      )}
    >
      <div className='rounded-full bg-muted p-3'>
        <Icon className='size-6 text-muted-foreground' aria-hidden='true' />
      </div>
      <div className='space-y-1'>
        <p className='text-sm font-medium'>{title}</p>
        {description ? (
          <p className='max-w-md text-sm text-muted-foreground'>
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  )
}

interface ErrorStateProps {
  error: unknown
  title?: string
  onRetry?: () => void
  className?: string
}

/** 请求失败态：展示后端错误文案并提供重试 */
export function ErrorState({
  error,
  title = '加载失败',
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 py-12 text-center',
        className
      )}
      role='alert'
    >
      <div className='rounded-full bg-destructive/10 p-3'>
        <AlertTriangle
          className='size-6 text-destructive'
          aria-hidden='true'
        />
      </div>
      <div className='space-y-1'>
        <p className='text-sm font-medium'>{title}</p>
        <p className='max-w-md text-sm text-muted-foreground'>
          {apiErrorMessage(error)}
        </p>
      </div>
      {onRetry ? (
        <Button variant='outline' size='sm' onClick={onRetry}>
          <RefreshCw className='size-4' />
          重试
        </Button>
      ) : null}
    </div>
  )
}
