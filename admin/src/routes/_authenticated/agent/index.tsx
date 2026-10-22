import { createFileRoute } from '@tanstack/react-router'
import { AgentWorkflow } from '@/features/agent'

export const Route = createFileRoute('/_authenticated/agent/')({
  component: AgentWorkflow,
})
