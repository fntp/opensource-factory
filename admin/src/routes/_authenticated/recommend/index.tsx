import { createFileRoute } from '@tanstack/react-router'
import { Recommend } from '@/features/recommend'

export const Route = createFileRoute('/_authenticated/recommend/')({
  component: Recommend,
})
