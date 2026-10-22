import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

import {
  buildAdminUrl,
  buildBookmarkPayload,
  buildRepoInfo,
  cleanDescription,
  formatStars,
  isValidTokenFormat,
  normalizeApiBase,
  parseCountText,
  parseRepoFullName,
  parseRepoUrl,
  tokenHint,
} from '../src/lib/repo.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

test('parseRepoFullName 接受合法 owner/repo 并去掉 .git', () => {
  assert.deepEqual(parseRepoFullName('facebook/react'), {
    owner: 'facebook',
    name: 'react',
    fullName: 'facebook/react',
  });
  assert.equal(parseRepoFullName('  owner/repo.git  ').fullName, 'owner/repo');
  assert.equal(parseRepoFullName('my-org/my_repo.js').fullName, 'my-org/my_repo.js');
});

test('parseRepoFullName 拒绝保留路径与非法格式', () => {
  assert.equal(parseRepoFullName('settings/profile'), null);
  assert.equal(parseRepoFullName('topics/react'), null);
  assert.equal(parseRepoFullName('foo'), null);
  assert.equal(parseRepoFullName('foo/bar/baz'), null);
  assert.equal(parseRepoFullName('foo/'), null);
  assert.equal(parseRepoFullName('/bar'), null);
  assert.equal(parseRepoFullName('foo/ba r'), null);
  assert.equal(parseRepoFullName(null), null);
});

test('parseRepoUrl 识别 GitHub 仓库页与子页面', () => {
  assert.deepEqual(parseRepoUrl('https://github.com/facebook/react'), {
    platform: 'github',
    owner: 'facebook',
    name: 'react',
    fullName: 'facebook/react',
    url: 'https://github.com/facebook/react',
  });
  assert.equal(
    parseRepoUrl('https://github.com/facebook/react/tree/main/packages').fullName,
    'facebook/react'
  );
  assert.equal(parseRepoUrl('https://github.com/facebook/react.git').fullName, 'facebook/react');
  assert.equal(parseRepoUrl('https://www.github.com/facebook/react').fullName, 'facebook/react');
});

test('parseRepoUrl 识别 Gitee 仓库页', () => {
  const parsed = parseRepoUrl('https://gitee.com/mindspore/mindspore');
  assert.equal(parsed.platform, 'gitee');
  assert.equal(parsed.fullName, 'mindspore/mindspore');
  assert.equal(parsed.url, 'https://gitee.com/mindspore/mindspore');
});

test('parseRepoUrl 拒绝非仓库页与第三方站点', () => {
  assert.equal(parseRepoUrl('https://github.com/'), null);
  assert.equal(parseRepoUrl('https://github.com/facebook'), null);
  assert.equal(parseRepoUrl('https://github.com/settings/profile'), null);
  assert.equal(parseRepoUrl('https://github.com/marketplace/actions/checkout'), null);
  assert.equal(parseRepoUrl('https://gitlab.com/foo/bar'), null);
  assert.equal(parseRepoUrl('ftp://github.com/foo/bar'), null);
  assert.equal(parseRepoUrl('not a url'), null);
  assert.equal(parseRepoUrl(undefined), null);
});

test('parseCountText 解析千分位、k、万、M', () => {
  assert.equal(parseCountText('12,345'), 12345);
  assert.equal(parseCountText('1.2k'), 1200);
  assert.equal(parseCountText('3.4万'), 34000);
  assert.equal(parseCountText('2M'), 2000000);
  assert.equal(parseCountText('1,234 stars'), 1234);
  assert.equal(parseCountText(''), 0);
  assert.equal(parseCountText(null), 0);
});

test('cleanDescription 过滤 GitHub 默认 SEO 文案', () => {
  assert.equal(
    cleanDescription([
      'Contribute to facebook/react development by creating an account on GitHub.',
      'The library for web and native user interfaces.',
    ]),
    'The library for web and native user interfaces.'
  );
  assert.equal(cleanDescription(['GitHub - facebook/react: A JS library']), null);
  assert.equal(cleanDescription(['  多行\n描述  ']), '多行 描述');
  assert.equal(cleanDescription([]), null);
});

