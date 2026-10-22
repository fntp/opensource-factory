/**
 * Telegram Bot 查询入口纯函数（M8-03）。
 *
 * 职责：
 * - 解析 `/favorites`、`/recommend`、`/trending` 等命令与参数；
 * - 把 D1 查询结果拼装成 Telegram HTML 消息（全部动态内容转义）；
 * - 统一 Star / 分数 / 日期格式化与超长消息分片。
 *
 * 不依赖 Hono / D1 / 网络，便于 node:test 直接覆盖。
 */

/** Telegram 单条消息上限；按 3800 字符打包，留出 HTML 标签余量。 */
export const TELEGRAM_MAX_MESSAGE_CHARS = 4096;
export const TELEGRAM_MESSAGE_TARGET_CHARS = 3800;

/** 单次查询默认返回条数 / 上限。 */
export const TELEGRAM_DEFAULT_LIMIT = 5;
export const TELEGRAM_MAX_LIMIT = 8;

export type TelegramCommand =
  | 'start'
  | 'help'
  | 'favorites'
  | 'recommend'
  | 'trending'
  | 'link'
  | 'unlink'
  | 'unknown';

export interface ParsedTelegramCommand {
  command: TelegramCommand;
  args: string;
}

/** Bot 命令菜单（admin 状态接口与帮助文案共用）。 */
export const TELEGRAM_BOT_COMMANDS = [
  { command: 'favorites', description: '查看我的收藏（可带关键词）' },
  { command: 'recommend', description: '查看今日推荐' },
  { command: 'trending', description: '查看今日热榜（可带语言）' },
  { command: 'link', description: '绑定 OpenFactory 账号' },
  { command: 'unlink', description: '解绑当前会话' },
  { command: 'help', description: '查看帮助' },
] as const;

export interface TelegramFavoriteItem {
  id: string;
  name: string;
  description: string | null;
  html_url: string;
  stars: number | null;
  language: string | null;
  category_name?: string | null;
}

export interface TelegramRecommendationItem {
  id: string;
  owner: string | null;
  name: string | null;
  description: string | null;
  language: string | null;
  stars: number | null;
  score: number | null;
  rerank_score?: number | null;
  reason: string | null;
  url: string | null;
}

export interface TelegramTrendingItem {
  id: string;
  owner: string | null;
  name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  stars: number | null;
  stars_today: number | null;
  star_delta: number | null;
  rank: number | null;
  date?: string | null;
}

const COMMAND_ALIASES: Record<string, TelegramCommand> = {
  '/start': 'start',
  '/help': 'help',
  '/帮助': 'help',
  '/favorites': 'favorites',
  '/fav': 'favorites',
  '/收藏': 'favorites',
  '/recommend': 'recommend',
  '/rec': 'recommend',
  '/推荐': 'recommend',
  '/trending': 'trending',
  '/hot': 'trending',
  '/热榜': 'trending',
  '/link': 'link',
  '/bind': 'link',
  '/绑定': 'link',
  '/unlink': 'unlink',
  '/解绑': 'unlink',
};

/** 解析 Telegram 文本命令；支持 `/command@BotName` 与中文别名。 */
export function parseTelegramCommand(text: string | null | undefined): ParsedTelegramCommand {
  const trimmed = String(text ?? '').trim();
  if (!trimmed) return { command: 'unknown', args: '' };

  const separator = trimmed.search(/\s/);
  const head = (separator === -1 ? trimmed : trimmed.slice(0, separator)).toLowerCase();
  const args = separator === -1 ? '' : trimmed.slice(separator).trim();
  const base = head.split('@')[0] ?? head;
  return { command: COMMAND_ALIASES[base] ?? 'unknown', args };
}

/** HTML 转义（Telegram parse_mode=HTML）。 */
export function escapeTelegramHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 压缩空白并按需截断，避免消息里出现大段换行。 */
export function truncateTelegramText(value: unknown, limit = 100): string {
  const text = String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text || text.length <= limit) return text;
  return `${text.slice(0, Math.max(1, limit - 1)).trimEnd()}…`;
}

/** 千分位整数（不依赖 locale，保证测试稳定）。 */
export function formatInteger(value: number | null | undefined): string {
  const parsed = Number(value ?? 0);
  const number = Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : 0;
  return String(number).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function trimDecimal(value: number): string {
  return value.toFixed(1).replace(/\.0$/, '');
}

/** Star 数紧凑格式：1234 → 1.2k，1234567 → 1.2m。 */
export function formatCompactNumber(value: number | null | undefined): string {
  const number = Math.max(0, Number(value ?? 0));
  if (number >= 1_000_000) return `${trimDecimal(number / 1_000_000)}m`;
  if (number >= 1_000) return `${trimDecimal(number / 1_000)}k`;
  return formatInteger(number);
}

/** 0~1 分数 → 百分比整数。 */
export function formatPercent(value: number | null | undefined): string {
  const number = Number(value ?? 0);
  const clamped = Number.isFinite(number) ? Math.min(1, Math.max(0, number)) : 0;
  return `${Math.round(clamped * 100)}%`;
}

/** 日期标签：YYYY-MM-DD 或 ISO 字符串只取日期部分。 */
export function formatDateLabel(value: string | null | undefined): string {
  const text = String(value ?? '').trim();
  if (!text) return '最新';
  return text.slice(0, 10);
}

/** 收藏查询关键词归一化：去空白、限长。 */
export function normalizeTelegramKeyword(value: string | null | undefined): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 100);
}

