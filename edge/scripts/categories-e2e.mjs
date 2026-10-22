#!/usr/bin/env node
/**
 * 分类树 CRUD 端到端验证（零第三方依赖）
 *
 * 启动 `wrangler dev`（独立端口 / 独立本地 D1），直接种入用户与会话，
 * 用真实 HTTP 覆盖：列表 → 新建（顶级 / 子级 / 孙级）→ 编辑 → 移动（同级 / 换父级）
 * → 环检测负例 → 删除保护（子分类 / 仓库引用）→ 删除 → 未登录 401。
 *
 * 用法（在 edge/ 下，先 npm ci）：
 *   npm run test:categories
 *   node scripts/categories-e2e.mjs --keep     # 保留 .wrangler/e2e-categories-<pid> 便于排查
 */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { existsSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const EDGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const WRANGLER_BIN = join(EDGE_ROOT, 'node_modules', 'wrangler', 'bin', 'wrangler.js');
const DB_NAME = 'opensource-factory';
const ALLOWED_ORIGIN = 'http://localhost:5173';
const SESSION_TOKEN = 'e2e-categories-session-token';

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

async function http(url, options = {}) {
  const headers = {};
  if (options.cookie) headers.Cookie = options.cookie;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(url, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  return { status: res.status, text, json };
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

  const persistDir = join(EDGE_ROOT, '.wrangler', `e2e-categories-${process.pid}`);
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

  const sessionId = createHash('sha256').update(SESSION_TOKEN).digest('hex');
  console.log('• 种入测试用户与会话…');
  await runWrangler(
    [
      'd1',
      'execute',
      DB_NAME,
      '--local',
      '--persist-to',
      persistDir,
      '--command',
      `INSERT INTO users (id, login, name) VALUES ('1001', 'tester', 'Tester');
       INSERT INTO sessions (id, user_id, expires_at) VALUES ('${sessionId}', '1001', '2099-01-01T00:00:00.000Z');`,
    ],
    env
  );

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

  const cookie = `of_session=${SESSION_TOKEN}`;
  const auth = { cookie };

  try {
    console.log('• 启动 wrangler dev（本地 D1）…');
    await waitForHealth(workerUrl, wrangler, () => wranglerOutput);

    // ── 1. 空列表 ────────────────────────────────────────────
    const empty = await http(`${workerUrl}/api/categories`);
    assertEqual(empty.status, 200, 'GET /api/categories 应 200');
    assertEqual(empty.json?.categories?.length, 0, '初始分类应为空');
    ok('列表：空库返回空分类数组');

    // ── 2. 未登录写操作被拒 ──────────────────────────────────
    const anonymous = await http(`${workerUrl}/api/categories`, {
      method: 'POST',
      body: { name: '匿名分类' },
    });
    assertEqual(anonymous.status, 401, '未登录新建应 401');
    ok('鉴权：未登录新建返回 401');

    // ── 3. 新建顶级 / 子级 / 孙级 ────────────────────────────
    const pay = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: '支付系统', description: '支付与账务' },
    });
    assertEqual(pay.status, 201, '新建顶级分类应 201');
    assertEqual(pay.json?.parentId, null, '顶级分类 parentId 应为 null');
    assertEqual(pay.json?.sortOrder, 0, '首个分类 sortOrder 应为 0');

    const ai = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: 'AI' },
    });
    assertEqual(ai.status, 201, '新建第二个顶级分类应 201');
    assertEqual(ai.json?.sortOrder, 1, '第二个分类应追加到末尾');

    const gateway = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: '网关', parentId: pay.json.id },
    });
    assertEqual(gateway.status, 201, '新建子分类应 201');
    assertEqual(gateway.json?.parentId, pay.json.id, '子分类 parentId');
    assertEqual(gateway.json?.sortOrder, 0, '首个子分类 sortOrder 应为 0');

    const channel = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: '渠道', parentId: gateway.json.id },
    });
    assertEqual(channel.status, 201, '新建孙分类应 201');
    assertEqual(channel.json?.parentId, gateway.json.id, '孙分类 parentId');
    ok('新建：顶级 / 子级 / 孙级均成功，parentId 与 sortOrder 正确');

    // ── 4. 重名与非法父级 ────────────────────────────────────
    const duplicate = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: '支付系统' },
    });
    assertEqual(duplicate.status, 409, '同级重名应 409');
    assertEqual(duplicate.json?.error, 'category_name_exists', '重名错误码');

    const badParent = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: '野分类', parentId: 'missing-parent' },
    });
    assertEqual(badParent.status, 400, '父级不存在应 400');
    assertEqual(badParent.json?.error, 'invalid_parent', '父级错误码');
    ok('校验：同级重名 409、父级不存在 400');

    // ── 5. 列表结构与排序 ────────────────────────────────────
    const list = await http(`${workerUrl}/api/categories`);
    assertEqual(list.status, 200, '列表应 200');
    assertEqual(list.json?.categories?.length, 4, '应有 4 个分类');
    const byName = new Map(list.json.categories.map((item) => [item.name, item]));
    assertEqual(byName.get('AI').sortOrder, 1, 'AI 的 sortOrder');
    assertEqual(byName.get('网关').parentId, pay.json.id, '网关的 parentId');
    assertEqual(byName.get('渠道').parentId, gateway.json.id, '渠道的 parentId');
    ok('列表：返回 parentId / sortOrder / count 扁平结构');

    // ── 6. 编辑名称与描述 ────────────────────────────────────
    const renamed = await http(`${workerUrl}/api/categories/${gateway.json.id}`, {
      ...auth,
      method: 'PATCH',
      body: { name: '支付网关', description: '统一支付网关' },
    });
    assertEqual(renamed.status, 200, '编辑应 200');
    assertEqual(renamed.json?.name, '支付网关', '名称应更新');
    assertEqual(renamed.json?.description, '统一支付网关', '描述应更新');
    ok('编辑：名称 / 描述更新成功');

    // ── 7. 同级重排：把 AI 移到支付系统之前 ─────────────────
    const reordered = await http(`${workerUrl}/api/categories/${ai.json.id}/move`, {
      ...auth,
      method: 'POST',
      body: { parentId: null, beforeId: pay.json.id },
    });
    assertEqual(reordered.status, 200, '移动应 200');
    assertEqual(reordered.json?.sortOrder, 0, 'AI 应变为第 0 位');
    const afterReorder = await http(`${workerUrl}/api/categories`);
    const rootOrder = afterReorder.json.categories
      .filter((item) => item.parentId === null)
      .sort((a, b) => a.sortOrder - b.sortOrder)
      .map((item) => item.name);
    assertEqual(JSON.stringify(rootOrder), JSON.stringify(['AI', '支付系统']), '顶级顺序');
    ok('移动：同级重排后顺序与 sortOrder 归一化');

    // ── 7.5 编辑未改父级时不得挪动排序 ─────────────────────
    const editedInPlace = await http(`${workerUrl}/api/categories/${ai.json.id}`, {
      ...auth,
      method: 'PATCH',
      body: { name: 'AI', parentId: null, description: '人工智能' },
    });
    assertEqual(editedInPlace.status, 200, '编辑应 200');
    assertEqual(editedInPlace.json?.sortOrder, 0, '编辑未改父级时应保持原排序');
    assertEqual(editedInPlace.json?.description, '人工智能', '描述应更新');
    ok('编辑：未变更父级时保持原排序位置');

    // ── 8. 换父级：把「渠道」移到 AI 下 ─────────────────────
    const reparented = await http(`${workerUrl}/api/categories/${channel.json.id}/move`, {
      ...auth,
      method: 'POST',
      body: { parentId: ai.json.id },
    });
    assertEqual(reparented.status, 200, '换父级应 200');
    assertEqual(reparented.json?.parentId, ai.json.id, '渠道 parentId 应变为 AI');
    assertEqual(reparented.json?.sortOrder, 0, '渠道在 AI 下应为第 0 位');
    ok('移动：换父级后 parentId 与 sortOrder 正确');

    // ── 9. 环检测：把 AI 移到自己的孙分类下 ─────────────────
    const cycle = await http(`${workerUrl}/api/categories/${ai.json.id}/move`, {
      ...auth,
      method: 'POST',
      body: { parentId: channel.json.id },
    });
    assertEqual(cycle.status, 409, '移动到后代下应 409');
    assertEqual(cycle.json?.error, 'category_cycle', '环错误码');
    ok('环检测：移动到自己的后代下被拒绝（409 category_cycle）');

    // ── 10. 删除保护：有子分类 ──────────────────────────────
    const deleteParent = await http(`${workerUrl}/api/categories/${ai.json.id}`, {
      ...auth,
      method: 'DELETE',
    });
    assertEqual(deleteParent.status, 409, '删除含子分类应 409');
    assertEqual(deleteParent.json?.error, 'category_has_children', '子分类保护错误码');
    ok('删除保护：有子分类时拒绝（409 category_has_children）');

    // ── 11. 删除保护：仍被仓库引用（选叶子节点，避免先撞子分类保护）──
    await runWrangler(
      [
        'd1',
        'execute',
        DB_NAME,
        '--local',
        '--persist-to',
        persistDir,
        '--command',
        `INSERT INTO my_repositories (id, platform, name, html_url, category_id, user_id)
         VALUES ('tester/used-repo', 'github', 'used-repo', 'https://github.com/tester/used-repo', '${gateway.json.id}', '1001');`,
      ],
      env
    );
    const deleteUsed = await http(`${workerUrl}/api/categories/${gateway.json.id}`, {
      ...auth,
      method: 'DELETE',
    });
    assertEqual(deleteUsed.status, 409, '删除被引用分类应 409');
    assertEqual(deleteUsed.json?.error, 'category_in_use', '引用保护错误码');
    ok('删除保护：仍被仓库引用时拒绝（409 category_in_use）');

    // ── 12. 正常删除空分类 ──────────────────────────────────
    const temp = await http(`${workerUrl}/api/categories`, {
      ...auth,
      method: 'POST',
      body: { name: '临时分类' },
    });
    const deleted = await http(`${workerUrl}/api/categories/${temp.json.id}`, {
      ...auth,
      method: 'DELETE',
    });
    assertEqual(deleted.status, 204, '删除空分类应 204');
    const finalList = await http(`${workerUrl}/api/categories`);
    assert(
      !finalList.json.categories.some((item) => item.id === temp.json.id),
      '删除后列表中不应再有该分类'
    );
    ok('删除：空分类删除成功（204）并从列表移除');

    console.log(`\n分类树 CRUD 端到端验证通过：${passed.length} 项`);
  } finally {
    await stopChild(wrangler);
    if (!KEEP) {
      rmSync(persistDir, { recursive: true, force: true });
    } else {
      console.log(`• 保留本地 D1 目录：${persistDir}`);
    }
  }
}

main().catch((err) => {
  console.error(`\n✖ ${err.message}`);
  process.exitCode = 1;
});
