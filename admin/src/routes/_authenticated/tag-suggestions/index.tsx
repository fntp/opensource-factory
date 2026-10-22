import { createFileRoute } from '@tanstack/react-router'
import { TagSuggestions } from '@/features/tag-suggestions'

export const Route = createFileRoute('/_authenticated/tag-suggestions/')({
  component: TagSuggestions,
})
