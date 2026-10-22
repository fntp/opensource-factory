/**
 * 数据保留与隐私策略（REQ-202610-0983 / M9-06）。
 *
 * 本文件是保留策略的单一事实来源：
 * - `RETENTION_POLICIES` 面向用户展示（GET /api/privacy/policy 与 admin 隐私页）；
 * - `retentionSettings()` 把可配置项归一为清理任务使用的天数；
 * - 所有清理 SQL 的截止时间都由这里的天数推导，避免文档与代码漂移。
 */
import type { Env } from '../types';

/** 策略版本：保留期或处理目的变化时递增（日期形式）。 */
export const PRIVACY_POLICY_VERSION = '2026-10-22';
export const PRIVACY_POLICY_UPDATED_AT = '2026-10-22T00:00:00.000Z';

export type RetentionUnit = 'days' | 'until_deleted';

export interface RetentionPolicy {
  /** 稳定 key，供前端与清理任务对齐 */
  key: string;
  /** 数据类别（用户可读） */
  category: string;
  /** 涉及的表 / 位置 */
  storage: string;
  /** 处理目的 */
  purpose: string;
  /** 保留天数；null 表示保留至账号删除 */
  retentionDays: number | null;
  /** 用户可读的保留期文案 */
  retentionLabel: string;
  /** 到期动作 */
  action: string;
  /** 补充说明（可选） */
  note?: string;
}

/**
 * 默认保留期（天）。均可通过同名环境变量覆盖，见 `retentionSettings`。
 * 0 表示「到期即清理」，仅用于可再生成的短期数据。
 */
export const RETENTION_DEFAULTS = {
  sessionGraceDays: 0,
  loginAttemptDays: 30,
  securityEventDays: 90,
  recommendationDays: 90,
  savedRecommendationDays: 365,
  notificationReadDays: 180,
  notificationUnreadDays: 365,
  repoUpdateReadDays: 180,
  repoUpdateUnreadDays: 365,
  feedbackDays: 365,
  dismissalDays: 365,
  suggestionResolvedDays: 90,
  suggestionPendingDays: 180,
  reportDays: 365,
  revokedTokenDays: 30,
  workerMetricDays: 90,
  privacyEventDays: 365,
} as const;

