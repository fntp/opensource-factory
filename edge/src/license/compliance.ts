/**
 * License 识别与合规提示（M6-06）。
 *
 * 与 `vps/app/services/license.py` 保持同一套口径：VPS 负责识别与落库，
 * edge 负责按目录把 `license_spdx` 映射为前端可直接展示的合规提示。
 * 纯函数、无 D1 依赖，便于 node:test 直接覆盖。
 *
 * 说明：合规提示仅为工程辅助信息，不构成法律意见。
 */

export type LicenseCategory =
  | 'permissive'
  | 'weak-copyleft'
  | 'strong-copyleft'
  | 'network-copyleft'
  | 'public-domain'
  | 'unknown';

export type LicenseRisk = 'low' | 'medium' | 'high' | 'unknown';

export interface LicenseInfo {
  spdxId: string | null;
  name: string | null;
  category: LicenseCategory;
  categoryLabel: string;
  riskLevel: LicenseRisk;
  riskLabel: string;
  summary: string;
  obligations: string[];
  warnings: string[];
  source: string | null;
  checkedAt: string | null;
}

export interface LicenseDefinition {
  spdxId: string;
  name: string;
  category: Exclude<LicenseCategory, 'unknown'>;
  riskLevel: Exclude<LicenseRisk, 'unknown'>;
  summary: string;
  obligations: string[];
  warnings: string[];
}

export const CATEGORY_LABELS: Record<LicenseCategory, string> = {
  permissive: '宽松许可',
  'weak-copyleft': '弱著佐权',
  'strong-copyleft': '强著佐权',
  'network-copyleft': '网络著佐权',
  'public-domain': '公共领域',
  unknown: '未知许可',
};

export const CATEGORY_DESCRIPTIONS: Record<LicenseCategory, string> = {
  permissive: '允许商用、修改、再分发与闭源衍生，通常只需保留版权与许可证声明。',
  'weak-copyleft': '允许与闭源代码组合，但修改过的库文件本身需要以同许可证开源。',
  'strong-copyleft': '分发衍生作品时，衍生作品整体需要以同许可证开源。',
  'network-copyleft': '通过网络提供服务也可能被视为分发，需要向用户提供源码。',
  'public-domain': '作者放弃版权或贡献到公共领域，几乎没有强制义务。',
  unknown: '未识别到有效许可证，默认保留所有权利，使用前需要获得作者授权。',
};

export const RISK_LABELS: Record<LicenseRisk, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  unknown: '未知风险',
};

