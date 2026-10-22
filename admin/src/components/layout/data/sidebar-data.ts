import {
  Bell,
  Flame,
  FolderGit2,
  FolderTree,
  LayoutDashboard,
  Monitor,
  Palette,
  Settings,
  Sparkles,
  User,
} from 'lucide-react'
import type { SidebarData } from '../types'

/**
 * 侧边栏与命令菜单的导航数据。
 *
 * 说明：该文件曾被 .gitignore 的 data 目录规则误伤而未入库，导致 admin 无法构建；
 * 已在 .gitignore 增加例外，后续新增导航项直接改这里。
 */
export const sidebarData: SidebarData = {
  user: { name: '', email: '', avatar: '' },
  teams: [],
  navGroups: [
    {
      title: '总览',
      items: [{ title: '仪表盘', url: '/', icon: LayoutDashboard }],
    },
    {
      title: '开源资产',
      items: [
        { title: '我的仓库', url: '/repos', icon: FolderGit2 },
        { title: '分类', url: '/categories', icon: FolderTree },
        { title: '热榜', url: '/trending', icon: Flame },
        { title: '推荐', url: '/recommend', icon: Sparkles },
      ],
    },
    {
      title: '系统',
      items: [
        {
          title: '设置',
          icon: Settings,
          items: [
            { title: '个人资料', url: '/settings', icon: User },
            { title: '账号设置', url: '/settings/account', icon: User },
            { title: '通知设置', url: '/settings/notifications', icon: Bell },
            { title: '外观', url: '/settings/appearance', icon: Palette },
            { title: '显示', url: '/settings/display', icon: Monitor },
          ],
        },
      ],
    },
  ],
}
