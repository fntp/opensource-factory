import { useState } from 'react'
import { useNavigate, useLocation } from '@tanstack/react-router'
import { useAuthStore } from '@/stores/auth-store'
import { logout } from '@/lib/api'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ConfirmDialog } from '@/components/confirm-dialog'

interface SignOutDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SignOutDialog({ open, onOpenChange }: SignOutDialogProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { auth } = useAuthStore()
  const [allDevices, setAllDevices] = useState(false)

  const handleOpenChange = (next: boolean) => {
    if (!next) setAllDevices(false)
    onOpenChange(next)
  }

  const handleSignOut = () => {
    void logout({ all: allDevices }) // 通知边缘服务清除会话（失败不影响本地退出）
    auth.reset()
    // 记录当前位置，登录后可跳回
    const currentPath = location.href
    navigate({
      to: '/sign-in',
      search: { redirect: currentPath },
      replace: true,
    })
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={handleOpenChange}
      title='退出登录'
      desc='确定要退出当前账号吗？退出后需要重新使用 GitHub 登录。'
      cancelBtnText='取消'
      confirmText='退出登录'
      destructive
      handleConfirm={handleSignOut}
      className='sm:max-w-sm'
    >
      <div className='flex items-start gap-2 rounded-md border p-3'>
        <Checkbox
          id='signout-all-devices'
          checked={allDevices}
          onCheckedChange={(checked) => setAllDevices(checked === true)}
        />
        <div className='grid gap-1'>
          <Label htmlFor='signout-all-devices'>同时退出所有设备</Label>
          <p className='text-xs text-muted-foreground'>
            其他设备上的登录会话也会立即失效。
          </p>
        </div>
      </div>
    </ConfirmDialog>
  )
}
