import { apiFetch, DEMO_MODE, fetchWithFallback } from '@/lib/api'

export interface DependencySummary {
  repos: number
  analyzed: number
  noManifest: number
  failed: number
  pending: number
  dependencyRows: number
  uniqueDependencies: number
  ecosystems: number
}

export interface TechStackItem {
  language: string
  count: number
  percent: number
}

export interface EcosystemItem {
  ecosystem: string
  repos: number
  dependencies: number
}

export interface DependencyItem {
  name: string
  ecosystem: string
  kind: 'runtime' | 'dev'
  repoCount: number
  coverage: number
  versions: string[]
  languages: Array<{ language: string; count: number }>
  repos: Array<{ id: string; name: string; language: string }>
}

export interface DependencyLink {
  dependency: string
  ecosystem: string
  language: string
  count: number
  strength: number
}

export interface RepoCoverage {
  repoId: string
  name: string
  language: string
  status: 'ok' | 'no_manifest' | 'failed' | 'pending' | 'unknown'
  manifests: string[]
  dependencyCount: number
  error?: string | null
  topDependencies: Array<{ name: string; ecosystem: string }>
}

export interface DependencyAnalysis {
  generatedAt: string
  summary: DependencySummary
  techStack: TechStackItem[]
  ecosystems: EcosystemItem[]
  dependencies: DependencyItem[]
  links: DependencyLink[]
  repos: RepoCoverage[]
  mode?: 'vps' | 'local'
}

export interface RefreshResult {
  status: string
  mode?: 'vps' | 'local'
  message?: string
  scanned: number
  ok: number
  noManifest: number
  failed: number
  dependencies: number
  repos: Array<Record<string, unknown>>
}

