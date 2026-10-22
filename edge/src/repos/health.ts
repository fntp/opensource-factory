/**
 * 项目健康度（M6-05）：最后提交 / issue 活跃 / 归档标记。
 *
 * 计算口径与 VPS `app/services/repo_health.py` 保持一致：
 * - 归档 > 禁用 > 缺失 pushed_at > 按最后提交天数分档（90 / 180 / 365 天）；
 * - 未关闭 issue 占 Star 比例只做小幅扣分，不改变天数分档得到的状态；
 * - D1 中已有 VPS 回写结果时优先采用，保证边缘侧与算力节点一致。
 */
import type { HealthStatus, RepoHealth, RepoHealthSummary, RepoRow } from '../types';

export const HEALTH_LABELS: Record<HealthStatus, string> = {
  active: '活跃',
  attention: '需关注',
  stale: '停滞',
  archived: '已归档',
  unknown: '未知',
};

export const DEFAULT_ACTIVE_DAYS = 90;
export const DEFAULT_ATTENTION_DAYS = 180;
export const DEFAULT_STALE_DAYS = 365;

const DAY_MS = 24 * 60 * 60 * 1000;

export function normalizeHealthStatus(value: unknown): HealthStatus {
  const text = String(value ?? '')
    .trim()
    .toLowerCase();
  return text in HEALTH_LABELS ? (text as HealthStatus) : 'unknown';
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  let text = String(value).trim();
  if (!text) return null;
  // D1 的 DATETIME 常为 "YYYY-MM-DD HH:mm:ss"（UTC），补 T/Z 后再解析
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(text)) {
    text = `${text.replace(' ', 'T')}Z`;
  }
  const ms = Date.parse(text);
  return Number.isFinite(ms) ? new Date(ms) : null;
}

function toIso(value: Date | string | null | undefined): string | null {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return null;
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function clamp(value: number, low = 0, high = 100): number {
  return Math.max(low, Math.min(high, Math.round(value)));
}

export interface EvaluateHealthInput {
  pushedAt?: string | Date | null;
  openIssues?: number | null;
  archived?: boolean | number | null;
  disabled?: boolean | number | null;
  stars?: number | null;
  now?: Date;
  activeDays?: number;
  attentionDays?: number;
  staleDays?: number;
}

/** 纯函数：根据元数据计算健康度（与 VPS 口径一致）。 */
export function evaluateHealth(input: EvaluateHealthInput): RepoHealth {
  const now = input.now ?? new Date();
  const activeDays = Math.max(1, Math.trunc(input.activeDays ?? DEFAULT_ACTIVE_DAYS));
  const attentionDays = Math.max(activeDays, Math.trunc(input.attentionDays ?? DEFAULT_ATTENTION_DAYS));
  const staleDays = Math.max(attentionDays, Math.trunc(input.staleDays ?? DEFAULT_STALE_DAYS));
  const issues = Math.max(0, Math.trunc(Number(input.openIssues ?? 0) || 0));
  const pushedAt = input.pushedAt instanceof Date ? input.pushedAt : parseDate(input.pushedAt ?? null);
  const pushedIso = toIso(pushedAt);
  const archived = Boolean(input.archived);

  if (archived) {
    return {
      status: 'archived',
      label: HEALTH_LABELS.archived,
      score: 0,
      lastPushAt: pushedIso,
      daysSincePush: null,
      openIssues: issues,
      archived: true,
      reasons: ['仓库已归档，不再接收更新'],
      checkedAt: null,
    };
  }

  if (!pushedAt) {
    return {
      status: 'unknown',
      label: HEALTH_LABELS.unknown,
      score: 0,
      lastPushAt: null,
      daysSincePush: null,
      openIssues: issues,
      archived: false,
      reasons: ['缺少最后提交时间，无法判断活跃度'],
      checkedAt: null,
    };
  }

  const days = Math.max(0, Math.floor((now.getTime() - pushedAt.getTime()) / DAY_MS));
  let status: HealthStatus;
  let score: number;
  if (days <= activeDays) {
    status = 'active';
    score = 100;
  } else if (days <= attentionDays) {
    status = 'attention';
    score = 70;
  } else if (days <= staleDays) {
    status = 'stale';
    score = 45;
  } else {
    status = 'stale';
    score = 20;
  }

  let issueReason: string;
  if (issues <= 0) {
    score += 5;
    issueReason = '当前没有未关闭 issue';
  } else {
    const stars = Math.max(1, Math.trunc(Number(input.stars ?? 0) || 0));
    const ratio = issues / stars;
    if (ratio >= 0.5) {
      score -= 20;
      issueReason = `存在 ${issues} 个未关闭 issue / PR（占 Star ${Math.round(ratio * 100)}%），需关注维护压力`;
    } else if (ratio >= 0.2) {
      score -= 10;
      issueReason = `存在 ${issues} 个未关闭 issue / PR（占 Star ${Math.round(ratio * 100)}%）`;
    } else {
      issueReason = `存在 ${issues} 个未关闭 issue / PR`;
    }
  }

  const reasons = [`最后提交于 ${days} 天前`];
  if (Boolean(input.disabled)) {
    score = Math.min(score, 30);
    status = 'stale';
    reasons.push('仓库已被 GitHub 禁用');
  }
  if (days > attentionDays) {
    reasons.push(`超过 ${attentionDays} 天无提交，建议评估是否仍在使用`);
  }
  reasons.push(issueReason);

  return {
    status,
    label: HEALTH_LABELS[status],
    score: clamp(score),
    lastPushAt: pushedIso,
    daysSincePush: days,
    openIssues: issues,
    archived: false,
    reasons,
    checkedAt: null,
  };
}

/** 从 D1 行读取健康度：优先使用 VPS 回写结果，否则本地按字段计算。 */
export function healthFromRow(row: RepoRow, now: Date = new Date()): RepoHealth {
  const computed = evaluateHealth({
    pushedAt: row.pushed_at ?? null,
    openIssues: row.open_issues_count ?? 0,
    archived: row.archived ?? false,
    disabled: row.disabled ?? false,
    stars: row.stars ?? 0,
    now,
  });

  const stored = normalizeHealthStatus(row.health_status);
  if (!row.health_status || !row.health_checked_at) {
    return computed;
  }
  return {
    ...computed,
    status: stored,
    label: HEALTH_LABELS[stored],
    score: clamp(Number(row.health_score ?? computed.score)),
    checkedAt: toIso(row.health_checked_at),
  };
}

/** 汇总健康度：各状态计数 + 平均分（保留 1 位小数）。兼容扁平与 { health } 两种条目。 */
export function summarizeRepoHealth(
  items: Array<RepoHealth | { health: RepoHealth }>
): RepoHealthSummary {
  const summary: RepoHealthSummary = {
    total: items.length,
    active: 0,
    attention: 0,
    stale: 0,
    archived: 0,
    unknown: 0,
    averageScore: 0,
  };
  let scoreSum = 0;
  for (const item of items) {
    const health = 'health' in item ? item.health : item;
    summary[normalizeHealthStatus(health.status)] += 1;
    scoreSum += Number(health.score ?? 0);
  }
  summary.averageScore = items.length ? Math.round((scoreSum / items.length) * 10) / 10 : 0;
  return summary;
}
