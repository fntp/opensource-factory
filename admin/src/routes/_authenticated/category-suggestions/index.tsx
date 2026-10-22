import { createFileRoute } from '@tanstack/react-router'
import { CategorySuggestions } from '@/features/category-suggestions'

export const Route = createFileRoute('/_authenticated/category-suggestions/')({
  component: CategorySuggestions,
})