export const LICENSE_CATALOG: LicenseDefinition[] = [
  {
    spdxId: 'MIT',
    name: 'MIT License',
    category: 'permissive',
    riskLevel: 'low',
    summary: '允许商用、修改、再分发与闭源衍生，需保留版权与许可证声明。',
    obligations: ['保留版权声明', '保留许可证文本'],
    warnings: [],
  },
  {
    spdxId: 'Apache-2.0',
    name: 'Apache License 2.0',
    category: 'permissive',
    riskLevel: 'low',
    summary: '允许商用、修改、再分发与专利授权，需保留许可证与 NOTICE 文件并标注修改。',
    obligations: ['保留许可证文本', '保留 NOTICE 文件', '标注修改过的文件'],
    warnings: [],
  },
  {
    spdxId: 'BSD-2-Clause',
    name: 'BSD 2-Clause License',
    category: 'permissive',
    riskLevel: 'low',
    summary: '允许商用、修改与再分发，需保留版权声明与免责声明。',
    obligations: ['保留版权声明', '保留免责声明'],
    warnings: [],
  },
  {
    spdxId: 'BSD-3-Clause',
    name: 'BSD 3-Clause License',
    category: 'permissive',
    riskLevel: 'low',
    summary: '允许商用、修改与再分发，需保留版权声明，且不得用作者名义为衍生品背书。',
    obligations: ['保留版权声明', '不得使用作者名义背书'],
    warnings: [],
  },
  {
    spdxId: 'ISC',
    name: 'ISC License',
    category: 'permissive',
    riskLevel: 'low',
    summary: '与 MIT 等价的宽松许可，需保留版权与许可证声明。',
    obligations: ['保留版权声明', '保留许可证文本'],
    warnings: [],
  },
  {
    spdxId: 'Zlib',
    name: 'zlib License',
    category: 'permissive',
    riskLevel: 'low',
    summary: '允许商用与修改，需保留来源声明，且不得歪曲软件来源。',
    obligations: ['保留来源声明', '不得歪曲来源'],
    warnings: [],
  },
  {
    spdxId: '0BSD',
    name: 'BSD Zero Clause License',
    category: 'public-domain',
    riskLevel: 'low',
    summary: '近乎公共领域，允许任意使用，无需保留版权声明。',
    obligations: [],
    warnings: [],
  },
  {
    spdxId: 'MPL-2.0',
    name: 'Mozilla Public License 2.0',
    category: 'weak-copyleft',
    riskLevel: 'medium',
    summary: '文件级著佐权：修改过的 MPL 文件需以 MPL 开源，其他文件可闭源。',
    obligations: ['修改的 MPL 文件需开源', '保留许可证与源码获取方式'],
    warnings: ['与 GPL 组合时需确认兼容性'],
  },
  {
    spdxId: 'LGPL-2.1',
    name: 'GNU Lesser General Public License 2.1',
    category: 'weak-copyleft',
    riskLevel: 'medium',
    summary: '允许动态链接闭源程序，但修改库本身需以 LGPL 开源。',
    obligations: ['修改的库需开源', '允许用户替换库版本'],
    warnings: [],
  },
  {
    spdxId: 'LGPL-3.0',
    name: 'GNU Lesser General Public License 3.0',
    category: 'weak-copyleft',
    riskLevel: 'medium',
    summary: '允许动态链接闭源程序，但修改库本身需以 LGPL 开源，并保留安装信息。',
    obligations: ['修改的库需开源', '提供安装信息以便替换库'],
    warnings: [],
  },
  {
    spdxId: 'EPL-2.0',
    name: 'Eclipse Public License 2.0',
    category: 'weak-copyleft',
    riskLevel: 'medium',
    summary: '修改过的 EPL 文件需以 EPL 开源，其他代码可闭源；含专利授权。',
    obligations: ['修改的 EPL 文件需开源', '保留许可证与专利条款'],
    warnings: [],
  },
  {
    spdxId: 'GPL-2.0',
    name: 'GNU General Public License 2.0',
    category: 'strong-copyleft',
    riskLevel: 'high',
    summary: '分发衍生作品时，衍生作品整体需以 GPL-2.0 开源并提供源码。',
    obligations: ['衍生作品需以 GPL 开源', '分发时提供完整源码'],
    warnings: ['闭源商用分发通常不可行'],
  },
  {
    spdxId: 'GPL-3.0',
    name: 'GNU General Public License 3.0',
    category: 'strong-copyleft',
    riskLevel: 'high',
    summary: '分发衍生作品时，衍生作品整体需以 GPL-3.0 开源，并禁止额外限制。',
    obligations: ['衍生作品需以 GPL 开源', '分发时提供完整源码', '不得附加额外限制'],
    warnings: ['闭源商用分发通常不可行', '含专利授权与反 Tivoization 条款'],
  },
  {
    spdxId: 'AGPL-3.0',
    name: 'GNU Affero General Public License 3.0',
    category: 'network-copyleft',
    riskLevel: 'high',
    summary: '通过网络向用户提供服务也可能触发源码开放义务，影响 SaaS 场景。',
    obligations: ['网络服务需提供完整源码', '衍生作品需以 AGPL 开源'],
    warnings: ['SaaS / 托管服务需重点评估', '闭源商用通常不可行'],
  },
  {
    spdxId: 'Unlicense',
    name: 'The Unlicense',
    category: 'public-domain',
    riskLevel: 'low',
    summary: '贡献到公共领域，允许任意使用，无强制义务。',
    obligations: [],
    warnings: ['建议保留出处与免责声明'],
  },
  {
    spdxId: 'CC0-1.0',
    name: 'Creative Commons Zero 1.0',
    category: 'public-domain',
    riskLevel: 'low',
    summary: '放弃版权与相关权利，允许任意使用，无强制义务。',
    obligations: [],
    warnings: ['建议保留出处'],
  },
];

