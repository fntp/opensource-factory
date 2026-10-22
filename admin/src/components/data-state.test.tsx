import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { ApiHttpError } from '@/lib/api'
import { EmptyState, ErrorState, LoadingState } from './data-state'

describe('DataState', () => {
  it('renders loading label and skeleton rows', async () => {
    const { getByText, container } = await render(
      <LoadingState label='正在加载仓库…' rows={2} />
    )

    await expect.element(getByText('正在加载仓库…')).toBeInTheDocument()
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(2)
  })

  it('renders empty title, description, and action', async () => {
    const { getByText, getByRole } = await render(
      <EmptyState
        title='还没有仓库'
        description='同步后展示'
        action={<button>立即同步</button>}
      />
    )

    await expect.element(getByText('还没有仓库')).toBeInTheDocument()
    await expect.element(getByText('同步后展示')).toBeInTheDocument()
    await expect
      .element(getByRole('button', { name: '立即同步' }))
      .toBeInTheDocument()
  })

  it('renders a readable error and calls onRetry', async () => {
    const onRetry = vi.fn()
    const { getByText, getByRole } = await render(
      <ErrorState
        error={new ApiHttpError(401, 'Unauthorized', { error: 'unauthorized' })}
        onRetry={onRetry}
      />
    )

    await expect.element(getByText('加载失败')).toBeInTheDocument()
    await expect
      .element(getByText('登录已过期，请重新登录'))
      .toBeInTheDocument()

    await userEvent.click(getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('hides the retry button without onRetry', async () => {
    const { container } = await render(<ErrorState error={new Error('boom')} />)

    expect(container.textContent).not.toContain('重试')
  })
})
