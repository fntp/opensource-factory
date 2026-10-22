/**
 * 开源项目工厂 · PWA Service Worker
 *
 * 策略：
 * - App Shell（/、offline.html、manifest、图标）安装时预缓存；
 * - 导航请求网络优先，断网时回退缓存页面；
 * - 同源静态资源缓存优先，运行时回填；
 * - /api/*、非 GET、跨域请求一律不拦截，避免缓存鉴权数据。
 */

const CACHE_VERSION = '2026-10-22-1'
const APP_SHELL_CACHE = `of-app-shell-${CACHE_VERSION}`
const RUNTIME_CACHE = `of-runtime-${CACHE_VERSION}`

const APP_SHELL_URLS = [
  '/',
  '/offline.html',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-192.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(APP_SHELL_CACHE)
      .then((cache) => cache.addAll(APP_SHELL_URLS))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) => key !== APP_SHELL_CACHE && key !== RUNTIME_CACHE
            )
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request))
    return
  }

  if (isCacheableAsset(url.pathname)) {
    event.respondWith(cacheFirst(request))
  }
})

function isCacheableAsset(pathname) {
  if (pathname === '/sw.js') return false
  return (
    pathname.startsWith('/assets/') ||
    pathname.startsWith('/icons/') ||
    pathname.startsWith('/images/') ||
    /\.(?:css|js|mjs|woff2?|png|jpe?g|svg|webp|ico)$/i.test(pathname)
  )
}

async function networkFirstNavigation(request) {
  const cache = await caches.open(RUNTIME_CACHE)
  try {
    const response = await fetch(request)
    if (response && response.ok) {
      cache.put(request, response.clone())
    }
    return response
  } catch {
    const cached = await cache.match(request)
    if (cached) return cached
    return (
      (await caches.match('/')) ||
      (await caches.match('/offline.html')) ||
      new Response('Offline', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      })
    )
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request)
  if (cached) return cached

  try {
    const response = await fetch(request)
    if (response && response.ok) {
      const cache = await caches.open(RUNTIME_CACHE)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    return new Response('Offline', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    })
  }
}
