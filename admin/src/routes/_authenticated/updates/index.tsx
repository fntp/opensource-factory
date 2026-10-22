import { createFileRoute } from '@tanstack/react-router'
import { RepoUpdates } from '@/features/repo-updates'

export const Route = createFileRoute('/_authenticated/updates/')({
  component: RepoUpdates,
})
