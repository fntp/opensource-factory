/**
 * 登录防护（M5-05）。
 *
 * - 同一 IP 在 LOGIN_FAILURE_WINDOW_SECONDS 内失败达到 LOGIN_MAX_FAILURES 次后锁定；
 * - 锁定时长 LOGIN_LOCKOUT_SECONDS，从首次触发锁定开始计算；
 * - 成功登录清零失败计数与锁定事件；
 * - 只保存 sha-256(login:ip)，不落明文 IP；
 * - D1 异常时 fail-open，不阻塞正常登录。
 */
import { first, run } from '../db.ts';
import { sha256Hex } from './crypto.ts';

export interface LoginGuardEnv {
  LOGIN_MAX_FAILURES?: string;
  LOGIN_FAILURE_WINDOW_SECONDS?: string;
  LOGIN_LOCKOUT_SECONDS?: string;
}

export interface LoginGuardSettings {
  maxFailures: number;
  failureWindowSeconds: number;
  lockoutSeconds: number;
}

export interface LoginLockState {
  locked: boolean;
  failures: number;
  retryAfterSeconds: number;
  unavailable: boolean;
}

const DEFAULT_MAX_FAILURES = 10;
const DEFAULT_FAILURE_WINDOW_SECONDS = 900;
const DEFAULT_LOCKOUT_SECONDS = 900;

function positiveInt(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt((value ?? '').trim(), 10);
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) return fallback;
  return parsed;
}

export function loginGuardSettings(env: LoginGuardEnv): LoginGuardSettings {
  return {
    maxFailures: positiveInt(env.LOGIN_MAX_FAILURES, DEFAULT_MAX_FAILURES, 1, 1000),
    failureWindowSeconds: positiveInt(
      env.LOGIN_FAILURE_WINDOW_SECONDS,
      DEFAULT_FAILURE_WINDOW_SECONDS,
      60,
      86_400
    ),
    lockoutSeconds: positiveInt(env.LOGIN_LOCKOUT_SECONDS, DEFAULT_LOCKOUT_SECONDS, 60, 86_400),
  };
}

/** 登录身份哈希：与限流桶隔离，避免同 IP 的两个用途互相干扰。 */
export async function loginIdentityHash(ip: string): Promise<string> {
  return sha256Hex(`login:${ip}`);
}

/** 记录安全事件（best-effort，不影响主流程）。 */
export async function recordSecurityEvent(
  db: D1Database,
  eventType: string,
  actorHash: string,
  detail: string,
  nowIso: string
): Promise<void> {
  try {
    await run(
      db,
      'INSERT INTO security_events (event_type, actor_hash, detail, created_at) VALUES (?, ?, ?, ?)',
      [eventType, actorHash, detail, nowIso]
    );
  } catch (err) {
    console.error('security event unavailable:', err);
  }
}

/** 统计窗口内失败次数。 */
export async function countRecentFailures(
  db: D1Database,
  ipHash: string,
  sinceIso: string
): Promise<number> {
  const row = await first<{ n: number }>(
    db,
    `SELECT COUNT(*) AS n FROM login_attempts
     WHERE ip_hash = ? AND outcome = 'failure' AND created_at >= ?`,
    [ipHash, sinceIso]
  );
  return Number(row?.n ?? 0);
}

/**
 * 登录锁定状态。
 * 失败次数达到阈值后，再查最近的 login_locked 事件计算剩余锁定时间。
 */
export async function loginLockState(
  db: D1Database,
  ipHash: string,
  settings: LoginGuardSettings,
  nowMs: number
): Promise<LoginLockState> {
  try {
    const sinceIso = new Date(nowMs - settings.failureWindowSeconds * 1000).toISOString();
    const failures = await countRecentFailures(db, ipHash, sinceIso);
    if (failures < settings.maxFailures) {
      return { locked: false, failures, retryAfterSeconds: 0, unavailable: false };
    }

    const lockedAt = await first<{ created_at: string }>(
      db,
      `SELECT created_at FROM security_events
       WHERE event_type = 'login_locked' AND actor_hash = ?
       ORDER BY id DESC LIMIT 1`,
      [ipHash]
    );
    const nowIso = new Date(nowMs).toISOString();
    if (lockedAt) {
      const elapsed = nowMs - new Date(lockedAt.created_at).getTime();
      const remaining = settings.lockoutSeconds * 1000 - elapsed;
      if (remaining > 0) {
        return {
          locked: true,
          failures,
          retryAfterSeconds: Math.max(1, Math.ceil(remaining / 1000)),
          unavailable: false,
        };
      }
    }

    // 首次达到阈值或上一次锁定已过期：登记一次新的锁定事件
    await recordSecurityEvent(db, 'login_locked', ipHash, `failures=${failures}`, nowIso);
    return {
      locked: true,
      failures,
      retryAfterSeconds: settings.lockoutSeconds,
      unavailable: false,
    };
  } catch (err) {
    console.error('login guard unavailable:', err);
    return { locked: false, failures: 0, retryAfterSeconds: 0, unavailable: true };
  }
}

/** 记录一次登录失败；达到阈值时写入 login_locked 事件。 */
export async function recordLoginFailure(
  db: D1Database,
  ipHash: string,
  reason: string,
  settings: LoginGuardSettings,
  nowMs: number
): Promise<number> {
  const nowIso = new Date(nowMs).toISOString();
  try {
    await run(
      db,
      `INSERT INTO login_attempts (ip_hash, outcome, reason, created_at)
       VALUES (?, 'failure', ?, ?)`,
      [ipHash, reason.slice(0, 64), nowIso]
    );
    const sinceIso = new Date(nowMs - settings.failureWindowSeconds * 1000).toISOString();
    const failures = await countRecentFailures(db, ipHash, sinceIso);
    if (failures === settings.maxFailures) {
      await recordSecurityEvent(db, 'login_locked', ipHash, `failures=${failures}`, nowIso);
    }
    return failures;
  } catch (err) {
    console.error('login failure record unavailable:', err);
    return 0;
  }
}

/** 记录一次成功登录（审计用）。 */
export async function recordLoginSuccess(
  db: D1Database,
  ipHash: string,
  nowMs: number
): Promise<void> {
  try {
    await run(
      db,
      `INSERT INTO login_attempts (ip_hash, outcome, reason, created_at)
       VALUES (?, 'success', 'ok', ?)`,
      [ipHash, new Date(nowMs).toISOString()]
    );
  } catch (err) {
    console.error('login success record unavailable:', err);
  }
}

/** 成功登录后清除失败计数与锁定事件。 */
export async function clearLoginFailures(db: D1Database, ipHash: string): Promise<void> {
  try {
    await run(db, `DELETE FROM login_attempts WHERE ip_hash = ? AND outcome = 'failure'`, [ipHash]);
    await run(
      db,
      `DELETE FROM security_events WHERE event_type = 'login_locked' AND actor_hash = ?`,
      [ipHash]
    );
  } catch (err) {
    console.error('login failure cleanup unavailable:', err);
  }
}
