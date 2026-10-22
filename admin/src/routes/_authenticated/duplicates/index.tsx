import { createFileRoute } from '@tanstack/react-router'
import { DuplicateDetection } from '@/features/duplicates'

export const Route = createFileRoute('/_authenticated/duplicates/')({
  component: DuplicateDetection,
})
