import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { LicenseInfo } from './api'
import { licenseBadgeLabel, licenseToneClass } from './utils'

interface LicenseBadgeProps {
  license?: LicenseInfo | null
  className?: string
  /** 未识别时是否显示「未识别」徽章；false 时返回 null */
  showUnknown?: boolean
}

/** 仓库 License 徽章：按风险着色，hover 显示合规摘要 */
export function LicenseBadge({
  license,
  className,
  showUnknown = true,
}: LicenseBadgeProps) {
  if (!license && !showUnknown) return null
  return (
    <Badge
      variant='outline'
      className={cn(licenseToneClass(license), className)}
      title={license?.summary ?? '尚未识别 License，建议运行补全任务'}
    >
      {licenseBadgeLabel(license)}
    </Badge>
  )
}