export const MOCK_ANALYSIS: DependencyAnalysis = {
  generatedAt: '2026-10-22T08:30:00Z',
  mode: 'local',
  summary: {
    repos: 8,
    analyzed: 7,
    noManifest: 1,
    failed: 0,
    pending: 0,
    dependencyRows: 46,
    uniqueDependencies: 31,
    ecosystems: 4,
  },
  techStack: [
    { language: 'TypeScript', count: 4, percent: 0.5 },
    { language: 'Python', count: 2, percent: 0.25 },
    { language: 'Go', count: 1, percent: 0.125 },
    { language: 'Rust', count: 1, percent: 0.125 },
  ],
  ecosystems: [
    { ecosystem: 'npm', repos: 4, dependencies: 24 },
    { ecosystem: 'pypi', repos: 2, dependencies: 12 },
    { ecosystem: 'go', repos: 1, dependencies: 6 },
    { ecosystem: 'cargo', repos: 1, dependencies: 4 },
  ],
  dependencies: [
    {
      name: 'react',
      ecosystem: 'npm',
      kind: 'runtime',
      repoCount: 4,
      coverage: 0.5,
      versions: ['^18.2.0', '^19.0.0'],
      languages: [{ language: 'TypeScript', count: 4 }],
      repos: [
        { id: 'fntp/opensource-factory', name: 'opensource-factory', language: 'TypeScript' },
        { id: 'fntp/admin-kit', name: 'admin-kit', language: 'TypeScript' },
      ],
    },
    {
      name: 'typescript',
      ecosystem: 'npm',
      kind: 'dev',
      repoCount: 4,
      coverage: 0.5,
      versions: ['~5.6.0'],
      languages: [{ language: 'TypeScript', count: 4 }],
      repos: [
        { id: 'fntp/opensource-factory', name: 'opensource-factory', language: 'TypeScript' },
      ],
    },
    {
      name: 'fastapi',
      ecosystem: 'pypi',
      kind: 'runtime',
      repoCount: 2,
      coverage: 0.25,
      versions: ['>=0.115'],
      languages: [{ language: 'Python', count: 2 }],
      repos: [{ id: 'fntp/vps-node', name: 'vps-node', language: 'Python' }],
    },
    {
      name: 'pydantic',
      ecosystem: 'pypi',
      kind: 'runtime',
      repoCount: 2,
      coverage: 0.25,
      versions: ['^2.9.0'],
      languages: [{ language: 'Python', count: 2 }],
      repos: [{ id: 'fntp/vps-node', name: 'vps-node', language: 'Python' }],
    },
    {
      name: 'github.com/gin-gonic/gin',
      ecosystem: 'go',
      kind: 'runtime',
      repoCount: 1,
      coverage: 0.125,
      versions: ['v1.10.0'],
      languages: [{ language: 'Go', count: 1 }],
      repos: [{ id: 'fntp/edge-gateway', name: 'edge-gateway', language: 'Go' }],
    },
    {
      name: 'serde',
      ecosystem: 'cargo',
      kind: 'runtime',
      repoCount: 1,
      coverage: 0.125,
      versions: ['1.0'],
      languages: [{ language: 'Rust', count: 1 }],
      repos: [{ id: 'fntp/cli-tools', name: 'cli-tools', language: 'Rust' }],
    },
  ],
  links: [
    { dependency: 'react', ecosystem: 'npm', language: 'TypeScript', count: 4, strength: 1 },
    { dependency: 'typescript', ecosystem: 'npm', language: 'TypeScript', count: 4, strength: 1 },
    { dependency: 'fastapi', ecosystem: 'pypi', language: 'Python', count: 2, strength: 1 },
  ],
  repos: [
    {
      repoId: 'fntp/opensource-factory',
      name: 'opensource-factory',
      language: 'TypeScript',
      status: 'ok',
      manifests: ['package.json'],
      dependencyCount: 14,
      error: null,
      topDependencies: [
        { name: 'react', ecosystem: 'npm' },
        { name: 'typescript', ecosystem: 'npm' },
      ],
    },
    {
      repoId: 'fntp/vps-node',
      name: 'vps-node',
      language: 'Python',
      status: 'ok',
      manifests: ['requirements.txt', 'pyproject.toml'],
      dependencyCount: 11,
      error: null,
      topDependencies: [
        { name: 'fastapi', ecosystem: 'pypi' },
        { name: 'pydantic', ecosystem: 'pypi' },
      ],
    },
    {
      repoId: 'fntp/edge-gateway',
      name: 'edge-gateway',
      language: 'Go',
      status: 'ok',
      manifests: ['go.mod'],
      dependencyCount: 6,
      error: null,
      topDependencies: [{ name: 'github.com/gin-gonic/gin', ecosystem: 'go' }],
    },
    {
      repoId: 'fntp/cli-tools',
      name: 'cli-tools',
      language: 'Rust',
      status: 'ok',
      manifests: ['Cargo.toml'],
      dependencyCount: 4,
      error: null,
      topDependencies: [{ name: 'serde', ecosystem: 'cargo' }],
    },
    {
      repoId: 'fntp/docs',
      name: 'docs',
      language: '',
      status: 'no_manifest',
      manifests: [],
      dependencyCount: 0,
      error: null,
      topDependencies: [],
    },
  ],
}

export async function fetchDependencyAnalysis(
  top = 20
): Promise<DependencyAnalysis> {
  return fetchWithFallback<DependencyAnalysis>(
    `/api/analysis/dependencies?top=${top}`,
    MOCK_ANALYSIS
  )
}

export async function refreshDependencyAnalysis(): Promise<RefreshResult> {
  if (DEMO_MODE) {
    return {
      status: 'ok',
      mode: 'local',
      message: '演示模式：已刷新本地示例数据',
      scanned: MOCK_ANALYSIS.summary.repos,
      ok: MOCK_ANALYSIS.summary.analyzed,
      noManifest: MOCK_ANALYSIS.summary.noManifest,
      failed: 0,
      dependencies: MOCK_ANALYSIS.summary.dependencyRows,
      repos: [],
    }
  }
  return apiFetch<RefreshResult>('/api/analysis/dependencies/refresh', {
    method: 'POST',
  })
}
