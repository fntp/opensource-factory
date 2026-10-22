import { fetchWithFallback } from '@/lib/api'

export type StarTrendScope = 'trending' | 'my'

export interface StarTrendPoint {
  date: string
  trackedRepos: number
  totalStars: number
  starGain: number
  newRepos: number
}

export interface StarMover {
  repoId: string
  name: string
  owner: string
  url: string
  language: string | null
  stars: number
  gain: number
  growthRate: number
  appearances: number
  trend: 'new' | 'up' | 'down' | 'steady'
  sparkline: number[]
  firstDate: string
  lastDate: string
}

export interface StarLanguageInsight {
  language: string
  repoCount: number
  starGain: number
  share: number
  topRepo: string | null
}

export interface StarInsight {
  kind: 'growth' | 'language' | 'new' | 'concentration' | 'cooling'
  title: string
  description: string
  repoId?: string
}

export interface StarTrendsResponse {
  scope: StarTrendScope
  period: {
    days: number
    startDate: string | null
    endDate: string | null
    snapshotDays: number
  }
  summary: {
    trackedRepos: number
    totalStars: number
    starGain: number
    averageDailyGain: number
    fastestGrowing: {
      repoId: string
      name: string
      gain: number
      growthRate: number
    } | null
    newEntries: number
    risingRepos: number
    fallingRepos: number
    portfolioRepos?: number
    coverage?: number
  }
  series: StarTrendPoint[]
  topMovers: StarMover[]
  newEntries: StarMover[]
  languages: StarLanguageInsight[]
  insights: StarInsight[]
  generatedAt: string
}

const MOCK_END = Date.UTC(2026, 9, 22)
const MOCK_DAYS = 30

function mockDate(offsetFromEnd: number): string {
  return new Date(MOCK_END - offsetFromEnd * 86400000)
    .toISOString()
    .slice(0, 10)
}

function buildMockSeries(days: number): StarTrendPoint[] {
  const safeDays = Math.min(MOCK_DAYS, Math.max(1, days))
  return Array.from({ length: safeDays }, (_, index) => {
    const offset = safeDays - 1 - index
    const wave = Math.round(120 + Math.sin(index / 2.4) * 55 + index * 4)
    return {
      date: mockDate(offset),
      trackedRepos: 108 + (index % 9),
      totalStars: 1284000 + index * 7350,
      starGain: Math.max(20, wave),
      newRepos: index % 6 === 0 ? 4 : index % 4 === 0 ? 2 : 0,
    }
  })
}

const MOCK_MOVERS: StarMover[] = [
  {
    repoId: 'langchain-ai/langchain',
    name: 'langchain',
    owner: 'langchain-ai',
    url: 'https://github.com/langchain-ai/langchain',
    language: 'Python',
    stars: 98200,
    gain: 4820,
    growthRate: 5.2,
    appearances: 12,
    trend: 'up',
    sparkline: [93400, 93800, 94100, 94600, 95000, 95500, 96000, 96500, 97000, 97500, 97900, 98200],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'ollama/ollama',
    name: 'ollama',
    owner: 'ollama',
    url: 'https://github.com/ollama/ollama',
    language: 'Go',
    stars: 112400,
    gain: 3960,
    growthRate: 3.7,
    appearances: 18,
    trend: 'up',
    sparkline: [108440, 108900, 109300, 109800, 110200, 110700, 111100, 111500, 111900, 112100, 112300, 112400],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'microsoft/autogen',
    name: 'autogen',
    owner: 'microsoft',
    url: 'https://github.com/microsoft/autogen',
    language: 'Python',
    stars: 41200,
    gain: 2870,
    growthRate: 7.5,
    appearances: 9,
    trend: 'up',
    sparkline: [38330, 38600, 39000, 39400, 39800, 40100, 40400, 40700, 40900, 41050, 41150, 41200],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'shadcn-ui/ui',
    name: 'ui',
    owner: 'shadcn-ui',
    url: 'https://github.com/shadcn-ui/ui',
    language: 'TypeScript',
    stars: 82600,
    gain: 2410,
    growthRate: 3.0,
    appearances: 14,
    trend: 'up',
    sparkline: [80190, 80400, 80700, 81000, 81300, 81600, 81900, 82100, 82300, 82450, 82550, 82600],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'open-webui/open-webui',
    name: 'open-webui',
    owner: 'open-webui',
    url: 'https://github.com/open-webui/open-webui',
    language: 'TypeScript',
    stars: 68400,
    gain: 2180,
    growthRate: 3.3,
    appearances: 11,
    trend: 'up',
    sparkline: [66220, 66500, 66800, 67100, 67400, 67700, 67900, 68100, 68250, 68340, 68390, 68400],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'n8n-io/n8n',
    name: 'n8n',
    owner: 'n8n-io',
    url: 'https://github.com/n8n-io/n8n',
    language: 'TypeScript',
    stars: 143800,
    gain: 1920,
    growthRate: 1.4,
    appearances: 21,
    trend: 'up',
    sparkline: [141880, 142100, 142400, 142700, 142950, 143200, 143400, 143550, 143650, 143720, 143770, 143800],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'modelcontextprotocol/servers',
    name: 'servers',
    owner: 'modelcontextprotocol',
    url: 'https://github.com/modelcontextprotocol/servers',
    language: 'TypeScript',
    stars: 57800,
    gain: 1760,
    growthRate: 3.1,
    appearances: 7,
    trend: 'up',
    sparkline: [56040, 56300, 56600, 56900, 57100, 57300, 57480, 57600, 57700, 57750, 57780, 57800],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'astral-sh/uv',
    name: 'uv',
    owner: 'astral-sh',
    url: 'https://github.com/astral-sh/uv',
    language: 'Rust',
    stars: 49100,
    gain: 1540,
    growthRate: 3.2,
    appearances: 10,
    trend: 'up',
    sparkline: [47560, 47800, 48050, 48300, 48500, 48700, 48850, 48960, 49020, 49060, 49090, 49100],
    firstDate: '2026-10-11',
    lastDate: '2026-10-22',
  },
]

