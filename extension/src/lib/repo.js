/**
 * OpenFactory 收藏助手 · 纯函数库
 *
 * 负责 GitHub / Gitee 仓库地址解析、页面元数据归一化、计数解析与配置校验。
 * 不依赖 chrome.*，可直接用 node:test 覆盖。
 */

const PLATFORM_HOSTS = {
  github: 'github.com',
  gitee: 'gitee.com',
};

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

function cleanText(value, maxLength) {
  if (typeof value !== 'string') return null;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized) return null;
  return normalized.slice(0, maxLength);
}

/** 解析 owner/repo（允许前后空格与 .git 后缀）。 */
export function parseRepoFullName(value) {
  if (typeof value !== 'string') return null;
  const cleaned = value.trim().replace(/\.git$/i, '');
  const parts = cleaned.split('/');
  if (parts.length !== 2) return null;
  const owner = (parts[0] || '').trim();
  const name = (parts[1] || '').trim();
  if (!owner || !name) return null;
  if (!OWNER_RE.test(owner) || !NAME_RE.test(name)) return null;
  if (RESERVED_OWNERS.has(owner.toLowerCase())) return null;
  return { owner, name, fullName: `${owner}/${name}` };
}

/** 从 GitHub / Gitee 仓库页 URL 解析仓库；非仓库页返回 null。 */
export function parseRepoUrl(raw) {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  let url;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  const platform = host === PLATFORM_HOSTS.github ? 'github' : host === PLATFORM_HOSTS.gitee ? 'gitee' : null;
  if (!platform) return null;

  const segments = url.pathname.split('/').filter(Boolean);
  if (segments.length < 2) return null;
  let owner;
  let name;
  try {
    owner = decodeURIComponent(segments[0] || '');
    name = decodeURIComponent(segments[1] || '').replace(/\.git$/i, '');
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

/** 解析 "12,345" / "1.2k" / "3.4万" / "2M" 等页面计数文本。 */
export function parseCountText(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.floor(value));
  if (typeof value !== 'string') return 0;
  const match = value.replace(/,/g, '').match(/(\d+(?:\.\d+)?)\s*([kKmM万])?/);
  if (!match) return 0;
  const num = Number.parseFloat(match[1]);
  if (!Number.isFinite(num)) return 0;
  const unit = (match[2] || '').toLowerCase();
  const multiplier = unit === 'k' ? 1e3 : unit === 'm' ? 1e6 : unit === '万' ? 1e4 : 1;
  return Math.max(0, Math.round(num * multiplier));
}

/** 从多个候选描述中挑选可用的一条（过滤 GitHub 默认 SEO 文案）。 */
export function cleanDescription(candidates) {
  const list = Array.isArray(candidates) ? candidates : [candidates];
  for (const candidate of list) {
    const text = cleanText(candidate, 500);
    if (!text) continue;
    if (/^contribute to .+ development by creating an account on github\.?$/i.test(text)) continue;
    if (/^github\s*[-–—]\s*/i.test(text)) continue;
    return text;
  }
  return null;
}

/** 把页面提取结果归一化为仓库信息；非仓库页返回 null。 */
export function buildRepoInfo(page) {
  if (!page || typeof page !== 'object') return null;
  const canonical = typeof page.canonicalUrl === 'string' ? page.canonicalUrl : '';
  const parsed = parseRepoUrl(canonical) || parseRepoUrl(page.url);
  if (!parsed) return null;
  return {
    ...parsed,
    title: cleanText(page.title, 120),
    description: cleanDescription(page.descriptionCandidates ?? page.description),
    language: cleanText(page.language, 40),
    stars: parseCountText(page.starsText),
    forks: parseCountText(page.forksText),
  };
}

/** 生成 edge `POST /api/extension/bookmark` 请求体。 */
export function buildBookmarkPayload(info) {
  if (!info || !info.fullName || !info.url) return null;
  return {
    repo: {
      platform: info.platform,
      fullName: info.fullName,
      url: info.url,
      description: info.description || null,
      language: info.language || null,
      stars: Number.isFinite(info.stars) ? info.stars : 0,
      forks: Number.isFinite(info.forks) ? info.forks : 0,
    },
  };
}

/** 归一化 API 地址：仅允许 http(s)，去掉末尾斜杠与 query/hash。 */
export function normalizeApiBase(input) {
  if (typeof input !== 'string' || !input.trim()) return null;
  let url;
  try {
    url = new URL(input.trim());
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
  const path = url.pathname.replace(/\/+$/, '');
  return `${url.origin}${path}`;
}

/** 扩展令牌格式：ofx_ + 64 位十六进制。 */
export function isValidTokenFormat(token) {
  return typeof token === 'string' && /^ofx_[0-9a-f]{64}$/.test(token.trim());
}

/** 令牌尾号提示，例如 ofx_…a1b2。 */
export function tokenHint(token) {
  const normalized = String(token || '').trim();
  return `ofx_…${normalized.slice(-4)}`;
}

/** 收藏数展示：1234 → 1.2k，1234567 → 1.2M。 */
export function formatStars(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return '0';
  if (num >= 1e6) return `${(num / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
  if (num >= 1e3) return `${(num / 1e3).toFixed(1).replace(/\.0$/, '')}k`;
  return String(Math.floor(num));
}

/** 根据页面 URL 与 API 地址拼出后台仓库页地址。 */
export function buildAdminUrl(apiBase, path = '/repos') {
  const base = normalizeApiBase(apiBase);
  if (!base) return null;
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}
