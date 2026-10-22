/**
 * 边缘服务（Cloudflare Worker）API 客户端。
 *
 * - 生产环境：通过 VITE_API_BASE_URL 指向 Worker 地址，使用 GitHub OAuth 会话（httpOnly Cookie）。
 * - 本地开发：未配置 VITE_API_BASE_URL 时自动进入演示模式（DEMO_MODE），使用内置演示数据。
 */

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

/** 是否处于本地演示模式（无后端预览） */
export const DEMO_MODE: boolean =
  String(import.meta.env.VITE_DEMO_MODE ?? '') === 'true' || API_BASE === ''

export class ApiHttpError extends Error {
  status: number
  /** 后端错误码（响应体 `{ error: "<code>" }`），用于业务侧精确提示 */
  code?: string

  constructor(status: number, statusText: string, code?: string) {
    super(`API ${status}: ${statusText}`)
    this.name = 'ApiHttpError'
    this.status = status
    this.code = code
  }
}

/** 基础请求封装：自动携带会话 Cookie，非 2xx 抛出 ApiHttpError */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.headers ?? {}),
    },
  })
  if (!res.ok) {
    let code: string | undefined
    try {
      const body = (await res.json()) as { error?: unknown }
      if (typeof body.error === 'string') code = body.error
    } catch {
      // 响应体不是 JSON（如网关错误页）时忽略，仅保留状态码
    }
    throw new ApiHttpError(res.status, res.statusText, code)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

/** 当前登录用户（与边缘服务 /api/auth/me 对齐） */
export interface AuthUser {
  id: string
  login: string
  name: string
  email: string | null
  avatarUrl: string | null
}

/** 生成 GitHub OAuth 登录跳转地址 */
export function githubLoginUrl(redirectTo?: string): string {
  const url = new URL(
    `${API_BASE}/api/auth/github/login`,
    window.location.origin
  )
  if (redirectTo) {
    url.searchParams.set('redirect', redirectTo)
  }
  return url.toString()
}

/** 拉取当前登录用户；未登录或网络失败返回 null */
export async function fetchCurrentUser(): Promise<AuthUser | null> {
  try {
    return await apiFetch<AuthUser>('/api/auth/me')
  } catch {
    return null
  }
}

/** 退出登录（通知边缘服务清除会话；失败不影响本地退出） */
export async function logout(): Promise<void> {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' })
  } catch {
    // 忽略退出失败（例如离线或演示模式）
  }
}

/** 通用的「演示数据兜底」请求：请求失败时回退到演示数据 */
export async function fetchWithFallback<T>(
  path: string,
  fallback: T
): Promise<T> {
  try {
    return await apiFetch<T>(path)
  } catch {
    // eslint-disable-next-line no-console
    console.info(`[opensource-factory] API 不可用，使用演示数据：${path}`)
    return fallback
  }
}
