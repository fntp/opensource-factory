import { createFileRoute } from '@tanstack/react-router'
import { SettingsExtension } from '@/features/extension'

export const Route = createFileRoute('/_authenticated/settings/extension')({
  component: SettingsExtension,
})
