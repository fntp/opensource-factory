import { clearCookies } from '@/test-utils/cookies'
import { beforeEach, describe, expect, it, vi } from 'vitest'

async function importAuthStore() {
  const mod = await import('./auth-store')
  return mod
}

const sampleUser = {
  id: '1',
  login: 'fntp',
  name: 'Fntp',
  email: 'fntp@example.com',
  avatarUrl: null,
}

describe('useAuthStore', () => {
  beforeEach(() => {
    clearCookies()
    vi.resetModules()
  })

  it('starts signed out when nothing is persisted', async () => {
    const { useAuthStore } = await importAuthStore()

    expect(useAuthStore.getState().auth.user).toBeNull()
  })

  it('persists the demo session so a fresh store instance reads it back', async () => {
    const { saveDemoSession } = await importAuthStore()
    saveDemoSession(sampleUser)

    // 通过查询参数击穿模块缓存，模拟「刷新页面后重新加载 store」
    vi.resetModules()
    const { useAuthStore } = (await import(
      /* @vite-ignore */ `./auth-store?fresh=${Date.now()}`
    )) as typeof import('./auth-store')

    expect(useAuthStore.getState().auth.user).toEqual(sampleUser)
  })

  it('updates the signed-in user via setUser', async () => {
    const { useAuthStore } = await importAuthStore()

    useAuthStore.getState().auth.setUser({ ...sampleUser })

    expect(useAuthStore.getState().auth.user).toEqual(sampleUser)
  })

  it('reset clears user and drops persistence', async () => {
    const { useAuthStore, saveDemoSession } = await importAuthStore()
    saveDemoSession(sampleUser)
    useAuthStore.getState().auth.setUser({ ...sampleUser })

    useAuthStore.getState().auth.reset()

    expect(useAuthStore.getState().auth.user).toBeNull()

    vi.resetModules()
    const { useAuthStore: useAuthStoreAfterReload } = (await import(
      /* @vite-ignore */ `./auth-store?fresh=${Date.now()}`
    )) as typeof import('./auth-store')

    expect(useAuthStoreAfterReload.getState().auth.user).toBeNull()
  })
})
