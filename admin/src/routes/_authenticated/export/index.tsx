import { createFileRoute } from '@tanstack/react-router'
import { KnowledgeExport } from '@/features/export'

export const Route = createFileRoute('/_authenticated/export/')({
  component: KnowledgeExport,
})
