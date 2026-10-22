import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_PUSH_PREFERENCES,
  PushPreferenceValidationError,
  describePushPreferences,
  enabledChannelLabels,
  normalizePushPreferences,
  normalizeTimeOfDay,
  parsePushPreferenceRow,
  pushPreferenceParams,
  validatePushPreferencesInput,
} from '../src/push-preferences/helpers.ts';

test('normalizeTimeOfDay 接受 HH:MM 并补零', () => {
  assert.equal(normalizeTimeOfDay('9:05'), '09:05');
  assert.equal(normalizeTimeOfDay('09:05'), '09:05');
  assert.equal(normalizeTimeOfDay('23:59'), '23:59');
  assert.equal(normalizeTimeOfDay('24:00'), '09:00');
  assert.equal(normalizeTimeOfDay('9:5'), '09:00');
  assert.equal(normalizeTimeOfDay(undefined), '09:00');
});

test('normalizePushPreferences 对 D1 行做容错解析', () => {
  const prefs = normalizePushPreferences({
    enabled: 0,
    time_of_day: '8:30',
    timezone: 'UTC',
    min_score: 1.5,
    min_quality_score: -1,
    channels: { inapp: false, bark: true, telegram: 0, email: 1 },
    updated_at: '2026-10-22T08:00:00.000Z',
  });
  assert.equal(prefs.enabled, false);
  assert.equal(prefs.timeOfDay, '08:30');
  assert.equal(prefs.timezone, 'UTC');
  assert.equal(prefs.minScore, 1);
  assert.equal(prefs.minQualityScore, 0);
  assert.deepEqual(prefs.channels, {
    inapp: false,
    bark: true,
    telegram: false,
    email: true,
  });
  assert.equal(prefs.updatedAt, '2026-10-22T08:00:00.000Z');
});

test('validatePushPreferencesInput 拒绝非法时间 / 阈值 / 时区', () => {
  assert.throws(
    () => validatePushPreferencesInput({ timeOfDay: '25:00' }),
    (err) =>
      err instanceof PushPreferenceValidationError &&
      /HH:MM/.test(err.message)
  );
  assert.throws(
    () => validatePushPreferencesInput({ minScore: 2 }),
    (err) => err instanceof PushPreferenceValidationError && /0~1/.test(err.message)
  );
  assert.throws(
    () => validatePushPreferencesInput({ timezone: 'Mars/Olympus' }),
    (err) => err instanceof PushPreferenceValidationError && /IANA/.test(err.message)
  );
  assert.throws(
    () => validatePushPreferencesInput({ channels: { bark: 'yes' } }),
    (err) => err instanceof PushPreferenceValidationError && /布尔/.test(err.message)
  );
});

test('validatePushPreferencesInput 返回完整偏好', () => {
  const prefs = validatePushPreferencesInput({
    enabled: true,
    timeOfDay: '20:30',
    timezone: 'Asia/Tokyo',
    minScore: 0.4,
    minQualityScore: 0.6,
    channels: { inapp: true, bark: true, telegram: false, email: false },
  });
  assert.equal(prefs.timeOfDay, '20:30');
  assert.equal(prefs.timezone, 'Asia/Tokyo');
  assert.equal(prefs.minScore, 0.4);
  assert.equal(prefs.minQualityScore, 0.6);
  assert.equal(prefs.channels.bark, true);
});

test('parsePushPreferenceRow 转换 0/1 通道开关', () => {
  const prefs = parsePushPreferenceRow({
    user_id: 'u1',
    enabled: 1,
    time_of_day: '09:00',
    timezone: 'Asia/Shanghai',
    min_score: 0.35,
    min_quality_score: 0.55,
    channel_inapp: 1,
    channel_bark: 0,
    channel_telegram: 1,
    channel_email: 0,
    updated_at: '2026-10-22T08:00:00.000Z',
  });
  assert.deepEqual(prefs.channels, {
    inapp: true,
    bark: false,
    telegram: true,
    email: false,
  });
});

test('enabledChannelLabels / describePushPreferences 生成摘要', () => {
  const prefs = {
    ...DEFAULT_PUSH_PREFERENCES,
    channels: { inapp: true, bark: true, telegram: false, email: false },
  };
  assert.deepEqual(enabledChannelLabels(prefs), ['站内通知', 'Bark']);
  assert.match(describePushPreferences(prefs), /每天 09:00 · Asia\/Shanghai · 站内通知 \/ Bark/);
});

test('pushPreferenceParams 输出与 D1 列顺序一致', () => {
  const params = pushPreferenceParams(
    'u1',
    {
      ...DEFAULT_PUSH_PREFERENCES,
      channels: { inapp: true, bark: true, telegram: false, email: false },
    },
    '2026-10-22T08:00:00.000Z'
  );
  assert.equal(params.length, 11);
  assert.equal(params[0], 'u1');
  assert.equal(params[1], 1);
  assert.equal(params[2], '09:00');
  assert.equal(params[7], 1); // channel_bark
  assert.equal(params[10], '2026-10-22T08:00:00.000Z');
});
