/**
 * OpenFactory 收藏助手 · Service Worker
 *
 * - 统一读取本地配置并发起 Bearer 请求（令牌不进入内容脚本 / 页面）；
 * - 快捷键 Ctrl+Shift+O 直接收藏当前仓库；
 * - 通过 action 徽标给出成功 / 失败反馈。
 */
import {
  buildBookmarkPayload,
  buildRepoInfo,
  normalizeApiBase,
} from './lib/repo.js';
import { extractRepoPage } from './content/extract.js';

const STORAGE_DEFAULTS = { apiBase: '', token: '' };

async function getSettings() {
  const stored = await chrome.storage.local.get(STORAGE_DEFAULTS);
  return {
    apiBase: normalizeApiBase(stored.apiBase) || '',
    token: typeof stored.token === 'string' ? stored.token.trim() : '',
  };
}

async function apiRequest(path, { method = 'GET', body } = {}) {
  const { apiBase, token } = await getSettings();
  if (!apiBase) return { ok: false, status: 0, error: 'not_configured' };
  if (!token) return { ok: false, status: 0, error: 'missing_token' };

  try {
    const res = await fetch(`${apiBase}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, error: 'network_error', message: String(err) };
  }
}

async function extractFromTab(tabId) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: extractRepoPage,
  });
  return result?.result ?? null;
}

async function saveTab(tabId) {
  let extraction;
  try {
    extraction = await extractFromTab(tabId);
  } catch {
    return { ok: false, status: 0, error: 'cannot_access_page' };
  }
  const info = buildRepoInfo(extraction);
  if (!info) return { ok: false, status: 0, error: 'not_repo' };
  const payload = buildBookmarkPayload(info);
  if (!payload) return { ok: false, status: 0, error: 'not_repo' };
  const result = await apiRequest('/api/extension/bookmark', {
    method: 'POST',
    body: payload,
  });
  return { ...result, repo: info };
}

async function flashBadge(tabId, text, color) {
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color });
    await chrome.action.setBadgeText({ tabId, text });
    setTimeout(() => {
      chrome.action.setBadgeText({ tabId, text: '' }).catch(() => {});
    }, 3000);
  } catch {
    // 标签页可能已关闭，忽略。
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || typeof message !== 'object') return undefined;

  if (message.type === 'OF_SETTINGS') {
    getSettings().then(sendResponse);
    return true;
  }

  if (message.type === 'OF_API') {
    apiRequest(String(message.path || ''), {
      method: message.method || 'GET',
      body: message.body,
    }).then(sendResponse);
    return true;
  }

  if (message.type === 'OF_SAVE_CURRENT') {
    saveTab(message.tabId).then(sendResponse);
    return true;
  }

  return undefined;
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'save-current-page') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  const result = await saveTab(tab.id);
  if (result.ok) {
    await flashBadge(tab.id, '✓', '#16a34a');
  } else if (result.error === 'not_repo') {
    await flashBadge(tab.id, '—', '#64748b');
  } else {
    await flashBadge(tab.id, '!', '#dc2626');
  }
});

chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === 'install') {
    chrome.runtime.openOptionsPage();
  }
});
