import { describe, expect, it } from 'vitest'
import {
  DEFAULT_TELEGRAM_COMMANDS,
  formatLinkCodeRemaining,
  formatTelegramTime,
  maskTelegramChatId,
  normalizeTelegramStatus,
  parseTelegramLinkCode,
} from './telegram-bot-api'

describe('normalizeTelegramStatus', () => {
  it('parses a linked status and masks the chat id', () => {
    const status = normalizeTelegramStatus({
      configured: true,
      botUsername: 'OpenFactoryBot',
      webhookPath: '/api/telegram/webhook',
      linked: true,
      link: {
        chatId: '1234567890',
        username: 'alice_tg',
        login: 'alice',
        linkedAt: '2026-10-22T08:00:00.000Z',
        lastSeenAt: '2026-10-22T09:00:00.000Z',
      },
      commands: [{ command: 'favorites', description: '查看收藏' }],
    })
    expect(status.configured).toBe(true)
    expect(status.linked).toBe(true)
    expect(status.link?.chatId).toBe('***7890')
    expect(status.link?.login).toBe('alice')
    expect(status.commands).toEqual([{ command: 'favorites', description: '查看收藏' }])
  })

  it('falls back to default commands and unlinked state', () => {
    const status = normalizeTelegramStatus({
      configured: false,
      linked: false,
      commands: [],
    })
    expect(status.configured).toBe(false)
    expect(status.linked).toBe(false)
    expect(status.link).toBeNull()
    expect(status.commands).toEqual(DEFAULT_TELEGRAM_COMMANDS)
  })

  it('does not double-mask an already masked chat id', () => {
    expect(maskTelegramChatId('***7890')).toBe('***7890')
    expect(maskTelegramChatId('42')).toBe('***')
    expect(maskTelegramChatId(null)).toBe('')
  })
})

describe('parseTelegramLinkCode', () => {
  it('parses a valid code response', () => {
    const code = parseTelegramLinkCode({
      code: '012345',
      expiresAt: '2026-10-22T09:10:00.000Z',
      command: '/link 012345',
      deepLink: 'https://t.me/OpenFactoryBot?start=012345',
      botUsername: 'OpenFactoryBot',
    })
    expect(code.code).toBe('012345')
    expect(code.command).toBe('/link 012345')
    expect(code.deepLink).toContain('start=012345')
  })

  it('rejects malformed codes', () => {
    expect(() => parseTelegramLinkCode({ code: '12ab' })).toThrow()
    expect(() => parseTelegramLinkCode(null)).toThrow()
  })
})

describe('formatLinkCodeRemaining', () => {
  it('formats minutes and seconds', () => {
    const now = Date.parse('2026-10-22T09:00:00.000Z')
    expect(formatLinkCodeRemaining('2026-10-22T09:02:05.000Z', now)).toBe('剩余 2 分 5 秒')
    expect(formatLinkCodeRemaining('2026-10-22T09:00:30.000Z', now)).toBe('剩余 30 秒')
  })

  it('marks expired and invalid values', () => {
    const now = Date.parse('2026-10-22T09:00:00.000Z')
    expect(formatLinkCodeRemaining('2026-10-22T08:59:00.000Z', now)).toBe('已过期')
    expect(formatLinkCodeRemaining('not-a-date', now)).toBe('有效期未知')
  })
})

describe('formatTelegramTime', () => {
  it('formats local timestamps and handles invalid values', () => {
    const local = new Date(2026, 9, 22, 8, 5)
    expect(formatTelegramTime(local.toISOString())).toBe('2026-10-22 08:05')
    expect(formatTelegramTime('bad')).toBe('—')
    expect(formatTelegramTime(null)).toBe('—')
  })
})
