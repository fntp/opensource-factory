import { createFileRoute } from '@tanstack/react-router'
import { Monitoring } from '@/features/monitoring'

export const Route = createFileRoute('/_authenticated/monitoring/')({
  component: Monitoring,
})
