/**
 * 多轮问答式检索的轻量上下文解析（M6-09）。
 *
 * 这些纯函数与 VPS `conversation_search` 的规则保持同构，用于：
 * - 请求体校验（消息条数 / 长度 / 角色）；
 * - VPS 不可达时在 edge 本地回放上下文并生成兜底答案与追问建议；
 * - 单测不依赖网络与数据库。
 */
export type ChatRole = 'user' | 'assistant';
export type ChatScope = 'my' | 'trending' | 'all';
export type ChatIntent = 'list' | 'count' | 'more' | 'detail' | 'compare';

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatContext {
  topic: string;
  language: string;
  scope: ChatScope;
  intent: ChatIntent;
  turn: number;
  excluded: string[];
}

export interface ChatAnswerItem {
  id?: string;
  source?: string;
  fullName: string;
  name: string;
  description: string;
  language: string;
  stars: number;
}

export interface ChatFacet {
  name: string;
  count: number;
}

export interface ChatFacets {
  languages: ChatFacet[];
  sources: ChatFacet[];
}

export const MAX_CHAT_MESSAGES = 20;
export const MAX_CHAT_MESSAGE_LENGTH = 500;
export const MAX_SHOWN_IDS = 500;

const SCOPE_LABELS: Record<ChatScope, string> = {
  my: '你的收藏',
  trending: '每日热榜',
  all: '全部来源',
};

const LANGUAGE_ALIASES: Array<[string, string[]]> = [
  ['TypeScript', ['typescript', 'ts']],
  ['JavaScript', ['javascript', 'js', 'ecmascript']],
  ['Python', ['python', 'python3', 'py']],
  ['Go', ['golang', 'go语言', 'go 语言', 'go']],
  ['Rust', ['rust', 'rustlang']],
  ['Java', ['java']],
  ['Kotlin', ['kotlin']],
  ['Swift', ['swift']],
  ['C++', ['c++', 'cpp']],
  ['C#', ['c#', 'csharp']],
  ['Ruby', ['ruby']],
  ['PHP', ['php']],
  ['Scala', ['scala']],
  ['Dart', ['dart']],
  ['Elixir', ['elixir']],
  ['Lua', ['lua']],
];

const MY_SCOPE_TERMS = [
  '我的收藏',
  '我收藏',
  '收藏里',
  '收藏中',
  '我的仓库',
  '我的库',
  '已收藏',
  'my collection',
  'my repos',
  'saved',
  'favorites',
];
const TRENDING_SCOPE_TERMS = ['热榜', '榜单', '趋势', 'trending', 'hot list'];
const ALL_SCOPE_TERMS = ['全部来源', '所有来源', '全库', '全部', '所有', 'all sources', 'everywhere'];

const TOPIC_NOISE_PATTERNS = [
  '我的收藏(里|中)?',
  '我收藏的?',
  '收藏(里|中|库)?',
  '我的仓库',
  '我的库',
  '已收藏',
  '有哪些',
  '有什么',
  '有多少',
  '多少个',
  '几个',
  '多少',
  '哪些',
  '哪个',
  '请帮我',
  '帮我',
  '帮忙',
  '麻烦',
  '请',
  '找一下',
  '找一些',
  '找找',
  '找',
  '查一下',
  '查查',
  '查',
  '看看',
  '看一下',
  '列出',
  '显示',
  '告诉',
  '换个话题',
  '换一个话题',
  '聊点别的',
  '那么',
  '那',
  '这些',
  '那些',
  '其中',
  '还有',
  '再找',
  '再来',
  '再看',
  '更多',
  '其他',
  '其它',
  '别的',
  '只看',
  '只要',
  '不限',
  '所有',
  '全部',
  '来源',
  '热榜',
  '榜单',
  '趋势',
  '收藏',
  '对比',
  '比较',
  '区别',
  '第一个',
  '第1个',
  '这个项目',
  '那个项目',
  '这个',
  '那个',
  '它们',
  '它',
  '怎么样',
  '相关',
  '项目',
  '仓库',
  '开源',
  '一下',
  '的',
  '里',
  '中',
  '和',
  '与',
  '及',
  '呢',
  '吗',
  '啊',
  '吧',
];

