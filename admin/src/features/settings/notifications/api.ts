/**
 * 推送偏好 API（M4-06）。
 *
 * 边缘服务接口：
 *   GET /api/push-preferences  读取当前用户偏好（未保存时返回默认值）
 *   PUT /api/push-preferences  保存当前用户偏好
 *
 * 与 edge/src/push-preferences/helpers.ts 保持字段一致：
 * 时间使用用户本地时区的 HH:MM，阈值范围 0~1，通道开关为布尔值。
 */
import { DEMO_MODE, apiFetch, fetchWithFallback } from '@/lib/api'

export const CHANNEL_KEYS = ['inapp', 'bark', 'telegram', 'email'] as const
export type ChannelKey = (typeof CHANNEL_KEYS)[number]

export const CHANNEL_LABELS: Record<ChannelKey, string> = {
  inapp: '站内通知',
  bark: 'Bark',
  telegram: 'Telegram',
  email: 'Email',
}

export const CHANNEL_DESCRIPTIONS: Record<ChannelKey, string> = {
  inapp: '在通知中心展示推荐结果，始终建议保留。',
  bark: '推送到 Bark App（需在 VPS 配置 Bark 地址）。',
  telegram: '通过 Telegram Bot 发送（需配置 Bot Token 与 Chat ID）。',
  email: '发送邮件摘要（需配置 SMTP）。',
}

export interface PushChannels {
  inapp: boolean
  bark: boolean
  telegram: boolean
  email: boolean
}

export interface PushPreferences {
  enabled: boolean
  timeOfDay: string
  timezone: string
  minScore: number
  minQualityScore: number
  channels: PushChannels
  updatedAt: string | null
}

export interface PushPreferencesPayload {
  preferences: PushPreferences
  isDefault: boolean
  availableChannels: ChannelKey[]
}

export const DEFAULT_PUSH_PREFERENCES: PushPreferences = {
  enabled: true,
  timeOfDay: '09:00',
  timezone: 'Asia/Shanghai',
  minScore: 0.35,
  minQualityScore: 0.55,
  channels: {
    inapp: true,
    bark: false,
    telegram: false,
    email: false,
  },
  updatedAt: null,
}

export const MOCK_PUSH_PREFERENCES: PushPreferencesPayload = {
  preferences: DEFAULT_PUSH_PREFERENCES,
  isDefault: true,
  availableChannels: [...CHANNEL_KEYS],
}

/** 设置页时区下拉的常用选项（按 UTC 偏移大致排序）。 */
export const TIMEZONE_OPTIONS = [
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Taipei',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Moscow',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Australia/Sydney',
  'Pacific/Auckland',
  'UTC',
] as const

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function clamp01(value: unknown, fallback: number): number {
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(1, Math.max(0, Math.round(number * 1000) / 1000))
}

export function isValidTimeOfDay(value: string): boolean {
  return /^([01]?\d|2[0-3]):([0-5]\d)$/.test(value.trim())
}

export function normalizeTimeOfDay(value: unknown): string {
  const text = String(value ?? '').trim()
  return isValidTimeOfDay(text)
    ? text.padStart(5, '0')
    : DEFAULT_PUSH_PREFERENCES.timeOfDay
}

export function isValidTimezone(value: string): boolean {
  if (!value.trim()) return false
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value })
    return true
  } catch {
    return false
  }
}

export function normalizeChannels(value: unknown): PushChannels {
  const record = asRecord(value)
  const result = { ...DEFAULT_PUSH_PREFERENCES.channels }
  if (!record) return result
  for (const key of CHANNEL_KEYS) {
    const candidate = record[key]
    if (typeof candidate === 'boolean') result[key] = candidate
    else if (candidate === 0 || candidate === 1) result[key] = candidate === 1
  }
  return result
}

/** 容错解析边缘服务返回值，非法字段回退默认值。 */
export function normalizePushPreferences(value: unknown): PushPreferences {
  const record = asRecord(value)
  if (!record) return { ...DEFAULT_PUSH_PREFERENCES, channels: { ...DEFAULT_PUSH_PREFERENCES.channels } }
  return {
    enabled: typeof record.enabled === 'boolean' ? record.enabled : DEFAULT_PUSH_PREFERENCES.enabled,
    timeOfDay: normalizeTimeOfDay(record.timeOfDay ?? record.time_of_day),
    timezone:
      typeof record.timezone === 'string' && isValidTimezone(record.timezone)
        ? record.timezone
        : DEFAULT_PUSH_PREFERENCES.timezone,
    minScore: clamp01(record.minScore ?? record.min_score, DEFAULT_PUSH_PREFERENCES.minScore),
    minQualityScore: clamp01(
      record.minQualityScore ?? record.min_quality_score,
      DEFAULT_PUSH_PREFERENCES.minQualityScore
    ),
    channels: normalizeChannels(record.channels),
    updatedAt:
      typeof record.updatedAt === 'string'
        ? record.updatedAt
        : typeof record.updated_at === 'string'
          ? record.updated_at
          : null,
  }
}

/** 解析接口响应；兼容直接返回偏好对象或 `{ preferences }` 包装。 */
export function parsePushPreferencesPayload(value: unknown): PushPreferencesPayload {
  const record = asRecord(value)
  const wrapped = record && 'preferences' in record
  const preferences = normalizePushPreferences(wrapped ? record?.preferences : value)
  return {
    preferences,
    isDefault: record?.isDefault === true,
    availableChannels: [...CHANNEL_KEYS],
  }
}

/** 保存前校验；返回中文错误列表，空数组表示通过。 */
export function validatePushPreferences(preferences: PushPreferences): string[] {
  const errors: string[] = []
  if (!isValidTimeOfDay(preferences.timeOfDay)) {
    errors.push('推送时间格式必须为 HH:MM')
  }
  if (!isValidTimezone(preferences.timezone)) {
    errors.push('时区不是有效的 IANA 时区')
  }
  if (!Number.isFinite(preferences.minScore) || preferences.minScore < 0 || preferences.minScore > 1) {
    errors.push('匹配度阈值必须在 0~1 之间')
  }
  if (
    !Number.isFinite(preferences.minQualityScore) ||
    preferences.minQualityScore < 0 ||
    preferences.minQualityScore > 1
  ) {
    errors.push('质量分阈值必须在 0~1 之间')
  }
  return errors
}

export function enabledChannelLabels(preferences: PushPreferences): string[] {
  return CHANNEL_KEYS.filter((key) => preferences.channels[key]).map(
    (key) => CHANNEL_LABELS[key]
  )
}

/** 设置页摘要：例如「每天 09:00 · Asia/Shanghai · 站内通知」。 */
export function describePushPreferences(preferences: PushPreferences): string {
  const channels = enabledChannelLabels(preferences)
  const channelText = channels.length > 0 ? channels.join(' / ') : '未开启任何通道'
  return `每天 ${preferences.timeOfDay} · ${preferences.timezone} · ${channelText}`
}

export function fetchPushPreferences(): Promise<PushPreferencesPayload> {
  return fetchWithFallback<unknown>('/api/push-preferences', MOCK_PUSH_PREFERENCES).then(
    parsePushPreferencesPayload
  )
}

export function savePushPreferences(
  preferences: PushPreferences
): Promise<PushPreferencesPayload> {
  if (DEMO_MODE) {
    return Promise.resolve({
      preferences: { ...preferences, updatedAt: new Date().toISOString() },
      isDefault: false,
      availableChannels: [...CHANNEL_KEYS],
    })
  }
  return apiFetch<unknown>('/api/push-preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preferences }),
  }).then(parsePushPreferencesPayload)
}
