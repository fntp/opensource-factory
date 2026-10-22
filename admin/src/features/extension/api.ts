/**
 * 浏览器扩展令牌管理 API（M8-02）。
 *
 * 列表走会话 Cookie；创建返回的明文令牌只出现一次，前端不持久化。
 */
import { API_BASE, apiFetch, fetchWithFallback } from '@/lib/api'

export interface ExtensionToken {
  id: string
  label: string
  hint: string
  createdAt: string
  lastUsedAt: string | null
  revokedAt: string | null
  status: 'active' | 'revoked'
}

export interface ExtensionTokenList {
  items: ExtensionToken[]
}

export interface CreatedExtensionToken {
  token: string
  item: ExtensionToken
}

/** 演示模式下的占位令牌，避免设置页空白。 */
export const DEMO_TOKENS: ExtensionToken[] = [
  {
    id: 'tok_demo',
    label: '演示令牌（未连接后端）',
    hint: 'ofx_…demo',
    createdAt: '2026-10-01T09:00:00.000Z',
    lastUsedAt: null,
    revokedAt: null,
    status: 'active',
  },
]

export async function fetchExtensionTokens(): Promise<ExtensionToken[]> {
  const data = await fetchWithFallback<ExtensionTokenList>(
    '/api/extension/tokens',
    { items: DEMO_TOKENS }
  )
  return data.items
}

export async function createExtensionToken(
  label: string
): Promise<CreatedExtensionToken> {
  return apiFetch<CreatedExtensionToken>('/api/extension/tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label }),
  })
}

export async function revokeExtensionToken(id: string): Promise<void> {
  await apiFetch(`/api/extension/tokens/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

/** 扩展设置页展示的站点地址（演示模式下回退到当前站点）。 */
export function extensionApiBase(): string {
  if (API_BASE) return API_BASE.replace(/\/+$/, '')
  if (typeof window !== 'undefined') return window.location.origin
  return ''
}

/** 格式化为本地 `YYYY-MM-DD HH:mm`；空值返回占位文案。 */
export function formatTokenDate(
  value: string | null,
  emptyText = '尚未使用'
): string {
  if (!value) return emptyText
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function tokenStatusLabel(status: ExtensionToken['status']): string {
  return status === 'active' ? '有效' : '已撤销'
}

export function tokenUsageLabel(token: ExtensionToken): string {
  if (token.status === 'revoked')
    return `撤销于 ${formatTokenDate(token.revokedAt)}`
  if (!token.lastUsedAt) return '尚未使用'
  return `最近使用 ${formatTokenDate(token.lastUsedAt)}`
}

export const EXTENSION_INSTALL_STEPS = [
  '打开 chrome://extensions（Edge 为 edge://extensions），开启「开发者模式」。',
  '点击「加载已解压的扩展程序」，选择仓库中的 extension/ 目录。',
  '在下方创建一个扩展令牌，复制后粘贴到扩展设置页。',
  '打开任意 GitHub / Gitee 仓库页，点击扩展图标或按 Ctrl+Shift+O 收藏。',
] as const
