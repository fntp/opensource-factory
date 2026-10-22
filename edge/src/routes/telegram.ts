/**
 * Telegram Bot 查询入口（M8-03）。
 *
 * 登录态接口（admin 设置页）：
 *   GET    /api/telegram/status     配置 / 绑定状态
 *   POST   /api/telegram/link-code  生成 6 位绑定码（10 分钟有效，只存摘要）
 *   DELETE /api/telegram/link       解绑当前用户的 Telegram 会话
 *
 * Bot webhook（Telegram → edge，X-Telegram-Bot-Api-Secret-Token 鉴权）：
 *   POST   /api/telegram/webhook
 *     /favorites [关键词] / /recommend / /trending [语言]
 *     /link <绑定码> / /unlink / /help
 *
 * 设计：webhook 与查询全部在 edge Worker 完成，不经过 VPS；
 * 所有数据查询都带 user_id，未绑定会话不返回任何用户数据。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type {
  Env,
  RecommendationRow,
  TelegramLinkCodeRow,
  TelegramLinkRow,
  TrendingRow,
  TrendingSnapshotRow,
  UserRow,
  Variables,
} from '../types';
import { all, first, run } from '../db';
import { sha256Hex, timingSafeEqualHex } from '../security/crypto.ts';
import {
  buildFavoritesMessage,
  buildHelpMessage,
  buildLinkFailureMessage,
  buildLinkSuccessMessage,
  buildLinkUsageMessage,
  buildPrivateOnlyMessage,
  buildRecommendationsMessage,
  buildTrendingMessage,
  buildUnlinkedMessage,
  buildUnknownCommandMessage,
  buildUnlinkMessage,
  chunkTelegramMessage,
  isTelegramLinkCode,
  maskTelegramChatId,
  normalizeTelegramKeyword,
  normalizeTelegramLimit,
  parseTelegramCommand,
  TELEGRAM_BOT_COMMANDS,
  TELEGRAM_DEFAULT_LIMIT,
  type TelegramFavoriteItem,
  type TelegramRecommendationItem,
  type TelegramTrendingItem,
} from '../telegram/bot.ts';

type AppEnv = { Bindings: Env; Variables: Variables };
type AppContext = Context<AppEnv>;

const telegram = new Hono<AppEnv>();

const LINK_CODE_TTL_MS = 10 * 60 * 1000;
const WEBHOOK_SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token';
const DEFAULT_API_BASE = 'https://api.telegram.org';

interface TelegramUpdate {
  update_id?: number;
  message?: {
    message_id?: number;
    text?: string;
    chat?: {
      id?: number | string;
      type?: string;
      username?: string;
    };
    from?: {
      id?: number;
      username?: string;
      is_bot?: boolean;
    };
  };
}

interface TelegramLinkWithLogin extends TelegramLinkRow {
  login: string | null;
}

interface TelegramStatusResponse {
  configured: boolean;
  botUsername: string | null;
  webhookPath: string;
  linked: boolean;
  link: {
    chatId: string;
    username: string | null;
    login: string | null;
    linkedAt: string;
    lastSeenAt: string | null;
  } | null;
  commands: typeof TELEGRAM_BOT_COMMANDS;
}

function telegramConfigured(env: Env): boolean {
  return Boolean((env.TELEGRAM_BOT_TOKEN ?? '').trim() && (env.TELEGRAM_WEBHOOK_SECRET ?? '').trim());
}

/** Bot 用户名归一化：去掉配置里可能误带的 @。 */
function telegramBotUsername(env: Env): string {
  return (env.TELEGRAM_BOT_USERNAME ?? '').trim().replace(/^@+/, '');
}

/** 生成 6 位数字绑定码（crypto 随机 + 拒绝采样，避免取模偏差）。 */
export function generateLinkCode(): string {
  const bytes = new Uint32Array(1);
  const max = Math.floor(0x1_0000_0000 / 1_000_000) * 1_000_000;
  let value = 0;
  do {
    crypto.getRandomValues(bytes);
    value = bytes[0] ?? 0;
  } while (value >= max);
  return String(value % 1_000_000).padStart(6, '0');
}

/** Telegram API 根地址（去掉末尾斜杠，默认官方地址）。 */
function apiBase(env: Env): string {
  const configured = (env.TELEGRAM_API_BASE ?? '').trim();
  return (configured || DEFAULT_API_BASE).replace(/\/+$/, '');
}

/**
 * 调用 Bot API sendMessage；失败只记录状态码，不输出 token。
 * 返回是否发送成功，调用方不因回复失败而让 webhook 500（避免 Telegram 反复重试）。
 */
