import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { getCookie } from '@/lib/cookies'
import { ApiHttpError, fetchCurrentUser } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth-store'
import { LayoutProvider } from '@/context/layout-provider'
import { SearchProvider } from '@/context/search-provider'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { SkipToMain } from '@/components/skip-to-main'
import { ErrorState } from '@/components/data-state'

type AuthenticatedLayoutProps = {
  children?: React.ReactNode
}

type SessionStatus = 'checking' | 'ready' | 'unauthenticated' | 'error'

export function AuthenticatedLayout({ children }: AuthenticatedLayoutProps) {
  const defaultOpen = getCookie('sidebar_state') !== 'false'
  const { auth } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [status, setStatus] = useState<SessionStatus>(
    auth.user ? 'ready' : 'checking'
  )
  const [error, setError] = useState<unknown>(null)
  const [retryKey, setRetryKey] = useState(0)

  // 会话检查：本地已有用户（刚登录）直接用；否则向后端确认一次。
  // 401 → 跳登录；网络 / 5xx → 可重试错误态，避免误判为未登录。
  useEffect(() => {
    if (auth.user) return
    let cancelled = false

    fetchCurrentUser()
      .then((user) => {
        if (cancelled) return
        auth.setUser(user)
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiHttpError && err.status === 401) {
          setStatus('unauthenticated')
          return
        }
        setError(err)
        setStatus('error')
      })

    return () => {
      cancelled = true
    }
    // 仅在挂载 / 手动重试时检查会话
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retryKey])

  useEffect(() => {
    if (status === 'unauthenticated') {
      navigate({
        to: '/sign-in',
        search: { redirect: location.href },
        replace: true,
      })
    }
  }, [status, navigate, location.href])

  if (status === 'checking') {
    return (
      <div className='flex h-svh flex-col items-center justify-center gap-3'>
        <Loader2 className='size-6 animate-spin text-muted-foreground' />
        <p className='text-sm text-muted-foreground'>正在确认登录状态…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className='flex h-svh items-center justify-center p-6'>
        <ErrorState
          error={error}
          title='无法确认登录状态'
          onRetry={() => {
            setStatus('checking')
            setError(null)
            setRetryKey((key) => key + 1)
          }}
        />
      </div>
    )
  }

  if (status === 'unauthenticated') {
    return null
  }

  return (
    <SearchProvider>
      <LayoutProvider>
        <SidebarProvider defaultOpen={defaultOpen}>
          <SkipToMain />
          <AppSidebar />
          <SidebarInset
            className={cn(
              // Set content container, so we can use container queries
              '@container/content',

              // If layout is fixed, set the height
              // to 100svh to prevent overflow
              'has-data-[layout=fixed]:h-svh',

              // If layout is fixed and sidebar is inset,
              // set the height to 100svh - spacing (total margins) to fit
              'peer-data-[variant=inset]:has-data-[layout=fixed]:h-[calc(100svh-(var(--spacing)*4))]'
            )}
          >
            {children ?? <Outlet />}
          </SidebarInset>
        </SidebarProvider>
      </LayoutProvider>
    </SearchProvider>
  )
}
