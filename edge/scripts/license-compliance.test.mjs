import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildLicenseHint,
  catalogPayload,
  licenseFromRow,
  normalizeSpdx,
  summarizeLicenseRows,
} from '../src/license/compliance.ts';
import { toTrendingDetail } from '../src/trending/detail.ts';

test('normalizeSpdx 支持常见写法与 SPDX 后缀', () => {
  assert.equal(normalizeSpdx('MIT'), 'MIT');
  assert.equal(normalizeSpdx('mit'), 'MIT');
  assert.equal(normalizeSpdx('Apache 2.0'), 'Apache-2.0');
  assert.equal(normalizeSpdx('GPL-3.0-only'), 'GPL-3.0');
  assert.equal(normalizeSpdx('AGPL-3.0-or-later'), 'AGPL-3.0');
  assert.equal(normalizeSpdx('LGPL-2.1+'), 'LGPL-2.1');
  assert.equal(normalizeSpdx('BSD 3-Clause'), 'BSD-3-Clause');
  assert.equal(normalizeSpdx('NOASSERTION'), null);
  assert.equal(normalizeSpdx('NoSuchLicense-1.0'), null);
});

test('buildLicenseHint 输出分类、风险与义务', () => {
  const mit = buildLicenseHint('MIT', 'MIT License', { source: 'github' });
  assert.equal(mit.category, 'permissive');
  assert.equal(mit.riskLevel, 'low');
  assert.equal(mit.source, 'github');
  assert.ok(mit.obligations.length > 0);

  const agpl = buildLicenseHint('AGPL-3.0', 'AGPL', { source: 'readme' });
  assert.equal(agpl.category, 'network-copyleft');
  assert.equal(agpl.riskLevel, 'high');
  assert.ok(agpl.warnings.length > 0);

  const unknown = buildLicenseHint(null, null, { source: 'none' });
  assert.equal(unknown.category, 'unknown');
  assert.equal(unknown.riskLevel, 'unknown');
  assert.ok(unknown.warnings.includes('无许可证不等于可以自由使用'));
});

test('licenseFromRow 未识别过返回 null', () => {
  assert.equal(licenseFromRow(null), null);
  assert.equal(licenseFromRow({ license_spdx: null, license_source: null }), null);
  const hint = licenseFromRow({
    license_spdx: 'GPL-3.0',
    license_name: 'GNU General Public License 3.0',
    license_source: 'github',
    license_checked_at: '2026-10-22T08:00:00',
  });
  assert.equal(hint.spdxId, 'GPL-3.0');
  assert.equal(hint.riskLevel, 'high');
  assert.equal(hint.checkedAt, '2026-10-22T08:00:00');
});

test('catalog 与 summary 统计口径一致', () => {
  const catalog = catalogPayload();
  assert.ok(catalog.licenses.length >= 10);
  assert.ok(catalog.categories.some((item) => item.key === 'strong-copyleft'));

  const summary = summarizeLicenseRows([
    { license_spdx: 'MIT', license_name: 'MIT License', license_source: 'github' },
    { license_spdx: 'MIT', license_name: 'MIT License', license_source: 'readme' },
    { license_spdx: 'AGPL-3.0', license_name: 'AGPL', license_source: 'github' },
    { license_spdx: null, license_name: null, license_source: 'none' },
    { license_spdx: null, license_name: null, license_source: null },
  ]);
  assert.equal(summary.total, 5);
  assert.equal(summary.known, 3);
  assert.equal(summary.unknown, 2);
  assert.equal(summary.checked, 4);
  assert.equal(summary.unchecked, 1);
  assert.equal(summary.riskCounts.low, 2);
  assert.equal(summary.riskCounts.high, 1);
  assert.equal(summary.riskCounts.unknown, 2);
});

test('trending 详情 DTO 携带 license', () => {
  const trendingRow = {
    id: 'openai/whisper',
    platform: 'github',
    name: 'whisper',
    html_url: 'https://github.com/openai/whisper',
    stars_today: 100,
    description: null,
    tech_stack: null,
    crawled_at: '2026-10-22',
    owner: 'openai',
    language: 'Python',
    stars: 1000,
    readme_summary: null,
    license_spdx: 'AGPL-3.0',
    license_name: 'AGPL',
    license_source: 'github',
    license_checked_at: '2026-10-22T08:00:00',
  };
  const detail = toTrendingDetail(trendingRow);
  assert.equal(detail.license.spdxId, 'AGPL-3.0');
  assert.equal(detail.license.riskLevel, 'high');
  assert.equal(detail.license.source, 'github');
});
