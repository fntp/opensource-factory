/**
 * OpenFactory 收藏助手 · 设置页
 *
 * 保存 API 地址与扩展令牌，并按需申请该站点的 host 权限。
 */
import {
  buildAdminUrl,
  isValidTokenFormat,
  normalizeApiBase,
} from './lib/repo.js';

const $ = (id) => document.getElementById(id);

function setStatus(id, text, type = '') {
  const el = $(id);
  el.textContent = text || '';
  el.classList.remove('success', 'error');
  if (type) el.classList.add(type);
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, status: 0, error: 'runtime_error' });
        return;
      }
      resolve(response);
    });
  });
}

async function readStored() {
  return chrome.storage.local.get({ apiBase: '', token: '' });
}

async function hasHostPermission(apiBase) {
  try {
    const origin = new URL(apiBase).origin;
    return chrome.permissions.contains({ origins: [`${origin}/*`] });
  } catch {
    return false;
  }
}

async function requestHostPermission(apiBase) {
  const origin = new URL(apiBase).origin;
  return chrome.permissions.request({ origins: [`${origin}/*`] });
}

async function updatePermissionStatus() {
  const apiBase = normalizeApiBase($('api-base').value);
  if (!apiBase) {
    setStatus('permission-status', '先填写有效的 API 地址。');
    return;
  }
  const granted = await hasHostPermission(apiBase);
  setStatus(
    'permission-status',
    granted ? '已获得该站点的访问权限。' : '尚未授予该站点的访问权限。',
    granted ? 'success' : ''
  );
}

async function testConnection() {
  const result = await send({ type: 'OF_API', path: '/api/extension/me' });
  if (result && result.ok && result.data && result.data.user) {
    const name = result.data.user.name || result.data.user.email || result.data.user.id;
    setStatus('status', `连接成功，当前账号：${name}`, 'success');
    return true;
  }
  if (result && result.status === 401) {
    setStatus('status', '连接失败：令牌无效或已被撤销。', 'error');
  } else if (result && (result.error === 'network_error' || result.error === 'runtime_error')) {
    setStatus('status', '连接失败：无法访问该地址，请检查 API 地址、网络与站点权限。', 'error');
  } else {
    setStatus('status', `连接失败（HTTP ${result?.status || '未知'}）。`, 'error');
  }
  return false;
}

async function save() {
  const apiBase = normalizeApiBase($('api-base').value);
  const token = $('token').value.trim();

  if (!apiBase) {
    setStatus('status', '请填写有效的 API 地址（http:// 或 https://）。', 'error');
    return;
  }
  if (!isValidTokenFormat(token)) {
    setStatus('status', '令牌格式不正确，应以 ofx_ 开头，共 68 位。', 'error');
    return;
  }

  const button = $('save');
  button.disabled = true;
  button.textContent = '保存中…';

  try {
    const granted = await hasHostPermission(apiBase);
    if (!granted) {
      const ok = await requestHostPermission(apiBase);
      if (!ok) {
        setStatus('status', '未授予站点访问权限，扩展无法连接该地址。', 'error');
        return;
      }
    }

    await chrome.storage.local.set({ apiBase, token });
    setStatus('status', '配置已保存，正在测试连接…');
    await testConnection();
    await updatePermissionStatus();
  } catch {
    setStatus('status', '保存失败，请重试。', 'error');
  } finally {
    button.disabled = false;
    button.textContent = '保存并测试连接';
  }
}

async function grantPermission() {
  const apiBase = normalizeApiBase($('api-base').value);
  if (!apiBase) {
    setStatus('permission-status', '请先填写有效的 API 地址并保存。', 'error');
    return;
  }
  try {
    const ok = await requestHostPermission(apiBase);
    setStatus(
      'permission-status',
      ok ? '已获得该站点的访问权限。' : '未授予权限，扩展将无法连接站点。',
      ok ? 'success' : 'error'
    );
  } catch {
    setStatus('permission-status', '申请权限失败，请重试。', 'error');
  }
}

async function openAdmin() {
  const apiBase = normalizeApiBase($('api-base').value);
  const url = apiBase ? buildAdminUrl(apiBase, '/settings/extension') : null;
  if (!url) {
    setStatus('status', '请先填写有效的 API 地址。', 'error');
    return;
  }
  await chrome.tabs.create({ url });
}

async function clearConfig() {
  await chrome.storage.local.remove(['apiBase', 'token']);
  $('api-base').value = '';
  $('token').value = '';
  setStatus('status', '本地配置已清除。');
  setStatus('permission-status', '');
}

async function init() {
  const manifest = chrome.runtime.getManifest();
  $('version').textContent = `v${manifest.version}`;

  const stored = await readStored();
  $('api-base').value = stored.apiBase || '';
  $('token').value = stored.token || '';
  if (stored.apiBase) await updatePermissionStatus();

  $('save').addEventListener('click', save);
  $('grant').addEventListener('click', grantPermission);
  $('open-admin').addEventListener('click', openAdmin);
  $('clear').addEventListener('click', clearConfig);
  $('api-base').addEventListener('change', updatePermissionStatus);
}

init().catch(() => {
  setStatus('status', '设置页加载失败，请重新打开。', 'error');
});
