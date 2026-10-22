import { create } from 'zustand'
import type { AuthUser } from '@/lib/api'

/**
 * 登录用户状态（仅内存）。
 *
 * 真实会话由边缘服务的 httpOnly Cookie 维护，页面刷新后由
 * `AuthenticatedLayout` 调用 `/api/auth/me` 恢复，不在浏览器持久化用户信息。
 */
interface AuthState {
  auth: {
    user: AuthUser | null
    setUser: (user: AuthUser | null) => void
    reset: () => void
  }
}

export const useAuthStore = create<AuthState>()((set) => ({
  auth: {
    user: null,
    setUser: (user) =>
      set((state) => ({ ...state, auth: { ...state.auth, user } })),
    reset: () =>
      set((state) => ({ ...state, auth: { ...state.auth, user: null } })),
  },
}))
