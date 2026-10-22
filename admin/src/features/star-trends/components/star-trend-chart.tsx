import { useId } from 'react'
import type { StarTrendPoint } from '../api'
import {
  buildAreaPath,
  buildLinePath,
  buildPolylinePoints,
  dateLabel,
  formatCompactNumber,
} from '../utils'

interface StarTrendChartProps {
  series: readonly StarTrendPoint[]
}

const WIDTH = 800
const HEIGHT = 260
const PADDING = 24

/** 每日 Star 净增面积折线图（纯 SVG，无图表库依赖） */
export function StarTrendChart({ series }: StarTrendChartProps) {
  const gradientId = useId()
  const values = series.map((point) => point.starGain)
  const points = buildPolylinePoints(values, WIDTH, HEIGHT, PADDING)
  const linePath = buildLinePath(points)
  const areaPath = buildAreaPath(points, HEIGHT, PADDING)
  const max = values.length > 0 ? Math.max(...values) : 0
  const min = values.length > 0 ? Math.min(...values) : 0
  const span = max - min || 1
  const first = series[0]
  const middle = series[Math.floor(series.length / 2)]
  const last = series[series.length - 1]
  const totalGain = values.reduce((sum, value) => sum + value, 0)

  if (series.length === 0) {
    return (
      <div className='flex h-56 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground'>
        暂无快照数据，等待热榜每日快照积累。
      </div>
    )
  }

  return (
    <figure className='w-full'>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role='img'
        aria-label={`每日 Star 净增趋势，共 ${series.length} 天，合计 ${totalGain} Star`}
        className='h-64 w-full text-[#2a78d6] dark:text-[#3987e5]'
      >
        <defs>
          <linearGradient id={gradientId} x1='0' y1='0' x2='0' y2='1'>
            <stop offset='0%' stopColor='currentColor' stopOpacity='0.28' />
            <stop offset='100%' stopColor='currentColor' stopOpacity='0' />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = PADDING + ratio * (HEIGHT - PADDING * 2)
          const value = max - ratio * span
          return (
            <g key={ratio}>
              <line
                x1={PADDING}
                x2={WIDTH - PADDING}
                y1={y}
                y2={y}
                className='stroke-muted-foreground/20'
                strokeDasharray={ratio === 1 ? '0' : '4 6'}
              />
              <text
                x={PADDING - 6}
                y={y + 3}
                textAnchor='end'
                className='fill-muted-foreground text-[10px]'
              >
                {formatCompactNumber(Math.round(value))}
              </text>
            </g>
          )
        })}

        <g className='text-[#2a78d6] dark:text-[#3987e5]'>
          {areaPath && <path d={areaPath} fill={`url(#${gradientId})`} stroke='none' />}
          {linePath && (
            <path
              d={linePath}
              fill='none'
              stroke='currentColor'
              strokeWidth={2.4}
              strokeLinecap='round'
              strokeLinejoin='round'
            />
          )}
          {points.map((point, index) => {
            const day = series[index]
            if (!day) return null
            return (
              <circle
                key={day.date}
                cx={point.x}
                cy={point.y}
                r={2.4}
                fill='currentColor'
                opacity={0.9}
              >
                <title>{`${day.date}：${day.starGain >= 0 ? '+' : ''}${day.starGain} Star · ${day.trackedRepos} 个仓库`}</title>
              </circle>
            )
          })}
        </g>

        {first && middle && last && (
          <g className='fill-muted-foreground text-[10px]'>
            <text x={PADDING} y={HEIGHT - 6} textAnchor='start'>
              {dateLabel(first.date)}
            </text>
            <text x={WIDTH / 2} y={HEIGHT - 6} textAnchor='middle'>
              {dateLabel(middle.date)}
            </text>
            <text x={WIDTH - PADDING} y={HEIGHT - 6} textAnchor='end'>
              {dateLabel(last.date)}
            </text>
          </g>
        )}
      </svg>
      <figcaption className='mt-1 flex items-center justify-between text-xs text-muted-foreground'>
        <span>每日 Star 净增（快照 star_delta 合计）</span>
        <span>合计 {formatCompactNumber(totalGain)} Star</span>
      </figcaption>
    </figure>
  )
}
