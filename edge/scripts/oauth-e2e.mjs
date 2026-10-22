#!/usr/bin/env node
/**
 * GitHub OAuth 全链路端到端验证（零第三方依赖）
 *
 * 启动本地 mock GitHub + `wrangler dev`（独立端口 / 独立本地 D1），用真实 HTTP 走完：
 *   登录 302 → mock 授权 → 回调换 token → upsert 用户 → 会话 cookie
 *   → /api/auth/me → 登出 → 401
 * 并覆盖 CSRF（state 不匹配）、开放重定向回退、用户拒绝授权三个负例。
 *
 * 用法（在 edge/ 下，先 npm ci）：
 *   npm run test:oauth
 *   node scripts/oauth-e2e.mjs --keep     # 保留 .wrangler/e2e-state-<pid> 便于排查
 */
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createMockGithubServer } from './mock-github-oauth.mjs';

const EDGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const WRANGLER_BIN = join(EDGE_ROOT, 'node_modules', 'wrangler', 'bin', 'wrangler.js');
const CLIENT_ID = 'test-client-id';
const CLIENT_SECRET = 'test-client-secret';
const ALLOWED_ORIGIN = 'http://localhost:5173';
const DB_NAME = 'opensource-factory';

const args = new Set(process.argv.slice(2));
const KEEP = args.has('--keep');

