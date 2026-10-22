/**
 * 个人数据导出（数据主体访问 / 可携带权，REQ-202610-0983 / M9-06）。
 *
 * 纯函数：路由负责按 user_id 查询并传入已脱敏的行，本模块只组装稳定 JSON 结构。
 * 安全约定：
 * - 不输出会话 token 哈希、扩展令牌哈希或任何密钥；
 * - 只输出用户自己的数据；共享分类 / 标签作为工作区配置单独标注；
 * - 输出带 schemaVersion 与 policyVersion，便于后续迁移与审计。
 */
import type { UserRow } from '../types';
import { PRIVACY_POLICY_VERSION } from './policy';

export const PERSONAL_DATA_SCHEMA_VERSION = 'openfactory.personal-data.v1';

export interface PersonalDataSections {
  repositories: unknown[];
  categories: unknown[];
  tags: unknown[];
  recommendations: unknown[];
  notifications: unknown[];
  repoUpdates: unknown[];
  pushPreferences: unknown | null;
  tagSuggestions: unknown[];
  categorySuggestions: unknown[];
  curatedReports: unknown[];
  recommendationFeedback: unknown[];
  duplicateDismissals: unknown[];
  extensionTokens: unknown[];
  telegramLink: unknown | null;
  sessions: unknown[];
  privacyEvents: unknown[];
}

export interface PersonalDataExport {
  schemaVersion: string;
  policyVersion: string;
  generatedAt: string;
  subject: {
    id: string;
    login: string;
    name: string | null;
    email: string | null;
    avatarUrl: string | null;
    createdAt: string;
  };
  counts: Record<string, number>;
  data: PersonalDataSections;
  notes: string[];
}

function countOf(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  return value === null || value === undefined ? 0 : 1;
}

/** 组装个人数据导出文档；字段顺序稳定，便于测试与人工核对。 */
export function buildPersonalDataExport(
  user: UserRow,
  data: PersonalDataSections,
  generatedAt: string
): PersonalDataExport {
  return {
    schemaVersion: PERSONAL_DATA_SCHEMA_VERSION,
    policyVersion: PRIVACY_POLICY_VERSION,
    generatedAt,
    subject: {
      id: user.id,
      login: user.login,
      name: user.name,
      email: user.email,
      avatarUrl: user.avatar_url,
      createdAt: user.created_at,
    },
    counts: {
      repositories: countOf(data.repositories),
      categories: countOf(data.categories),
      tags: countOf(data.tags),
      recommendations: countOf(data.recommendations),
      notifications: countOf(data.notifications),
      repoUpdates: countOf(data.repoUpdates),
      tagSuggestions: countOf(data.tagSuggestions),
      categorySuggestions: countOf(data.categorySuggestions),
      curatedReports: countOf(data.curatedReports),
      recommendationFeedback: countOf(data.recommendationFeedback),
      duplicateDismissals: countOf(data.duplicateDismissals),
      pushPreferences: countOf(data.pushPreferences),
      extensionTokens: countOf(data.extensionTokens),
      sessions: countOf(data.sessions),
      privacyEvents: countOf(data.privacyEvents),
    },
    data,
    notes: [
      '本文件仅包含当前账号的个人数据，由 OpenFactory 在请求时实时生成。',
      '会话与扩展令牌只导出元数据，不包含令牌明文或哈希。',
      '分类与标签为工作区共享配置，不随账号删除；导出仅用于完整备份。',
      '删除账号不可恢复；备份中的历史副本按备份保留策略自然过期。',
    ],
  };
}

/** 导出文件名：openfactory-personal-data-YYYY-MM-DD.json（UTC）。 */
export function personalDataFileName(generatedAt: string): string {
  const date = new Date(generatedAt);
  const safe = Number.isNaN(date.getTime())
    ? generatedAt.slice(0, 10)
    : date.toISOString().slice(0, 10);
  return `openfactory-personal-data-${safe}.json`;
}
