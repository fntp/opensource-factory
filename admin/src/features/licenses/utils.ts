import type { LicenseInfo, LicenseRisk, LicenseSummary } from './api'

const RISK_TONE: Record<LicenseRisk, string> = {
  low: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300',
  medium:
    'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300',
  high: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300',
  unknown:
    'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300',
}

const RISK_LABEL: Record<LicenseRisk, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  unknown: '未知风险',
}

export function riskToneClass(risk: LicenseRisk): string {
  return RISK_TONE[risk] ?? RISK_TONE.unknown
}

export function riskLabel(risk: LicenseRisk): string {
  return RISK_LABEL[risk] ?? RISK_LABEL.unknown
}

/** 徽章文案：优先 SPDX，未识别统一显示「未识别」 */
export function licenseBadgeLabel(license?: LicenseInfo | null): string {
  if (!license) return '未识别'
  return license.spdxId || '未识别'
}

export function licenseToneClass(license?: LicenseInfo | null): string {
  return riskToneClass(license?.riskLevel ?? 'unknown')
}

/** 识别来源文案 */
export function licenseSourceLabel(source?: string | null): string {
  switch (source) {
    case 'github':
      return 'GitHub 元数据'
    case 'readme':
      return 'README 识别'
    case 'none':
      return '无许可证'
    default:
      return '尚未识别'
  }
}

/** ISO 时间 → `YYYY-MM-DD HH:mm`；无值返回「尚未识别」 */
export function formatLicenseCheckedAt(value?: string | null): string {
  if (!value) return '尚未识别'
  return value.replace('T', ' ').slice(0, 16)
}

/** 识别覆盖率（0-100 整数） */
export function licenseCoverage(summary?: LicenseSummary | null): number {
  if (!summary || summary.total <= 0) return 0
  return Math.round((summary.checked / summary.total) * 100)
}

/** 单一许可证占比（0-100 整数） */
export function licenseShare(count: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((count / total) * 100)
}
