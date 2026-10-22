import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiHttpError,
  ApiNetworkError,
  apiErrorMessage,
  apiFetch,
  githubLoginUrl,
} from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ApiHttpError', () => {
  it('keeps status and backend error code', () => {
    const error = new ApiHttpError(403, 'Forbidden', {
      error: 'forbidden',
      message: '没有权限',
    })

    expect(error.status).toBe(403)
    expect(error.code).toBe('forbidden')
    expect(error.detail).toBe('没有权限')
    expect(error.message).toContain('forbidden')
  })

  it('works without an error payload', () => {
    const error = new ApiHttpError(500, 'Internal Server Error')

    expect(error.code).toBeNull()
    expect(error.detail).toBeNull()
    expect(error.message).toBe('API 500: Internal Server Error')
  })
})

describe('apiFetch', () => {
  it('sends credentials and parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ hello: 'world' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiFetch<{ hello: string }>('/api/demo')).resolves.toEqual({
      hello: 'world',
    })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/demo')
    expect(init.credentials).toBe('include')
    expect((init.headers as Record<string, string>).Accept).toBe(
      'application/json'
    )
  })

  it('returns undefined for 204 responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    )

    await expect(apiFetch<void>('/api/auth/logout')).resolves.toBeUndefined()
  })

  it('throws ApiHttpError with the backend error code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: 'unauthorized' }, 401)
      )
    )

    await expect(apiFetch('/api/auth/me')).rejects.toMatchObject({
      name: 'ApiHttpError',
      status: 401,
      code: 'unauthorized',
    })
  })

  it('throws ApiNetworkError when fetch rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    )

    await expect(apiFetch('/api/repos')).rejects.toBeInstanceOf(
      ApiNetworkError
    )
  })
})

describe('apiErrorMessage', () => {
  it('maps known status codes', () => {
    expect(apiErrorMessage(new ApiHttpError(401, 'Unauthorized'))).toBe(
      '登录已过期，请重新登录'
    )
  })

  it('prefers the backend code mapping', () => {
    expect(
      apiErrorMessage(
        new ApiHttpError(502, 'Bad Gateway', { error: 'vps_node_error' })
      )
    ).toBe('VPS 节点返回错误，请稍后重试')
  })

  it('falls back to the detail or status text', () => {
    expect(
      apiErrorMessage(
        new ApiHttpError(422, 'Unprocessable Entity', { message: '字段不合法' })
      )
    ).toBe('字段不合法')
    expect(apiErrorMessage(new ApiHttpError(418, 'I am a teapot'))).toBe(
      '请求失败（418）'
    )
  })

  it('uses the provided fallback for unknown errors', () => {
    expect(apiErrorMessage(undefined, '自定义兜底')).toBe('自定义兜底')
  })
})

describe('githubLoginUrl', () => {
  it('builds the login URL and keeps the redirect target', () => {
    const url = new URL(githubLoginUrl('/repos'))
    expect(url.pathname).toBe('/api/auth/github/login')
    expect(url.searchParams.get('redirect')).toBe('/repos')
  })
})