test('buildRepoInfo 优先使用 canonical 地址', () => {
  const info = buildRepoInfo({
    url: 'https://github.com/other/repo/issues/1',
    canonicalUrl: 'https://gitee.com/mindspore/mindspore',
    title: 'MindSpore',
    descriptionCandidates: ['MindSpore is a new open source deep learning framework.'],
    language: 'Python',
    starsText: '1.2k',
    forksText: '345',
  });
  assert.equal(info.platform, 'gitee');
  assert.equal(info.fullName, 'mindspore/mindspore');
  assert.equal(info.stars, 1200);
  assert.equal(info.forks, 345);
  assert.equal(info.language, 'Python');
});

test('buildRepoInfo 对非仓库页返回 null', () => {
  assert.equal(buildRepoInfo({ url: 'https://github.com/explore' }), null);
  assert.equal(buildRepoInfo(null), null);
});

test('buildBookmarkPayload 生成 edge 契约结构', () => {
  const payload = buildBookmarkPayload({
    platform: 'github',
    fullName: 'facebook/react',
    url: 'https://github.com/facebook/react',
    description: 'UI library',
    language: 'JavaScript',
    stars: 220000,
    forks: 45000,
  });
  assert.deepEqual(payload, {
    repo: {
      platform: 'github',
      fullName: 'facebook/react',
      url: 'https://github.com/facebook/react',
      description: 'UI library',
      language: 'JavaScript',
      stars: 220000,
      forks: 45000,
    },
  });
  assert.equal(buildBookmarkPayload(null), null);
});

test('normalizeApiBase 归一化站点地址', () => {
  assert.equal(normalizeApiBase('https://example.com/'), 'https://example.com');
  assert.equal(normalizeApiBase('https://example.com/app/?a=1#top'), 'https://example.com/app');
  assert.equal(normalizeApiBase(' http://localhost:8787 '), 'http://localhost:8787');
  assert.equal(normalizeApiBase('ftp://example.com'), null);
  assert.equal(normalizeApiBase('example.com'), null);
  assert.equal(normalizeApiBase(''), null);
});

test('扩展令牌格式与尾号提示', () => {
  const token = `ofx_${'a'.repeat(64)}`;
  assert.equal(isValidTokenFormat(token), true);
  assert.equal(isValidTokenFormat(`ofx_${'A'.repeat(64)}`), false);
  assert.equal(isValidTokenFormat('ofx_1234'), false);
  assert.equal(isValidTokenFormat(null), false);
  assert.equal(tokenHint(token), 'ofx_…aaaa');
});

test('formatStars 展示为紧凑格式', () => {
  assert.equal(formatStars(0), '0');
  assert.equal(formatStars(999), '999');
  assert.equal(formatStars(1200), '1.2k');
  assert.equal(formatStars(1000000), '1M');
  assert.equal(formatStars(null), '0');
});

test('buildAdminUrl 拼接后台地址', () => {
  assert.equal(buildAdminUrl('https://example.com/', '/settings/extension'), 'https://example.com/settings/extension');
  assert.equal(buildAdminUrl('https://example.com/base', 'repos'), 'https://example.com/base/repos');
  assert.equal(buildAdminUrl('not-a-url'), null);
});

test('manifest 为 MV3 且声明最小权限与快捷键', () => {
  const manifestPath = join(root, 'manifest.json');
  assert.equal(existsSync(manifestPath), true);
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ['activeTab', 'scripting', 'storage']);
  assert.equal(manifest.background.type, 'module');
  assert.equal(manifest.action.default_popup, 'src/popup.html');
  assert.equal(manifest.options_page, 'src/options.html');
  assert.equal(manifest.commands['save-current-page'].suggested_key.default, 'Ctrl+Shift+O');
  for (const file of ['src/popup.html', 'src/options.html', 'src/background.js', 'src/popup.js', 'src/options.js']) {
    assert.equal(existsSync(join(root, file)), true, `${file} 应存在`);
  }
  for (const size of [16, 32, 48, 128]) {
    assert.equal(existsSync(join(root, 'icons', `icon${size}.png`)), true, `icon${size}.png 应存在`);
  }
});