/** 单次查询条数：默认 5，最大 8。 */
export function normalizeTelegramLimit(value: unknown, fallback = TELEGRAM_DEFAULT_LIMIT): number {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(parsed, TELEGRAM_MAX_LIMIT);
}

/** 绑定码校验：6 位数字。 */
export function isTelegramLinkCode(value: string): boolean {
  return /^\d{6}$/.test(value.trim());
}

/** chat id 脱敏：只保留末四位。 */
export function maskTelegramChatId(value: string | null | undefined): string {
  const text = String(value ?? '').trim();
  if (!text) return '';
  return text.length > 4 ? `***${text.slice(-4)}` : '***';
}

/** 收藏列表消息。 */
export function buildFavoritesMessage(
  items: TelegramFavoriteItem[],
  options: { keyword?: string } = {}
): string {
  const keyword = normalizeTelegramKeyword(options.keyword);
  const lines: string[] = [];
  lines.push(`<b>🔖 我的收藏</b>${keyword ? ` · 关键词「${escapeTelegramHtml(keyword)}」` : ''}`);

  if (items.length === 0) {
    lines.push('');
    lines.push(keyword ? '没有找到匹配的收藏项目。' : '收藏库还是空的，先去同步 GitHub Star 吧。');
    return lines.join('\n');
  }

  lines.push(`共 ${items.length} 个：`);
  items.forEach((item, index) => {
    const title = item.id || item.name;
    const meta = [
      `⭐ ${formatCompactNumber(item.stars)}`,
      item.language,
      item.category_name,
    ]
      .filter(Boolean)
      .join(' · ');
    lines.push(
      `${index + 1}. <a href="${escapeTelegramHtml(item.html_url)}">${escapeTelegramHtml(title)}</a>${meta ? ` · ${escapeTelegramHtml(meta)}` : ''}`
    );
    const description = truncateTelegramText(item.description, 80);
    if (description) lines.push(`   ${escapeTelegramHtml(description)}`);
  });
  return lines.join('\n');
}

/** 推荐列表消息。 */
export function buildRecommendationsMessage(items: TelegramRecommendationItem[]): string {
  const lines: string[] = ['<b>✨ 今日推荐</b>'];
  if (items.length === 0) {
    lines.push('');
    lines.push('暂无待处理推荐，稍后再来看看。');
    return lines.join('\n');
  }

  lines.push(`共 ${items.length} 个待处理推荐：`);
  items.forEach((item, index) => {
    const owner = item.owner ?? '';
    const name = item.name ?? item.id;
    const title = owner ? `${owner}/${name}` : name;
    const url = item.url ?? (owner ? `https://github.com/${owner}/${name}` : '');
    const score = item.rerank_score && item.rerank_score > 0 ? item.rerank_score : item.score;
    const meta = [
      `匹配度 ${formatPercent(score)}`,
      `⭐ ${formatCompactNumber(item.stars)}`,
      item.language,
    ]
      .filter(Boolean)
      .join(' · ');
    const linked = url
      ? `<a href="${escapeTelegramHtml(url)}">${escapeTelegramHtml(title)}</a>`
      : escapeTelegramHtml(title);
    lines.push(`${index + 1}. ${linked} · ${escapeTelegramHtml(meta)}`);
    const reason = truncateTelegramText(item.reason ?? item.description, 100);
    if (reason) lines.push(`   ${escapeTelegramHtml(reason)}`);
  });
  return lines.join('\n');
}

/** 热榜列表消息。 */
export function buildTrendingMessage(
  items: TelegramTrendingItem[],
  options: { language?: string; date?: string | null } = {}
): string {
  const language = normalizeTelegramKeyword(options.language);
  const date = formatDateLabel(options.date ?? items[0]?.date);
  const lines: string[] = [
    `<b>🔥 今日热榜</b> · ${escapeTelegramHtml(date)}${language ? ` · ${escapeTelegramHtml(language)}` : ''}`,
  ];
  if (items.length === 0) {
    lines.push('');
    lines.push(language ? `没有找到 ${language} 的热榜项目。` : '暂无热榜数据，等待下一次抓取。');
    return lines.join('\n');
  }

  items.forEach((item, index) => {
    const owner = item.owner ?? '';
    const title = owner ? `${owner}/${item.name}` : item.name;
    const delta = item.star_delta ?? item.stars_today ?? 0;
    const meta = [
      `+${formatCompactNumber(delta)} / 日`,
      `⭐ ${formatCompactNumber(item.stars)}`,
      item.language,
    ]
      .filter(Boolean)
      .join(' · ');
    lines.push(
      `${index + 1}. <a href="${escapeTelegramHtml(item.html_url)}">${escapeTelegramHtml(title)}</a> · ${escapeTelegramHtml(meta)}`
    );
    const description = truncateTelegramText(item.description, 80);
    if (description) lines.push(`   ${escapeTelegramHtml(description)}`);
  });
  return lines.join('\n');
}

