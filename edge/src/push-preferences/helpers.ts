/**
 * 推送偏好（M4-06）纯函数。
 *
 * - 默认值：启用、09:00、Asia/Shanghai、匹配度 0.35、质量分 0.55、仅站内通知；
 * - `normalizePushPreferences` 容错解析 D1 行 / 请求体，非法字段回退默认值；
 * - `validatePushPreferencesInput` 严格校验 PUT 请求，返回中文错误信息。
 */
import type { PushPreferenceRow } from '../types';

export const CHANNEL_KEYS = ['inapp', 'bark', 'telegram', 'email'] as const;
export type ChannelKey = (typeof CHANNEL_KEYS)[number];

export const CHANNEL_LABELS: Record<ChannelKey, string> = {
  inapp: '站内通知',
  bark: 'Bark',
  telegram: 'Telegram',
  email: 'Email',
};

export interface PushChannels {
  inapp: boolean;
  bark: boolean;
  telegram: boolean;
  email: boolean;
}

export interface PushPreferences {
  enabled: boolean;
  timeOfDay: string;
  timezone: string;
  minScore: number;
  minQualityScore: number;
  channels: PushChannels;
  updatedAt: string | null;
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
};

export class PushPreferenceValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PushPreferenceValidationError';
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function clamp01(value: unknown, fallback: number): number {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(1, Math.max(0, number));
}

export function normalizeTimeOfDay(
  value: unknown,
  fallback = DEFAULT_PUSH_PREFERENCES.timeOfDay
): string {
  const text = String(value ?? '').trim();
  const match = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(text);
  if (!match) return fallback;
  const hour = match[1] ?? '00';
  const minute = match[2] ?? '00';
  return `${hour.padStart(2, '0')}:${minute}`;
}

export function isValidTimezone(value: unknown): boolean {
  const text = String(value ?? '').trim();
  if (!text) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: text });
    return true;
  } catch {
    return false;
  }
}

export function normalizeTimezone(
  value: unknown,
  fallback = DEFAULT_PUSH_PREFERENCES.timezone
): string {
  return isValidTimezone(value) ? String(value).trim() : fallback;
}

export function normalizeThreshold(value: unknown, fallback: number): number {
  return Math.round(clamp01(value, fallback) * 1000) / 1000;
}

export function normalizeChannels(
  value: unknown,
  fallback: PushChannels = DEFAULT_PUSH_PREFERENCES.channels
): PushChannels {
  const record = asRecord(value);
  const result = { ...fallback };
  if (!record) return result;
  for (const key of CHANNEL_KEYS) {
    const candidate = record[key];
    if (typeof candidate === 'boolean') {
      result[key] = candidate;
    } else if (candidate === 0 || candidate === 1) {
      result[key] = candidate === 1;
    }
  }
  return result;
}

/** 容错解析：用于 D1 行与内部接口返回值，任何非法字段回退默认值。 */
export function normalizePushPreferences(
  value: unknown,
  base: PushPreferences = DEFAULT_PUSH_PREFERENCES
): PushPreferences {
  const record = asRecord(value);
  if (!record) return { ...base, channels: { ...base.channels } };
  return {
    enabled:
      typeof record.enabled === 'boolean'
        ? record.enabled
        : record.enabled === 0 || record.enabled === 1
          ? record.enabled === 1
          : base.enabled,
    timeOfDay: normalizeTimeOfDay(record.timeOfDay ?? record.time_of_day, base.timeOfDay),
    timezone: normalizeTimezone(record.timezone, base.timezone),
    minScore: normalizeThreshold(record.minScore ?? record.min_score, base.minScore),
    minQualityScore: normalizeThreshold(
      record.minQualityScore ?? record.min_quality_score,
      base.minQualityScore
    ),
    channels: normalizeChannels(record.channels, base.channels),
    updatedAt:
      typeof record.updatedAt === 'string'
        ? record.updatedAt
        : typeof record.updated_at === 'string'
          ? record.updated_at
          : base.updatedAt,
  };
}

