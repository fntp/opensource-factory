import {
  Activity,
  Archive,
  Bell,
  BellRing,
  Boxes,
  Cpu,
  FileText,
  Flame,
  FolderGit2,
  FolderTree,
  GitMerge,
  LayoutDashboard,
  Monitor,
  Network,
  Palette,
  Scale,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Tags,
  TrendingUp,
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
      items: [
        { title: '仪表盘', url: '/', icon: LayoutDashboard },
        { title: '通知中心', url: '/notifications', icon: Bell },
      ],
    },
    {
      title: '开源资产',
      items: [
        { title: '我的仓库', url: '/repos', icon: FolderGit2 },
        { title: '分类', url: '/categories', icon: FolderTree },
        { title: '分类建议', url: '/category-suggestions', icon: Tags },
        { title: '热榜', url: '/trending', icon: Flame },
        { title: 'License 合规', url: '/licenses', icon: Scale },
        { title: '推荐', url: '/recommend', icon: Sparkles },
        { title: '精排工作台', url: '/rerank', icon: SlidersHorizontal },
        { title: '语义搜索', url: '/search', icon: Search },
        { title: '重复检测', url: '/duplicates', icon: GitMerge },
        { title: '技术栈图谱', url: '/tech-stack', icon: Network },
        { title: 'Star 趋势', url: '/star-trends', icon: TrendingUp },
        { title: '依赖分析', url: '/dependencies', icon: Boxes },
        { title: '知识库导出', url: '/export', icon: Archive },
        { title: '打标建议', url: '/tag-suggestions', icon: Tags },
        { title: '精选报告', url: '/reports', icon: FileText },
        { title: '更新提醒', url: '/updates', icon: BellRing },
      ],
    },
    {
      title: '系统',
      items: [
        { title: '系统监控', url: '/monitoring', icon: Activity },
        { title: '模型路由', url: '/model-routing', icon: Cpu },
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
