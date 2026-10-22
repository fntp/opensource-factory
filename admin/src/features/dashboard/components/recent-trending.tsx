import { useQuery } from '@tanstack/react-query'
import { Flame } from 'lucide-react'
import { IconGithub } from '@/assets/brand-icons'
import { EmptyState, ErrorState, LoadingState } from '@/components/data-state'
import { fetchRecentTrending } from '../api'

export function RecentTrending() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['recent-trending'],
    queryFn: fetchRecentTrending,
  })
  const items = data ?? []

  if (isPending) {
    return <LoadingState label='正在加载热榜…' rows={4} />
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => void refetch()} />
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={Flame}
        title='今日暂无热榜'
        description='热榜抓取任务运行后会自动展示。'
      />
    )
  }

  return (
    <div className='space-y-6'>
      {items.map((item) => (
        <div key={item.id} className='flex items-center gap-4'>
          <div className='flex size-9 items-center justify-center rounded-lg border'>
            <IconGithub className='size-4' />
          </div>
          <div className='flex flex-1 flex-wrap items-center justify-between gap-2'>
            <div className='min-w-0 space-y-1'>
              <a
                href={item.url}
                target='_blank'
                rel='noreferrer'
                className='text-sm leading-none font-medium hover:underline'
              >
                {item.owner}/{item.name}
              </a>
              <p className='max-w-60 truncate text-sm text-muted-foreground'>
                {item.description ?? '暂无描述'}
              </p>
            </div>
            <div className='text-end'>
              <div className='text-sm font-medium'>+{item.starsToday}</div>
              <div className='text-xs text-muted-foreground'>
                {item.language ?? '未知语言'}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
