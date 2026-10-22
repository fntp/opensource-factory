/**
 * D1 保留清理（REQ-202610-0983 / M9-06）。
 *
 * 由 Worker Cron 每日调用，也可通过内部接口手动触发。
 * - 单次 `db.batch()` 提交，保证同一轮清理要么全部生效、要么全部回滚；
 * - 时间比较统一用 SQLite `datetime()`，兼容 ISO 8601 与 `CURRENT_TIMESTAMP` 两种写法；
 * - 清理完成后写 `privacy_events`，只记录策略版本与各表删除数，不记录个人数据。
 */
import type { Env } from '../types';
import { run } from '../db';
import {
  PRIVACY_POLICY_VERSION,
  privacyEventId,
  retentionCutoff,
  retentionSettings,
} from './policy';

export interface RetentionCleanupResult {
  executedAt: string;
  policyVersion: string;
  deleted: Record<string, number>;
  total: number;
  auditRecorded: boolean;
}

interface CleanupStatement {
  key: string;
  sql: string;
  params: Array<string | number>;
}

/** 构建本轮清理语句（导出以便单元测试核对保留期与表名）。 */
export function buildCleanupStatements(now: Date, env: Partial<Env> = {}): CleanupStatement[] {
  const settings = retentionSettings(env);
  const cutoff = (days: number) => retentionCutoff(now, days);
  const nowIso = now.toISOString();

  return [
    {
      key: 'sessions',
      sql: 'DELETE FROM sessions WHERE datetime(expires_at) < datetime(?)',
      params: [cutoff(settings.sessionGraceDays)],
    },
    {
      key: 'rateLimitCounters',
      sql: 'DELETE FROM rate_limit_counters WHERE datetime(expires_at) < datetime(?)',
      params: [nowIso],
    },
    {
      key: 'loginAttempts',
      sql: 'DELETE FROM login_attempts WHERE datetime(created_at) < datetime(?)',
      params: [cutoff(settings.loginAttemptDays)],
    },
    {
      key: 'securityEvents',
      sql: 'DELETE FROM security_events WHERE datetime(created_at) < datetime(?)',
      params: [cutoff(settings.securityEventDays)],
    },
    {
      key: 'recommendationsUnsaved',
      sql: `DELETE FROM recommendations
             WHERE user_id IS NOT NULL
               AND status != 'saved'
               AND datetime(created_at) < datetime(?)`,
      params: [cutoff(settings.recommendationDays)],
    },
    {
      key: 'recommendationsSaved',
      sql: `DELETE FROM recommendations
             WHERE user_id IS NOT NULL
               AND status = 'saved'
               AND datetime(created_at) < datetime(?)`,
      params: [cutoff(settings.savedRecommendationDays)],
    },
    {
      key: 'notificationsRead',
      sql: `DELETE FROM notifications
             WHERE status IN ('read', 'dismissed')
               AND datetime(created_at) < datetime(?)`,
      params: [cutoff(settings.notificationReadDays)],
    },
    {
      key: 'notificationsUnread',
      sql: `DELETE FROM notifications
             WHERE status = 'unread'
               AND datetime(created_at) < datetime(?)`,
      params: [cutoff(settings.notificationUnreadDays)],
    },
    {
      key: 'repoUpdatesRead',
      sql: `DELETE FROM repo_updates
             WHERE status IN ('read', 'dismissed')
               AND datetime(created_at) < datetime(?)`,
      params: [cutoff(settings.repoUpdateReadDays)],
    },
    {
      key: 'repoUpdatesUnread',
      sql: `DELETE FROM repo_updates
             WHERE status = 'unread'
               AND datetime(created_at) < datetime(?)`,
      params: [cutoff(settings.repoUpdateUnreadDays)],
    },
    {
      key: 'recommendationFeedback',
      sql: 'DELETE FROM recommendation_feedback WHERE datetime(created_at) < datetime(?)',
      params: [cutoff(settings.feedbackDays)],
    },
    {
      key: 'duplicateDismissals',
      sql: 'DELETE FROM duplicate_dismissals WHERE datetime(created_at) < datetime(?)',
      params: [cutoff(settings.dismissalDays)],
    },
    {
      key: 'tagSuggestionsResolved',
      sql: `DELETE FROM tag_suggestions
             WHERE status != 'pending'
               AND datetime(updated_at) < datetime(?)`,
      params: [cutoff(settings.suggestionResolvedDays)],
    },
    {
      key: 'tagSuggestionsPending',
      sql: `DELETE FROM tag_suggestions
             WHERE status = 'pending'
               AND datetime(updated_at) < datetime(?)`,
      params: [cutoff(settings.suggestionPendingDays)],
    },
    {
      key: 'categorySuggestionsResolved',
      sql: `DELETE FROM category_suggestions
             WHERE status != 'pending'
               AND datetime(updated_at) < datetime(?)`,
      params: [cutoff(settings.suggestionResolvedDays)],
    },
    {
      key: 'categorySuggestionsPending',
      sql: `DELETE FROM category_suggestions
             WHERE status = 'pending'
               AND datetime(updated_at) < datetime(?)`,
      params: [cutoff(settings.suggestionPendingDays)],
    },
    {
      key: 'curatedReports',
      sql: 'DELETE FROM curated_reports WHERE datetime(generated_at) < datetime(?)',
      params: [cutoff(settings.reportDays)],
    },
    {
      key: 'extensionTokens',
      sql: `DELETE FROM extension_tokens
             WHERE revoked_at IS NOT NULL
               AND datetime(revoked_at) < datetime(?)`,
      params: [cutoff(settings.revokedTokenDays)],
    },
    {
      key: 'telegramLinkCodes',
      sql: 'DELETE FROM telegram_link_codes WHERE datetime(expires_at) < datetime(?)',
      params: [nowIso],
    },
    {
      key: 'workerMetrics',
      sql: 'DELETE FROM worker_metrics WHERE metric_date < ?',
      params: [cutoff(settings.workerMetricDays).slice(0, 10)],
    },
    {
      key: 'privacyEvents',
      sql: 'DELETE FROM privacy_events WHERE datetime(created_at) < datetime(?)',
      params: [cutoff(settings.privacyEventDays)],
    },
  ];
}

/** 执行一轮保留清理并写入审计事件。 */
export async function cleanupExpiredData(
  db: D1Database,
  now: Date,
  env: Partial<Env> = {}
): Promise<RetentionCleanupResult> {
  const statements = buildCleanupStatements(now, env);
  const results = await db.batch(
    statements.map((statement) => db.prepare(statement.sql).bind(...statement.params))
  );

  const deleted: Record<string, number> = {};
  statements.forEach((statement, index) => {
    deleted[statement.key] = results[index]?.meta?.changes ?? 0;
  });
  const total = Object.values(deleted).reduce((sum, value) => sum + value, 0);
  const executedAt = now.toISOString();

  let auditRecorded = true;
  try {
    await run(
      db,
      'INSERT INTO privacy_events (id, event_type, actor_hash, detail, created_at) VALUES (?, ?, ?, ?, ?)',
      [
        privacyEventId(),
        'retention_cleanup',
        null,
        JSON.stringify({ policyVersion: PRIVACY_POLICY_VERSION, deleted, total }),
        executedAt,
      ]
    );
  } catch (err) {
    auditRecorded = false;
    console.error('privacy cleanup audit write failed:', err);
  }

  return {
    executedAt,
    policyVersion: PRIVACY_POLICY_VERSION,
    deleted,
    total,
    auditRecorded,
  };
}
