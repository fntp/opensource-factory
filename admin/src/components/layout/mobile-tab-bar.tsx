import { Link } from '@tanstack/react-router'
import { Flame, FolderGit2, LayoutDashboard, Sparkles } from 'lucide-react'

const tabs = [
  { to: '/', label: '仪表盘', icon: LayoutDashboard, exact: true },
  { to: '/repos', label: '仓库', icon: FolderGit2, exact: false },
  { to: '/trending', label: '热榜', icon: Flame, exact: false },
  { to: '/recommend', label: '推荐', icon: Sparkles, exact: false },
] as const

/**
 * 移动端底部主导航。
 *
 * 桌面端继续使用侧边栏；窄屏把最高频的四个入口固定在底部，并预留
 * iPhone 安全区，避免被 Home Indicator 遮挡。
 */
export function MobileTabBar() {
  return (
    <nav
      aria-label='移动端主导航'
      className='fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden'
    >
      <div className='grid h-14 grid-cols-4'>
        {tabs.map((tab) => (
          <Link
            key={tab.to}
            to={tab.to}
            activeOptions={{ exact: tab.exact }}
            activeProps={{ className: 'text-primary' }}
            className='flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground'
          >
            <tab.icon className='size-5' aria-hidden='true' />
            <span>{tab.label}</span>
          </Link>
        ))}
      </div>
    </nav>
  )
}
