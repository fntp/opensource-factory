import { useQuery } from '@tanstack/react-query'
import { IconGithub } from '@/assets/brand-icons'
import { fetchRecentTrending, MOCK_TRENDING } from '../api'

export function RecentTrending() {
  const { data } = useQuery({
    queryKey: ['recent-trending'],
    queryFn: fetchRecentTrending,
  })
  const items = data ?? MOCK_TRENDING

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
                {item.description}
              </p>
            </div>
            <div className='text-end'>
              <div className='text-sm font-medium'>+{item.starsToday}</div>
              <div className='text-xs text-muted-foreground'>
                {item.language}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