const ENGLISH_STOPWORDS = new Set([
  'what',
  'which',
  'are',
  'is',
  'in',
  'my',
  'collection',
  'saved',
  'favorites',
  'favourite',
  'project',
  'projects',
  'repo',
  'repos',
  'repository',
  'repositories',
  'related',
  'about',
  'show',
  'list',
  'me',
  'find',
  'any',
  'how',
  'many',
  'more',
  'other',
  'others',
  'please',
  'the',
  'a',
  'an',
  'of',
  'to',
  'for',
  'and',
  'or',
  'with',
  'using',
  'written',
  'language',
  'languages',
  'all',
  'sources',
  'source',
  'trending',
  'hot',
  'top',
  'compare',
  'versus',
  'vs',
  'first',
  'one',
  'this',
  'that',
  'there',
  'have',
  'has',
  'do',
  'does',
]);

const PUNCTUATION_RE = /[，。！？、；：,.!?;:()（）[\]【】"“”'‘’]+/g;
const FOLLOWUP_RE = /(还有|再找|再来|再看|更多|其他|其它|别的|只看|只要|不限|第一个|第1个|对比|比较|区别|怎么样|呢[？?]?$)/;

export class ChatInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatInputError';
  }
}

/** 校验并归一化会话消息；最后一条必须是 user。 */
export function normalizeChatMessages(input: unknown): ChatMessage[] {
  if (!Array.isArray(input)) throw new ChatInputError('messages 必须是数组');
  if (input.length < 1) throw new ChatInputError('至少需要一条消息');
  if (input.length > MAX_CHAT_MESSAGES) {
    throw new ChatInputError(`会话最多 ${MAX_CHAT_MESSAGES} 条消息`);
  }
  const messages: ChatMessage[] = input.map((entry) => {
    if (!entry || typeof entry !== 'object') throw new ChatInputError('消息格式非法');
    const role = String((entry as Record<string, unknown>).role ?? '').toLowerCase();
    if (role !== 'user' && role !== 'assistant') {
      throw new ChatInputError('消息角色仅支持 user / assistant');
    }
    const raw = (entry as Record<string, unknown>).content;
    if (typeof raw !== 'string') throw new ChatInputError('消息内容不能为空');
    const content = raw.replace(/\s+/g, ' ').trim();
    if (!content) throw new ChatInputError('消息内容不能为空');
    if (content.length > MAX_CHAT_MESSAGE_LENGTH) {
      throw new ChatInputError(`单条消息不能超过 ${MAX_CHAT_MESSAGE_LENGTH} 字`);
    }
    return { role, content };
  });
  if (messages[messages.length - 1]?.role !== 'user') {
    throw new ChatInputError('最后一条消息必须来自用户');
  }
  return messages;
}

/** 校验 shownIds：字符串数组、去重、最多 500 个。 */
export function normalizeShownIds(input: unknown): string[] {
  if (input === undefined || input === null) return [];
  if (!Array.isArray(input)) throw new ChatInputError('shownIds 必须是字符串数组');
  const values: string[] = [];
  for (const entry of input) {
    if (typeof entry !== 'string') throw new ChatInputError('shownIds 必须是字符串数组');
    const value = entry.trim();
    if (value && !values.includes(value)) values.push(value);
  }
  if (values.length > MAX_SHOWN_IDS) throw new ChatInputError(`shownIds 最多 ${MAX_SHOWN_IDS} 个`);
  return values;
}

function hasAscii(value: string): boolean {
  return [...value].every((char) => char.charCodeAt(0) < 128);
}

