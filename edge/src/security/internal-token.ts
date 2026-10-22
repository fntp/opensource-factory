/**
 * 内部令牌校验（M5-05 安全加固）。
 *
 * 支持双令牌轮换：
 * - `INTERNAL_TOKEN`：当前令牌；
 * - `INTERNAL_TOKEN_PREVIOUS`：上一枚令牌（轮换过渡期仍接受，验证完成后删除）。
 *
 * 比较前先做 sha-256，再对定长摘要做常量时间比较，避免长度 / 前缀时序侧信道。
 */
import type { Context } from 'hono';
import type { Env, Variables } from '../types';
import { sha256Hex, timingSafeEqualHex } from './crypto.ts';

export type InternalTokenVerdict = 'ok' | 'not_configured' | 'unauthorized';

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;

function normalize(value: string | undefined | null): string {
  return (value ?? '').trim();
}

/** 校验请求头中的 X-Internal-Token；未配置任何令牌时返回 not_configured。 */
export async function verifyInternalToken(
  env: Env,
  provided: string | null | undefined
): Promise<InternalTokenVerdict> {
  const candidates = [normalize(env.INTERNAL_TOKEN), normalize(env.INTERNAL_TOKEN_PREVIOUS)].filter(
    Boolean
  );
  if (candidates.length === 0) return 'not_configured';
  const supplied = normalize(provided);
  if (!supplied) return 'unauthorized';
  const suppliedHash = await sha256Hex(supplied);
  for (const candidate of candidates) {
    if (timingSafeEqualHex(suppliedHash, await sha256Hex(candidate))) return 'ok';
  }
  return 'unauthorized';
}

/** 严格模式：未配置令牌 → 503；不匹配 → 401；通过 → null。 */
export async function requireInternalToken(c: AppContext): Promise<Response | null> {
  const verdict = await verifyInternalToken(c.env, c.req.header('X-Internal-Token'));
  if (verdict === 'not_configured') {
    return c.json({ error: 'internal_token_not_configured' }, 503);
  }
  if (verdict === 'unauthorized') {
    return c.json({ error: 'unauthorized' }, 401);
  }
  return null;
}

/** 可选模式：未配置令牌时放行（本地开发），配置后严格校验。 */
export async function checkOptionalInternalToken(c: AppContext): Promise<Response | null> {
  const verdict = await verifyInternalToken(c.env, c.req.header('X-Internal-Token'));
  if (verdict === 'unauthorized') {
    return c.json({ error: 'unauthorized' }, 401);
  }
  return null;
}

/** 令牌状态（只输出指纹，不输出明文），用于内部安全状态接口。 */
export async function internalTokenStatus(env: Env): Promise<{
  configured: boolean;
  previousConfigured: boolean;
  rotationPending: boolean;
  currentFingerprint: string;
  previousFingerprint: string;
}> {
  const current = normalize(env.INTERNAL_TOKEN);
  const previous = normalize(env.INTERNAL_TOKEN_PREVIOUS);
  return {
    configured: Boolean(current),
    previousConfigured: Boolean(previous),
    rotationPending: Boolean(current && previous),
    currentFingerprint: current ? (await sha256Hex(current)).slice(0, 12) : '',
    previousFingerprint: previous ? (await sha256Hex(previous)).slice(0, 12) : '',
  };
}
