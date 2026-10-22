import { createFileRoute } from '@tanstack/react-router'
import { Trending } from '@/features/trending'

export const Route = createFileRoute('/_authenticated/trending/')({
  component: Trending,
})
