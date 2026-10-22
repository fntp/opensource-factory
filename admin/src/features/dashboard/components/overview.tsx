import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { FolderGit2 } from 'lucide-react'
import { EmptyState, ErrorState, LoadingState } from '@/components/data-state'
import { fetchRepos } from '@/features/repos/api'

/** 仓库 Star 分布（Top 8，数据来自 GET /api/repos） */
export function Overview() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['repos'],
    queryFn: fetchRepos,
  })

  if (isPending) {
    return <LoadingState label='正在加载 Star 分布…' rows={4} />
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => void refetch()} />
  }

  const top = [...(data ?? [])]
    .sort((a, b) => b.stars - a.stars)
    .slice(0, 8)
    .map((repo) => {
      const parts = repo.fullName.split('/')
      return {
        name: parts[parts.length - 1] ?? repo.fullName,
        total: repo.stars,
      }
    })

  if (top.length === 0) {
    return (
      <EmptyState
        icon={FolderGit2}
        title='暂无仓库数据'
        description='同步 GitHub 仓库后，这里会展示 Star 分布。'
      />
    )
  }

  return (
    <ResponsiveContainer width='100%' height={350}>
      <BarChart data={top} layout='vertical' margin={{ left: 8, right: 16 }}>
        <XAxis type='number' stroke='#888888' fontSize={12} tickLine={false} axisLine={false} />
        <YAxis
          type='category'
          dataKey='name'
          width={130}
          stroke='#888888'
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <Bar
          dataKey='total'
          fill='currentColor'
          radius={[0, 4, 4, 0]}
          className='fill-primary'
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
