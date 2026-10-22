import { PWA_UPDATE_EVENT } from './pwa'

/**
 * 注册 PWA Service Worker。
 *
 * - 只在生产构建注册，避免开发时 SW 缓存干扰 HMR；
 * - 注册失败视为增强能力不可用，不影响页面主流程；
 * - 新版本安装完成且已有页面受控时，派发更新事件供界面提示刷新。
 */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return
  if (typeof window === 'undefined') return
  if (!('serviceWorker' in navigator)) return

  const register = () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        registration.addEventListener('updatefound', () => {
          const worker = registration.installing
          if (!worker) return
          worker.addEventListener('statechange', () => {
            if (
              worker.state === 'installed' &&
              navigator.serviceWorker.controller
            ) {
              window.dispatchEvent(new Event(PWA_UPDATE_EVENT))
            }
          })
        })
      })
      .catch(() => {
        // PWA 是渐进增强能力：注册失败不阻塞页面。
      })
  }

  if (document.readyState === 'complete') {
    register()
  } else {
    window.addEventListener('load', register, { once: true })
  }
}
