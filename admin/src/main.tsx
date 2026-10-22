import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import {
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'
import { ApiHttpError, ApiNetworkError } from '@/lib/api'
import { DirectionProvider } from './context/direction-provider'
import { FontProvider } from './context/font-provider'
import { ThemeProvider } from './context/theme-provider'
// Generated Routes
import { routeTree } from './routeTree.gen'
// Styles
import './styles/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // eslint-disable-next-line no-console
        if (import.meta.env.DEV) console.log({ failureCount, error })

        // 4xx 是确定性错误，重试没有意义
        if (
          error instanceof ApiHttpError &&
          [400, 401, 403, 404, 409, 429].includes(error.status)
        ) {
          return false
        }
        // 网络错误 / 5xx 最多重试 2 次
        return failureCount < 2
      },
      refetchOnWindowFocus: import.meta.env.PROD,
      staleTime: 10 * 1000, // 10s
    },
  },
  queryCache: new QueryCache({
    onError: (error) => {
      if (error instanceof ApiHttpError) {
        if (error.status === 401) {
          toast.error('登录已过期，请重新登录')
          useAuthStore.getState().auth.reset()
          const redirect = router.history.location.href
          if (!redirect.startsWith('/sign-in')) {
            router.navigate({ to: '/sign-in', search: { redirect } })
          }
        } else if (error.status === 403) {
          toast.error('没有权限执行此操作')
        } else if (error.status >= 500) {
          toast.error('服务暂时不可用，请稍后重试')
        }
        return
      }
      if (error instanceof ApiNetworkError) {
        toast.error(error.message)
      }
    },
  }),
})

// Create a new router instance
const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
})

// Register the router instance for type safety
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

// Render the app
const rootElement = document.getElementById('root')!
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement)
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <FontProvider>
            <DirectionProvider>
              <RouterProvider router={router} />
            </DirectionProvider>
          </FontProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </StrictMode>
  )
}
