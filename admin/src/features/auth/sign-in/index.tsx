import { useSearch } from '@tanstack/react-router'
import { AlertCircle } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { AuthLayout } from '../auth-layout'
import { GithubAuthForm } from './components/github-auth-form'

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  oauth_denied: '你取消了 GitHub 授权，请重新登录。',
  invalid_oauth_state: '登录状态已失效，请重新发起登录。',
  github_token_exchange_failed: 'GitHub 授权失败，请稍后重试。',
  github_user_fetch_failed: '获取 GitHub 用户信息失败，请稍后重试。',
  github_oauth_not_configured: 'GitHub OAuth 尚未配置，请联系维护者。',
}

export function SignIn() {
  const { redirect, error } = useSearch({ from: '/(auth)/sign-in' })
  const errorMessage = error
    ? (OAUTH_ERROR_MESSAGES[error] ?? '登录失败，请重新尝试。')
    : null

  return (
    <AuthLayout>
      <Card className='max-w-sm gap-4'>
        <CardHeader>
          <CardTitle className='text-lg tracking-tight'>登录</CardTitle>
          <CardDescription>
            使用 GitHub 账号登录「开源项目工厂」，<br className='max-sm:hidden' />
            管理你的开源资产、每日热榜与智能推荐。
          </CardDescription>
        </CardHeader>
        <CardContent className='space-y-4'>
          {errorMessage ? (
            <div
              className='flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive'
              role='alert'
            >
              <AlertCircle className='mt-0.5 size-4 shrink-0' />
              <span>{errorMessage}</span>
            </div>
          ) : null}
          <GithubAuthForm redirectTo={redirect} />
        </CardContent>
      </Card>
    </AuthLayout>
  )
}
