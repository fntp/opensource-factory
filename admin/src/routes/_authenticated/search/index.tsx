import { createFileRoute } from '@tanstack/react-router'
import { SemanticSearch } from '@/features/search'

export const Route = createFileRoute('/_authenticated/search/')({
  component: SemanticSearch,
})
