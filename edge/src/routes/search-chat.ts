/**
 * 多轮问答式检索路由（M6-09）
 * POST /api/search/chat
 *
 * 权限：`my` 来源的候选必须属于当前登录用户。edge 先从 D1 读取当前用户的
 * `my_repositories.id` 白名单传给 VPS，VPS 返回后再按 `user_id` 二次水合，
 * 保证 VPS 全局镜像不会造成跨用户泄漏。
 *
 * 降级：VPS 不可达 / 响应非法时，在 edge 本地回放上下文并用 D1 关键词检索，
 * 返回 `mode=keyword` 的模板答案，页面不空白。
 */
import { Hono } from 'hono';
import type { ChatFacets, ChatResponse, ChatResultItem, Env, Variables } from '../types';
import { all } from '../db.ts';
import {
  buildChatFacets,
  buildChatSuggestions,
  buildFallbackAnswer,
  ChatInputError,
  keywordTermsForTopic,
  normalizeChatMessages,
  normalizeShownIds,
  resolveChatTurn,
  type ChatContext,
} from '../search/chat.ts';
import {
  hydrate,
  keywordSearch,
  postVps,
  type Hit,
  type Scope,
} from './search.ts';

const searchChat = new Hono<{ Bindings: Env; Variables: Variables }>();

const DEFAULT_TOP_K = 8;
const MAX_TOP_K = 20;
const MAX_MY_REPOS = 5000;

type ScopeInput = 'auto' | Scope;

interface VpsChatItem {
  id?: unknown;
  source?: unknown;
  score?: unknown;
  citation?: unknown;
  reason?: unknown;
}

interface VpsChatResponse {
  question?: unknown;
  answer?: unknown;
  intent?: unknown;
  scope?: unknown;
  topic?: unknown;
  language?: unknown;
  filters?: {
    language?: unknown;
    concepts?: unknown;
    terms?: unknown;
  };
  count?: unknown;
  total?: unknown;
  items?: unknown;
  facets?: {
    languages?: unknown;
    sources?: unknown;
  };
  suggestions?: unknown;
  mode?: unknown;
  tookMs?: unknown;
  turn?: unknown;
  backend?: unknown;
  model?: unknown;
}

function parseScopeInput(value: unknown): ScopeInput | null {
  if (value === undefined || value === null || value === '' || value === 'auto') return 'auto';
  return value === 'my' || value === 'trending' || value === 'all' ? value : null;
}

function parseTopK(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_TOP_K;
  return Math.min(MAX_TOP_K, Math.max(1, Math.trunc(parsed)));
}

function stringArray(value: unknown, max = 20): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, max);
}

function facetList(value: unknown): Array<{ name: string; count: number }> {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (item): item is { name: string; count: number } =>
        Boolean(item) &&
        typeof item === 'object' &&
        typeof (item as { name?: unknown }).name === 'string' &&
        typeof (item as { count?: unknown }).count === 'number'
    )
    .map((item) => ({ name: item.name, count: Math.max(0, Math.trunc(item.count)) }));
}

function normalizeFacets(value: VpsChatResponse['facets']): ChatFacets | null {
  if (!value || typeof value !== 'object') return null;
  return {
    languages: facetList(value.languages),
    sources: facetList(value.sources),
  };
}

function toChatItem(
  item: VpsChatItem,
  fallbackCitation: number
): { hit: Hit; citation: number; reason: string } | null {
  if (
    !item ||
    typeof item.id !== 'string' ||
    (item.source !== 'my' && item.source !== 'trending') ||
    typeof item.score !== 'number' ||
    !Number.isFinite(item.score)
  ) {
    return null;
  }
  return {
    hit: { source: item.source, repoId: item.id, score: item.score },
    citation:
      typeof item.citation === 'number' && Number.isFinite(item.citation)
        ? Math.max(0, Math.trunc(item.citation))
        : fallbackCitation,
    reason: typeof item.reason === 'string' ? item.reason : '',
  };
}

/** 按 D1 重新水合 VPS 结果，并按 user_id 二次过滤 my 来源。 */
async function hydrateChatItems(
  env: Env,
  userId: string,
  rawItems: VpsChatItem[],
  limit: number
): Promise<ChatResultItem[]> {
  const mapped = rawItems
    .map((item, index) => toChatItem(item, index + 1))
    .filter((item): item is { hit: Hit; citation: number; reason: string } => Boolean(item));
  if (mapped.length === 0) return [];

  const hydrated = await hydrate(
    env,
    userId,
    mapped.map((item) => item.hit),
    limit
  );
  const byKey = new Map(mapped.map((item) => [`${item.hit.source}:${item.hit.repoId}`, item]));
  const items: ChatResultItem[] = [];
  for (const item of hydrated) {
    const original = byKey.get(`${item.source}:${item.id}`);
    if (!original) continue;
    items.push({
      ...item,
      citation: original.citation,
      reason: original.reason || item.reason,
    });
  }
  return items;
}

async function loadMyRepoIds(env: Env, userId: string): Promise<string[]> {
  const rows = await all<{ id: string }>(
    env.DB,
    'SELECT id FROM my_repositories WHERE user_id = ? LIMIT ?',
    [userId, MAX_MY_REPOS]
  );
  return rows.map((row) => row.id).filter(Boolean);
}

function sourceCounts(items: Array<{ source: string }>): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    counts[item.source] = (counts[item.source] ?? 0) + 1;
  }
  return counts;
}

