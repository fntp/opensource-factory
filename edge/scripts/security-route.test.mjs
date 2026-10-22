import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clientIpFromHeaders,
  policyFor,
  positiveInt,
  rateLimitBucket,
  rateLimitEnabled,
  rateLimitIdentity,
  retryAfterSeconds,
  windowStartSeconds,
} from '../src/security/rate-limit.ts';
import { internalTokenStatus, verifyInternalToken } from '../src/security/internal-token.ts';
import { timingSafeEqualHex } from '../src/security/crypto.ts';
import { loginGuardSettings } from '../src/security/login-guard.ts';

test('rateLimitEnabled：默认开启，显式关闭值生效', () => {
  assert.equal(rateLimitEnabled(undefined), true);
  assert.equal(rateLimitEnabled('true'), true);
  assert.equal(rateLimitEnabled('false'), false);
  assert.equal(rateLimitEnabled('0'), false);
  assert.equal(rateLimitEnabled('off'), false);
});

test('positiveInt：合法值生效，非法 / 越界回退默认值', () => {
  assert.equal(positiveInt('120', 300), 120);
  assert.equal(positiveInt('0', 300), 300);
  assert.equal(positiveInt('-5', 300), 300);
  assert.equal(positiveInt('abc', 300), 300);
  assert.equal(positiveInt('99999999', 300), 300);
});

test('policyFor：auth / read / write 分桶，内部接口不限流', () => {
  const env = {
    RATE_LIMIT_READ_PER_MINUTE: '300',
    RATE_LIMIT_WRITE_PER_MINUTE: '60',
    RATE_LIMIT_AUTH_PER_MINUTE: '10',
  };
  assert.deepEqual(policyFor('GET', '/api/auth/github/login', env), {
    scope: 'auth',
    limit: 10,
    windowSeconds: 60,
  });
  assert.deepEqual(policyFor('GET', '/api/repos', env), {
    scope: 'read',
    limit: 300,
    windowSeconds: 60,
  });
  assert.deepEqual(policyFor('POST', '/api/repos', env), {
    scope: 'write',
    limit: 60,
    windowSeconds: 60,
  });
  assert.equal(policyFor('POST', '/api/internal/trending/snapshots', env), null);
  assert.equal(policyFor('GET', '/healthz', env), null);
});

test('policyFor：RATE_LIMIT_ENABLED=false 时全部放行', () => {
  assert.equal(policyFor('GET', '/api/repos', { RATE_LIMIT_ENABLED: 'false' }), null);
});

test('固定窗口：起点对齐、Retry-After 至少 1 秒', () => {
  assert.equal(windowStartSeconds(1_700_000_123_000, 60), 1_700_000_100);
  assert.equal(retryAfterSeconds(1_700_000_123_000, 1_700_000_100, 60), 37);
  assert.equal(retryAfterSeconds(1_700_000_159_900, 1_700_000_100, 60), 1);
});

test('clientIpFromHeaders：Cloudflare 优先，其次 X-Forwarded-For 第一跳', () => {
  assert.equal(clientIpFromHeaders('203.0.113.7', '10.0.0.1, 10.0.0.2'), '203.0.113.7');
  assert.equal(clientIpFromHeaders('', '10.0.0.1, 10.0.0.2'), '10.0.0.1');
  assert.equal(clientIpFromHeaders(undefined, undefined), 'unknown');
});

test('限流身份：用户与匿名 IP 哈希不同，且不暴露明文', async () => {
  const userHash = await rateLimitIdentity('read', 'u-1', '203.0.113.7');
  const ipHash = await rateLimitIdentity('read', null, '203.0.113.7');
  assert.notEqual(userHash, ipHash);
  assert.match(userHash, /^[0-9a-f]{64}$/);
  assert.equal(rateLimitBucket('read', userHash), `read:${userHash}`);
});

test('timingSafeEqualHex：相同为 true，长度 / 内容不同为 false', () => {
  assert.equal(timingSafeEqualHex('abcd', 'abcd'), true);
  assert.equal(timingSafeEqualHex('abcd', 'abce'), false);
  assert.equal(timingSafeEqualHex('abcd', 'abcde'), false);
});

test('内部令牌：双令牌均可通过，未配置 / 不匹配分别返回状态', async () => {
  const env = { INTERNAL_TOKEN: 'token-current', INTERNAL_TOKEN_PREVIOUS: 'token-previous' };
  assert.equal(await verifyInternalToken(env, 'token-current'), 'ok');
  assert.equal(await verifyInternalToken(env, 'token-previous'), 'ok');
  assert.equal(await verifyInternalToken(env, 'token-old'), 'unauthorized');
  assert.equal(await verifyInternalToken(env, ''), 'unauthorized');
  assert.equal(await verifyInternalToken({}, 'anything'), 'not_configured');
});

test('内部令牌状态：只输出指纹与轮换标记', async () => {
  const status = await internalTokenStatus({
    INTERNAL_TOKEN: 'token-current',
    INTERNAL_TOKEN_PREVIOUS: 'token-previous',
  });
  assert.equal(status.configured, true);
  assert.equal(status.previousConfigured, true);
  assert.equal(status.rotationPending, true);
  assert.match(status.currentFingerprint, /^[0-9a-f]{12}$/);
  assert.notEqual(status.currentFingerprint, status.previousFingerprint);
  assert.equal(JSON.stringify(status).includes('token-current'), false);
});

test('登录防护配置：默认值 10 次 / 15 分钟 / 锁定 15 分钟', () => {
  assert.deepEqual(loginGuardSettings({}), {
    maxFailures: 10,
    failureWindowSeconds: 900,
    lockoutSeconds: 900,
  });
  assert.equal(loginGuardSettings({ LOGIN_MAX_FAILURES: '3' }).maxFailures, 3);
  assert.equal(loginGuardSettings({ LOGIN_MAX_FAILURES: '0' }).maxFailures, 10);
});
