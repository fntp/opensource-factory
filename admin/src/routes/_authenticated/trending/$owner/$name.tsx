import { createFileRoute } from '@tanstack/react-router'
import { TrendingDetailRoute } from '@/features/trending/detail-page'

export const Route = createFileRoute('/_authenticated/trending/$owner/$name')({
  component: TrendingDetailRoute,
})