function aliasPattern(alias: string): RegExp {
  const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?<![a-z0-9])${escaped}(?![a-z0-9])`);
}

/** 返回规范语言名与是否显式提及；「不限语言」返回空语言 + explicit=true。 */
export function detectLanguage(text: string): { language: string; explicit: boolean } {
  const folded = (text || '').toLowerCase();
  if (['不限语言', '所有语言', '任何语言', 'any language'].some((word) => folded.includes(word))) {
    return { language: '', explicit: true };
  }
  for (const [canonical, aliases] of LANGUAGE_ALIASES) {
    for (const alias of aliases) {
      if (hasAscii(alias) ? aliasPattern(alias).test(folded) : folded.includes(alias)) {
        return { language: canonical, explicit: true };
      }
    }
  }
  return { language: '', explicit: false };
}

export function detectScope(text: string): ChatScope | null {
  const folded = (text || '').toLowerCase();
  const my = MY_SCOPE_TERMS.some((term) => folded.includes(term));
  const trending = TRENDING_SCOPE_TERMS.some((term) => folded.includes(term));
  const allScope = ALL_SCOPE_TERMS.some((term) => folded.includes(term));
  if (my && trending) return 'all';
  if (my) return 'my';
  if (trending) return 'trending';
  if (allScope) return 'all';
  return null;
}

export function detectIntent(text: string): ChatIntent {
  const folded = (text || '').toLowerCase();
  if (['多少', '几个', '数量', 'count', 'how many'].some((word) => folded.includes(word))) {
    return 'count';
  }
  if (['还有', '再找', '更多', '其他', '其它', '别的', 'more', 'other'].some((word) => folded.includes(word))) {
    return 'more';
  }
  if (['第一个', '第1个', '这个项目', '详情', 'detail', 'first one'].some((word) => folded.includes(word))) {
    return 'detail';
  }
  if (['对比', '比较', '区别', 'compare', 'versus', ' vs '].some((word) => folded.includes(word))) {
    return 'compare';
  }
  return 'list';
}

export function stripChatNoise(text: string): string {
  let cleaned = (text || '').replace(PUNCTUATION_RE, ' ');
  for (const pattern of TOPIC_NOISE_PATTERNS) {
    cleaned = cleaned.replace(new RegExp(pattern, 'gi'), ' ');
  }
  for (const [, aliases] of LANGUAGE_ALIASES) {
    for (const alias of aliases) {
      cleaned = hasAscii(alias)
        ? cleaned.toLowerCase().replace(new RegExp(aliasPattern(alias).source, 'g'), ' ')
        : cleaned.replaceAll(alias, ' ');
    }
  }
  return cleaned
    .split(/\s+/)
    .filter((token) => token && !ENGLISH_STOPWORDS.has(token.toLowerCase()))
    .join(' ')
    .trim();
}

export function extractTopic(text: string): string {
  return stripChatNoise(text).slice(0, 60);
}

function isFollowup(text: string): boolean {
  return FOLLOWUP_RE.test((text || '').toLowerCase());
}

function unique(values: string[]): string[] {
  const result: string[] = [];
  for (const value of values) {
    if (value && !result.includes(value)) result.push(value);
  }
  return result;
}

/** 回放用户轮次，得到本轮主题 / 语言 / 范围 / 意图 / 已展示排除。 */
export function resolveChatTurn(
  messages: ChatMessage[],
  shownIds: string[] = [],
  scopeOverride?: ChatScope
): ChatContext {
  const state: ChatContext = {
    topic: '',
    language: '',
    scope: 'all',
    intent: 'list',
    turn: 0,
    excluded: [],
  };

  for (const message of messages) {
    if (message.role !== 'user') continue;
    const question = message.content;
    const explicitScope = detectScope(question);
    const language = detectLanguage(question);
    const topic = extractTopic(question);
    const intent = detectIntent(question);
    const followup = isFollowup(question);

    if (topic) {
      state.topic = topic;
      if (!language.explicit) state.language = '';
    } else if (!followup && !explicitScope && !language.explicit) {
      const fallback = stripChatNoise(question);
      if (fallback) {
        state.topic = fallback.slice(0, 60);
        if (!language.explicit) state.language = '';
      }
    }

    if (explicitScope) state.scope = explicitScope;
    else if (state.turn === 0) {
      state.scope = question.includes('收藏') || question.toLowerCase().includes('saved') ? 'my' : 'all';
    }

    if (language.explicit) state.language = language.language;
    state.intent = intent;
    state.excluded = intent === 'more' ? unique(shownIds) : [];
    state.turn += 1;
  }

  if (scopeOverride) state.scope = scopeOverride;
  return state;
}

export function scopeLabel(scope: ChatScope): string {
  return SCOPE_LABELS[scope] ?? '全部来源';
}

function languageSuffix(language: string): string {
  return language ? `，语言限定为 ${language}` : '';
}

function formatItem(item: ChatAnswerItem, index: number): string {
  const language = item.language || '未标注语言';
  const stars = Number(item.stars || 0);
  const description = (item.description || '').trim();
  const suffix = description ? `—— ${description.slice(0, 60)}` : '';
  return `[${index}] ${item.fullName || item.name}（${language}，★${stars}）${suffix}`;
}

/** 确定性兜底答案（VPS 不可达时使用），带 [n] 引用。 */
export function buildFallbackAnswer(
  context: ChatContext,
  items: ChatAnswerItem[],
  total: number,
  sourceCounts: Record<string, number> = {}
): string {
  const topic = context.topic || '当前问题';
  const label = scopeLabel(context.scope);
  const suffix = languageSuffix(context.language);

  if (total === 0) {
    return `在${label}里没有找到与「${topic}」相关的项目。可以换个关键词，或把范围放宽到全部来源。`;
  }

  if (context.intent === 'count') {
    const names = items
      .slice(0, 3)
      .map((item, index) => `[${index + 1}] ${item.fullName || item.name}`)
      .join('、');
    return `在${label}里，与「${topic}」相关的项目共有 ${total} 个${suffix}。${names ? `例如：${names}。` : ''}`;
  }

  if (context.intent === 'detail' && items[0]) {
    const item = items[0];
    return `当前最匹配的是 [1] ${item.fullName || item.name}：${
      (item.description || '暂无项目简介').slice(0, 160)
    }（${item.language || '未标注语言'}，★${Number(item.stars || 0)}）。`;
  }

  if (context.intent === 'compare') {
    const myCount = Number(sourceCounts.my ?? 0);
    const trendingCount = Number(sourceCounts.trending ?? 0);
    if (myCount || trendingCount) {
      return (
        `与「${topic}」相关的项目：你的收藏 ${myCount} 个，每日热榜 ${trendingCount} 个${suffix}。` +
        (myCount >= trendingCount
          ? '收藏库更多，建议优先从收藏里挑选。'
          : '热榜更多，可以关注近期趋势。')
      );
    }
  }

  const lines =
    context.intent === 'more'
      ? [`继续为你找到 ${total} 个与「${topic}」相关的项目${suffix}：`]
      : [`在${label}里找到 ${total} 个与「${topic}」相关的项目${suffix}：`];
  lines.push(...items.map((item, index) => formatItem(item, index + 1)));
  if (total > items.length) {
    lines.push(`还有 ${total - items.length} 个结果，可以说「还有吗」继续查看。`);
  }
  return lines.join('\n');
}

/** 追问建议：翻页、解除语言限制、切换范围、查看 Star 最高。 */
export function buildChatSuggestions(
  context: ChatContext,
  items: ChatAnswerItem[],
  total: number,
  facets: ChatFacets = { languages: [], sources: [] }
): string[] {
  const topic = context.topic || '这个主题';
  const suggestions: string[] = [];
  if (total > items.length) suggestions.push('还有吗？');
  if (context.language) suggestions.push('不限语言再看看');
  if (context.scope !== 'my') suggestions.push('只看我的收藏');
  if (context.scope !== 'trending') suggestions.push(`热榜里有哪些${topic}项目？`);
  const topLanguage = facets.languages[0]?.name;
  if (topLanguage && topLanguage !== context.language) suggestions.push(`只看${topLanguage}的`);
  if (items.length > 0) suggestions.push('其中 Star 最多的是哪个？');
  return unique(suggestions).slice(0, 4);
}

/** 由结果集统计语言与来源分布。 */
export function buildChatFacets(items: ChatAnswerItem[]): ChatFacets {
  const languages = new Map<string, number>();
  const sources = new Map<string, number>();
  for (const item of items) {
    const language = (item.language || '未标注').trim() || '未标注';
    languages.set(language, (languages.get(language) ?? 0) + 1);
    const source = item.source ?? '';
    if (source) sources.set(source, (sources.get(source) ?? 0) + 1);
  }
  const sort = (map: Map<string, number>): ChatFacet[] =>
    [...map.entries()]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .map(([name, count]) => ({ name, count }));
  return { languages: sort(languages).slice(0, 5), sources: sort(sources) };
}

/** 兜底检索词：主题按空格拆分，去重后最多 8 个。 */
export function keywordTermsForTopic(topic: string): string[] {
  return unique(
    topic
      .split(/\s+/)
      .map((term) => term.trim())
      .filter(Boolean)
  ).slice(0, 8);
}
