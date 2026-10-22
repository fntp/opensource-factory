/**
 * PWA 安装 / 运行模式判定。
 *
 * 这里只放可在浏览器与测试环境复用的纯函数，Service Worker 注册见
 * `service-worker.ts`，界面见 `components/pwa/pwa-provider.tsx`。
 */

export const PWA_UPDATE_EVENT = 'of:pwa-update-ready'

/** 用户关闭安装提示后，7 天内不再展示。 */
export const INSTALL_DISMISS_TTL_MS = 7 * 24 * 60 * 60 * 1000

const INSTALL_DISMISS_KEY = 'of.pwa.install.dismissedAt'

export interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[]
  readonly userChoice: Promise<{
    outcome: 'accepted' | 'dismissed'
    platform: string
  }>
  prompt: () => Promise<void>
}

export interface StandaloneEnvironment {
  /** `window.matchMedia('(display-mode: standalone)').matches` */
  displayModeStandalone: boolean
  /** iOS Safari 的 `navigator.standalone` */
  navigatorStandalone?: boolean
}

export function isStandaloneApp(env: StandaloneEnvironment): boolean {
  return env.displayModeStandalone || Boolean(env.navigatorStandalone)
}

/**
 * 识别 iOS / iPadOS。iPadOS 13+ 的桌面 UA 是 Macintosh，需要用触摸点数区分。
 */
export function isIosDevice(userAgent: string, maxTouchPoints = 0): boolean {
  if (/iphone|ipad|ipod/i.test(userAgent)) return true
  return /macintosh/i.test(userAgent) && maxTouchPoints > 1
}

export interface InstallPromptVisibilityOptions {
  standalone: boolean
  dismissedAt: number | null
  now?: number
  ttl?: number
}

export function shouldShowInstallPrompt({
  standalone,
  dismissedAt,
  now = Date.now(),
  ttl = INSTALL_DISMISS_TTL_MS,
}: InstallPromptVisibilityOptions): boolean {
  if (standalone) return false
  if (dismissedAt === null) return true
  return now - dismissedAt >= ttl
}

export function readInstallDismissedAt(
  storage: Pick<Storage, 'getItem'>
): number | null {
  const raw = storage.getItem(INSTALL_DISMISS_KEY)
  if (!raw) return null
  const value = Number(raw)
  return Number.isFinite(value) && value > 0 ? value : null
}

export function markInstallDismissed(
  storage: Pick<Storage, 'setItem'>,
  now = Date.now()
): void {
  storage.setItem(INSTALL_DISMISS_KEY, String(now))
}