export const RETENTION_POLICIES: RetentionPolicy[] = [
  {
    key: 'account',
    category: '账号资料',
    storage: 'D1 · users',
    purpose: 'GitHub OAuth 登录、账号展示与数据归属',
    retentionDays: null,
    retentionLabel: '保留至账号删除',
    action: '账号删除时立即清除',
    note: '仅包含 GitHub 公开资料与邮箱，不采集密码、支付信息或精确位置。',
  },
  {
    key: 'sessions',
    category: '登录会话',
    storage: 'D1 · sessions（仅存 token 的 SHA-256）',
    purpose: '维持登录态',
    retentionDays: RETENTION_DEFAULTS.sessionGraceDays,
    retentionLabel: '会话过期即清理（最长 30 天）',
    action: '过期后删除',
    note: 'Cookie 为 HttpOnly + SameSite=Lax，HTTPS 下加 Secure。',
  },
  {
    key: 'login_attempts',
    category: '登录审计',
    storage: 'D1 · login_attempts（仅存 IP 哈希）',
    purpose: '防暴力破解与登录防护',
    retentionDays: RETENTION_DEFAULTS.loginAttemptDays,
    retentionLabel: '30 天',
    action: '到期删除',
  },
  {
    key: 'security_events',
    category: '安全事件',
    storage: 'D1 · security_events（仅存身份哈希）',
    purpose: '限流、锁定与内部令牌使用审计',
    retentionDays: RETENTION_DEFAULTS.securityEventDays,
    retentionLabel: '90 天',
    action: '到期删除',
    note: '不记录令牌明文、Cookie 或原始 IP。',
  },
  {
    key: 'recommendations',
    category: '推荐记录',
    storage: 'D1 · recommendations',
    purpose: '生成个性化推荐与效果评估',
    retentionDays: RETENTION_DEFAULTS.recommendationDays,
    retentionLabel: '未收藏 90 天 / 已收藏 365 天',
    action: '到期删除',
    note: '已收藏项目仍保留在「我的仓库」中，不受推荐记录清理影响。',
  },
  {
    key: 'notifications',
    category: '站内通知',
    storage: 'D1 · notifications',
    purpose: '推荐与系统消息提醒',
    retentionDays: RETENTION_DEFAULTS.notificationReadDays,
    retentionLabel: '已读 180 天 / 未读 365 天',
    action: '到期删除',
  },
  {
    key: 'repo_updates',
    category: '项目更新提醒',
    storage: 'D1 · repo_updates',
    purpose: '收藏项目的 Release / 重大变更提醒',
    retentionDays: RETENTION_DEFAULTS.repoUpdateReadDays,
    retentionLabel: '已读 180 天 / 未读 365 天',
    action: '到期删除',
  },
  {
    key: 'recommendation_feedback',
    category: '推荐反馈',
    storage: 'D1 · recommendation_feedback',
    purpose: '改进推荐质量（收藏 / 忽略 / 点击）',
    retentionDays: RETENTION_DEFAULTS.feedbackDays,
    retentionLabel: '365 天',
    action: '到期删除',
  },
  {
    key: 'duplicate_dismissals',
    category: '重复项目忽略记录',
    storage: 'D1 · duplicate_dismissals',
    purpose: '记住用户忽略的重复簇',
    retentionDays: RETENTION_DEFAULTS.dismissalDays,
    retentionLabel: '365 天',
    action: '到期删除',
  },
  {
    key: 'suggestions',
    category: '标签 / 分类建议',
    storage: 'D1 · tag_suggestions / category_suggestions',
    purpose: '自动打标与分类建议',
    retentionDays: RETENTION_DEFAULTS.suggestionPendingDays,
    retentionLabel: '待处理 180 天 / 已处理 90 天',
    action: '到期删除',
  },
  {
    key: 'reports',
    category: '精选报告',
    storage: 'D1 · curated_reports',
    purpose: '周报 / 月报归档与下载',
    retentionDays: RETENTION_DEFAULTS.reportDays,
    retentionLabel: '365 天',
    action: '到期删除',
  },
  {
    key: 'extension_tokens',
    category: '浏览器扩展令牌',
    storage: 'D1 · extension_tokens（仅存 SHA-256 与提示片段）',
    purpose: '浏览器扩展一键收藏鉴权',
    retentionDays: RETENTION_DEFAULTS.revokedTokenDays,
    retentionLabel: '有效期内保留；撤销后 30 天',
    action: '撤销满 30 天删除',
    note: '令牌明文只在创建时返回一次，服务端不保存。',
  },
  {
    key: 'telegram',
    category: 'Telegram 绑定',
    storage: 'D1 · telegram_links / telegram_link_codes',
    purpose: 'Telegram Bot 查询入口',
    retentionDays: null,
    retentionLabel: '保留至解绑 / 账号删除；绑定码 10 分钟',
    action: '解绑或账号删除时清除',
  },
  {
    key: 'push_preferences',
    category: '推送偏好',
    storage: 'D1 · push_preferences',
    purpose: '按用户时区、阈值与通道设置推送',
    retentionDays: null,
    retentionLabel: '保留至账号删除',
    action: '账号删除时清除',
  },
  {
    key: 'worker_metrics',
    category: '运行指标',
    storage: 'D1 · worker_metrics（按日聚合）',
    purpose: '接口性能与容量监控',
    retentionDays: RETENTION_DEFAULTS.workerMetricDays,
    retentionLabel: '90 天',
    action: '到期删除',
    note: '仅聚合计数与耗时，不含请求内容或个人标识。',
  },
  {
    key: 'privacy_events',
    category: '隐私审计',
    storage: 'D1 · privacy_events（仅存用户 id 哈希）',
    purpose: '证明导出 / 删除 / 清理已执行',
    retentionDays: RETENTION_DEFAULTS.privacyEventDays,
    retentionLabel: '365 天',
    action: '到期删除',
  },
];

