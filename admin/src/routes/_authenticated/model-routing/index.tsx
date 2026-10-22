import { createFileRoute } from '@tanstack/react-router'
import { ModelRouting } from '@/features/model-routing'

export const Route = createFileRoute('/_authenticated/model-routing/')({
  component: ModelRouting,
})
