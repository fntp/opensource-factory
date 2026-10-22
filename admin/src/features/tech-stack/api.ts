import { fetchWithFallback } from '@/lib/api'

export interface TechStackSummary {
  totalRepos: number
  withLanguage: number
  withFramework: number
  languageCount: number
  frameworkCount: number
  topLanguage: string | null
  topFramework: string | null
  coverage: number
  totalStars: number
}

export interface TechStackLanguage {
  name: string
  repoCount: number
  starCount: number
  share: number
  frameworks: string[]
}

export interface TechStackFramework {
  name: string
  category: string
  repoCount: number
  starCount: number
  share: number
  languages: string[]
}

export interface TechStackGraphNode {
  id: string
  label: string
  kind: 'language' | 'framework'
  category?: string
  weight: number
}

export interface TechStackGraphLink {
  source: string
  target: string
  weight: number
}

export interface TechStackResponse {
  summary: TechStackSummary
  languages: TechStackLanguage[]
  frameworks: TechStackFramework[]
  graph: {
    nodes: TechStackGraphNode[]
    links: TechStackGraphLink[]
  }
  generatedAt: string
}

const MOCK_LANGUAGES: TechStackLanguage[] = [
  {
    name: 'TypeScript',
    repoCount: 8,
    starCount: 182400,
    share: 33.3,
    frameworks: ['React', 'Next.js', 'Tailwind CSS', 'Vite', 'Prisma'],
  },
  {
    name: 'Python',
    repoCount: 6,
    starCount: 151200,
    share: 25,
    frameworks: ['FastAPI', 'PostgreSQL', 'PyTorch', 'Django', 'LangChain'],
  },
  {
    name: 'Go',
    repoCount: 3,
    starCount: 112000,
    share: 12.5,
    frameworks: ['Docker', 'Kubernetes', 'Redis'],
  },
  {
    name: 'Rust',
    repoCount: 3,
    starCount: 98600,
    share: 12.5,
    frameworks: ['Tauri', 'Docker'],
  },
  {
    name: 'JavaScript',
    repoCount: 2,
    starCount: 54300,
    share: 8.3,
    frameworks: ['React', 'Vue', 'Next.js'],
  },
  {
    name: 'Java',
    repoCount: 1,
    starCount: 22100,
    share: 4.2,
    frameworks: ['PostgreSQL', 'Redis'],
  },
  {
    name: 'Shell',
    repoCount: 1,
    starCount: 4300,
    share: 4.2,
    frameworks: ['Docker'],
  },
]

const MOCK_FRAMEWORKS: TechStackFramework[] = [
  { name: 'React', category: '前端', repoCount: 6, starCount: 132000, share: 25, languages: ['TypeScript', 'JavaScript'] },
  { name: 'FastAPI', category: '后端', repoCount: 5, starCount: 128000, share: 20.8, languages: ['Python'] },
  { name: 'PostgreSQL', category: '数据库', repoCount: 5, starCount: 118000, share: 20.8, languages: ['Python', 'Java', 'Go'] },
  { name: 'Docker', category: 'DevOps', repoCount: 5, starCount: 96400, share: 20.8, languages: ['Go', 'Python', 'Rust', 'Shell'] },
  { name: 'Next.js', category: '前端', repoCount: 4, starCount: 98200, share: 16.7, languages: ['TypeScript', 'JavaScript'] },
  { name: 'Tailwind CSS', category: '前端', repoCount: 3, starCount: 76400, share: 12.5, languages: ['TypeScript'] },
  { name: 'PyTorch', category: 'AI/数据', repoCount: 3, starCount: 69200, share: 12.5, languages: ['Python'] },
  { name: 'Redis', category: '数据库', repoCount: 3, starCount: 58100, share: 12.5, languages: ['Python', 'Java', 'Go'] },
  { name: 'Kubernetes', category: 'DevOps', repoCount: 2, starCount: 81200, share: 8.3, languages: ['Go'] },
  { name: 'LangChain', category: 'AI/数据', repoCount: 2, starCount: 47600, share: 8.3, languages: ['Python'] },
  { name: 'Vite', category: '工具链', repoCount: 2, starCount: 44100, share: 8.3, languages: ['TypeScript'] },
  { name: 'Django', category: '后端', repoCount: 2, starCount: 38900, share: 8.3, languages: ['Python'] },
  { name: 'Prisma', category: '工具链', repoCount: 2, starCount: 33700, share: 8.3, languages: ['TypeScript'] },
  { name: 'Vue', category: '前端', repoCount: 1, starCount: 48900, share: 4.2, languages: ['JavaScript'] },
  { name: 'Tauri', category: '桌面端', repoCount: 1, starCount: 92100, share: 4.2, languages: ['Rust'] },
  { name: 'Playwright', category: '测试', repoCount: 1, starCount: 28600, share: 4.2, languages: ['TypeScript'] },
]

