/**
 * 精排纯函数（REQ-202610-0966 / M7-07）。
 *
 * VPS 可用时由 `POST /api/recommend/rerank/preview` 做六路信号 + MMR 精排；
 * VPS 不可达时这里用 D1 已有字段做同构的本地启发式精排（mode=local）：
 * - 相关性 = 粗排分；
 * - 画像亲和：无用户画像，按「有语言信息」给中性 0.5；
 * - 时效：推荐创建时间 30 天半衰期；
 * - 动量 / 人气：总 star 对数归一化；
 * - 健康度：简介 / 语言 / star 完整度；
 * - 多样性：同语言候选互相惩罚（MMR）。
 *
 * 与路由分离，便于 `node --test` 直接导入。
 */
import type { RecommendationRow, RerankDetail } from '../types';

export interface RerankWeights {
  relevance: number;
  affinity: number;
  freshness: number;
  momentum: number;
  popularity: number;
  health: number;
}

export const DEFAULT_RERANK_WEIGHTS: RerankWeights = {
  relevance: 0.45,
  affinity: 0.15,
  freshness: 0.12,
  momentum: 0.1,
  popularity: 0.08,
  health: 0.1,
};

export interface RerankCandidateInput {
  repoId: string;
  name?: string | null;
  htmlUrl?: string | null;
  baseScore?: number | null;
  similarity?: number | null;
  starsToday?: number | null;
  stars?: number | null;
  language?: string | null;
  techStack?: string[] | null;
  description?: string | null;
  readmeSummary?: string | null;
  licenseSpdx?: string | null;
  pushedAt?: string | null;
  healthScore?: number | null;
}

export interface RerankResultItem {
  repoId: string;
  name: string;
  htmlUrl: string;
  language: string;
  baseScore: number;
  rerankScore: number;
  rankBefore: number;
  rankAfter: number;
  signals: Record<string, number>;
  contributions: Record<string, number>;
  reasons: string[];
  diversityPenalty: number;
}

export interface RerankMetrics {
  total: number;
  selected: number;
  movedUp: number;
  movedDown: number;
  unchanged: number;
  avgRankShift: number;
  diversityBefore: number;
  diversityAfter: number;
  languageCoverage: number;
}

export interface RerankResult {
  items: RerankResultItem[];
  metrics: RerankMetrics;
  weights: RerankWeights;
  mmrLambda: number;
}

const SIGNAL_REASONS: Record<string, string> = {
  relevance: '与你收藏方向语义相关',
  affinity: '语言 / 技术栈与你的收藏高度重合',
  freshness: '近期仍有活跃提交',
  momentum: '今日热度快速上升',
  popularity: '社区关注度高',
  health: '项目元数据完整、维护状态良好',
};

