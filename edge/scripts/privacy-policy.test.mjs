import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildPrivacyPolicy,
  isAccountDeletionConfirmed,
  PRIVACY_POLICY_VERSION,
  retentionCutoff,
  retentionDays,
  retentionSettings,
  RETENTION_DEFAULTS,
  RETENTION_POLICIES,
} from '../src/privacy/policy.ts';
import {
  buildPersonalDataExport,
  personalDataFileName,
  PERSONAL_DATA_SCHEMA_VERSION,
} from '../src/privacy/export.ts';
import { buildCleanupStatements } from '../src/privacy/cleanup.ts';

const NOW = new Date('2026-10-22T12:00:00.000Z');

test('策略文档：版本、保留期与数据主体权利完整', () => {
  const policy = buildPrivacyPolicy();
  assert.equal(policy.version, PRIVACY_POLICY_VERSION);
  assert.ok(policy.retention.length >= 15);
  assert.ok(policy.retention.some((item) => item.key === 'account'));
  assert.ok(policy.retention.some((item) => item.key === 'recommendations'));
  assert.deepEqual(
    policy.rights.map((right) => right.key),
    ['access', 'erasure', 'rectification', 'restriction']
  );
  assert.ok(policy.outbound.some((item) => item.target.includes('github.com')));
  assert.equal(JSON.stringify(policy).includes('token_hash'), false);
  assert.equal(JSON.stringify(policy).includes('api_key'), false);
});

test('保留期环境变量：非法 / 负数回退默认值，合法值生效并封顶 3650', () => {
  assert.equal(retentionDays(undefined, 90), 90);
  assert.equal(retentionDays('', 90), 90);
  assert.equal(retentionDays('abc', 90), 90);
  assert.equal(retentionDays('-1', 90), 90);
  assert.equal(retentionDays('0', 90), 0);
  assert.equal(retentionDays('45', 90), 45);
  assert.equal(retentionDays('999999', 90), 3650);
});

test('retentionSettings：默认值与 PRIVACY_* 覆盖', () => {
  const defaults = retentionSettings({});
  assert.equal(defaults.recommendationDays, RETENTION_DEFAULTS.recommendationDays);
  assert.equal(defaults.notificationReadDays, RETENTION_DEFAULTS.notificationReadDays);
  assert.equal(defaults.privacyEventDays, RETENTION_DEFAULTS.privacyEventDays);

  const custom = retentionSettings({
    PRIVACY_RECOMMENDATION_RETENTION_DAYS: '30',
    PRIVACY_NOTIFICATION_UNREAD_RETENTION_DAYS: '90',
    PRIVACY_EVENT_RETENTION_DAYS: '730',
  });
  assert.equal(custom.recommendationDays, 30);
  assert.equal(custom.notificationUnreadDays, 90);
  assert.equal(custom.privacyEventDays, 730);
});

test('retentionCutoff：按 UTC 自然日回推', () => {
  assert.equal(retentionCutoff(NOW, 0), '2026-10-22T12:00:00.000Z');
  assert.equal(retentionCutoff(NOW, 1), '2026-10-21T12:00:00.000Z');
  assert.equal(retentionCutoff(NOW, 90), '2026-07-24T12:00:00.000Z');
});

test('账号删除确认：必须精确输入 DELETE', () => {
  assert.equal(isAccountDeletionConfirmed({ confirmation: 'DELETE' }), true);
  assert.equal(isAccountDeletionConfirmed({ confirmation: 'delete' }), false);
  assert.equal(isAccountDeletionConfirmed({ confirmation: ' DELETE ' }), false);
  assert.equal(isAccountDeletionConfirmed({}), false);
  assert.equal(isAccountDeletionConfirmed(null), false);
  assert.equal(isAccountDeletionConfirmed('DELETE'), false);
});

test('清理语句：覆盖主要个人数据表并带保留期参数', () => {
  const statements = buildCleanupStatements(NOW, {});
  const keys = statements.map((item) => item.key);
  for (const key of [
    'sessions',
    'loginAttempts',
    'securityEvents',
    'recommendationsUnsaved',
    'recommendationsSaved',
    'notificationsRead',
    'repoUpdatesUnread',
    'recommendationFeedback',
    'duplicateDismissals',
    'tagSuggestionsResolved',
    'categorySuggestionsPending',
    'curatedReports',
    'extensionTokens',
    'telegramLinkCodes',
    'workerMetrics',
    'privacyEvents',
  ]) {
    assert.ok(keys.includes(key), `missing cleanup key: ${key}`);
  }
  const recommendation = statements.find((item) => item.key === 'recommendationsUnsaved');
  assert.match(recommendation.sql, /status != 'saved'/);
  assert.equal(recommendation.params[0], retentionCutoff(NOW, RETENTION_DEFAULTS.recommendationDays));
});

test('个人数据导出：结构、计数与脱敏字段', () => {
  const user = {
    id: 'u-1',
    login: 'alice',
    name: 'Alice',
    email: 'alice@example.com',
    avatar_url: 'https://avatars.example.com/a.png',
    created_at: '2026-01-01 00:00:00',
  };
  const data = {
    repositories: [{ id: 'owner/repo' }],
    categories: [{ id: 'c1', name: 'AI' }],
    tags: [{ id: 1, name: 'llm' }],
    recommendations: [{ id: 'r1' }, { id: 'r2' }],
    notifications: [],
    repoUpdates: [],
    pushPreferences: { user_id: 'u-1', enabled: 1 },
    tagSuggestions: [],
    categorySuggestions: [],
    curatedReports: [],
    recommendationFeedback: [],
    duplicateDismissals: [],
    extensionTokens: [{ id: 'tok_1', hint: 'ofx_…a1b2' }],
    telegramLink: { chat_id: '123', username: 'alice' },
    sessions: [{ created_at: '2026-10-01', expires_at: '2026-10-31' }],
    privacyEvents: [{ id: 'pe_1', event_type: 'export' }],
  };
  const document = buildPersonalDataExport(user, data, '2026-10-22T12:00:00.000Z');
  assert.equal(document.schemaVersion, PERSONAL_DATA_SCHEMA_VERSION);
  assert.equal(document.policyVersion, PRIVACY_POLICY_VERSION);
  assert.equal(document.subject.login, 'alice');
  assert.equal(document.counts.repositories, 1);
  assert.equal(document.counts.recommendations, 2);
  assert.equal(document.counts.extensionTokens, 1);
  assert.equal(document.counts.pushPreferences, 1);
  assert.equal(JSON.stringify(document).includes('token_hash'), false);
  assert.equal(JSON.stringify(document).includes('ofx_'), true);
});

test('导出文件名：UTC 日期', () => {
  assert.equal(
    personalDataFileName('2026-10-22T23:59:59.000Z'),
    'openfactory-personal-data-2026-10-22.json'
  );
});

test('保留策略 key 唯一且保留期文案非空', () => {
  const keys = RETENTION_POLICIES.map((item) => item.key);
  assert.equal(new Set(keys).size, keys.length);
  for (const policy of RETENTION_POLICIES) {
    assert.ok(policy.category.length > 0);
    assert.ok(policy.purpose.length > 0);
    assert.ok(policy.retentionLabel.length > 0);
  }
});
