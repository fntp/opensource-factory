/**
 * 浏览器扩展收藏助手（M8-02）纯函数：
 * - GitHub / Gitee 仓库地址解析与归一化；
 * - 收藏请求体校验（平台 / owner/repo / URL 主机 / 元数据截断）；
 * - 扩展令牌生成、格式校验与尾号提示。
 *
 * 不依赖 Hono / D1，便于 node:test 直接覆盖。
 */

export type RepoPlatform = 'github' | 'gitee';

export interface ParsedRepo {
  platform: RepoPlatform;
  owner: string;
  name: string;
  fullName: string;
  url: string;
}

export interface NormalizedBookmarkRepo extends ParsedRepo {
  id: string;
  description: string | null;
  language: string | null;
  stars: number;
  forks: number;
}

export type NormalizeBookmarkResult =
  | { ok: true; repo: NormalizedBookmarkRepo }
  | { ok: false; error: string };

const PLATFORM_HOSTS: Record<RepoPlatform, string> = {
  github: 'github.com',
  gitee: 'gitee.com',
};

/** GitHub 保留的一级路径，避免把设置 / 市场 / 话题页误判成仓库。 */
const RESERVED_OWNERS = new Set([
  'about',
  'account',
  'apps',
  'codespaces',
  'collections',
  'contact',
  'customer-stories',
  'dashboard',
  'enterprise',
  'events',
  'explore',
  'features',
  'issues',
  'login',
  'logout',
  'marketplace',
  'new',
  'notifications',
  'organizations',
  'orgs',
  'pricing',
  'pulls',
  'readme',
  'search',
  'security',
  'settings',
  'site',
  'sponsors',
  'stars',
  'topics',
  'trending',
  'users',
  'watching',
]);

const OWNER_RE = /^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,63})$/;
const NAME_RE = /^[A-Za-z0-9._-]{1,100}$/;

function trimString(value: unknown, maxLength: number): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized) return null;
  return normalized.slice(0, maxLength);
}

function normalizeCount(value: unknown): number {
  const num =
    typeof value === 'number'
      ? value
      : Number.parseInt(String(value ?? '').replace(/[,_\s]/g, ''), 10);
  if (!Number.isFinite(num) || num <= 0) return 0;
  return Math.min(Math.floor(num), 2_000_000_000);
}

/** 解析 owner/repo（允许前后空格与 .git 后缀）。 */
export function parseRepoFullName(
  value: unknown
): { owner: string; name: string; fullName: string } | null {
  if (typeof value !== 'string') return null;
  const cleaned = value.trim().replace(/\.git$/i, '');
  const parts = cleaned.split('/');
  if (parts.length !== 2) return null;
  const owner = (parts[0] ?? '').trim();
  const name = (parts[1] ?? '').trim();
  if (!owner || !name) return null;
  if (!OWNER_RE.test(owner) || !NAME_RE.test(name)) return null;
  if (RESERVED_OWNERS.has(owner.toLowerCase())) return null;
  return { owner, name, fullName: `${owner}/${name}` };
}

/** 从 GitHub / Gitee 仓库页 URL 解析仓库；非仓库页返回 null。 */
export function parseRepoUrl(raw: unknown): ParsedRepo | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  const platform: RepoPlatform | null =
    host === PLATFORM_HOSTS.github
      ? 'github'
      : host === PLATFORM_HOSTS.gitee
        ? 'gitee'
        : null;
  if (!platform) return null;

  const segments = url.pathname.split('/').filter(Boolean);
  if (segments.length < 2) return null;
  let owner: string;
  let name: string;
  try {
    owner = decodeURIComponent(segments[0] ?? '');
    name = decodeURIComponent(segments[1] ?? '').replace(/\.git$/i, '');
  } catch {
    return null;
  }
  const parsed = parseRepoFullName(`${owner}/${name}`);
  if (!parsed) return null;
  return {
    platform,
    owner: parsed.owner,
    name: parsed.name,
    fullName: parsed.fullName,
    url: `https://${PLATFORM_HOSTS[platform]}/${parsed.fullName}`,
  };
}

/** 归一化收藏请求体；字段非法时返回可读错误。 */
export function normalizeBookmarkPayload(body: unknown): NormalizeBookmarkResult {
  if (!body || typeof body !== 'object') {
    return { ok: false, error: 'invalid_body' };
  }
  const raw = (body as { repo?: unknown }).repo;
  if (!raw || typeof raw !== 'object') {
    return { ok: false, error: 'invalid_repo' };
  }
  const input = raw as Record<string, unknown>;

  const fromUrl = parseRepoUrl(input.url);
  const fromFullName = parseRepoFullName(input.fullName ?? input.id);
  if (!fromUrl && !fromFullName) {
    return { ok: false, error: 'invalid_repo_url' };
  }

  const platformInput = typeof input.platform === 'string' ? input.platform.trim().toLowerCase() : '';
  const platform = (platformInput || fromUrl?.platform || 'github') as RepoPlatform;
  if (platform !== 'github' && platform !== 'gitee') {
    return { ok: false, error: 'invalid_platform' };
  }

  // URL 与 fullName 同时提供时，两者必须指向同一仓库，避免错存。
  if (fromUrl && fromFullName && fromUrl.fullName.toLowerCase() !== fromFullName.fullName.toLowerCase()) {
    return { ok: false, error: 'repo_url_mismatch' };
  }
  if (fromUrl && fromUrl.platform !== platform) {
    return { ok: false, error: 'platform_url_mismatch' };
  }

  const base = fromUrl ?? fromFullName;
  if (!base) return { ok: false, error: 'invalid_repo' };

  return {
    ok: true,
    repo: {
      platform,
      owner: base.owner,
      name: base.name,
      fullName: base.fullName,
      id: base.fullName,
      url: `https://${PLATFORM_HOSTS[platform]}/${base.fullName}`,
      description: trimString(input.description, 500),
      language: trimString(input.language, 40),
      stars: normalizeCount(input.stars),
      forks: normalizeCount(input.forks),
    },
  };
}

export const EXTENSION_TOKEN_PREFIX = 'ofx_';

/** 生成扩展令牌：ofx_ + 64 位十六进制随机串。 */
export function generateExtensionToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return (
    EXTENSION_TOKEN_PREFIX +
    [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
  );
}

/** 令牌格式校验（只接受本系统生成的 ofx_ 前缀）。 */
export function isExtensionTokenFormat(token: unknown): token is string {
  return typeof token === 'string' && /^ofx_[0-9a-f]{64}$/.test(token);
}

/** 令牌尾号提示，例如 ofx_…a1b2；绝不返回完整令牌。 */
export function tokenHint(token: string): string {
  const normalized = token.trim();
  return `${EXTENSION_TOKEN_PREFIX}…${normalized.slice(-4)}`;
}

/** 备注归一化：默认「浏览器扩展」，最长 60 字。 */
export function normalizeTokenLabel(value: unknown): string {
  return trimString(value, 60) ?? '浏览器扩展';
}

/** 稳定令牌 id：tok_ + 16 位十六进制。 */
export function generateTokenId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return 'tok_' + [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export interface ExtensionTokenRowLike {
  id: string;
  user_id: string;
  label: string | null;
  hint: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** D1 行 → 前端 DTO（不含 token_hash）。 */
export function toTokenDto(row: ExtensionTokenRowLike) {
  return {
    id: row.id,
    label: row.label ?? '浏览器扩展',
    hint: row.hint,
    createdAt: row.created_at,
    lastUsedAt: row.last_used_at,
    revokedAt: row.revoked_at,
    status: row.revoked_at ? ('revoked' as const) : ('active' as const),
  };
}
