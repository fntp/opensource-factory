import { createFileRoute } from '@tanstack/react-router'
import { TechStack } from '@/features/tech-stack'

export const Route = createFileRoute('/_authenticated/tech-stack/')({
  component: TechStack,
})
