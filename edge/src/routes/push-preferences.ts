/**
 * 推送偏好路由（M4-06）。
 *
 * 登录态接口：
 *   GET /api/push-preferences  读取当前用户偏好（未保存时返回默认值）
 *   PUT /api/push-preferences  保存当前用户偏好（全量覆盖）
 *
 * 内部接口（X-Internal-Token）：
 *   GET /api/internal/push-preferences?userId=xxx  单个用户（VPS 推送任务使用）
 *   GET /api/internal/push-preferences             全部已保存偏好（批量）
 *
 * D1 为偏好唯一数据源；VPS 定时任务读取失败时回退默认值，不阻塞推送。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, PushPreferenceRow, Variables } from '../types';
import { all, first, run } from '../db';
import { hasInternalToken } from './notifications';
import {
  CHANNEL_KEYS,
  DEFAULT_PUSH_PREFERENCES,
  PushPreferenceValidationError,
  parsePushPreferenceRow,
  pushPreferenceParams,
  validatePushPreferencesInput,
} from '../push-preferences/helpers';

type AppEnv = { Bindings: Env; Variables: Variables };
type AppContext = Context<AppEnv>;

const pushPreferences = new Hono<AppEnv>();

const UPSERT_SQL = `INSERT INTO push_preferences
  (user_id, enabled, time_of_day, timezone, min_score, min_quality_score,
   channel_inapp, channel_bark, channel_telegram, channel_email, updated_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  ON CONFLICT(user_id) DO UPDATE SET
    enabled = excluded.enabled,
    time_of_day = excluded.time_of_day,
    timezone = excluded.timezone,
    min_score = excluded.min_score,
    min_quality_score = excluded.min_quality_score,
    channel_inapp = excluded.channel_inapp,
    channel_bark = excluded.channel_bark,
    channel_telegram = excluded.channel_telegram,
    channel_email = excluded.channel_email,
    updated_at = excluded.updated_at`;

function currentUser(c: AppContext) {
  return c.get('user');
}

function payload(
  preferences: ReturnType<typeof parsePushPreferenceRow> | typeof DEFAULT_PUSH_PREFERENCES,
  isDefault: boolean
) {
  return {
    preferences,
    isDefault,
    availableChannels: [...CHANNEL_KEYS],
  };
}

pushPreferences.get('/', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<PushPreferenceRow>(
    c.env.DB,
    `SELECT * FROM push_preferences WHERE user_id = ?`,
    [user.id]
  );
  return c.json(
    payload(row ? parsePushPreferenceRow(row) : DEFAULT_PUSH_PREFERENCES, !row)
  );
});

pushPreferences.put('/', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const input =
    body && typeof body === 'object' && 'preferences' in body
      ? (body as { preferences: unknown }).preferences
      : body;

  let preferences;
  try {
    preferences = validatePushPreferencesInput(input);
  } catch (err) {
    if (err instanceof PushPreferenceValidationError) {
      return c.json({ error: 'invalid_preferences', message: err.message }, 400);
    }
    throw err;
  }

  const updatedAt = new Date().toISOString();
  await run(
    c.env.DB,
    UPSERT_SQL,
    pushPreferenceParams(user.id, preferences, updatedAt)
  );
  return c.json(payload({ ...preferences, updatedAt }, false));
});

export default pushPreferences;

export const internalPushPreferences = new Hono<AppEnv>();

internalPushPreferences.get('/', async (c) => {
  if (!hasInternalToken(c)) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  const userId = (c.req.query('userId') || '').trim();
  if (userId) {
    const row = await first<PushPreferenceRow>(
      c.env.DB,
      `SELECT * FROM push_preferences WHERE user_id = ?`,
      [userId]
    );
    return c.json({
      userId,
      preferences: row
        ? parsePushPreferenceRow(row)
        : DEFAULT_PUSH_PREFERENCES,
      isDefault: !row,
    });
  }

  const rows = await all<PushPreferenceRow>(
    c.env.DB,
    `SELECT * FROM push_preferences ORDER BY updated_at DESC LIMIT 1000`
  );
  return c.json({
    items: rows.map((row) => ({
      userId: row.user_id,
      preferences: parsePushPreferenceRow(row),
    })),
  });
});
