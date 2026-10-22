import { useMemo, useRef, useState, type MouseEvent } from 'react'
import type { TechStackGraphLink, TechStackGraphNode } from '../api'
import {
  buildRadialLayout,
  RADIAL_INNER_RATIO,
  RADIAL_OUTER_RATIO,
  type PositionedNode,
} from '../utils'

const WIDTH = 760
const HEIGHT = 560

interface TechStackGraphProps {
  nodes: TechStackGraphNode[]
  links: TechStackGraphLink[]
}

interface HoverState {
  node: PositionedNode
  x: number
  y: number
}

/**
 * 语言 × 框架径向关系图。
 *
 * 内圈为语言（蓝色），外圈为框架（橙色）；连线粗细表示同语言仓库中出现该框架的次数。
 * 节点支持鼠标悬停与键盘聚焦，颜色之外另有文字标签与图例，避免只靠颜色区分。
 */
export function TechStackGraph({ nodes, links }: TechStackGraphProps) {
  const layout = useMemo(
    () => buildRadialLayout({ nodes, links }, WIDTH, HEIGHT),
    [nodes, links]
  )
  const [hover, setHover] = useState<HoverState | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const activeId = hover?.node.id ?? null

  const neighbors = useMemo(() => {
    if (!activeId) return new Set<string>()
    const ids = new Set<string>([activeId])
    for (const link of layout.links) {
      if (link.source === activeId) ids.add(link.target)
      if (link.target === activeId) ids.add(link.source)
    }
    return ids
  }, [activeId, layout.links])

  function pointerPosition(event: MouseEvent): { x: number; y: number } {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  function focusPosition(node: PositionedNode): { x: number; y: number } {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return {
      x: (node.x / WIDTH) * rect.width,
      y: (node.y / HEIGHT) * (rect.width * (HEIGHT / WIDTH)),
    }
  }

  if (layout.nodes.length === 0) {
    return (
      <p className='py-12 text-center text-sm text-muted-foreground'>
        暂无可展示的语言 / 框架数据。
      </p>
    )
  }

  const innerRadius = Math.min(WIDTH, HEIGHT) * RADIAL_INNER_RATIO
  const outerRadius = Math.min(WIDTH, HEIGHT) * RADIAL_OUTER_RATIO

  return (
    <div>
      <div className='mb-2 flex flex-wrap items-center gap-4 text-xs text-muted-foreground'>
        <span className='flex items-center gap-1.5'>
          <span className='size-2.5 rounded-full bg-[#2a78d6] dark:bg-[#3987e5]' />
          语言
        </span>
        <span className='flex items-center gap-1.5'>
          <span className='size-2.5 rounded-full bg-[#eb6834] dark:bg-[#d95926]' />
          框架
        </span>
        <span className='ms-auto hidden sm:inline'>
          悬停或聚焦节点查看仓库数；连线越粗表示组合越常见
        </span>
      </div>

      <div ref={containerRef} className='relative'>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role='img'
          aria-label='语言与框架关系图：内圈为语言，外圈为框架，连线表示组合出现次数'
          className='w-full'
          onMouseLeave={() => setHover(null)}
        >
          <circle
            cx={layout.center.x}
            cy={layout.center.y}
            r={innerRadius}
            fill='none'
            stroke='var(--border)'
            strokeDasharray='4 6'
            opacity={0.55}
          />
          <circle
            cx={layout.center.x}
            cy={layout.center.y}
            r={outerRadius}
            fill='none'
            stroke='var(--border)'
            strokeDasharray='4 6'
            opacity={0.35}
          />

          <text
            x={layout.center.x}
            y={layout.center.y - 6}
            textAnchor='middle'
            fill='var(--muted-foreground)'
            fontSize={11}
          >
            技术栈
          </text>
          <text
            x={layout.center.x}
            y={layout.center.y + 10}
            textAnchor='middle'
            fill='var(--muted-foreground)'
            fontSize={11}
          >
            图谱
          </text>

          <g>
            {layout.links.map((link) => {
              const connected =
                !activeId || link.source === activeId || link.target === activeId
              return (
                <line
                  key={`${link.source}-${link.target}`}
                  x1={link.x1}
                  y1={link.y1}
                  x2={link.x2}
                  y2={link.y2}
                  className='stroke-[#2a78d6] dark:stroke-[#3987e5]'
                  strokeWidth={Math.min(3, 1 + link.weight * 0.35)}
                  opacity={activeId ? (connected ? 0.55 : 0.06) : 0.18}
                />
              )
            })}
          </g>

          <g>
            {layout.nodes.map((node) => {
              const dimmed = activeId !== null && !neighbors.has(node.id)
              const isLanguage = node.kind === 'language'
              const labelX = isLanguage
                ? node.x
                : node.x + Math.cos(node.angle) * (node.r + 8)
              const labelY = isLanguage
                ? node.y + node.r + 13
                : node.y + Math.sin(node.angle) * (node.r + 8)
              const anchor = isLanguage
                ? 'middle'
                : Math.cos(node.angle) > 0.25
                  ? 'start'
                  : Math.cos(node.angle) < -0.25
                    ? 'end'
                    : 'middle'
              return (
                <g
                  key={node.id}
                  tabIndex={0}
                  role='button'
                  aria-label={`${node.label}，${isLanguage ? '语言' : '框架'}，${node.weight} 个仓库`}
                  opacity={dimmed ? 0.35 : 1}
                  className='cursor-pointer outline-none transition-opacity'
                  onMouseMove={(event) =>
                    setHover({ node, ...pointerPosition(event) })
                  }
                  onFocus={() => setHover({ node, ...focusPosition(node) })}
                  onBlur={() => setHover(null)}
                >
                  <title>{`${node.label} · ${node.weight} 个仓库`}</title>
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={node.r}
                    stroke='var(--background)'
                    strokeWidth={2}
                    className={
                      isLanguage
                        ? 'fill-[#2a78d6] dark:fill-[#3987e5]'
                        : 'fill-[#eb6834] dark:fill-[#d95926]'
                    }
                  />
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor={anchor}
                    dominantBaseline='middle'
                    fontSize={isLanguage ? 11 : 10.5}
                    fill='var(--foreground)'
                    stroke='var(--background)'
                    strokeWidth={3}
                    paintOrder='stroke'
                    className='pointer-events-none select-none'
                  >
                    {node.label}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {hover && (
          <div
            className='pointer-events-none absolute z-10 w-max max-w-56 rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md'
            style={{
              left: `clamp(90px, ${hover.x}px, calc(100% - 90px))`,
              top: `clamp(72px, ${hover.y}px, calc(100% - 8px))`,
              transform: 'translate(-50%, calc(-100% - 12px))',
            }}
          >
            <div className='font-medium'>{hover.node.label}</div>
            <div className='text-muted-foreground'>
              {hover.node.kind === 'language'
                ? '语言'
                : `框架 · ${hover.node.category ?? '未分类'}`}
            </div>
            <div className='mt-1 tabular-nums'>{hover.node.weight} 个仓库</div>
          </div>
        )}
      </div>
    </div>
  )
}
