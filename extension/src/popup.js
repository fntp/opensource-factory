/**
 * OpenFactory 收藏助手 · Popup
 *
 * 展示当前标签页的仓库信息、收藏状态，并支持一键收藏。
 * 网络请求统一交给 background service worker（令牌不进入页面上下文）。
 */
import { extractRepoPage } from './content/extract.js';
import { buildRepoInfo, formatStars } from './lib/repo.js';

const $ = (id) => document.getElementById(id);

const SECTIONS = ['state-loading', 'state-setup', 'state-not-repo', 'state-repo'];
let currentInfo = null;
let currentTabId = null;
let saved = false;

function show(sectionId) {
  for (const id of SECTIONS) {
    $(id).classList.toggle('hidden', id !== sectionId);
  }
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

function setHint(text, isError = false) {
  const hint = $('save-hint');
  hint.textContent = text || '';
  hint.classList.toggle('error', Boolean(isError));
}

function renderRepo(info) {
  $('repo-platform').textContent = info.platform === 'github' ? 'GitHub' : 'Gitee';
  $('repo-stars').textContent = `★ ${formatStars(info.stars)}`;
  $('repo-name').textContent = info.fullName;
  $('repo-description').textContent = info.description || '暂无简介';
  $('repo-language').textContent = info.language || '未知语言';
  $('repo-forks').textContent = `Fork ${formatStars(info.forks)}`;
  show('state-repo');
}

function markSaved(message) {
  saved = true;
  const button = $('save-button');
  button.textContent = '已收藏';
  button.classList.add('success');
  button.disabled = true;
  setHint(message || '已在我的仓库中');
}

function errorText(result) {
  switch (result.error) {
    case 'not_configured':
    case 'missing_token':
      return '尚未完成配置，请先打开设置。';
    case 'cannot_access_page':
      return '无法读取当前页面，请刷新后重试。';
    case 'network_error':
    case 'runtime_error':
      return '无法连接 OpenFactory，请检查 API 地址与网络。';
    case 'not_repo':
      return '当前页面不是仓库页。';
    default:
      break;
  }
  switch (result.status) {
    case 401:
      return '令牌无效或已被撤销，请在设置中重新生成。';
    case 409:
      return '该仓库已被其他用户收藏。';
    case 429:
      return '操作太频繁，请稍后再试。';
    default:
      return `保存失败（HTTP ${result.status || '未知'}），请稍后重试。`;
  }
}

async function loadSettings() {
  const settings = await send({ type: 'OF_SETTINGS' });
  if (!settings || !settings.apiBase || !settings.token) {
    show('state-setup');
    return null;
  }
  return settings;
}

async function extractCurrentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return null;
  currentTabId = tab.id;
  try {
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractRepoPage,
    });
    return injection?.result ?? null;
  } catch {
    return null;
  }
}

async function checkSaved(info) {
  const result = await send({
    type: 'OF_API',
    path: `/api/extension/check?id=${encodeURIComponent(info.fullName)}`,
  });
  if (result && result.ok && result.data && result.data.saved) {
    markSaved('已在我的仓库中');
  } else if (result && result.status === 401) {
    setHint('令牌无效或已被撤销，请在设置中重新生成。', true);
  }
}

async function save() {
  if (!currentInfo || saved) return;
  const button = $('save-button');
  button.disabled = true;
  button.textContent = '收藏中…';
  setHint('');

  const result = await send({ type: 'OF_SAVE_CURRENT', tabId: currentTabId });
  if (result && result.ok) {
    markSaved(result.data && result.data.created ? '收藏成功，已加入我的仓库' : '收藏成功，已更新仓库信息');
    return;
  }

  button.disabled = false;
  button.textContent = '重试收藏';
  setHint(errorText(result || {}), true);
}

async function init() {
  $('open-settings').addEventListener('click', () => chrome.runtime.openOptionsPage());
  $('setup-button').addEventListener('click', () => chrome.runtime.openOptionsPage());
  $('save-button').addEventListener('click', save);

  const manifest = chrome.runtime.getManifest();
  $('version').textContent = `v${manifest.version}`;

  const settings = await loadSettings();
  if (!settings) return;

  const page = await extractCurrentTab();
  if (!page) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    $('current-host').textContent = tab && tab.url ? new URL(tab.url).hostname : '';
    show('state-not-repo');
    return;
  }

  currentInfo = buildRepoInfo(page);
  if (!currentInfo) {
    $('current-host').textContent = page.host || '';
    show('state-not-repo');
    return;
  }

  renderRepo(currentInfo);
  await checkSaved(currentInfo);
}

init().catch(() => {
  show('state-not-repo');
});