export interface PrivacyPolicyDocument {
  version: string;
  updatedAt: string;
  controller: string;
  contact: string;
  retention: RetentionPolicy[];
  rights: Array<{ key: string; title: string; description: string; endpoint: string }>;
  outbound: Array<{ target: string; purpose: string; data: string }>;
  notes: string[];
}

/** 面向用户与 admin 的完整策略文档（不含任何密钥 / 内部地址）。 */
export function buildPrivacyPolicy(): PrivacyPolicyDocument {
  return {
    version: PRIVACY_POLICY_VERSION,
    updatedAt: PRIVACY_POLICY_UPDATED_AT,
    controller: 'OpenFactory（个人开源资产管理与智能推荐系统）',
    contact: '通过 GitHub 账号登录后在「设置 → 隐私与数据」发起请求',
    retention: RETENTION_POLICIES.map((policy) => ({ ...policy })),
    rights: [
      {
        key: 'access',
        title: '访问与导出',
        description: '随时下载账号下的全部个人数据（JSON），包含资料、收藏、推荐、通知与偏好。',
        endpoint: 'GET /api/privacy/export',
      },
      {
        key: 'erasure',
        title: '删除账号',
        description: '删除账号及其个人数据；删除不可恢复，共享的热榜与分类配置不受影响。',
        endpoint: 'DELETE /api/privacy/account',
      },
      {
        key: 'rectification',
        title: '更正资料',
        description: 'GitHub 资料在下次登录时自动刷新；其余数据可在对应页面修改或删除。',
        endpoint: 'GET /api/auth/me',
      },
      {
        key: 'restriction',
        title: '限制处理',
        description: '可在通知 / 推送设置中关闭非必要处理，或直接删除账号。',
        endpoint: 'GET /api/push-preferences',
      },
    ],
    outbound: [
      {
        target: 'github.com / api.github.com',
        purpose: 'OAuth 登录、仓库与 Star 同步',
        data: 'OAuth code、公开仓库元数据',
      },
      {
        target: 'localhost:11434（Ollama）',
        purpose: '本地摘要与向量化',
        data: 'README 文本，不出机器',
      },
      {
        target: 'api.deepseek.com（可选降级）',
        purpose: '云端摘要降级',
        data: 'README 文本（不含用户身份）',
      },
      {
        target: 'Cloudflare（D1 / Workers / Pages / Vectorize）',
        purpose: '边缘 API、会话、向量存储',
        data: '上述 D1 数据与向量',
      },
    ],
    notes: [
      '不采集密码、支付信息、通讯录或精确位置；GitHub 邮箱仅用于账号展示。',
      '登录审计只保存 IP 哈希，安全事件只保存身份哈希，均不可反推原始值。',
      '删除账号会同时清除边缘 D1 主数据与 VPS 本地镜像中的用户关联记录；备份中的历史副本按备份保留策略自然过期。',
      '保留期可通过 PRIVACY_* 环境变量调整；调整后以服务端返回的策略版本为准。',
    ],
  };
}

/** 读取非负整数环境变量，非法值回退默认值。 */
export function retentionDays(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return Math.min(parsed, 3650);
}

export interface RetentionSettings {
  sessionGraceDays: number;
  loginAttemptDays: number;
  securityEventDays: number;
  recommendationDays: number;
  savedRecommendationDays: number;
  notificationReadDays: number;
  notificationUnreadDays: number;
  repoUpdateReadDays: number;
  repoUpdateUnreadDays: number;
  feedbackDays: number;
  dismissalDays: number;
  suggestionResolvedDays: number;
  suggestionPendingDays: number;
  reportDays: number;
  revokedTokenDays: number;
  workerMetricDays: number;
  privacyEventDays: number;
}

