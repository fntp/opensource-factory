import { useState } from 'react'
import { Loader2, PlayCircle } from 'lucide-react'
import { toast } from 'sonner'
import { IconGithub } from '@/assets/brand-icons'
import { Button } from '@/components/ui/button'
import { API_BASE, DEMO_MODE, githubLoginUrl, type AuthUser } from '@/lib/api'
import { cn } from '@/lib/utils'
import { saveDemoSession, useAuthStore } from '@/stores/auth-store'

/** 演示模式使用的内置账号 */
const DEMO_USER: AuthUser = {
  id: 'demo-user',
  login: 'fntp',
  name: 'Fntp（演示）',
  email: 'fntp@example.com',
  avatarUrl: null,
}

interface GithubAuthFormProps extends React.HTMLAttributes<HTMLDivElement> {
  redirectTo?: string
}

export function GithubAuthForm({
  className,
  redirectTo,
  ...props
}: GithubAuthFormProps) {
  const [isRedirecting, setIsRedirecting] = useState(false)
  const { auth } = useAuthStore()

  const goTo = (target?: string) => {
    window.location.assign(target || '/')
  }

  const handleGithubLogin = () => {
    if (!API_BASE) {
      toast.error('未配置边缘服务地址（VITE_API_BASE_URL），无法发起 GitHub 登录')
      return
    }
    setIsRedirecting(true)
    // 跳转到边缘服务的 GitHub OAuth 登录端点
    window.location.href = githubLoginUrl(redirectTo)
  }

  const handleDemoLogin = () => {
    saveDemoSession(DEMO_USER)
    auth.setUser(DEMO_USER)
    toast.success('已进入演示模式')
    goTo(redirectTo)
  }

  return (
    <div className={cn('grid gap-3', className)} {...props}>
      <Button
        onClick={handleGithubLogin}
        disabled={isRedirecting || !API_BASE}
        title={API_BASE ? undefined : '未配置 VITE_API_BASE_URL'}
      >
        {isRedirecting ? (
          <Loader2 className='animate-spin' />
        ) : (
          <IconGithub className='size-4' />
        )}
        使用 GitHub 登录
      </Button>

      {DEMO_MODE && (
        <Button variant='outline' onClick={handleDemoLogin}>
          <PlayCircle className='size-4' />
          进入演示模式
        </Button>
      )}

      <p className='text-center text-xs text-muted-foreground'>
        仅支持 GitHub 授权登录，授权后即可管理你的开源资产。
      </p>
    </div>
  )
}
