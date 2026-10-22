/**
 * 热榜查询纯函数：参数解析、排名与趋势计算。
 *
 * 放在独立模块中，便于用 node:test 直接覆盖，不依赖 Hono / D1。
 */

export type TrendingTrend = 'up' | 'down' | 'new' | 'same';

export interface TrendingQuery {
  /** 空串表示取最新快照日 */
  date: string;
  /** 空串表示全部语言 */
  language: string;
  limit: number;
}

export type TrendingQueryResult =
  | { ok: true; query: TrendingQuery }
  | { ok: false; field: string; message: string };

export interface RankableRow {
  id: string;
  stars_today: number | null;
}

export interface TrendInfo {
  rank: number;
  rankChange: number | null;
  trend: TrendingTrend;
}

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;
const MAX_LANGUAGE_LENGTH = 64;

/** 严格校验 YYYY-MM-DD（拒绝 2026-02-31 这类非法日期）。 */
export function isValidDate(value: string): boolean {
  const match = DATE_RE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

/** 解析 GET /api/trending 查询参数；非法值返回字段级错误。 */
export function parseTrendingQuery(params: URLSearchParams): TrendingQueryResult {
  const rawDate = (params.get('date') ?? '').trim();
  if (rawDate && !isValidDate(rawDate)) {
    return { ok: false, field: 'date', message: 'date 需为合法的 YYYY-MM-DD 日期' };
  }

  const rawLanguage = (params.get('language') ?? '').trim();
  if (rawLanguage.length > MAX_LANGUAGE_LENGTH) {
    return {
      ok: false,
      field: 'language',
      message: `language 最长 ${MAX_LANGUAGE_LENGTH} 个字符`,
    };
  }

  const rawLimit = params.get('limit');
  let limit = DEFAULT_LIMIT;
  if (rawLimit !== null && rawLimit !== '') {
    if (!/^\d+$/.test(rawLimit)) {
      return { ok: false, field: 'limit', message: 'limit 需为正整数' };
    }
    const parsed = Number.parseInt(rawLimit, 10);
    if (!Number.isSafeInteger(parsed) || parsed <= 0) {
      return { ok: false, field: 'limit', message: 'limit 需为正整数' };
    }
    limit = Math.min(parsed, MAX_LIMIT);
  }

  return { ok: true, query: { date: rawDate, language: rawLanguage, limit } };
}

/** 根据排名变化生成趋势类型：null = 上一快照日未上榜。 */
export function trendFromRankChange(rankChange: number | null): TrendingTrend {
  if (rankChange === null) return 'new';
  if (rankChange > 0) return 'up';
  if (rankChange < 0) return 'down';
  return 'same';
}

/**
 * 计算当日排名与相对上一快照日的排名变化。
 *
 * `currentRows` 需已按 `stars_today DESC, id ASC` 排序；排名从 1 开始。
 * `previousRanks` 为上一快照日的 `repo id -> rank` 映射。
 */
export function computeTrendMap(
  currentRows: RankableRow[],
  previousRanks: ReadonlyMap<string, number>
): Map<string, TrendInfo> {
  const result = new Map<string, TrendInfo>();
  currentRows.forEach((row, index) => {
    const rank = index + 1;
    const previousRank = previousRanks.get(row.id);
    const rankChange = previousRank === undefined ? null : previousRank - rank;
    result.set(row.id, {
      rank,
      rankChange,
      trend: trendFromRankChange(rankChange),
    });
  });
  return result;
}

/** 语言匹配：大小写不敏感，空筛选表示全部。 */
export function matchesLanguage(language: string | null, filter: string): boolean {
  if (!filter) return true;
  return (language ?? '').toLowerCase() === filter.toLowerCase();
}
