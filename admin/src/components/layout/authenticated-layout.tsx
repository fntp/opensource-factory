import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { getCookie } from '@/lib/cookies'
import { DEMO_MODE, fetchCurrentUser } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth-store'
import { LayoutProvider } from '@/context/layout-provider'
import { SearchProvider } from '@/context/search-provider'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { SkipToMain } from '@/components/skip-to-main'

type AuthenticatedLayoutProps = {
  children?: React.ReactNode
}

export function AuthenticatedLayout({ children }: AuthenticatedLayoutProps) {
  const defaultOpen = getCookie('sidebar_state') !== 'false'
  const { auth } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [status, setStatus] = useState<'checking' | 'ready' | 'redirect'>(
    auth.user ? 'ready' : DEMO_MODE ? 'redirect' : 'checking'
  )

  // 会话检查：本地已有用户或演示模式无需请求；否则向后端确认一次
  useEffect(() => {
    if (auth.user || DEMO_MODE) return
    let cancelled = false
    fetchCurrentUser().then((user) => {
      if (cancelled) return
      if (user) {
        auth.setUser(user)
        setStatus('ready')
      } else {
        setStatus('redirect')
      }
    })
    return () => {
      cancelled = true
    }
    // 仅在挂载时检查一次会话
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (status === 'redirect') {
      navigate({
        to: '/sign-in',
        search: { redirect: location.href },
        replace: true,
      })
    }
  }, [status, navigate, location.href])

  if (status === 'checking') {
    return (
      <div className='flex h-svh items-center justify-center'>
        <Loader2 className='size-6 animate-spin text-muted-foreground' />
      </div>
    )
  }

  if (status === 'redirect') {
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
              // set the height to 100svh - spacing (total margins) to prevent overflow
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