const MOCK_NEW_ENTRIES: StarMover[] = [
  {
    repoId: 'deepseek-ai/DeepSeek-V3',
    name: 'DeepSeek-V3',
    owner: 'deepseek-ai',
    url: 'https://github.com/deepseek-ai/DeepSeek-V3',
    language: 'Python',
    stars: 86400,
    gain: 3260,
    growthRate: 3.9,
    appearances: 3,
    trend: 'new',
    sparkline: [83140, 84200, 85300, 86400],
    firstDate: '2026-10-19',
    lastDate: '2026-10-22',
  },
  {
    repoId: 'anthropics/claude-code',
    name: 'claude-code',
    owner: 'anthropics',
    url: 'https://github.com/anthropics/claude-code',
    language: 'TypeScript',
    stars: 38200,
    gain: 2140,
    growthRate: 5.9,
    appearances: 2,
    trend: 'new',
    sparkline: [36060, 37100, 38200],
    firstDate: '2026-10-20',
    lastDate: '2026-10-22',
  },
]

const MOCK_LANGUAGES: StarLanguageInsight[] = [
  { language: 'TypeScript', repoCount: 38, starGain: 9860, share: 34.2, topRepo: 'shadcn-ui/ui' },
  { language: 'Python', repoCount: 31, starGain: 8420, share: 29.2, topRepo: 'langchain-ai/langchain' },
  { language: 'Go', repoCount: 18, starGain: 4310, share: 15.0, topRepo: 'ollama/ollama' },
  { language: 'Rust', repoCount: 12, starGain: 3180, share: 11.0, topRepo: 'astral-sh/uv' },
  { language: 'JavaScript', repoCount: 14, starGain: 2040, share: 7.1, topRepo: 'vercel/next.js' },
  { language: 'Java', repoCount: 6, starGain: 1010, share: 3.5, topRepo: 'spring-projects/spring-boot' },
]

function buildMockInsights(): StarInsight[] {
  return [
    {
      kind: 'growth',
      title: '增长冠军',
      description: '近 30 天 langchain-ai/langchain Star 增长 4,820（+5.2%），连续上榜 12 天。',
      repoId: 'langchain-ai/langchain',
    },
    {
      kind: 'language',
      title: '语言升温',
      description: 'TypeScript 贡献了 34.2% 的 Star 增量（9,860），共有 38 个项目上榜。',
    },
    {
      kind: 'new',
      title: '新面孔',
      description: '本期有 2 个新上榜项目，deepseek-ai/DeepSeek-V3 以 3,260 Star 增量领跑。',
      repoId: 'deepseek-ai/DeepSeek-V3',
    },
    {
      kind: 'concentration',
      title: '头部集中',
      description: 'Star 增量集中在头部 3 个项目，合计贡献 51.6%（14,650 / 28,400）。',
    },
  ]
}

export function mockStarTrends(days = 30, scope: StarTrendScope = 'trending'): StarTrendsResponse {
  const series = buildMockSeries(days)
  const isMy = scope === 'my'
  return {
    scope,
    period: {
      days,
      startDate: series[0]?.date ?? null,
      endDate: series[series.length - 1]?.date ?? null,
      snapshotDays: series.length,
    },
    summary: isMy
      ? {
          trackedRepos: 14,
          totalStars: 624900,
          starGain: 12840,
          averageDailyGain: 642,
          fastestGrowing: {
            repoId: 'langchain-ai/langchain',
            name: 'langchain',
            gain: 4820,
            growthRate: 5.2,
          },
          newEntries: 2,
          risingRepos: 12,
          fallingRepos: 1,
          portfolioRepos: 24,
          coverage: 58.3,
        }
      : {
          trackedRepos: 116,
          totalStars: 1497550,
          starGain: 28840,
          averageDailyGain: 995,
          fastestGrowing: {
            repoId: 'langchain-ai/langchain',
            name: 'langchain',
            gain: 4820,
            growthRate: 5.2,
          },
          newEntries: 2,
          risingRepos: 92,
          fallingRepos: 7,
        },
    series,
    topMovers: MOCK_MOVERS,
    newEntries: MOCK_NEW_ENTRIES,
    languages: MOCK_LANGUAGES,
    insights: buildMockInsights(),
    generatedAt: '2026-10-22T10:00:00.000Z',
  }
}

export const MOCK_STAR_TRENDS = mockStarTrends()

export function fetchStarTrends(
  days: number,
  scope: StarTrendScope
): Promise<StarTrendsResponse> {
  const params = new URLSearchParams({
    days: String(days),
    scope,
  })
  return fetchWithFallback<StarTrendsResponse>(
    `/api/star-trends?${params.toString()}`,
    mockStarTrends(days, scope)
  )
}
