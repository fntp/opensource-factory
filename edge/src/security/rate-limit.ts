/**
 * Edge API 限流（M5-05）。
 *
 * 策略：D1 固定窗口计数。
 * - 已登录用户按 user id 计数，匿名请求按 IP 计数；
 * - 只保存 sha-256(scope:identity)，不落明文 IP；
 * - auth / write / read 三类桶分别限额；
 * - 内部接口（/api/internal/*）由 X-Internal-Token 保护，不做 IP 限流，避免批量任务被误伤；
 * - Telegram webhook 由 secret token 鉴权，且 Telegram 出口 IP 共享，不做 IP 限流。
 *
 * D1 不可用时 fail-open（放行并记录日志），优先保证业务可用性。
 */
import { first } from '../db.ts';
import { sha256Hex } from './crypto.ts';

export type RateLimitScope = 'auth' | 'write' | 'read';

export interface RateLimitEnv {
  RATE_LIMIT_ENABLED?: string;
  RATE_LIMIT_READ_PER_MINUTE?: string;
  RATE_LIMIT_WRITE_PER_MINUTE?: string;
  RATE_LIMIT_AUTH_PER_MINUTE?: string;
}

export interface RateLimitSettings {
  enabled: boolean;
  readPerMinute: number;
  writePerMinute: number;
  authPerMinute: number;
  windowSeconds: number;
}

export interface RateLimitPolicy {
  scope: RateLimitScope;
  limit: number;
  windowSeconds: number;
}

export interface RateLimitDecision {
  allowed: boolean;
  limit: number;
  remaining: number;
  resetAt: number;
  retryAfterSeconds: number;
}

const DEFAULT_READ_PER_MINUTE = 300;
const DEFAULT_WRITE_PER_MINUTE = 60;
const DEFAULT_AUTH_PER_MINUTE = 10;
const MINUTE = 60;

/** 读取正整数配置，越界时回退默认值。 */
export function positiveInt(value: string | undefined, fallback: number, min = 1, max = 1_000_000): number {
  const parsed = Number.parseInt((value ?? '').trim(), 10);
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) return fallback;
  return parsed;
}

/** 限流开关：默认开启，显式 false / 0 / off 才关闭。 */
export function rateLimitEnabled(value: string | undefined): boolean {
  const normalized = (value ?? '').trim().toLowerCase();
  return !['0', 'false', 'off', 'no'].includes(normalized);
}

export function rateLimitSettings(env: RateLimitEnv): RateLimitSettings {
  return {
    enabled: rateLimitEnabled(env.RATE_LIMIT_ENABLED),
    readPerMinute: positiveInt(env.RATE_LIMIT_READ_PER_MINUTE, DEFAULT_READ_PER_MINUTE),
    writePerMinute: positiveInt(env.RATE_LIMIT_WRITE_PER_MINUTE, DEFAULT_WRITE_PER_MINUTE),
    authPerMinute: positiveInt(env.RATE_LIMIT_AUTH_PER_MINUTE, DEFAULT_AUTH_PER_MINUTE),
    windowSeconds: MINUTE,
  };
}

/** 按方法 + 路径选择限流策略；内部接口与健康检查不参与。 */
export function policyFor(
  method: string,
  pathname: string,
  env: RateLimitEnv
): RateLimitPolicy | null {
  const settings = rateLimitSettings(env);
  if (!settings.enabled) return null;
  if (!pathname.startsWith('/api/')) return null;
  if (pathname.startsWith('/api/internal/')) return null;
  if (pathname === '/api/telegram/webhook') return null;

  if (pathname.startsWith('/api/auth/')) {
    return { scope: 'auth', limit: settings.authPerMinute, windowSeconds: settings.windowSeconds };
  }
  const upper = method.toUpperCase();
  if (upper === 'GET' || upper === 'HEAD' || upper === 'OPTIONS') {
    return { scope: 'read', limit: settings.readPerMinute, windowSeconds: settings.windowSeconds };
  }
  return { scope: 'write', limit: settings.writePerMinute, windowSeconds: settings.windowSeconds };
}

