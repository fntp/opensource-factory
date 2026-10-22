/**
 * Telegram Bot 查询入口 API（M8-03）。
 *
 * 边缘服务接口：
 *   GET    /api/telegram/status     配置 / 绑定状态
 *   POST   /api/telegram/link-code  生成 6 位绑定码（10 分钟有效）
 *   DELETE /api/telegram/link       解绑当前用户
 *
 * 与 edge/src/routes/telegram.ts 保持字段一致；所有展示用 chat id 均脱敏。
 */
import { DEMO_MODE, apiFetch, fetchWithFallback } from '@/lib/api'

export interface TelegramBotCommand {
  command: string
  description: string
}

export interface TelegramBotLink {
  chatId: string
  username: string | null
  login: string | null
  linkedAt: string
  lastSeenAt: string | null
}

export interface TelegramBotStatus {
  configured: boolean
  botUsername: string | null
  webhookPath: string
  linked: boolean
  link: TelegramBotLink | null
  commands: TelegramBotCommand[]
}

export interface TelegramLinkCode {
  code: string
  expiresAt: string
  command: string
  deepLink: string | null
  botUsername: string | null
}

export const DEFAULT_TELEGRAM_COMMANDS: TelegramBotCommand[] = [
  { command: 'favorites', description: '查看我的收藏（可带关键词）' },
  { command: 'recommend', description: '查看今日推荐' },
  { command: 'trending', description: '查看今日热榜（可带语言）' },
  { command: 'link', description: '绑定 OpenFactory 账号' },
  { command: 'unlink', description: '解绑当前会话' },
  { command: 'help', description: '查看帮助' },
]

export const MOCK_TELEGRAM_STATUS: TelegramBotStatus = {
  configured: true,
  botUsername: 'OpenFactoryBot',
  webhookPath: '/api/telegram/webhook',
  linked: false,
  link: null,
  commands: DEFAULT_TELEGRAM_COMMANDS,
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** chat id 脱敏：服务端已脱敏时原样返回，避免重复加星号。 */
export function maskTelegramChatId(value: unknown): string {
  const text = String(value ?? '').trim()
  if (!text) return ''
  if (text.includes('*')) return text
  return text.length > 4 ? `***${text.slice(-4)}` : '***'
}

/** 解析状态响应；非法字段回退默认值。 */
export function normalizeTelegramStatus(value: unknown): TelegramBotStatus {
  const record = asRecord(value)
  if (!record) return { ...MOCK_TELEGRAM_STATUS, commands: [...DEFAULT_TELEGRAM_COMMANDS] }

  const linkRecord = asRecord(record.link)
  const commands = Array.isArray(record.commands)
    ? record.commands
        .map((item) => {
          const entry = asRecord(item)
          const command = asString(entry?.command)
          const description = asString(entry?.description)
          return command && description ? { command, description } : null
        })
        .filter((item): item is TelegramBotCommand => item !== null)
    : []

  // 只有返回完整 link 才视为已绑定，避免脏响应出现「已绑定但无详情」的状态
  const linked = Boolean(linkRecord)
  return {
    configured: record.configured === true,
    botUsername: asString(record.botUsername),
    webhookPath: asString(record.webhookPath) ?? '/api/telegram/webhook',
    linked,
    link:
      linked && linkRecord
        ? {
            chatId: maskTelegramChatId(linkRecord.chatId),
            username: asString(linkRecord.username),
            login: asString(linkRecord.login),
            linkedAt: asString(linkRecord.linkedAt) ?? '',
            lastSeenAt: asString(linkRecord.lastSeenAt),
          }
        : null,
    commands: commands.length > 0 ? commands : [...DEFAULT_TELEGRAM_COMMANDS],
  }
}

/** 解析绑定码响应；格式不合法时抛错，避免把错误码展示给用户。 */
export function parseTelegramLinkCode(value: unknown): TelegramLinkCode {
  const record = asRecord(value)
  const code = asString(record?.code) ?? ''
  if (!/^\d{6}$/.test(code)) {
    throw new Error('invalid_telegram_link_code')
  }
  return {
    code,
    expiresAt: asString(record?.expiresAt) ?? '',
    command: asString(record?.command) ?? `/link ${code}`,
    deepLink: asString(record?.deepLink),
    botUsername: asString(record?.botUsername),
  }
}

/** 绑定码剩余时间文案（用于生成后倒计时展示）。 */
export function formatLinkCodeRemaining(expiresAt: string, nowMs = Date.now()): string {
  const expires = Date.parse(expiresAt)
  if (!Number.isFinite(expires)) return '有效期未知'
  const remainingSeconds = Math.ceil((expires - nowMs) / 1000)
  if (remainingSeconds <= 0) return '已过期'
  const minutes = Math.floor(remainingSeconds / 60)
  const seconds = remainingSeconds % 60
  return minutes > 0 ? `剩余 ${minutes} 分 ${seconds} 秒` : `剩余 ${seconds} 秒`
}

/** ISO 时间 → `YYYY-MM-DD HH:mm`；非法值显示破折号。 */
export function formatTelegramTime(value: string | null | undefined): string {
  const text = String(value ?? '').trim()
  if (!text) return '—'
  const date = new Date(text)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function fetchTelegramBotStatus(): Promise<TelegramBotStatus> {
  return fetchWithFallback<unknown>('/api/telegram/status', MOCK_TELEGRAM_STATUS).then(
    normalizeTelegramStatus
  )
}

export function createTelegramLinkCode(): Promise<TelegramLinkCode> {
  if (DEMO_MODE) {
    const code = String(Math.floor(Math.random() * 1_000_000)).padStart(6, '0')
    return Promise.resolve({
      code,
      expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
      command: `/link ${code}`,
      deepLink: `https://t.me/OpenFactoryBot?start=${code}`,
      botUsername: 'OpenFactoryBot',
    })
  }
  return apiFetch<unknown>('/api/telegram/link-code', { method: 'POST' }).then(
    parseTelegramLinkCode
  )
}

export function unlinkTelegram(): Promise<{ linked: boolean; removed: boolean }> {
  if (DEMO_MODE) return Promise.resolve({ linked: false, removed: true })
  return apiFetch<{ linked: boolean; removed: boolean }>('/api/telegram/link', {
    method: 'DELETE',
  })
}
