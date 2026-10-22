import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiHttpError, ApiNetworkError } from './api'
import { handleServerError } from './handle-server-error'

const toastError = vi.hoisted(() => vi.fn())

vi.mock('sonner', () => ({
  toast: {
    error: toastError,
  },
}))

beforeEach(() => {
  vi.mocked(toastError).mockClear()
})

describe('handleServerError', () => {
  it('shows a generic message when the error is not recognised', () => {
    handleServerError(new Error(''))

    expect(toastError).toHaveBeenCalledWith('操作失败，请稍后重试')
  })

  it('maps a plain object with status 204 to the no-content message', () => {
    handleServerError({ status: 204 })

    expect(toastError).toHaveBeenCalledWith('请求成功但无返回内容')
  })

  it('maps ApiHttpError status to a readable message', () => {
    handleServerError(new ApiHttpError(401, 'Unauthorized', { error: 'unauthorized' }))

    expect(toastError).toHaveBeenCalledWith('登录已过期，请重新登录')
  })

  it('prefers the backend error code mapping', () => {
    handleServerError(
      new ApiHttpError(502, 'Bad Gateway', { error: 'vps_node_unreachable' })
    )

    expect(toastError).toHaveBeenCalledWith('无法连接 VPS 节点，请稍后重试')
  })

  it('shows the network error message', () => {
    handleServerError(new ApiNetworkError('无法连接服务器，请检查网络或服务状态'))

    expect(toastError).toHaveBeenCalledWith('无法连接服务器，请检查网络或服务状态')
  })

  it('logs the error to the console in development', () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {})
    const err = new Error('logged')

    handleServerError(err)

    expect(log).toHaveBeenCalledTimes(1)
    expect(log).toHaveBeenCalledWith(err)

    log.mockRestore()
  })

  it('does not log the error to the console in production', () => {
    vi.stubEnv('DEV', false)

    const log = vi.spyOn(console, 'log').mockImplementation(() => {})
    const err = new Error('not logged')

    handleServerError(err)

    expect(log).not.toHaveBeenCalled()

    log.mockRestore()
  })
})
