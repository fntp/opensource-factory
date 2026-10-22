import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { IconGithub } from '@/assets/brand-icons'
import { Button } from '@/components/ui/button'
import { githubLoginUrl } from '@/lib/api'
import { cn } from '@/lib/utils'

interface GithubAuthFormProps extends React.HTMLAttributes<HTMLDivElement> {
  redirectTo?: string
}

export function GithubAuthForm({
  className,
  redirectTo,
  ...props
}: GithubAuthFormProps) {
  const [isRedirecting, setIsRedirecting] = useState(false)

  const handleGithubLogin = () => {
    setIsRedirecting(true)
    // 跳转到边缘服务的 GitHub OAuth 登录端点
    window.location.assign(githubLoginUrl(redirectTo))
  }

  return (
    <div className={cn('grid gap-3', className)} {...props}>
      <Button onClick={handleGithubLogin} disabled={isRedirecting}>
        {isRedirecting ? (
          <Loader2 className='animate-spin' />
        ) : (
          <IconGithub className='size-4' />
        )}
        使用 GitHub 登录
      </Button>

      <p className='text-center text-xs text-muted-foreground'>
        仅支持 GitHub 授权登录，授权后即可管理你的开源资产。
      </p>
    </div>
  )
}