const MOCK_NODES: TechStackGraphNode[] = [
  ...MOCK_LANGUAGES.map((item) => ({
    id: `lang:${item.name}`,
    label: item.name,
    kind: 'language' as const,
    weight: item.repoCount,
  })),
  ...MOCK_FRAMEWORKS.slice(0, 12).map((item) => ({
    id: `fw:${item.name}`,
    label: item.name,
    kind: 'framework' as const,
    category: item.category,
    weight: item.repoCount,
  })),
]

const MOCK_LINKS: TechStackGraphLink[] = [
  { source: 'lang:TypeScript', target: 'fw:React', weight: 5 },
  { source: 'lang:TypeScript', target: 'fw:Next.js', weight: 4 },
  { source: 'lang:TypeScript', target: 'fw:Tailwind CSS', weight: 3 },
  { source: 'lang:TypeScript', target: 'fw:Vite', weight: 2 },
  { source: 'lang:TypeScript', target: 'fw:Prisma', weight: 2 },
  { source: 'lang:TypeScript', target: 'fw:Playwright', weight: 1 },
  { source: 'lang:Python', target: 'fw:FastAPI', weight: 5 },
  { source: 'lang:Python', target: 'fw:PostgreSQL', weight: 4 },
  { source: 'lang:Python', target: 'fw:PyTorch', weight: 3 },
  { source: 'lang:Python', target: 'fw:Django', weight: 2 },
  { source: 'lang:Python', target: 'fw:LangChain', weight: 2 },
  { source: 'lang:Python', target: 'fw:Redis', weight: 2 },
  { source: 'lang:Python', target: 'fw:Docker', weight: 2 },
  { source: 'lang:Go', target: 'fw:Docker', weight: 3 },
  { source: 'lang:Go', target: 'fw:Kubernetes', weight: 2 },
  { source: 'lang:Go', target: 'fw:PostgreSQL', weight: 1 },
  { source: 'lang:Go', target: 'fw:Redis', weight: 1 },
  { source: 'lang:Rust', target: 'fw:Tauri', weight: 1 },
  { source: 'lang:Rust', target: 'fw:Docker', weight: 1 },
  { source: 'lang:JavaScript', target: 'fw:React', weight: 1 },
  { source: 'lang:JavaScript', target: 'fw:Vue', weight: 1 },
  { source: 'lang:JavaScript', target: 'fw:Next.js', weight: 1 },
  { source: 'lang:Java', target: 'fw:PostgreSQL', weight: 1 },
  { source: 'lang:Java', target: 'fw:Redis', weight: 1 },
  { source: 'lang:Shell', target: 'fw:Docker', weight: 1 },
]

/** 演示模式数据：与 `/api/tech-stack` 契约一致 */
export const MOCK_TECH_STACK: TechStackResponse = {
  summary: {
    totalRepos: 24,
    withLanguage: 24,
    withFramework: 21,
    languageCount: 7,
    frameworkCount: 16,
    topLanguage: 'TypeScript',
    topFramework: 'React',
    coverage: 100,
    totalStars: 624900,
  },
  languages: MOCK_LANGUAGES,
  frameworks: MOCK_FRAMEWORKS,
  graph: { nodes: MOCK_NODES, links: MOCK_LINKS },
  generatedAt: '2026-10-22T10:00:00.000Z',
}

/** 拉取当前用户的技术栈图谱；接口不可用时回退演示数据 */
export function fetchTechStack(): Promise<TechStackResponse> {
  return fetchWithFallback<TechStackResponse>('/api/tech-stack', MOCK_TECH_STACK)
}