const delay = (ms) => new Promise((resolveDelay) => setTimeout(resolveDelay, ms));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}：期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}`);
  }
}

function getFreePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close(() => resolvePort(port));
    });
  });
}

function getCookie(setCookies, name) {
  for (const header of setCookies ?? []) {
    const pair = header.split(';', 1)[0] ?? '';
    const idx = pair.indexOf('=');
    if (idx === -1) continue;
    if (pair.slice(0, idx).trim() === name) {
      return { value: pair.slice(idx + 1).trim(), raw: header };
    }
  }
  return null;
}

async function http(url, options = {}) {
  const headers = {};
  if (options.cookie) headers.Cookie = options.cookie;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(url, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    redirect: 'manual',
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  return {
    status: res.status,
    headers: res.headers,
    location: res.headers.get('location'),
    setCookies: res.headers.getSetCookie?.() ?? [],
    text,
    json,
  };
}

function runWrangler(argsList, env) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(process.execPath, [WRANGLER_BIN, ...argsList], {
      cwd: EDGE_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    child.stdout.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) resolveRun(output);
      else reject(new Error(`wrangler ${argsList.join(' ')} 失败（exit ${code}）：\n${output}`));
    });
  });
}

async function waitForHealth(workerUrl, child, getOutput, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`wrangler dev 提前退出（exit ${child.exitCode}）：\n${getOutput()}`);
    }
    try {
      const res = await fetch(`${workerUrl}/healthz`);
      if (res.ok) return;
    } catch {
      // 尚未就绪
    }
    await delay(500);
  }
  throw new Error(`等待 wrangler dev 就绪超时：\n${getOutput()}`);
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  try {
    if (process.platform !== 'win32') process.kill(-child.pid, 'SIGTERM');
    else child.kill('SIGTERM');
  } catch {
    child.kill('SIGTERM');
  }
  await Promise.race([once(child, 'exit'), delay(5_000)]);
  if (child.exitCode === null) {
    try {
      if (process.platform !== 'win32') process.kill(-child.pid, 'SIGKILL');
      else child.kill('SIGKILL');
    } catch {
      // 已退出
    }
  }
}

const passed = [];
function ok(message) {
  passed.push(message);
  console.log(`  ✔ ${message}`);
}

async function main() {
  if (!existsSync(WRANGLER_BIN)) {
    throw new Error('未找到 wrangler，请先在 edge/ 下执行 npm ci');
  }

  const persistDir = join(EDGE_ROOT, '.wrangler', `e2e-state-${process.pid}`);
  rmSync(persistDir, { recursive: true, force: true });

  const env = {
    ...process.env,
    CI: '1',
    WRANGLER_SEND_METRICS: 'false',
    NO_COLOR: '1',
    FORCE_COLOR: '0',
  };

  console.log('• 应用本地 D1 迁移…');
  await runWrangler(
    ['d1', 'migrations', 'apply', DB_NAME, '--local', '--persist-to', persistDir],
    env
  );

  const mock = createMockGithubServer({ clientId: CLIENT_ID, clientSecret: CLIENT_SECRET });
  const { url: mockUrl } = await mock.listen(0);

  const workerPort = await getFreePort();
  const inspectorPort = await getFreePort();
  const workerUrl = `http://127.0.0.1:${workerPort}`;

  let wranglerOutput = '';
  const wrangler = spawn(
    process.execPath,
    [
      WRANGLER_BIN,
      'dev',
      '--ip',
      '127.0.0.1',
      '--port',
      String(workerPort),
      '--inspector-port',
      String(inspectorPort),
      '--persist-to',
      persistDir,
      '--var',
      `GITHUB_CLIENT_ID:${CLIENT_ID}`,
      '--var',
      `GITHUB_CLIENT_SECRET:${CLIENT_SECRET}`,
      '--var',
      `GITHUB_OAUTH_BASE_URL:${mockUrl}`,
      '--var',
      `GITHUB_API_BASE_URL:${mockUrl}`,
      '--var',
      `ALLOWED_ORIGIN:${ALLOWED_ORIGIN}`,
    ],
    {
      cwd: EDGE_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: process.platform !== 'win32',
    }
  );
  wrangler.stdout.on('data', (chunk) => {
    wranglerOutput += chunk.toString();
  });
  wrangler.stderr.on('data', (chunk) => {
    wranglerOutput += chunk.toString();
  });

  try {
    console.log('• 启动 wrangler dev（本地 D1 + mock GitHub）…');
    await waitForHealth(workerUrl, wrangler, () => wranglerOutput);

    // ── 1. 登录跳转 ───────────────────────────────────────────
    const login = await http(`${workerUrl}/api/auth/github/login?redirect=%2Frepos`);
    assertEqual(login.status, 302, '登录应 302');
    assert(login.location, '登录响应缺少 Location');
    const authorizeUrl = new URL(login.location);
    assertEqual(authorizeUrl.origin, mockUrl, '应跳转 mock GitHub');
    assertEqual(authorizeUrl.pathname, '/login/oauth/authorize', '授权路径');
    assertEqual(authorizeUrl.searchParams.get('client_id'), CLIENT_ID, 'client_id');
    assertEqual(
      authorizeUrl.searchParams.get('redirect_uri'),
      `${workerUrl}/api/auth/github/callback`,
      'redirect_uri 应为干净的回调地址'
    );
    assertEqual((authorizeUrl.searchParams.get('state') ?? '').length, 64, 'state 长度');
    const stateCookie = getCookie(login.setCookies, 'of_oauth_state');
    assert(stateCookie, '缺少 of_oauth_state cookie');
    assert(/HttpOnly/i.test(stateCookie.raw), 'state cookie 应为 HttpOnly');
    assert(/SameSite=Lax/i.test(stateCookie.raw), 'state cookie 应为 SameSite=Lax');
    const statePayload = JSON.parse(decodeURIComponent(stateCookie.value));
    assertEqual(statePayload.redirect, '/repos', 'state cookie 中的回跳目标');
    ok('登录跳转：302 → mock 授权页，client_id / redirect_uri / state 正确');

    // ── 2. 模拟用户授权 ──────────────────────────────────────
    const authorize = await http(authorizeUrl.toString());
    assertEqual(authorize.status, 302, 'mock 授权应 302');
    const callbackUrl = new URL(authorize.location);
    assertEqual(callbackUrl.origin, workerUrl, '回调应回到 Worker');
    assertEqual(callbackUrl.pathname, '/api/auth/github/callback', '回调路径');
    assert(callbackUrl.searchParams.get('code'), '回调缺少 code');
    assertEqual(
      callbackUrl.searchParams.get('state'),
      authorizeUrl.searchParams.get('state'),
      '回调 state 应与授权请求一致'
    );
    ok('模拟授权：302 → 回调地址，code / state 透传正确');

    // ── 3. 回调换 token + 建会话 ─────────────────────────────
    const callback = await http(callbackUrl.toString(), {
      cookie: `of_oauth_state=${stateCookie.value}`,
    });
    assertEqual(callback.status, 302, '回调应 302');
    const redirectTarget = new URL(callback.location, workerUrl);
    assertEqual(redirectTarget.pathname, '/repos', '回调后应回到 /repos');
    const sessionCookie = getCookie(callback.setCookies, 'of_session');
    assert(sessionCookie, '回调未设置 of_session cookie');
    assert(/HttpOnly/i.test(sessionCookie.raw), '会话 cookie 应为 HttpOnly');
    const clearedState = getCookie(callback.setCookies, 'of_oauth_state');
    assert(clearedState && /Max-Age=0/i.test(clearedState.raw), 'state cookie 应被清除');
    ok('回调换 token：redirect_uri 校验通过，写入用户并建立会话');

    // ── 4. /api/auth/me ──────────────────────────────────────
    const sessionHeader = `of_session=${sessionCookie.value}`;
    const me = await http(`${workerUrl}/api/auth/me`, { cookie: sessionHeader });
    assertEqual(me.status, 200, '/api/auth/me 应 200');
    assertEqual(me.json?.login, 'octocat', '登录名');
    assertEqual(me.json?.id, '1001', '用户 id');
    assertEqual(me.json?.email, 'octocat@example.com', '应回退 /user/emails 取主邮箱');
    ok('/api/auth/me：会话有效，返回 GitHub 用户与主邮箱');

    // ── 5. 受保护接口 ───────────────────────────────────────
    const repos = await http(`${workerUrl}/api/repos`, { cookie: sessionHeader });
    assertEqual(repos.status, 200, '/api/repos 应 200');
    assert(Array.isArray(repos.json), '/api/repos 应返回数组');
    ok('受保护接口：携带会话 cookie 可正常访问 /api/repos');

    // ── 6. 登出 ─────────────────────────────────────────────
    const logout = await http(`${workerUrl}/api/auth/logout`, {
      method: 'POST',
      cookie: sessionHeader,
    });
    assertEqual(logout.status, 204, '登出应 204');
    const meAfterLogout = await http(`${workerUrl}/api/auth/me`, { cookie: sessionHeader });
    assertEqual(meAfterLogout.status, 401, '登出后 /api/auth/me 应 401');
    ok('登出：204 清除会话，旧 cookie 再访问返回 401');

    // ── 7. CSRF 负例：state 不匹配 ──────────────────────────
    const login2 = await http(`${workerUrl}/api/auth/github/login`);
    const state2 = getCookie(login2.setCookies, 'of_oauth_state');
    assert(state2, '第二次登录缺少 state cookie');
    const authorize2 = await http(login2.location);
    const badCallback = new URL(authorize2.location);
    badCallback.searchParams.set('state', 'wrong-state');
    const badState = await http(badCallback.toString(), {
      cookie: `of_oauth_state=${state2.value}`,
    });
    assertEqual(badState.status, 400, 'state 不匹配应 400');
    assertEqual(badState.json?.error, 'invalid_oauth_state', 'state 错误码');
    ok('CSRF 负例：state 不匹配被拒绝（400 invalid_oauth_state）');

    // ── 8. 开放重定向负例：外部 URL 回退 ────────────────────
    const login3 = await http(
      `${workerUrl}/api/auth/github/login?redirect=${encodeURIComponent('https://evil.example/phish')}`
    );
    const state3 = getCookie(login3.setCookies, 'of_oauth_state');
    assert(state3, '第三次登录缺少 state cookie');
    const authorize3 = await http(login3.location);
    const callback3 = await http(authorize3.location, {
      cookie: `of_oauth_state=${state3.value}`,
    });
    assertEqual(callback3.status, 302, '外部 redirect 仍应完成登录');
    const safeTarget = new URL(callback3.location, workerUrl);
    assertEqual(safeTarget.origin, ALLOWED_ORIGIN, '外部 redirect 应回退 ALLOWED_ORIGIN');
    ok('开放重定向负例：外部 URL 被回退到 ALLOWED_ORIGIN');

    // ── 9. 用户拒绝授权 ─────────────────────────────────────
    const login4 = await http(`${workerUrl}/api/auth/github/login`);
    const state4 = getCookie(login4.setCookies, 'of_oauth_state');
    assert(state4, '第四次登录缺少 state cookie');
    const denied = await http(
      `${workerUrl}/api/auth/github/callback?error=access_denied&error_description=denied&state=${encodeURIComponent(
        JSON.parse(decodeURIComponent(state4.value)).state
      )}`,
      { cookie: `of_oauth_state=${state4.value}` }
    );
    assertEqual(denied.status, 400, '拒绝授权应 400');
    assertEqual(denied.json?.error, 'oauth_denied', '拒绝授权错误码');
    ok('拒绝授权：返回 oauth_denied（不再误报 state 错误）');

    console.log(`\n全部 ${passed.length} 项 OAuth 全链路检查通过。`);
  } finally {
    await stopChild(wrangler);
    await mock.close();
    if (!KEEP) rmSync(persistDir, { recursive: true, force: true });
    else console.log(`• 已保留本地状态目录：${persistDir}`);
  }
}

main().catch((err) => {
  console.error(`\n✖ OAuth 全链路验证失败：${err?.message ?? err}`);
  process.exitCode = 1;
});
