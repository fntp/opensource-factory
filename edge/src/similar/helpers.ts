/**
 * 相似项目推荐纯函数（M6-02）。
 *
 * 参数归一化、关键词兜底打分与理由文案；不访问 D1 / 网络，便于 node:test 直接覆盖。
 */

export type SimilarSource = 'my' | 'trending';
export type SimilarScope = 'my' | 'trending' | 'all';

export const DEFAULT_SIMILAR_TOP_K = 8;
export const MAX_SIMILAR_TOP_K = 30;

export function normalizeSimilarSource(value: unknown): SimilarSource | null {
  if (value === 'my' || value === 'trending') return value;
  return null;
}

export function normalizeSimilarScope(value: unknown): SimilarScope | null {
  if (value === undefined || value === null || value === '') return 'all';
  return value === 'my' || value === 'trending' || value === 'all' ? value : null;
}

export function clampSimilarTopK(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_SIMILAR_TOP_K;
  return Math.min(MAX_SIMILAR_TOP_K, Math.max(1, Math.trunc(parsed)));
}

export function parseBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === '1') return true;
  if (value === 'false' || value === '0') return false;
  return fallback;
}

/** 关键词兜底打分：同语言 + 共享技术栈 > 同语言 > 共享技术栈。 */
export function fallbackScore(
  seedLanguage: string,
  seedTech: string[],
  candidateLanguage: string,
  candidateTech: string[]
): number {
  const language = seedLanguage.trim().toLowerCase();
  const candidate = candidateLanguage.trim().toLowerCase();
  const sameLanguage = Boolean(language) && language === candidate;
  const sharedTech = seedTech.filter((tech) =>
    candidateTech.some((item) => item.toLowerCase() === tech.toLowerCase())
  );
  if (sameLanguage && sharedTech.length > 0) return 0.55;
  if (sameLanguage) return 0.4;
  if (sharedTech.length > 0) return 0.3;
  return 0;
}

export function sharedTechStack(seedTech: string[], candidateTech: string[]): string[] {
  return seedTech.filter((tech) =>
    candidateTech.some((item) => item.toLowerCase() === tech.toLowerCase())
  );
}

/** 关键词兜底理由：明确说明是语言 / 技术栈匹配，不冒充语义相似度。 */
export function fallbackReason(
  seedName: string,
  candidateLanguage: string,
  sharedTech: string[]
): string {
  if (sharedTech.length > 0) {
    return `与「${seedName}」同属 ${sharedTech.join(' / ')} 技术栈。`;
  }
  if (candidateLanguage) {
    return `与「${seedName}」主要语言同为 ${candidateLanguage}。`;
  }
  return `与「${seedName}」语言 / 技术栈相近。`;
}
