import { create } from 'zustand'
import { getCookie, setCookie, removeCookie } from '@/lib/cookies'
import type { AuthUser } from '@/lib/api'

/** 演示模式会话持久化的 cookie 名（真实会话由边缘服务 httpOnly Cookie 维护） */
const DEMO_SESSION_COOKIE = 'of_demo_session'

function readDemoSession(): AuthUser | null {
  const raw = getCookie(DEMO_SESSION_COOKIE)
  if (!raw) return null
  try {
    return JSON.parse(decodeURIComponent(raw)) as AuthUser
  } catch {
    return null
  }
}

interface AuthState {
  auth: {
    user: AuthUser | null
    setUser: (user: AuthUser | null) => void
    reset: () => void
  }
}

export const useAuthStore = create<AuthState>()((set) => ({
  auth: {
    user: readDemoSession(),
    setUser: (user) =>
      set((state) => ({ ...state, auth: { ...state.auth, user } })),
    reset: () => {
      removeCookie(DEMO_SESSION_COOKIE)
      set((state) => ({ ...state, auth: { ...state.auth, user: null } }))
    },
  },
}))

/** 演示模式登录：持久化会话，刷新后仍保持登录态 */
export function saveDemoSession(user: AuthUser): void {
  setCookie(DEMO_SESSION_COOKIE, encodeURIComponent(JSON.stringify(user)))
}