/** 帮助 / 欢迎消息；未绑定时附带绑定指引。 */
export function buildHelpMessage(options: {
  linked: boolean;
  login?: string | null;
  botUsername?: string | null;
}): string {
  const lines: string[] = ['<b>OpenFactory 查询 Bot</b>', ''];
  if (options.linked) {
    lines.push(`当前已绑定 GitHub 账号 <b>@${escapeTelegramHtml(options.login ?? '未知用户')}</b>。`);
  } else {
    lines.push('当前会话尚未绑定账号。');
    lines.push('请在控制台「设置 → 通知设置 → Telegram 查询 Bot」生成绑定码，然后发送：');
    lines.push('<code>/link 123456</code>');
  }
  lines.push('');
  lines.push('<b>可用命令</b>');
  lines.push('/favorites [关键词] — 查看我的收藏');
  lines.push('/recommend — 查看今日推荐');
  lines.push('/trending [语言] — 查看今日热榜');
  lines.push('/link &lt;绑定码&gt; — 绑定账号');
  lines.push('/unlink — 解绑当前会话');
  lines.push('/help — 显示本帮助');
  if (options.botUsername) {
    lines.push('');
    lines.push(`Bot：@${escapeTelegramHtml(options.botUsername)}`);
  }
  return lines.join('\n');
}

/** 群组 / 频道提示：查询涉及个人数据，只允许私聊。 */
export function buildPrivateOnlyMessage(): string {
  return [
    '请在私聊中使用查询 Bot。',
    '',
    '群组会话无法安全区分成员，可能暴露绑定用户的收藏与推荐数据。',
  ].join('\n');
}

/** 未绑定提示。 */
export function buildUnlinkedMessage(): string {
  return [
    '<b>尚未绑定 OpenFactory 账号</b>',
    '',
    '请打开控制台「设置 → 通知设置 → Telegram 查询 Bot」生成绑定码，然后发送：',
    '<code>/link 123456</code>',
    '',
    '绑定后即可查询收藏、推荐与热榜。',
  ].join('\n');
}

/** 绑定成功提示。 */
export function buildLinkSuccessMessage(login: string | null | undefined): string {
  return [
    '✅ <b>绑定成功</b>',
    '',
    `当前会话已绑定 GitHub 账号 <b>@${escapeTelegramHtml(login || '未知用户')}</b>。`,
    '发送 /favorites、/recommend 或 /trending 开始查询。',
  ].join('\n');
}

/** 未携带绑定码时的用法提示。 */
export function buildLinkUsageMessage(): string {
  return [
    '请发送 <code>/link 123456</code> 完成绑定。',
    '绑定码在控制台「设置 → 通知设置 → Telegram 查询 Bot」生成，10 分钟内有效。',
  ].join('\n');
}

/** 绑定码无效 / 过期提示。 */
export function buildLinkFailureMessage(reason: 'invalid' | 'expired' | 'user_missing' = 'invalid'): string {
  if (reason === 'expired') {
    return '⌛ 绑定码已过期，请回到控制台重新生成。';
  }
  if (reason === 'user_missing') {
    return '绑定失败：生成绑定码的账号不存在，请重新登录控制台后再试。';
  }
  return '绑定码无效，请检查后重试，或回到控制台重新生成。';
}

/** 解绑结果提示。 */
export function buildUnlinkMessage(wasLinked: boolean): string {
  return wasLinked ? '✅ 已解绑当前 Telegram 会话。' : '当前会话尚未绑定账号。';
}

/** 未知命令提示。 */
export function buildUnknownCommandMessage(): string {
  return ['未识别的命令。', '发送 /help 查看可用命令。'].join('\n');
}

/**
 * 按行分片，保证单条不超过 Telegram 上限。
 * 单行超长时按字符硬切（当前消息每行都很短，不会截断 HTML 标签）。
 */
export function chunkTelegramMessage(
  text: string,
  limit = TELEGRAM_MESSAGE_TARGET_CHARS
): string[] {
  const value = String(text ?? '').trim();
  if (!value) return [];
  const safeLimit = Math.max(100, Math.trunc(limit));
  if (value.length <= safeLimit) return [value];

  const parts: string[] = [];
  let current = '';
  for (const line of value.split('\n')) {
    const candidate = current ? `${current}\n${line}` : line;
    if (candidate.length <= safeLimit) {
      current = candidate;
      continue;
    }
    if (current) {
      parts.push(current);
      current = '';
    }
    let rest = line;
    while (rest.length > safeLimit) {
      parts.push(rest.slice(0, safeLimit));
      rest = rest.slice(safeLimit);
    }
    current = rest;
  }
  if (current) parts.push(current);
  return parts;
}
