import { fetchWithFallback } from '@/lib/api'

export type LicenseCategory =
  | 'permissive'
  | 'weak-copyleft'
  | 'strong-copyleft'
  | 'network-copyleft'
  | 'public-domain'
  | 'unknown'

export type LicenseRisk = 'low' | 'medium' | 'high' | 'unknown'

/** 单个仓库的 License 合规提示（与 edge / VPS 契约一致） */
export interface LicenseInfo {
  spdxId: string | null
  name: string | null
  category: LicenseCategory
  categoryLabel: string
  riskLevel: LicenseRisk
  riskLabel: string
  summary: string
  obligations: string[]
  warnings: string[]
  source: string | null
  checkedAt: string | null
}

export interface LicenseDefinition {
  spdxId: string
  name: string
  category: Exclude<LicenseCategory, 'unknown'>
  riskLevel: Exclude<LicenseRisk, 'unknown'>
  summary: string
  obligations: string[]
  warnings: string[]
}

export interface LicenseCategoryDefinition {
  key: LicenseCategory
  label: string
  description: string
}

export interface LicenseCatalog {
  categories: LicenseCategoryDefinition[]
  licenses: LicenseDefinition[]
}

export interface LicenseSummaryEntry {
  spdxId: string | null
  name: string
  count: number
  category: LicenseCategory
  categoryLabel: string
  riskLevel: LicenseRisk
}

export interface LicenseSummary {
  scope?: string
  total: number
  known: number
  unknown: number
  checked: number
  unchecked: number
  riskCounts: Record<LicenseRisk, number>
  licenses: LicenseSummaryEntry[]
}

export type LicenseScope = 'my' | 'trending' | 'all'

export const MOCK_LICENSE_CATALOG: LicenseCatalog = {
  categories: [
    { key: 'permissive', label: '宽松许可', description: '允许商用、修改、再分发与闭源衍生，通常只需保留版权与许可证声明。' },
    { key: 'weak-copyleft', label: '弱著佐权', description: '允许与闭源代码组合，但修改过的库文件本身需要以同许可证开源。' },
    { key: 'strong-copyleft', label: '强著佐权', description: '分发衍生作品时，衍生作品整体需要以同许可证开源。' },
    { key: 'network-copyleft', label: '网络著佐权', description: '通过网络提供服务也可能被视为分发，需要向用户提供源码。' },
    { key: 'public-domain', label: '公共领域', description: '作者放弃版权或贡献到公共领域，几乎没有强制义务。' },
    { key: 'unknown', label: '未知许可', description: '未识别到有效许可证，默认保留所有权利，使用前需要获得作者授权。' },
  ],
  licenses: [
    {
      spdxId: 'MIT',
      name: 'MIT License',
      category: 'permissive',
      riskLevel: 'low',
      summary: '允许商用、修改、再分发与闭源衍生，需保留版权与许可证声明。',
      obligations: ['保留版权声明', '保留许可证文本'],
      warnings: [],
    },
    {
      spdxId: 'Apache-2.0',
      name: 'Apache License 2.0',
      category: 'permissive',
      riskLevel: 'low',
      summary: '允许商用、修改、再分发与专利授权，需保留许可证与 NOTICE 文件并标注修改。',
      obligations: ['保留许可证文本', '保留 NOTICE 文件', '标注修改过的文件'],
      warnings: [],
    },
    {
      spdxId: 'MPL-2.0',
      name: 'Mozilla Public License 2.0',
      category: 'weak-copyleft',
      riskLevel: 'medium',
      summary: '文件级著佐权：修改过的 MPL 文件需以 MPL 开源，其他文件可闭源。',
      obligations: ['修改的 MPL 文件需开源', '保留许可证与源码获取方式'],
      warnings: ['与 GPL 组合时需确认兼容性'],
    },
    {
      spdxId: 'GPL-3.0',
      name: 'GNU General Public License 3.0',
      category: 'strong-copyleft',
      riskLevel: 'high',
      summary: '分发衍生作品时，衍生作品整体需以 GPL-3.0 开源，并禁止额外限制。',
      obligations: ['衍生作品需以 GPL 开源', '分发时提供完整源码', '不得附加额外限制'],
      warnings: ['闭源商用分发通常不可行', '含专利授权与反 Tivoization 条款'],
    },
    {
      spdxId: 'AGPL-3.0',
      name: 'GNU Affero General Public License 3.0',
      category: 'network-copyleft',
      riskLevel: 'high',
      summary: '通过网络向用户提供服务也可能触发源码开放义务，影响 SaaS 场景。',
      obligations: ['网络服务需提供完整源码', '衍生作品需以 AGPL 开源'],
      warnings: ['SaaS / 托管服务需重点评估', '闭源商用通常不可行'],
    },
    {
      spdxId: 'Unlicense',
      name: 'The Unlicense',
      category: 'public-domain',
      riskLevel: 'low',
      summary: '贡献到公共领域，允许任意使用，无强制义务。',
      obligations: [],
      warnings: ['建议保留出处与免责声明'],
    },
  ],
}

export const MOCK_LICENSE_SUMMARY: LicenseSummary = {
  scope: 'all',
  total: 18,
  known: 14,
  unknown: 4,
  checked: 16,
  unchecked: 2,
  riskCounts: { low: 9, medium: 3, high: 2, unknown: 4 },
  licenses: [
    { spdxId: 'MIT', name: 'MIT License', count: 6, category: 'permissive', categoryLabel: '宽松许可', riskLevel: 'low' },
    { spdxId: 'Apache-2.0', name: 'Apache License 2.0', count: 3, category: 'permissive', categoryLabel: '宽松许可', riskLevel: 'low' },
    { spdxId: 'MPL-2.0', name: 'Mozilla Public License 2.0', count: 2, category: 'weak-copyleft', categoryLabel: '弱著佐权', riskLevel: 'medium' },
    { spdxId: 'GPL-3.0', name: 'GNU General Public License 3.0', count: 2, category: 'strong-copyleft', categoryLabel: '强著佐权', riskLevel: 'high' },
    { spdxId: 'AGPL-3.0', name: 'GNU Affero General Public License 3.0', count: 1, category: 'network-copyleft', categoryLabel: '网络著佐权', riskLevel: 'high' },
    { spdxId: null, name: '未识别', count: 4, category: 'unknown', categoryLabel: '未知许可', riskLevel: 'unknown' },
  ],
}

export function fetchLicenseCatalog(): Promise<LicenseCatalog> {
  return fetchWithFallback<LicenseCatalog>(
    '/api/licenses/catalog',
    MOCK_LICENSE_CATALOG
  )
}

export function fetchLicenseSummary(
  scope: LicenseScope = 'all'
): Promise<LicenseSummary> {
  return fetchWithFallback<LicenseSummary>(
    `/api/licenses/summary?scope=${scope}`,
    { ...MOCK_LICENSE_SUMMARY, scope }
  )
}