const CATALOG_BY_SPDX = new Map<string, LicenseDefinition>(
  LICENSE_CATALOG.map((item) => [item.spdxId, item])
);

/** 仅保留字母数字的小写形式，用于别名匹配 */
function aliasKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

const ALIASES = new Map<string, string>();

function registerAliases(spdx: string, ...aliases: string[]): void {
  ALIASES.set(aliasKey(spdx), spdx);
  for (const alias of aliases) ALIASES.set(aliasKey(alias), spdx);
}

registerAliases('MIT', 'MIT License', 'The MIT License', 'Expat');
registerAliases('Apache-2.0', 'Apache 2.0', 'Apache License 2.0', 'Apache License, Version 2.0', 'Apache-2');
registerAliases('BSD-2-Clause', 'BSD 2-Clause', 'BSD 2-Clause License', 'Simplified BSD', 'FreeBSD');
registerAliases('BSD-3-Clause', 'BSD 3-Clause', 'BSD 3-Clause License', 'New BSD', 'Modified BSD');
registerAliases('ISC', 'ISC License');
registerAliases('Zlib', 'zlib License', 'zlib/libpng');
registerAliases('0BSD', 'BSD Zero Clause License', 'Zero-Clause BSD');
registerAliases('MPL-2.0', 'MPL 2.0', 'Mozilla Public License 2.0', 'Mozilla Public License, Version 2.0');
registerAliases('LGPL-2.1', 'LGPL 2.1', 'LGPLv2.1', 'GNU Lesser General Public License 2.1');
registerAliases('LGPL-3.0', 'LGPL 3.0', 'LGPLv3', 'GNU Lesser General Public License 3.0');
registerAliases('EPL-2.0', 'EPL 2.0', 'Eclipse Public License 2.0', 'Eclipse Public License, Version 2.0');
registerAliases('GPL-2.0', 'GPL 2.0', 'GPLv2', 'GNU General Public License 2.0', 'GNU General Public License, Version 2');
registerAliases('GPL-3.0', 'GPL 3.0', 'GPLv3', 'GNU General Public License 3.0', 'GNU General Public License, Version 3');
registerAliases('AGPL-3.0', 'AGPL 3.0', 'AGPLv3', 'GNU Affero General Public License 3.0', 'GNU Affero General Public License, Version 3');
registerAliases('Unlicense', 'The Unlicense');
registerAliases('CC0-1.0', 'CC0 1.0', 'CC0', 'Creative Commons Zero 1.0');

/** SPDX 标识 / 名称 / GitHub license key → 目录中的 SPDX；无法识别返回 null */
export function normalizeSpdx(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  if (['NOASSERTION', 'NONE', 'UNKNOWN', 'OTHER'].includes(raw.toUpperCase())) return null;

  const direct = CATALOG_BY_SPDX.get(raw);
  if (direct) return direct.spdxId;

  // SPDX 版本后缀：-only / -or-later / + 统一归到基础版本
  const stripped = raw.replace(/-(?:only|or-later)$/i, '').replace(/\+$/, '');
  const strippedDirect = CATALOG_BY_SPDX.get(stripped);
  if (strippedDirect) return strippedDirect.spdxId;

  const cleaned = raw.replace(/\([^)]*\)/g, ' ');
  return ALIASES.get(aliasKey(cleaned)) ?? null;
}

export interface LicenseRowFields {
  license_spdx?: string | null;
  license_name?: string | null;
  license_source?: string | null;
  license_checked_at?: string | null;
}

