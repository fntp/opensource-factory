/** 语义搜索的纯函数辅助：查询归一化、校验与展示格式化。 */

export type SearchScope = 'my' | 'trending' | 'all'
export type SearchMode = 'vectorize' | 'local' | 'keyword'

export const MAX_QUERY_LENGTH = 200

/** 去首尾空白并把连续空白压成一个空格。 */
export function normalizeQuery(input: string): string {
  return input.trim().replace(/\s+/g, ' ')
}

/** 查询是否合法：1~200 字符。 */
export function isQueryValid(input: string): boolean {
  const query = normalizeQuery(input)
  return query.length > 0 && query.length <= MAX_QUERY_LENGTH
}

/** 匹配度展示：0.8734 → 87%。 */
export function formatScore(score: number): string {
  if (!Number.isFinite(score)) return '0%'
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`
}

/** 来源标签。 */
export function scopeLabel(scope: SearchScope): string {
  if (scope === 'my') return '我的仓库'
  if (scope === 'trending') return '每日热榜'
  return '全部来源'
}

/** 检索模式标签。 */
export function modeLabel(mode: SearchMode): string {
  if (mode === 'vectorize') return 'Vectorize 向量检索'
  if (mode === 'local') return '本地向量检索'
  return '关键词降级检索'
}