/** 严格校验 PUT 请求体；通过时返回完整偏好，失败抛出中文错误。 */
export function validatePushPreferencesInput(value: unknown): PushPreferences {
  const record = asRecord(value);
  if (!record) {
    throw new PushPreferenceValidationError('请求体必须是 JSON 对象');
  }

  if ('enabled' in record && typeof record.enabled !== 'boolean') {
    throw new PushPreferenceValidationError('enabled 必须是布尔值');
  }

  let timeOfDay = DEFAULT_PUSH_PREFERENCES.timeOfDay;
  if ('timeOfDay' in record) {
    const text = String(record.timeOfDay ?? '').trim();
    if (!/^([01]?\d|2[0-3]):([0-5]\d)$/.test(text)) {
      throw new PushPreferenceValidationError('推送时间格式必须为 HH:MM');
    }
    timeOfDay = normalizeTimeOfDay(text);
  }

  let timezone = DEFAULT_PUSH_PREFERENCES.timezone;
  if ('timezone' in record) {
    if (!isValidTimezone(record.timezone)) {
      throw new PushPreferenceValidationError('时区不是有效的 IANA 时区');
    }
    timezone = String(record.timezone).trim();
  }

  const threshold = (key: 'minScore' | 'minQualityScore'): number => {
    if (!(key in record)) return DEFAULT_PUSH_PREFERENCES[key];
    const raw = record[key];
    if (typeof raw !== 'number' || !Number.isFinite(raw)) {
      throw new PushPreferenceValidationError(`${key} 必须是数字`);
    }
    if (raw < 0 || raw > 1) {
      throw new PushPreferenceValidationError(`${key} 必须在 0~1 之间`);
    }
    return normalizeThreshold(raw, DEFAULT_PUSH_PREFERENCES[key]);
  };

  let channels = { ...DEFAULT_PUSH_PREFERENCES.channels };
  if ('channels' in record) {
    const channelRecord = asRecord(record.channels);
    if (!channelRecord) {
      throw new PushPreferenceValidationError('channels 必须是对象');
    }
    for (const key of CHANNEL_KEYS) {
      if (key in channelRecord && typeof channelRecord[key] !== 'boolean') {
        throw new PushPreferenceValidationError(`channels.${key} 必须是布尔值`);
      }
    }
    channels = normalizeChannels(channelRecord, channels);
  }

  return {
    enabled:
      typeof record.enabled === 'boolean'
        ? record.enabled
        : DEFAULT_PUSH_PREFERENCES.enabled,
    timeOfDay,
    timezone,
    minScore: threshold('minScore'),
    minQualityScore: threshold('minQualityScore'),
    channels,
    updatedAt: null,
  };
}

export function parsePushPreferenceRow(row: PushPreferenceRow): PushPreferences {
  return {
    enabled: row.enabled === 1,
    timeOfDay: normalizeTimeOfDay(row.time_of_day),
    timezone: normalizeTimezone(row.timezone),
    minScore: normalizeThreshold(row.min_score, DEFAULT_PUSH_PREFERENCES.minScore),
    minQualityScore: normalizeThreshold(
      row.min_quality_score,
      DEFAULT_PUSH_PREFERENCES.minQualityScore
    ),
    channels: {
      inapp: row.channel_inapp === 1,
      bark: row.channel_bark === 1,
      telegram: row.channel_telegram === 1,
      email: row.channel_email === 1,
    },
    updatedAt: row.updated_at ?? null,
  };
}

export function pushPreferenceParams(
  userId: string,
  preferences: PushPreferences,
  updatedAt: string
): Array<string | number> {
  return [
    userId,
    preferences.enabled ? 1 : 0,
    preferences.timeOfDay,
    preferences.timezone,
    preferences.minScore,
    preferences.minQualityScore,
    preferences.channels.inapp ? 1 : 0,
    preferences.channels.bark ? 1 : 0,
    preferences.channels.telegram ? 1 : 0,
    preferences.channels.email ? 1 : 0,
    updatedAt,
  ];
}

/** 已开启通道的中文名，用于设置页摘要与测试。 */
export function enabledChannelLabels(preferences: PushPreferences): string[] {
  return CHANNEL_KEYS.filter((key) => preferences.channels[key]).map(
    (key) => CHANNEL_LABELS[key]
  );
}

/** 设置页副标题：例如「每天 09:00 · Asia/Shanghai · 站内通知」。 */
export function describePushPreferences(preferences: PushPreferences): string {
  const channels = enabledChannelLabels(preferences);
  const channelText = channels.length > 0 ? channels.join(' / ') : '未开启任何通道';
  return `每天 ${preferences.timeOfDay} · ${preferences.timezone} · ${channelText}`;
}
