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
    vi.resetModules()
  })

  it('starts signed out', async () => {
    const { useAuthStore } = await importAuthStore()

    expect(useAuthStore.getState().auth.user).toBeNull()
  })

  it('updates the signed-in user via setUser', async () => {
    const { useAuthStore } = await importAuthStore()

    useAuthStore.getState().auth.setUser({ ...sampleUser })

    expect(useAuthStore.getState().auth.user).toEqual(sampleUser)
  })

  it('reset clears the user without persisting anything', async () => {
    const { useAuthStore } = await importAuthStore()
    useAuthStore.getState().auth.setUser({ ...sampleUser })

    useAuthStore.getState().auth.reset()

    expect(useAuthStore.getState().auth.user).toBeNull()

    // 刷新页面后不会从浏览器存储恢复用户，需重新走 /api/auth/me
    vi.resetModules()
    const { useAuthStore: useAuthStoreAfterReload } = await importAuthStore()

    expect(useAuthStoreAfterReload.getState().auth.user).toBeNull()
  })
})
