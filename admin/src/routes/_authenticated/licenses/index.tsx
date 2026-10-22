import { createFileRoute } from '@tanstack/react-router'
import { Licenses } from '@/features/licenses'

export const Route = createFileRoute('/_authenticated/licenses/')({
  component: Licenses,
})