function fallbackChat(
  env: Env,
  userId: string,
  messages: ReturnType<typeof normalizeChatMessages>,
  shownIds: string[],
  scopeOverride: Scope | undefined,
  topK: number,
  started: number
): Promise<ChatResponse> {
  const context = resolveChatTurn(messages, shownIds, scopeOverride);
  const last = messages[messages.length - 1];
  const question = last?.content ?? '';
  const query = context.topic || question;

  return keywordSearch(env, userId, query, context.scope, Math.min(60, topK * 4)).then(
    (candidates) => {
      const filtered = candidates.filter((item) => {
        if (context.excluded.includes(item.id)) return false;
        if (
          context.language &&
          (item.language ?? '').toLowerCase() !== context.language.toLowerCase()
        ) {
          return false;
        }
        return true;
      });
      const total = filtered.length;
      const items: ChatResultItem[] = filtered.slice(0, topK).map((item, index) => ({
        ...item,
        citation: index + 1,
      }));
      const facets = buildChatFacets(filtered);
      const counts = sourceCounts(filtered);
      const answer = buildFallbackAnswer(context, items, total, counts);
      return {
        question,
        answer,
        intent: context.intent,
        scope: context.scope,
        topic: context.topic,
        language: context.language,
        filters: {
          language: context.language,
          concepts: [],
          terms: keywordTermsForTopic(query),
        },
        count: items.length,
        total,
        items,
        facets,
        suggestions: buildChatSuggestions(context, items, total, facets),
        mode: 'keyword',
        tookMs: Date.now() - started,
        turn: context.turn,
        backend: '',
        model: '',
        fallback: true,
      } satisfies ChatResponse;
    }
  );
}

function fromVps(
  response: VpsChatResponse,
  items: ChatResultItem[],
  context: ChatContext,
  question: string,
  started: number
): ChatResponse | null {
  if (typeof response.answer !== 'string' || !response.answer.trim()) return null;
  const intent = ['list', 'count', 'more', 'detail', 'compare'].includes(String(response.intent))
    ? (response.intent as ChatResponse['intent'])
    : context.intent;
  const scope =
    response.scope === 'my' || response.scope === 'trending' || response.scope === 'all'
      ? response.scope
      : context.scope;
  const mode =
    response.mode === 'hybrid' || response.mode === 'vector' || response.mode === 'keyword'
      ? response.mode
      : 'hybrid';
  const facets = normalizeFacets(response.facets) ?? buildChatFacets(items);
  const suggestions = stringArray(response.suggestions, 8);
  return {
    question: typeof response.question === 'string' ? response.question : question,
    answer: response.answer,
    intent,
    scope,
    topic: typeof response.topic === 'string' ? response.topic : context.topic,
    language: typeof response.language === 'string' ? response.language : context.language,
    filters: {
      language:
        typeof response.filters?.language === 'string'
          ? response.filters.language
          : context.language,
      concepts: stringArray(response.filters?.concepts, 20),
      terms: stringArray(response.filters?.terms, 20),
    },
    count: items.length,
    total:
      typeof response.total === 'number' && Number.isFinite(response.total)
        ? Math.max(items.length, Math.trunc(response.total))
        : items.length,
    items,
    facets,
    suggestions:
      suggestions.length > 0
        ? suggestions
        : buildChatSuggestions(context, items, items.length, facets),
    mode,
    tookMs: Date.now() - started,
    turn:
      typeof response.turn === 'number' && Number.isFinite(response.turn)
        ? Math.max(1, Math.trunc(response.turn))
        : context.turn,
    backend: typeof response.backend === 'string' ? response.backend : '',
    model: typeof response.model === 'string' ? response.model : '',
  };
}

searchChat.post('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = (await c.req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== 'object') {
    return c.json({ error: 'invalid_body', message: '请求体必须是 JSON 对象' }, 400);
  }

  let messages: ReturnType<typeof normalizeChatMessages>;
  let shownIds: string[];
  try {
    messages = normalizeChatMessages(body.messages);
    shownIds = normalizeShownIds(body.shownIds);
  } catch (err) {
    if (err instanceof ChatInputError) {
      return c.json({ error: 'invalid_body', message: err.message }, 400);
    }
    throw err;
  }

  const scopeInput = parseScopeInput(body.scope);
  if (!scopeInput) {
    return c.json(
      { error: 'invalid_scope', message: 'scope 仅支持 auto / my / trending / all' },
      400
    );
  }

  const started = Date.now();
  const topK = parseTopK(body.topK);
  const scopeOverride = scopeInput === 'auto' ? undefined : scopeInput;
  const lastQuestion = messages[messages.length - 1]?.content ?? '';
  const context = resolveChatTurn(messages, shownIds, scopeOverride);

  let myRepoIds: string[] = [];
  try {
    myRepoIds = await loadMyRepoIds(c.env, user.id);
  } catch (err) {
    console.error('load my repo ids failed:', err);
  }

  const vps = await postVps<VpsChatResponse>(c.env, '/api/search/chat', {
    messages,
    myRepoIds,
    shownIds,
    topK,
    ...(scopeOverride ? { scope: scopeOverride } : {}),
  });

  if (vps && Array.isArray(vps.items)) {
    const rawItems = vps.items.filter(
      (item): item is VpsChatItem => Boolean(item) && typeof item === 'object'
    );
    const items = await hydrateChatItems(c.env, user.id, rawItems, topK);
    if (items.length > 0 || rawItems.length === 0) {
      const response = fromVps(vps, items, context, lastQuestion, started);
      if (response) return c.json(response satisfies ChatResponse);
    }
  }

  const response = await fallbackChat(
    c.env,
    user.id,
    messages,
    shownIds,
    scopeOverride,
    topK,
    started
  );
  return c.json(response satisfies ChatResponse);
});

export default searchChat;
