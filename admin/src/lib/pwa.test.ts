import { describe, expect, it, vi } from 'vitest'
import {
  INSTALL_DISMISS_TTL_MS,
  isIosDevice,
  isStandaloneApp,
  markInstallDismissed,
  readInstallDismissedAt,
  shouldShowInstallPrompt,
} from './pwa'

describe('isStandaloneApp', () => {
  it('detects display-mode standalone', () => {
    expect(
      isStandaloneApp({
        displayModeStandalone: true,
        navigatorStandalone: false,
      })
    ).toBe(true)
  })

  it('detects iOS navigator.standalone', () => {
    expect(
      isStandaloneApp({
        displayModeStandalone: false,
        navigatorStandalone: true,
      })
    ).toBe(true)
  })

  it('returns false in a normal browser tab', () => {
    expect(isStandaloneApp({ displayModeStandalone: false })).toBe(false)
  })
})

describe('isIosDevice', () => {
  it('detects iPhone and iPad user agents', () => {
    expect(
      isIosDevice(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15'
      )
    ).toBe(true)
    expect(
      isIosDevice(
        'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15'
      )
    ).toBe(true)
  })

  it('detects iPadOS desktop UA by touch points', () => {
    expect(
      isIosDevice(
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        5
      )
    ).toBe(true)
  })

  it('does not treat a desktop Mac as iOS', () => {
    expect(
      isIosDevice(
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        0
      )
    ).toBe(false)
  })
})

describe('shouldShowInstallPrompt', () => {
  const now = 1_700_000_000_000

  it('hides the prompt when already installed', () => {
    expect(
      shouldShowInstallPrompt({ standalone: true, dismissedAt: null, now })
    ).toBe(false)
  })

  it('shows the prompt when it was never dismissed', () => {
    expect(
      shouldShowInstallPrompt({ standalone: false, dismissedAt: null, now })
    ).toBe(true)
  })

  it('hides the prompt during the 7-day cooldown', () => {
    expect(
      shouldShowInstallPrompt({
        standalone: false,
        dismissedAt: now - INSTALL_DISMISS_TTL_MS + 1,
        now,
      })
    ).toBe(false)
  })

  it('shows the prompt again after the cooldown', () => {
    expect(
      shouldShowInstallPrompt({
        standalone: false,
        dismissedAt: now - INSTALL_DISMISS_TTL_MS,
        now,
      })
    ).toBe(true)
  })
})

describe('install dismissal storage', () => {
  it('reads a valid timestamp', () => {
    const storage = { getItem: vi.fn(() => '1700000000000') }
    expect(readInstallDismissedAt(storage)).toBe(1_700_000_000_000)
  })

  it('ignores missing or invalid values', () => {
    expect(readInstallDismissedAt({ getItem: () => null })).toBeNull()
    expect(readInstallDismissedAt({ getItem: () => 'not-a-number' })).toBeNull()
    expect(readInstallDismissedAt({ getItem: () => '-1' })).toBeNull()
  })

  it('writes the dismissal timestamp', () => {
    const setItem = vi.fn()
    markInstallDismissed({ setItem }, 1_700_000_000_000)
    expect(setItem).toHaveBeenCalledWith(
      'of.pwa.install.dismissedAt',
      '1700000000000'
    )
  })
})
