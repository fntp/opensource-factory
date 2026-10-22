/**
 * 边缘服务（Cloudflare Worker）API 客户端。
 *
 * - 通过 VITE_API_BASE_URL 指向 Worker 地址；留空表示与前端同源（开发期由 Vite 代理 /api）。
 * - 使用 GitHub OAuth 会话（httpOnly Cookie），前端不持久化任何用户凭证。
 * - 所有错误统一抛出 ApiHttpError / ApiNetworkError，由页面或全局 QueryCache 呈现。
 */

/** 边缘服务地址；空字符串表示同源 */
export const API_BASE: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''
).trim()

/** 请求超时（毫秒） */
const REQUEST_TIMEOUT_MS = 15_000

/** 后端错误响应体（与 edge 的 `{ error }` 约定一致） */
export interface ApiErrorPayload {
  error?: string
  message?: string
}

/** HTTP 非 2xx 错误：携带状态码与后端错误码，便于页面精确提示 */
export class ApiHttpError extends Error {
  status: number
  statusText: string
  /** 后端错误码，如 unauthorized / category_name_exists */
  code: string | null
  /** 后端可选的详细说明 */
  detail: string | null

  constructor(
    status: number,
    statusText: string,
    payload?: ApiErrorPayload | null
  ) {
    const code = typeof payload?.error === 'string' ? payload.error : null
    const detail = typeof payload?.message === 'string' ? payload.message : null
    super(
      code || detail
        ? `${code ?? 'API'}: ${detail ?? statusText}`
        : `API ${status}: ${statusText}`
    )
    this.name = 'ApiHttpError'
    this.status = status
    this.statusText = statusText
    this.code = code
    this.detail = detail
  }
}

/** 网络层错误：无法连接、超时等（没有 HTTP 状态码） */
export class ApiNetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiNetworkError'
  }
}

async function parseErrorPayload(
  res: Response
): Promise<ApiErrorPayload | null> {
  try {
    const data: unknown = await res.json()
    if (data && typeof data === 'object') {
      return data as ApiErrorPayload
    }
  } catch {
    // 非 JSON 错误体（网关 HTML 等）按无 payload 处理
  }
  return null
}

/** 基础请求封装：自动携带会话 Cookie，非 2xx 抛出 ApiHttpError */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, REQUEST_TIMEOUT_MS)

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init.headers ?? {}),
      },
      signal: init.signal ?? controller.signal,
    })
  } catch (err) {
    if (timedOut) {
      throw new ApiNetworkError('请求超时，请稍后重试')
    }
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiNetworkError('请求已取消')
    }
    throw new ApiNetworkError('无法连接服务器，请检查网络或服务状态')
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    const payload = await parseErrorPayload(res)
    throw new ApiHttpError(res.status, res.statusText, payload)
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
  name: string | null
  email: string | null
  avatarUrl: string | null
}

/** 生成 GitHub OAuth 登录跳转地址 */
export function githubLoginUrl(redirectTo?: string): string {
  const base = API_BASE || window.location.origin
  const url = new URL('/api/auth/github/login', base)
  if (redirectTo) {
    url.searchParams.set('redirect', redirectTo)
  }
  return url.toString()
}

/** 拉取当前登录用户；401 表示未登录，其余错误向上抛出供页面呈现 */
export function fetchCurrentUser(): Promise<AuthUser> {
  return apiFetch<AuthUser>('/api/auth/me')
}

/** 退出登录（通知边缘服务清除会话） */
export function logout(): Promise<void> {
  return apiFetch<void>('/api/auth/logout', { method: 'POST' })
}

const STATUS_MESSAGES: Record<number, string> = {
  400: '请求参数有误，请检查后重试',
  401: '登录已过期，请重新登录',
  403: '没有权限执行此操作',
  404: '请求的资源不存在',
  409: '数据冲突，请刷新后重试',
  429: '请求过于频繁，请稍后重试',
  500: '服务器内部错误，请稍后重试',
  502: '上游服务不可用，请稍后重试',
  503: '服务暂时不可用，请稍后重试',
}

const CODE_MESSAGES: Record<string, string> = {
  unauthorized: '登录已过期，请重新登录',
  forbidden: '没有权限执行此操作',
  not_found: '请求的资源不存在',
  github_oauth_not_configured: 'GitHub OAuth 尚未配置，请联系维护者',
  invalid_oauth_state: '登录状态已失效，请重新登录',
  github_token_exchange_failed: 'GitHub 授权失败，请重试',
  github_user_fetch_failed: '获取 GitHub 用户信息失败，请重试',
  oauth_denied: '你取消了 GitHub 授权',
  vps_node_not_configured: 'VPS 节点尚未配置，同步任务未执行',
  vps_node_unreachable: '无法连接 VPS 节点，请稍后重试',
  vps_node_error: 'VPS 节点返回错误，请稍后重试',
}

/** 把任意错误转成用户可读的中文文案 */
export function apiErrorMessage(
  error: unknown,
  fallback = '操作失败，请稍后重试'
): string {
  if (error instanceof ApiHttpError) {
    if (error.code && CODE_MESSAGES[error.code]) {
      return CODE_MESSAGES[error.code]
    }
    if (error.detail) return error.detail
    return STATUS_MESSAGES[error.status] ?? `请求失败（${error.status}）`
  }
  if (error instanceof ApiNetworkError) {
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}
