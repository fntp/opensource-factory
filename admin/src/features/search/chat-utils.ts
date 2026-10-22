/** 多轮问答检索的纯函数辅助：消息校验、历史裁剪、引用汇总与展示格式化。 */
import type {
  ChatIntent,
  ChatMessage,
  ChatMode,
  ChatResultItem,
  ChatScopeInput,
} from './api'
import { scopeLabel } from './utils'

export const MAX_CHAT_MESSAGE_LENGTH = 500
export const MAX_CHAT_HISTORY = 20
export const MAX_SHOWN_IDS = 500

/** 去首尾空白并把连续空白压成一个空格。 */
export function normalizeChatContent(input: string): string {
  return input.trim().replace(/\s+/g, ' ')
}

/** 单条提问是否合法：1~500 字符。 */
export function isChatContentValid(input: string): boolean {
  const content = normalizeChatContent(input)
  return content.length > 0 && content.length <= MAX_CHAT_MESSAGE_LENGTH
}

/** 请求只携带最近 20 条消息，避免长会话无限增长。 */
export function historyForRequest(
  messages: ChatMessage[],
  max = MAX_CHAT_HISTORY
): ChatMessage[] {
  return messages.slice(-Math.max(1, max))
}

/** 汇总历史 assistant 消息中已展示的项目 id，用于「还有吗」翻页排除。 */
export function collectShownIds(
  messages: Array<{ role: 'user' | 'assistant'; items?: ChatResultItem[] }>
): string[] {
  const ids: string[] = []
  for (const message of messages) {
    if (message.role !== 'assistant' || !message.items) continue
    for (const item of message.items) {
      if (item.id && !ids.includes(item.id)) ids.push(item.id)
    }
  }
  return ids.slice(0, MAX_SHOWN_IDS)
}

/** 消息时间：HH:mm。 */
export function formatChatTime(value: Date | string | number): string {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function chatModeLabel(mode: ChatMode): string {
  if (mode === 'hybrid') return '混合检索'
  if (mode === 'vector') return '向量检索'
  return '关键词降级检索'
}

export function chatScopeLabel(scope: ChatScopeInput): string {
  if (scope === 'auto') return '自动判断'
  return scopeLabel(scope)
}

export function intentLabel(intent: ChatIntent): string {
  if (intent === 'count') return '数量统计'
  if (intent === 'more') return '继续翻页'
  if (intent === 'detail') return '项目详情'
  if (intent === 'compare') return '来源对比'
  return '项目列表'
}

/** 引用编号展示：[1]。 */
export function citationLabel(citation: number): string {
  const value = Number.isFinite(citation)
    ? Math.max(0, Math.trunc(citation))
    : 0
  return `[${value}]`
}
