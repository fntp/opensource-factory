import { createFileRoute } from '@tanstack/react-router'
import { StarTrends } from '@/features/star-trends'

export const Route = createFileRoute('/_authenticated/star-trends/')({
  component: StarTrends,
})
