import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PUSH_PREFERENCES,
  describePushPreferences,
  enabledChannelLabels,
  normalizePushPreferences,
  parsePushPreferencesPayload,
  validatePushPreferences,
} from './api'

describe('normalizePushPreferences', () => {
  it('returns defaults for invalid input', () => {
    const preferences = normalizePushPreferences(null)
    expect(preferences).toEqual(DEFAULT_PUSH_PREFERENCES)
  })

  it('parses edge camelCase payload and clamps thresholds', () => {
    const preferences = normalizePushPreferences({
      enabled: false,
      timeOfDay: '9:05',
      timezone: 'Asia/Tokyo',
      minScore: 1.5,
      minQualityScore: -0.2,
      channels: { inapp: true, bark: 1, telegram: false, email: 0 },
      updatedAt: '2026-10-22T08:00:00.000Z',
    })
    expect(preferences.enabled).toBe(false)
    expect(preferences.timeOfDay).toBe('09:05')
    expect(preferences.timezone).toBe('Asia/Tokyo')
    expect(preferences.minScore).toBe(1)
    expect(preferences.minQualityScore).toBe(0)
    expect(preferences.channels.bark).toBe(true)
    expect(preferences.channels.email).toBe(false)
  })

  it('falls back for invalid timezone and time', () => {
    const preferences = normalizePushPreferences({
      timeOfDay: '25:00',
      timezone: 'Mars/Olympus',
    })
    expect(preferences.timeOfDay).toBe('09:00')
    expect(preferences.timezone).toBe('Asia/Shanghai')
  })
})

describe('parsePushPreferencesPayload', () => {
  it('unwraps the preferences envelope and keeps isDefault', () => {
    const payload = parsePushPreferencesPayload({
      preferences: { ...DEFAULT_PUSH_PREFERENCES, timeOfDay: '20:00' },
      isDefault: true,
    })
    expect(payload.preferences.timeOfDay).toBe('20:00')
    expect(payload.isDefault).toBe(true)
    expect(payload.availableChannels).toEqual([
      'inapp',
      'bark',
      'telegram',
      'email',
    ])
  })
})

describe('validatePushPreferences', () => {
  it('accepts the defaults', () => {
    expect(validatePushPreferences(DEFAULT_PUSH_PREFERENCES)).toEqual([])
  })

  it('reports time, timezone and threshold errors', () => {
    const errors = validatePushPreferences({
      ...DEFAULT_PUSH_PREFERENCES,
      timeOfDay: '25:00',
      timezone: 'Not/AZone',
      minScore: 2,
      minQualityScore: -1,
    })
    expect(errors).toHaveLength(4)
    expect(errors.join(' ')).toContain('HH:MM')
    expect(errors.join(' ')).toContain('IANA')
  })
})

describe('describePushPreferences', () => {
  it('summarises enabled channels', () => {
    const preferences = {
      ...DEFAULT_PUSH_PREFERENCES,
      channels: { inapp: true, bark: true, telegram: false, email: false },
    }
    expect(enabledChannelLabels(preferences)).toEqual(['站内通知', 'Bark'])
    expect(describePushPreferences(preferences)).toBe(
      '每天 09:00 · Asia/Shanghai · 站内通知 / Bark'
    )
  })

  it('marks the empty channel state', () => {
    const preferences = {
      ...DEFAULT_PUSH_PREFERENCES,
      channels: { inapp: false, bark: false, telegram: false, email: false },
    }
    expect(describePushPreferences(preferences)).toContain('未开启任何通道')
  })
})
