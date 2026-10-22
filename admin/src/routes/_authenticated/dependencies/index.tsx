import { createFileRoute } from '@tanstack/react-router'
import { Dependencies } from '@/features/dependencies'

export const Route = createFileRoute('/_authenticated/dependencies/')({
  component: Dependencies,
})