async function sendTelegramMessage(env: Env, chatId: string, text: string): Promise<boolean> {
  const token = (env.TELEGRAM_BOT_TOKEN ?? '').trim();
  if (!token) return false;

  const chunks = chunkTelegramMessage(text);
  for (const chunk of chunks) {
    try {
      const response = await fetch(`${apiBase(env)}/bot${token}/sendMessage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_id: chatId,
          text: chunk,
          parse_mode: 'HTML',
          disable_web_page_preview: true,
        }),
      });
      if (!response.ok) {
        console.error('telegram sendMessage failed:', response.status);
        return false;
      }
    } catch (err) {
      console.error('telegram sendMessage error:', err instanceof Error ? err.message : 'unknown');
      return false;
    }
  }
  return true;
}

/** 按 chat_id 查绑定用户（联表取 login；用户已删除时视为未绑定）。 */
async function findLinkByChat(db: D1Database, chatId: string): Promise<TelegramLinkWithLogin | null> {
  return first<TelegramLinkWithLogin>(
    db,
    `SELECT l.*, u.login AS login
       FROM telegram_links l
       LEFT JOIN users u ON u.id = l.user_id
      WHERE l.chat_id = ?`,
    [chatId]
  );
}

async function touchLink(db: D1Database, chatId: string, nowIso: string): Promise<void> {
  await run(db, 'UPDATE telegram_links SET last_seen_at = ? WHERE chat_id = ?', [nowIso, chatId]);
}

/** 收藏查询：仅当前用户，关键词匹配 name / description / id。 */
async function queryFavorites(
  db: D1Database,
  userId: string,
  keyword: string,
  limit: number
): Promise<TelegramFavoriteItem[]> {
  const rows = await all<TelegramFavoriteItem>(
    db,
    `SELECT m.id, m.name, m.description, m.html_url, m.stars, m.language,
            c.name AS category_name
       FROM my_repositories m
       LEFT JOIN categories c ON c.id = m.category_id
      WHERE m.user_id = ?
        AND (? = ''
             OR instr(lower(m.name), lower(?)) > 0
             OR instr(lower(COALESCE(m.description, '')), lower(?)) > 0
             OR instr(lower(m.id), lower(?)) > 0)
      ORDER BY m.stars DESC, m.id ASC
      LIMIT ?`,
    [userId, keyword, keyword, keyword, keyword, limit]
  );
  return rows;
}

/** 推荐查询：只取待处理（new / NULL），精排分优先。 */
async function queryRecommendations(
  db: D1Database,
  userId: string,
  limit: number
): Promise<TelegramRecommendationItem[]> {
  const rows = await all<RecommendationRow>(
    db,
    `SELECT *
       FROM recommendations
      WHERE user_id = ?
        AND (status = 'new' OR status IS NULL)
      ORDER BY COALESCE(NULLIF(rerank_score, 0), score, 0) DESC,
               created_at DESC,
               id ASC
      LIMIT ?`,
    [userId, limit]
  );
  return rows.map((row) => ({
    id: row.id,
    owner: row.owner,
    name: row.name,
    description: row.description,
    language: row.language,
    stars: row.stars,
    score: row.score,
    rerank_score: row.rerank_score ?? null,
    reason: row.reason,
    url: row.url,
  }));
}

/** 热榜：最新快照优先，无快照回退 trending_repositories。 */
async function queryTrending(
  db: D1Database,
  language: string,
  limit: number
): Promise<{ items: TelegramTrendingItem[]; date: string | null }> {
  const latest = await first<{ d: string | null }>(
    db,
    'SELECT MAX(snapshot_date) AS d FROM trending_snapshots'
  );
  const snapshotDate = latest?.d ?? '';

  if (snapshotDate) {
    const rows = await all<TrendingSnapshotRow>(
      db,
      `SELECT *
         FROM trending_snapshots
        WHERE snapshot_date = ?
          AND (? = '' OR lower(language) = lower(?))
        ORDER BY rank ASC, repo_id ASC
        LIMIT ?`,
      [snapshotDate, language, language, limit]
    );
    if (rows.length > 0) {
      return {
        date: snapshotDate,
        items: rows.map((row) => ({
          id: row.repo_id,
          owner: row.owner,
          name: row.name,
          html_url: row.html_url,
          description: row.description,
          language: row.language,
          stars: row.stars,
          stars_today: row.stars_today,
          star_delta: row.star_delta,
          rank: row.rank,
          date: row.snapshot_date,
        })),
      };
    }
    // 明确带语言但当天无匹配：不回退到全量，避免给出误导结果
    if (language) return { items: [], date: snapshotDate };
  }

  const rows = await all<TrendingRow & { date?: string | null }>(
    db,
    `SELECT *, crawled_at AS date
       FROM trending_repositories
      WHERE (? = '' OR lower(language) = lower(?))
      ORDER BY stars_today DESC, id ASC
      LIMIT ?`,
    [language, language, limit]
  );
  return {
    date: rows[0]?.date ?? null,
    items: rows.map((row, index) => ({
      id: row.id,
      owner: row.owner,
      name: row.name,
      html_url: row.html_url,
      description: row.description,
      language: row.language,
      stars: row.stars,
      stars_today: row.stars_today,
      star_delta: row.stars_today,
      rank: index + 1,
      date: row.crawled_at,
    })),
  };
}

/** 绑定：校验绑定码 → 删除旧绑定 → 写入新绑定（一人一聊）。 */
async function bindChat(
  db: D1Database,
  chatId: string,
  username: string | null,
  code: string
): Promise<string> {
  const normalized = code.trim();
  if (!isTelegramLinkCode(normalized)) return buildLinkFailureMessage('invalid');

  const codeHash = await sha256Hex(normalized);
  const row = await first<TelegramLinkCodeRow>(
    db,
    'SELECT * FROM telegram_link_codes WHERE code_hash = ?',
    [codeHash]
  );
  if (!row) return buildLinkFailureMessage('invalid');

  const expiresAt = Date.parse(row.expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await run(db, 'DELETE FROM telegram_link_codes WHERE code_hash = ?', [codeHash]);
    return buildLinkFailureMessage('expired');
  }

  const user = await first<UserRow>(db, 'SELECT * FROM users WHERE id = ?', [row.user_id]);
  if (!user) {
    await run(db, 'DELETE FROM telegram_link_codes WHERE user_id = ?', [row.user_id]);
    return buildLinkFailureMessage('user_missing');
  }

  const now = new Date().toISOString();
  await run(db, 'DELETE FROM telegram_links WHERE chat_id = ? OR user_id = ?', [chatId, row.user_id]);
  await run(
    db,
    `INSERT INTO telegram_links (chat_id, user_id, username, linked_at, last_seen_at)
     VALUES (?, ?, ?, ?, ?)`,
    [chatId, row.user_id, username, now, now]
  );
  await run(db, 'DELETE FROM telegram_link_codes WHERE user_id = ?', [row.user_id]);
  return buildLinkSuccessMessage(user.login);
}

/** 处理一条 Telegram 文本消息，返回要回复的 HTML 文案。 */
async function handleTextMessage(
  env: Env,
  chatId: string,
  username: string | null,
  text: string
): Promise<string> {
  const { command, args } = parseTelegramCommand(text);
  const link = await findLinkByChat(env.DB, chatId);

  if (command === 'help' || command === 'start') {
    // 支持 t.me/<bot>?start=<绑定码> 深链
    if (command === 'start' && isTelegramLinkCode(args)) {
      return bindChat(env.DB, chatId, username, args);
    }
    return buildHelpMessage({
      linked: Boolean(link?.login),
      login: link?.login ?? null,
      botUsername: telegramBotUsername(env) || null,
    });
  }

  if (command === 'link') {
    if (!args) return buildLinkUsageMessage();
    return bindChat(env.DB, chatId, username, args);
  }

  if (command === 'unlink') {
    const result = await run(env.DB, 'DELETE FROM telegram_links WHERE chat_id = ?', [chatId]);
    return buildUnlinkMessage((result.meta?.changes ?? 0) > 0);
  }

  if (command === 'unknown') {
    return buildUnknownCommandMessage();
  }

  // 查询类命令必须先绑定，且绑定用户仍然存在
  if (!link || !link.login) {
    return buildUnlinkedMessage();
  }

  const limit = normalizeTelegramLimit(TELEGRAM_DEFAULT_LIMIT);
  let reply: string;
  if (command === 'favorites') {
    const keyword = normalizeTelegramKeyword(args);
    const items = await queryFavorites(env.DB, link.user_id, keyword, limit);
    reply = buildFavoritesMessage(items, { keyword });
  } else if (command === 'recommend') {
    const items = await queryRecommendations(env.DB, link.user_id, limit);
    reply = buildRecommendationsMessage(items);
  } else {
    const language = normalizeTelegramKeyword(args);
    const result = await queryTrending(env.DB, language, limit);
    reply = buildTrendingMessage(result.items, { language, date: result.date });
  }

  await touchLink(env.DB, chatId, new Date().toISOString());
  return reply;
}

// ── Bot webhook ─────────────────────────────────────────────────

telegram.post('/webhook', async (c) => {
  const secret = (c.env.TELEGRAM_WEBHOOK_SECRET ?? '').trim();
  const token = (c.env.TELEGRAM_BOT_TOKEN ?? '').trim();
  if (!secret || !token) {
    return c.json({ error: 'telegram_not_configured' }, 503);
  }

  const provided = (c.req.header(WEBHOOK_SECRET_HEADER) ?? '').trim();
  if (!provided || !timingSafeEqualHex(provided, secret)) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  let update: TelegramUpdate;
  try {
    update = await c.req.json<TelegramUpdate>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }

  const message = update?.message;
  const chatId = message?.chat?.id != null ? String(message.chat.id) : '';
  const text = (message?.text ?? '').trim();
  if (!message || !chatId || !text) {
    // 非文本更新（加入群组、回调查询等）直接确认，避免 Telegram 重试
    return c.json({ ok: true, ignored: true });
  }
  if (message.from?.is_bot) {
    return c.json({ ok: true, ignored: true });
  }
  const chatType = message.chat?.type ?? 'private';
  if (chatType !== 'private') {
    // 群组 / 频道无法安全区分成员，统一提示私聊，避免个人数据外泄
    if (['group', 'supergroup'].includes(chatType)) {
      await sendTelegramMessage(c.env, chatId, buildPrivateOnlyMessage());
    }
    return c.json({ ok: true, ignored: true });
  }

  const username = (message.from?.username ?? message.chat?.username ?? '').trim() || null;
  try {
    const reply = await handleTextMessage(c.env, chatId, username, text);
    await sendTelegramMessage(c.env, chatId, reply);
  } catch (err) {
    // 记录错误类型即可，绝不输出 token / 完整请求 URL
    console.error('telegram webhook handling failed:', err instanceof Error ? err.message : 'unknown');
    return c.json({ error: 'internal_error' }, 500);
  }
  return c.json({ ok: true });
});

// ── 登录态接口（admin）──────────────────────────────────────────

telegram.get('/status', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<TelegramLinkWithLogin>(
    c.env.DB,
    `SELECT l.*, u.login AS login
       FROM telegram_links l
       LEFT JOIN users u ON u.id = l.user_id
      WHERE l.user_id = ?`,
    [user.id]
  );

  const body: TelegramStatusResponse = {
    configured: telegramConfigured(c.env),
    botUsername: telegramBotUsername(c.env) || null,
    webhookPath: '/api/telegram/webhook',
    linked: Boolean(row),
    link: row
      ? {
          chatId: maskTelegramChatId(row.chat_id),
          username: row.username,
          login: row.login,
          linkedAt: row.linked_at,
          lastSeenAt: row.last_seen_at,
        }
      : null,
    commands: TELEGRAM_BOT_COMMANDS,
  };
  return c.json(body);
});

telegram.post('/link-code', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  if (!telegramConfigured(c.env)) {
    return c.json({ error: 'telegram_not_configured' }, 503);
  }

  // 先清理过期码与该用户旧码，保证同一时间只有一个有效绑定码
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  await run(c.env.DB, 'DELETE FROM telegram_link_codes WHERE expires_at <= ?', [nowIso]);
  await run(c.env.DB, 'DELETE FROM telegram_link_codes WHERE user_id = ?', [user.id]);

  // 6 位码空间只有 100 万，生成时检查碰撞（极小概率，最多重试 5 次）
  let code = '';
  let codeHash = '';
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const candidate = generateLinkCode();
    const candidateHash = await sha256Hex(candidate);
    const existing = await first<{ code_hash: string }>(
      c.env.DB,
      'SELECT code_hash FROM telegram_link_codes WHERE code_hash = ?',
      [candidateHash]
    );
    if (!existing) {
      code = candidate;
      codeHash = candidateHash;
      break;
    }
  }
  if (!code) return c.json({ error: 'code_generation_failed' }, 500);

  const expiresAt = new Date(now + LINK_CODE_TTL_MS).toISOString();
  await run(
    c.env.DB,
    `INSERT INTO telegram_link_codes (code_hash, user_id, expires_at, created_at)
     VALUES (?, ?, ?, ?)`,
    [codeHash, user.id, expiresAt, nowIso]
  );

  const botUsername = telegramBotUsername(c.env);
  return c.json({
    code,
    expiresAt,
    command: `/link ${code}`,
    deepLink: botUsername ? `https://t.me/${botUsername}?start=${code}` : null,
    botUsername: botUsername || null,
  });
});

telegram.delete('/link', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const result = await run(c.env.DB, 'DELETE FROM telegram_links WHERE user_id = ?', [user.id]);
  return c.json({ linked: false, removed: (result.meta?.changes ?? 0) > 0 });
});

export default telegram;