/** 把 Env 中的 PRIVACY_* 配置归一为清理任务使用的天数。 */
export function retentionSettings(env: Partial<Env> = {}): RetentionSettings {
  return {
    sessionGraceDays: retentionDays(env.PRIVACY_SESSION_GRACE_DAYS, RETENTION_DEFAULTS.sessionGraceDays),
    loginAttemptDays: retentionDays(env.PRIVACY_LOGIN_ATTEMPT_RETENTION_DAYS, RETENTION_DEFAULTS.loginAttemptDays),
    securityEventDays: retentionDays(env.PRIVACY_SECURITY_EVENT_RETENTION_DAYS, RETENTION_DEFAULTS.securityEventDays),
    recommendationDays: retentionDays(env.PRIVACY_RECOMMENDATION_RETENTION_DAYS, RETENTION_DEFAULTS.recommendationDays),
    savedRecommendationDays: retentionDays(env.PRIVACY_SAVED_RECOMMENDATION_RETENTION_DAYS, RETENTION_DEFAULTS.savedRecommendationDays),
    notificationReadDays: retentionDays(env.PRIVACY_NOTIFICATION_READ_RETENTION_DAYS, RETENTION_DEFAULTS.notificationReadDays),
    notificationUnreadDays: retentionDays(env.PRIVACY_NOTIFICATION_UNREAD_RETENTION_DAYS, RETENTION_DEFAULTS.notificationUnreadDays),
    repoUpdateReadDays: retentionDays(env.PRIVACY_REPO_UPDATE_READ_RETENTION_DAYS, RETENTION_DEFAULTS.repoUpdateReadDays),
    repoUpdateUnreadDays: retentionDays(env.PRIVACY_REPO_UPDATE_UNREAD_RETENTION_DAYS, RETENTION_DEFAULTS.repoUpdateUnreadDays),
    feedbackDays: retentionDays(env.PRIVACY_FEEDBACK_RETENTION_DAYS, RETENTION_DEFAULTS.feedbackDays),
    dismissalDays: retentionDays(env.PRIVACY_DISMISSAL_RETENTION_DAYS, RETENTION_DEFAULTS.dismissalDays),
    suggestionResolvedDays: retentionDays(env.PRIVACY_SUGGESTION_RESOLVED_RETENTION_DAYS, RETENTION_DEFAULTS.suggestionResolvedDays),
    suggestionPendingDays: retentionDays(env.PRIVACY_SUGGESTION_PENDING_RETENTION_DAYS, RETENTION_DEFAULTS.suggestionPendingDays),
    reportDays: retentionDays(env.PRIVACY_REPORT_RETENTION_DAYS, RETENTION_DEFAULTS.reportDays),
    revokedTokenDays: retentionDays(env.PRIVACY_REVOKED_TOKEN_RETENTION_DAYS, RETENTION_DEFAULTS.revokedTokenDays),
    workerMetricDays: retentionDays(env.PRIVACY_WORKER_METRIC_RETENTION_DAYS, RETENTION_DEFAULTS.workerMetricDays),
    privacyEventDays: retentionDays(env.PRIVACY_EVENT_RETENTION_DAYS, RETENTION_DEFAULTS.privacyEventDays),
  };
}

/** 计算截止时间（UTC ISO 8601），供 SQL `datetime(column) < datetime(?)` 使用。 */
export function retentionCutoff(now: Date, days: number): string {
  const safeDays = Math.max(0, Math.floor(days));
  return new Date(now.getTime() - safeDays * 24 * 60 * 60 * 1000).toISOString();
}

/** 账号删除二次确认：必须精确输入 DELETE（大小写敏感）。 */
export function isAccountDeletionConfirmed(body: unknown): boolean {
  if (!body || typeof body !== 'object') return false;
  const value = (body as { confirmation?: unknown }).confirmation;
  return value === 'DELETE';
}

/** 生成隐私事件 id（pe_ + 32 位 hex）。 */
export function privacyEventId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return `pe_${[...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')}`;
}
