import { createFileRoute } from '@tanstack/react-router'
import { RerankWorkbench } from '@/features/rerank'

export const Route = createFileRoute('/_authenticated/rerank/')({
  component: RerankWorkbench,
})
