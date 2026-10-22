#!/usr/bin/env node
/**
 * 本地 mock GitHub OAuth 服务（零第三方依赖）
 *
 * 用途：在没有真实 OAuth App / 不访问外网的情况下，配合 `wrangler dev` 完成
 * 「授权跳转 → 回调换 token → 拉取用户 → 建立会话」全链路联调。
 *
 * 用法：
 *   node scripts/mock-github-oauth.mjs [--port 8788] [--client-id test-client-id] [--client-secret test-client-secret]
 *
 * 路由：
 *   GET  /login/oauth/authorize   302 回跳 redirect_uri?code=...&state=...
 *   POST /login/oauth/access_token 校验 client / code / redirect_uri，返回 access_token
 *   GET  /user                    返回用户（email 为 null，用于验证 /user/emails 回退）
 *   GET  /user/emails             返回 primary + verified 邮箱
 *   GET  /healthz                 健康检查
 */
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';

export const DEFAULT_USER = {
  id: 1001,
  login: 'octocat',
  name: 'The Octocat',
  email: null,
  avatar_url: 'https://avatars.githubusercontent.com/u/583231?v=4',
};

export const DEFAULT_EMAILS = [
  { email: 'octocat@github.com', primary: false, verified: true, visibility: 'public' },
  { email: 'octocat@example.com', primary: true, verified: true, visibility: 'private' },
];

function sendJson(res, status, body, extraHeaders = {}) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  res.end(payload);
}

function readJsonBody(req, limitBytes = 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limitBytes) {
        reject(new Error('request body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (chunks.length === 0) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(new Error('invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

/**
 * 创建 mock 服务（不自动监听）
 * @param {{clientId?: string, clientSecret?: string, user?: object, emails?: object[]}} [options]
 */
export function createMockGithubServer(options = {}) {
  const clientId = options.clientId ?? 'test-client-id';
  const clientSecret = options.clientSecret ?? 'test-client-secret';
  const user = options.user ?? DEFAULT_USER;
  const emails = options.emails ?? DEFAULT_EMAILS;

  /** code → { redirectUri, state } */
  const pendingCodes = new Map();
  /** 已签发的 access token */
  const issuedTokens = new Set();
  let codeSeq = 0;

  const server = createServer(async (req, res) => {
    let url;
    try {
      url = new URL(req.url ?? '/', `http://${req.headers.host ?? '127.0.0.1'}`);
    } catch {
      sendJson(res, 400, { error: 'bad_request' });
      return;
    }

    try {
      // ── 健康检查 ─────────────────────────────────────────────
      if (req.method === 'GET' && url.pathname === '/healthz') {
        sendJson(res, 200, { status: 'ok' });
        return;
      }

      // ── 授权页：直接 302 回回调地址（模拟用户点「Authorize」）──
      if (req.method === 'GET' && url.pathname === '/login/oauth/authorize') {
        if (url.searchParams.get('client_id') !== clientId) {
          sendJson(res, 400, { error: 'invalid_client' });
          return;
        }
        const redirectUri = url.searchParams.get('redirect_uri');
        if (!redirectUri) {
          sendJson(res, 400, { error: 'redirect_uri_missing' });
          return;
        }
        const state = url.searchParams.get('state') ?? '';
        const code = `mock_code_${Date.now()}_${++codeSeq}`;
        pendingCodes.set(code, { redirectUri, state });

        const target = new URL(redirectUri);
        target.searchParams.set('code', code);
        if (state) target.searchParams.set('state', state);
        res.writeHead(302, { Location: target.toString(), 'Cache-Control': 'no-store' });
        res.end();
        return;
      }

      // ── 换 token ─────────────────────────────────────────────
      if (req.method === 'POST' && url.pathname === '/login/oauth/access_token') {
        let body;
        try {
          body = await readJsonBody(req);
        } catch (err) {
          sendJson(res, 400, { error: 'invalid_request', error_description: String(err) });
          return;
        }
        if (body.client_id !== clientId || body.client_secret !== clientSecret) {
          sendJson(res, 200, { error: 'incorrect_client_credentials' });
          return;
        }
        const record = pendingCodes.get(body.code);
        if (!record) {
          sendJson(res, 200, { error: 'bad_verification_code' });
          return;
        }
        // GitHub 要求 token 交换的 redirect_uri 与 authorize 阶段完全一致
        if (record.redirectUri !== body.redirect_uri) {
          sendJson(res, 200, { error: 'redirect_uri_mismatch' });
          return;
        }
        pendingCodes.delete(body.code);
        const token = `gho_mock_${Date.now()}_${Math.random().toString(36).slice(2)}`;
        issuedTokens.add(token);
        sendJson(res, 200, {
          access_token: token,
          token_type: 'bearer',
          scope: 'read:user user:email',
        });
        return;
      }

      // ── 用户信息 ─────────────────────────────────────────────
      if (req.method === 'GET' && (url.pathname === '/user' || url.pathname === '/user/emails')) {
        const auth = req.headers.authorization ?? '';
        const token = auth.replace(/^Bearer\s+/i, '');
        if (!issuedTokens.has(token)) {
          sendJson(res, 401, { message: 'Bad credentials' });
          return;
        }
        if (url.pathname === '/user') {
          sendJson(res, 200, user);
        } else {
          sendJson(res, 200, emails);
        }
        return;
      }

      sendJson(res, 404, { error: 'not_found' });
    } catch (err) {
      sendJson(res, 500, { error: 'mock_error', error_description: String(err) });
    }
  });

  return {
    server,
    clientId,
    clientSecret,
    /** @param {number} [port] */
    listen(port = 0) {
      return new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, '127.0.0.1', () => {
          server.off('error', reject);
          const address = server.address();
          const actualPort = typeof address === 'object' && address ? address.port : port;
          resolve({ port: actualPort, url: `http://127.0.0.1:${actualPort}` });
        });
      });
    },
    close() {
      return new Promise((resolve) => server.close(() => resolve()));
    },
  };
}

/** 解析 CLI 参数：--key value */
function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (!item.startsWith('--')) continue;
    const key = item.slice(2);
    const value = argv[i + 1];
    if (value && !value.startsWith('--')) {
      args[key] = value;
      i += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const args = parseArgs(process.argv.slice(2));
  const mock = createMockGithubServer({
    clientId: typeof args['client-id'] === 'string' ? args['client-id'] : undefined,
    clientSecret:
      typeof args['client-secret'] === 'string' ? args['client-secret'] : undefined,
  });
  const port = Number(args.port ?? 8788);
  const { url } = await mock.listen(Number.isFinite(port) ? port : 8788);
  console.log(`[mock-github] listening on ${url}`);
  console.log(`[mock-github] client_id=${mock.clientId}`);
  const shutdown = async () => {
    await mock.close();
    process.exit(0);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}
