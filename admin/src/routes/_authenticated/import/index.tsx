import { createFileRoute } from '@tanstack/react-router'
import { DataImport } from '@/features/import'

export const Route = createFileRoute('/_authenticated/import/')({
  component: DataImport,
})