/** 构造前端展示用的合规提示 */
export function buildLicenseHint(
  spdxId: unknown = null,
  name: unknown = null,
  options: { source?: string | null; checkedAt?: string | null } = {}
): LicenseInfo {
  const normalized = normalizeSpdx(spdxId) ?? normalizeSpdx(name);
  if (normalized) {
    const definition = CATALOG_BY_SPDX.get(normalized)!;
    return {
      spdxId: definition.spdxId,
      name: definition.name,
      category: definition.category,
      categoryLabel: CATEGORY_LABELS[definition.category],
      riskLevel: definition.riskLevel,
      riskLabel: RISK_LABELS[definition.riskLevel],
      summary: definition.summary,
      obligations: [...definition.obligations],
      warnings: [...definition.warnings],
      source: options.source ?? null,
      checkedAt: options.checkedAt ?? null,
    };
  }

  return {
    spdxId: null,
    name: name ? String(name).trim() || null : null,
    category: 'unknown',
    categoryLabel: CATEGORY_LABELS.unknown,
    riskLevel: 'unknown',
    riskLabel: RISK_LABELS.unknown,
    summary: '未识别到有效许可证，默认保留所有权利；复制、修改、分发或商用前需联系作者获取明确授权。',
    obligations: ['使用前联系作者获取授权', '保留原始出处与作者信息'],
    warnings: ['无许可证不等于可以自由使用', '商用 / SaaS 场景建议进行法务复核'],
    source: options.source ?? null,
    checkedAt: options.checkedAt ?? null,
  };
}

/** D1 行 → LicenseInfo；从未识别过返回 null */
export function licenseFromRow(row: LicenseRowFields | null | undefined): LicenseInfo | null {
  if (!row) return null;
  if (!row.license_spdx && !row.license_source) return null;
  return buildLicenseHint(row.license_spdx, row.license_name, {
    source: row.license_source ?? null,
    checkedAt: row.license_checked_at ?? null,
  });
}

export interface LicenseCatalogPayload {
  categories: Array<{ key: LicenseCategory; label: string; description: string }>;
  licenses: LicenseDefinition[];
}

export function catalogPayload(): LicenseCatalogPayload {
  return {
    categories: (Object.keys(CATEGORY_LABELS) as LicenseCategory[]).map((key) => ({
      key,
      label: CATEGORY_LABELS[key],
      description: CATEGORY_DESCRIPTIONS[key],
    })),
    licenses: LICENSE_CATALOG.map((item) => ({
      ...item,
      obligations: [...item.obligations],
      warnings: [...item.warnings],
    })),
  };
}

export interface LicenseSummary {
  total: number;
  known: number;
  unknown: number;
  checked: number;
  unchecked: number;
  riskCounts: Record<LicenseRisk, number>;
  licenses: Array<{
    spdxId: string | null;
    name: string;
    count: number;
    category: LicenseCategory;
    categoryLabel: string;
    riskLevel: LicenseRisk;
  }>;
}

/** 按 (spdx, name, source) 行统计许可证与风险分布 */
export function summarizeLicenseRows(rows: LicenseRowFields[]): LicenseSummary {
  const counts = new Map<
    string,
    {
      spdxId: string | null;
      name: string;
      count: number;
      category: LicenseCategory;
      categoryLabel: string;
      riskLevel: LicenseRisk;
    }
  >();
  const riskCounts: Record<LicenseRisk, number> = { low: 0, medium: 0, high: 0, unknown: 0 };
  let checked = 0;

  for (const row of rows) {
    const hint = buildLicenseHint(row.license_spdx, row.license_name);
    const key = hint.spdxId ?? '__unknown__';
    const entry = counts.get(key) ?? {
      spdxId: hint.spdxId,
      name: hint.name ?? '未识别',
      count: 0,
      category: hint.category,
      categoryLabel: hint.categoryLabel,
      riskLevel: hint.riskLevel,
    };
    entry.count += 1;
    counts.set(key, entry);
    riskCounts[hint.riskLevel] += 1;
    if (row.license_source) checked += 1;
  }

  const licenses = [...counts.values()].sort(
    (a, b) => b.count - a.count || String(a.name).localeCompare(String(b.name))
  );
  const total = rows.length;
  return {
    total,
    known: licenses.filter((item) => item.spdxId).reduce((sum, item) => sum + item.count, 0),
    unknown: licenses.filter((item) => !item.spdxId).reduce((sum, item) => sum + item.count, 0),
    checked,
    unchecked: Math.max(0, total - checked),
    riskCounts,
    licenses,
  };
}