/** 固定窗口起点（秒）。 */
export function windowStartSeconds(nowMs: number, windowSeconds: number): number {
  const safeWindow = Math.max(1, Math.floor(windowSeconds));
  return Math.floor(nowMs / 1000 / safeWindow) * safeWindow;
}

/** 距离窗口重置的秒数（至少 1 秒）。 */
export function retryAfterSeconds(nowMs: number, windowStart: number, windowSeconds: number): number {
  const resetMs = (windowStart + Math.max(1, windowSeconds)) * 1000;
  return Math.max(1, Math.ceil((resetMs - nowMs) / 1000));
}

/** 从请求头解析客户端 IP：Cloudflare 优先，其次 X-Forwarded-For 第一跳。 */
export function clientIpFromHeaders(
  cfConnectingIp: string | undefined | null,
  forwardedFor: string | undefined | null
): string {
  const cf = (cfConnectingIp ?? '').trim();
  if (cf) return cf;
  const forwarded = (forwardedFor ?? '').split(',')[0]?.trim() ?? '';
  return forwarded || 'unknown';
}

/** 计算限流身份哈希（用户优先，其次 IP）。 */
export async function rateLimitIdentity(
  scope: RateLimitScope,
  userId: string | null | undefined,
  ip: string
): Promise<string> {
  const identity = userId ? `user:${userId}` : `ip:${ip}`;
  return sha256Hex(`${scope}:${identity}`);
}

/** 组装 D1 主键：scope + 身份哈希。 */
export function rateLimitBucket(scope: RateLimitScope, identityHash: string): string {
  return `${scope}:${identityHash}`;
}

/**
 * 原子累加固定窗口计数并返回判定。
 * 单条 UPSERT + RETURNING 保证并发下计数不丢。
 */
export async function consumeRateLimit(
  db: D1Database,
  bucket: string,
  limit: number,
  windowSeconds: number,
  nowMs: number
): Promise<RateLimitDecision> {
  const start = windowStartSeconds(nowMs, windowSeconds);
  const expiresAt = new Date((start + Math.max(1, windowSeconds)) * 1000).toISOString();
  const row = await first<{ count: number }>(
    db,
    `INSERT INTO rate_limit_counters (bucket, window_start, count, expires_at)
     VALUES (?, ?, 1, ?)
     ON CONFLICT(bucket) DO UPDATE SET
       count = CASE WHEN rate_limit_counters.window_start = excluded.window_start
                    THEN rate_limit_counters.count + 1 ELSE 1 END,
       window_start = excluded.window_start,
       expires_at = excluded.expires_at
     RETURNING count`,
    [bucket, start, expiresAt]
  );
  const count = Math.max(1, Number(row?.count ?? 1));
  const retry = retryAfterSeconds(nowMs, start, windowSeconds);
  return {
    allowed: count <= limit,
    limit,
    remaining: Math.max(0, limit - count),
    resetAt: (start + Math.max(1, windowSeconds)) * 1000,
    retryAfterSeconds: retry,
  };
}

/** 清理过期的限流计数、登录审计与安全事件（内部接口 / 低频维护）。 */
export async function cleanupSecurityData(
  db: D1Database,
  nowMs: number
): Promise<{ rateLimitCounters: number; loginAttempts: number; securityEvents: number }> {
  const nowIso = new Date(nowMs).toISOString();
  const attemptCutoff = new Date(nowMs - 30 * 24 * 3600 * 1000).toISOString();
  const eventCutoff = new Date(nowMs - 90 * 24 * 3600 * 1000).toISOString();
  const counters = await db
    .prepare('DELETE FROM rate_limit_counters WHERE expires_at < ?')
    .bind(nowIso)
    .run();
  const attempts = await db
    .prepare('DELETE FROM login_attempts WHERE created_at < ?')
    .bind(attemptCutoff)
    .run();
  const events = await db
    .prepare('DELETE FROM security_events WHERE created_at < ?')
    .bind(eventCutoff)
    .run();
  return {
    rateLimitCounters: counters.meta?.changes ?? 0,
    loginAttempts: attempts.meta?.changes ?? 0,
    securityEvents: events.meta?.changes ?? 0,
  };
}
