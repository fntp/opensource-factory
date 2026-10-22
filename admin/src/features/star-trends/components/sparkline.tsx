import { cn } from '@/lib/utils'
import { buildLinePath, buildPolylinePoints } from '../utils'

interface SparklineProps {
  values: readonly number[]
  className?: string
  label?: string
}

/** 迷你趋势线：用于 Top Movers 表格，不显示坐标轴 */
export function Sparkline({ values, className, label }: SparklineProps) {
  const points = buildPolylinePoints(values, 96, 28, 2)
  const path = buildLinePath(points)
  const last = points[points.length - 1]

  return (
    <svg
      viewBox='0 0 96 28'
      role='img'
      aria-label={label ?? `近 ${values.length} 次快照的 Star 趋势`}
      className={cn('h-7 w-24 text-[#2a78d6] dark:text-[#3987e5]', className)}
    >
      {path && (
        <path
          d={path}
          fill='none'
          stroke='currentColor'
          strokeWidth={1.6}
          strokeLinecap='round'
          strokeLinejoin='round'
        />
      )}
      {last && <circle cx={last.x} cy={last.y} r={2.2} fill='currentColor' />}
    </svg>
  )
}
