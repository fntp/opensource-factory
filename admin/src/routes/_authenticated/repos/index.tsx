import { createFileRoute } from '@tanstack/react-router'
import { Repos } from '@/features/repos'

export const Route = createFileRoute('/_authenticated/repos/')({
  component: Repos,
})