function clamp(value: number, min = 0, max = 1): number {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function numberOr(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function logNorm(value: number, maximum: number): number {
  if (maximum <= 0) return 0;
  return clamp(Math.log1p(Math.max(0, value)) / Math.log1p(maximum));
}

/** 权重归一化：负值按 0；全 0 退化为纯相关性。 */
export function normalizeRerankWeights(raw?: Partial<RerankWeights> | null): RerankWeights {
  const merged: RerankWeights = { ...DEFAULT_RERANK_WEIGHTS };
  if (raw && typeof raw === 'object') {
    for (const key of Object.keys(merged) as Array<keyof RerankWeights>) {
      const value = raw[key];
      if (typeof value === 'number' && Number.isFinite(value)) {
        merged[key] = Math.max(0, value);
      }
    }
  }
  const total = Object.values(merged).reduce((sum, value) => sum + value, 0);
  if (total <= 0) {
    return { relevance: 1, affinity: 0, freshness: 0, momentum: 0, popularity: 0, health: 0 };
  }
  return {
    relevance: merged.relevance / total,
    affinity: merged.affinity / total,
    freshness: merged.freshness / total,
    momentum: merged.momentum / total,
    popularity: merged.popularity / total,
    health: merged.health / total,
  };
}

function freshnessFromDate(raw: string | null | undefined, now: number): number {
  if (!raw) return 0.5;
  const parsed = Date.parse(raw);
  if (!Number.isFinite(parsed)) return 0.5;
  const days = Math.max(0, (now - parsed) / 86_400_000);
  return clamp(Math.pow(0.5, days / 30));
}

function healthOf(candidate: RerankCandidateInput): number {
  if (typeof candidate.healthScore === 'number' && Number.isFinite(candidate.healthScore)) {
    return clamp(candidate.healthScore / 100);
  }
  let score = 0;
  if ((candidate.description ?? '').trim()) score += 0.4;
  if ((candidate.language ?? '').trim()) score += 0.3;
  if (numberOr(candidate.stars) > 0) score += 0.3;
  return clamp(score);
}

function languageSimilarity(left: RerankCandidateInput, right: RerankCandidateInput): number {
  const a = (left.language ?? '').trim().toLowerCase();
  const b = (right.language ?? '').trim().toLowerCase();
  if (!a || !b) return 0;
  return a === b ? 1 : 0;
}

function meanPairwiseDiversity(
  items: RerankResultItem[],
  byId: Map<string, RerankCandidateInput>
): number {
  if (items.length < 2) return 0;
  let total = 0;
  let pairs = 0;
  for (let i = 0; i < items.length; i += 1) {
    for (let j = i + 1; j < items.length; j += 1) {
      const left = byId.get(items[i]?.repoId ?? '');
      const right = byId.get(items[j]?.repoId ?? '');
      if (!left || !right) continue;
      total += 1 - languageSimilarity(left, right);
      pairs += 1;
    }
  }
  return pairs > 0 ? clamp(total / pairs) : 0;
}

function languageCoverage(
  items: RerankResultItem[],
  byId: Map<string, RerankCandidateInput>
): number {
  if (items.length === 0) return 0;
  const languages = new Set<string>();
  for (const item of items) {
    const language = (byId.get(item.repoId)?.language ?? '').trim().toLowerCase();
    if (language) languages.add(language);
  }
  return clamp(languages.size / items.length);
}

/** D1 推荐行 → 本地精排候选。 */
export function candidateFromRow(row: RecommendationRow): RerankCandidateInput {
  const base = numberOr(row.base_score) > 0 ? numberOr(row.base_score) : numberOr(row.score);
  return {
    repoId: (row.repo_id ?? '').trim() || `${row.owner ?? ''}/${row.name ?? ''}`,
    name: row.name,
    htmlUrl: row.url,
    baseScore: base,
    similarity: numberOr(row.score),
    stars: numberOr(row.stars),
    language: row.language,
    description: row.description,
    healthScore: null,
  };
}

/** 本地启发式精排（VPS 不可达时使用）。 */
export function localRerank(
  candidates: RerankCandidateInput[],
  options: { topK?: number; mmrLambda?: number; weights?: Partial<RerankWeights> | null; now?: number } = {}
): RerankResult {
  const topK = Math.max(1, Math.min(100, Math.trunc(numberOr(options.topK, 20))));
  const mmrLambda = clamp(numberOr(options.mmrLambda, 0.75));
  const weights = normalizeRerankWeights(options.weights);
  const now = options.now ?? Date.now();
  const usable = candidates.filter((item) => item.repoId);
  const maxStars = Math.max(0, ...usable.map((item) => numberOr(item.stars)));

  const signalsById = new Map<string, Record<string, number>>();
  const contributionsById = new Map<string, Record<string, number>>();
  const scores = new Map<string, number>();
  for (const item of usable) {
    const signals = {
      relevance: clamp(numberOr(item.baseScore)),
      affinity: (item.language ?? '').trim() ? 0.5 : 0,
      freshness: freshnessFromDate(item.pushedAt ?? null, now),
      momentum: logNorm(numberOr(item.stars), maxStars),
      popularity: logNorm(numberOr(item.stars), maxStars),
      health: healthOf(item),
    };
    signalsById.set(item.repoId, signals);
    const contributions = Object.fromEntries(
      Object.entries(signals).map(([key, value]) => [key, value * weights[key as keyof RerankWeights]])
    );
    contributionsById.set(item.repoId, contributions);
    scores.set(
      item.repoId,
      clamp(Object.values(contributions).reduce((sum, value) => sum + value, 0))
    );
  }

  const beforeOrder = [...usable].sort(
    (a, b) => numberOr(b.baseScore) - numberOr(a.baseScore) || a.repoId.localeCompare(b.repoId)
  );
  const beforeRank = new Map(beforeOrder.map((item, index) => [item.repoId, index + 1]));

  const remaining = [...usable];
  const selected: RerankCandidateInput[] = [];
  const chosen: Array<{ candidate: RerankCandidateInput; penalty: number }> = [];
  while (remaining.length > 0 && chosen.length < topK) {
    let best: { score: number; candidate: RerankCandidateInput; penalty: number } | null = null;
    for (const candidate of remaining) {
      let maxSim = 0;
      for (const picked of selected) {
        maxSim = Math.max(maxSim, languageSimilarity(candidate, picked));
      }
      const mmr = mmrLambda * (scores.get(candidate.repoId) ?? 0) - (1 - mmrLambda) * maxSim;
      const better =
        !best ||
        mmr > best.score + 1e-12 ||
        (Math.abs(mmr - best.score) <= 1e-12 && candidate.repoId < best.candidate.repoId);
      if (better) {
        best = { score: mmr, candidate, penalty: (1 - mmrLambda) * maxSim };
      }
    }
    if (!best) break;
    remaining.splice(remaining.indexOf(best.candidate), 1);
    selected.push(best.candidate);
    chosen.push({ candidate: best.candidate, penalty: best.penalty });
  }

  const byId = new Map(usable.map((item) => [item.repoId, item]));
  const items: RerankResultItem[] = chosen.map(({ candidate, penalty }, index) => {
    const contributions = contributionsById.get(candidate.repoId) ?? {};
    const reasons = Object.entries(contributions)
      .filter(([, value]) => value >= 0.06)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([key]) => SIGNAL_REASONS[key])
      .filter((reason): reason is string => Boolean(reason));
    if (penalty >= 0.05) reasons.push('为提升列表多样性做了降权');
    return {
      repoId: candidate.repoId,
      name: (candidate.name ?? '').trim(),
      htmlUrl: (candidate.htmlUrl ?? '').trim(),
      language: (candidate.language ?? '').trim(),
      baseScore: numberOr(candidate.baseScore),
      rerankScore: scores.get(candidate.repoId) ?? 0,
      rankBefore: beforeRank.get(candidate.repoId) ?? 0,
      rankAfter: index + 1,
      signals: signalsById.get(candidate.repoId) ?? {},
      contributions,
      reasons: reasons.length > 0 ? reasons : ['综合信号排序'],
      diversityPenalty: penalty,
    };
  });

  const movedUp = items.filter((item) => item.rankBefore > item.rankAfter).length;
  const movedDown = items.filter((item) => item.rankBefore < item.rankAfter).length;
  const beforeItems = beforeOrder.slice(0, items.length).map((candidate, index) => ({
    repoId: candidate.repoId,
    name: '',
    htmlUrl: '',
    language: '',
    baseScore: numberOr(candidate.baseScore),
    rerankScore: scores.get(candidate.repoId) ?? 0,
    rankBefore: index + 1,
    rankAfter: index + 1,
    signals: {},
    contributions: {},
    reasons: [],
    diversityPenalty: 0,
  }));

  return {
    items,
    metrics: {
      total: usable.length,
      selected: items.length,
      movedUp,
      movedDown,
      unchanged: items.length - movedUp - movedDown,
      avgRankShift:
        items.length > 0
          ? Number(
              (
                items.reduce((sum, item) => sum + Math.abs(item.rankBefore - item.rankAfter), 0) /
                items.length
              ).toFixed(4)
            )
          : 0,
      diversityBefore: Number(meanPairwiseDiversity(beforeItems, byId).toFixed(4)),
      diversityAfter: Number(meanPairwiseDiversity(items, byId).toFixed(4)),
      languageCoverage: Number(languageCoverage(items, byId).toFixed(4)),
    },
    weights,
    mmrLambda,
  };
}

/** 把精排结果转成 D1 可回写的明细 JSON。 */
export function toRerankDetail(item: RerankResultItem): RerankDetail {
  return {
    repoId: item.repoId,
    baseScore: item.baseScore,
    rerankScore: item.rerankScore,
    rankBefore: item.rankBefore,
    rankAfter: item.rankAfter,
    signals: item.signals,
    contributions: item.contributions,
    reasons: item.reasons,
    diversityPenalty: item.diversityPenalty,
  };
}
