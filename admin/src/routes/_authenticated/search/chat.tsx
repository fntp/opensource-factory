import { createFileRoute } from '@tanstack/react-router'
import { ConversationalSearch } from '@/features/search/chat'

export const Route = createFileRoute('/_authenticated/search/chat')({
  component: ConversationalSearch,
})
