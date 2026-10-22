/**
 * 自动分类建议的本地业务线规则（M7-02）。
 *
 * 用途：VPS 节点不可用、或 VPS 未返回某个仓库的建议时，edge 用同一套业务线词表
 * 在 Worker 内完成降级计算，保证控制台不空白。纯函数，不依赖 D1 / 网络。
 */

export interface CategorySuggestionRepo {
  repoId: string;
  name: string;
  description: string;
  language: string;
  summary: string;
  tags: string[];
}

export interface LocalCategorySuggestion {
  categoryName: string;
  businessLine: string;
  score: number;
  reason: string;
  evidence: string;
}

export interface BusinessLineRule {
  key: string;
  name: string;
  description: string;
  keywords: string[];
  languages?: string[];
}

/** 首批业务线词表（与 VPS `category_suggestions.py` 保持一致）。 */
export const BUSINESS_LINES: BusinessLineRule[] = [
  {
    key: 'ai',
    name: 'AI / 大模型',
    description: '大模型、机器学习、推理框架与 AI 应用',
    keywords: [
      'ai', 'artificial intelligence', 'machine learning', 'deep learning', 'llm', 'gpt',
      'transformer', 'diffusion', 'stable diffusion', 'rag', 'embedding', 'agent', 'prompt',
      'nlp', 'natural language', 'computer vision', 'ocr', 'speech recognition',
      '大模型', '人工智能', '机器学习', '深度学习', '推理', '微调', '训练', '智能体', '提示词',
      '自然语言', '计算机视觉', '语音识别', '向量',
    ],
  },
  {
    key: 'fintech',
    name: '金融 / 支付',
    description: '支付、账务、风控与金融科技',
    keywords: [
      'payment', 'payments', 'fintech', 'banking', 'finance', 'financial', 'wallet', 'stripe',
      'paypal', 'ledger', 'accounting', 'billing', 'invoice', 'checkout',
      '支付', '金融', '银行', '账务', '钱包', '对账', '结算', '交易', '信贷', '保险', '理财',
      '证券', '计费', '发票',
    ],
  },
  {
    key: 'ecommerce',
    name: '电商 / 零售',
    description: '商城、订单、库存与零售业务',
    keywords: [
      'ecommerce', 'e-commerce', 'shop', 'store', 'cart', 'checkout', 'order', 'orders',
      'inventory', 'retail', 'marketplace', 'product',
      '电商', '商城', '购物车', '订单', '库存', '零售', '商品', '店铺', '促销', '会员', '供应链',
    ],
  },
  {
    key: 'saas',
    name: '企业服务 / SaaS',
    description: '多租户 SaaS、CRM / ERP、审批与工单',
    keywords: [
      'saas', 'crm', 'erp', 'hr', 'oa', 'bpm', 'workflow', 'tenant', 'multi-tenant',
      'multitenant', 'admin dashboard', 'enterprise', 'customer', 'ticket',
      '企业', '多租户', '客户关系', '办公', '审批', '工单', '人力', '财务系统', '后台管理',
      '管理后台', '中台', '协同',
    ],
  },
  {
    key: 'devtools',
    name: '开发工具',
    description: 'CLI、SDK、编辑器、构建与测试工具',
    keywords: [
      'cli', 'sdk', 'ide', 'editor', 'compiler', 'linter', 'formatter', 'debugger', 'testing',
      'test framework', 'package manager', 'scaffold', 'boilerplate', 'developer tool', 'devtool',
      '开发工具', '编辑器', '编译器', '调试', '测试框架', '脚手架', '命令行', '代码生成', '插件',
      '构建工具',
    ],
  },
  {
    key: 'data-infra',
    name: '数据工程',
    description: '数据库、缓存、消息队列、ETL 与数据分析',
    keywords: [
      'database', 'sql', 'nosql', 'cache', 'redis', 'kafka', 'queue', 'etl', 'data pipeline',
      'warehouse', 'olap', 'analytics', 'storage engine',
      '数据库', '缓存', '消息队列', '数据管道', '数据仓库', '数据分析', '存储引擎', '分布式',
      '数据同步', '数据治理',
    ],
  },
  {
    key: 'cloud-devops',
    name: 'DevOps / 云原生',
    description: '容器、Kubernetes、CI/CD、部署与可观测性',
    keywords: [
      'kubernetes', 'k8s', 'docker', 'container', 'devops', 'ci/cd', 'cicd', 'terraform',
      'ansible', 'serverless', 'observability', 'monitoring', 'logging', 'microservice',
      '云原生', '容器', '编排', '部署', '运维', '监控', '日志', '可观测', '微服务', '持续集成',
    ],
  },
  {
    key: 'security',
    name: '安全 / 合规',
    description: '认证授权、加密、漏洞与隐私合规',
    keywords: [
      'security', 'auth', 'authentication', 'authorization', 'oauth', 'jwt', 'encryption',
      'vulnerability', 'penetration', 'zero trust', 'privacy', 'compliance',
      '安全', '认证', '授权', '加密', '漏洞', '渗透', '合规', '隐私', '审计', '权限',
    ],
  },
  {
    key: 'web-frontend',
    name: '前端开发',
    description: 'Web 框架、组件库、样式与设计系统',
    keywords: [
      'react', 'vue', 'angular', 'svelte', 'next.js', 'nuxt', 'tailwind', 'css', 'html',
      'frontend', 'front-end', 'ui component', 'design system',
      '前端', '组件库', '样式', '页面', '设计系统', '可视化',
    ],
    languages: ['javascript', 'typescript', 'html', 'css'],
  },
  {
    key: 'mobile',
    name: '移动端',
    description: 'iOS / Android / 跨平台移动应用',
    keywords: [
      'ios', 'android', 'flutter', 'react native', 'swift', 'kotlin', 'mobile',
      '移动端', '安卓', '苹果', '小程序', '跨平台', '手机',
    ],
    languages: ['swift', 'kotlin', 'dart', 'objective-c'],
  },
  {
    key: 'content-media',
    name: '内容 / 媒体',
    description: 'CMS、博客、文档、音视频与知识库',
    keywords: [
      'cms', 'blog', 'markdown', 'wiki', 'documentation', 'podcast', 'video', 'audio', 'image',
      'photo', 'media',
      '内容', '博客', '文档', '知识库', '媒体', '视频', '音频', '图片', '相册', '写作', '笔记',
    ],
  },
  {
    key: 'education',
    name: '教育 / 学习',
    description: '课程、教程、题库与学习资源',
    keywords: [
      'education', 'learning', 'course', 'tutorial', 'teaching', 'quiz', 'exam',
      '教育', '学习', '教程', '课程', '考试', '题库', '知识', '培训', '面试',
    ],
  },
  {
    key: 'productivity',
    name: '效率 / 办公',
    description: '待办、日历、邮件、自动化与办公效率',
    keywords: [
      'productivity', 'todo', 'task', 'calendar', 'email', 'office', 'automation', 'shortcut',
      '效率', '待办', '日历', '邮件', '办公', '自动化', '快捷', '工作流',
    ],
  },
  {
    key: 'gaming',
    name: '游戏 / 娱乐',
    description: '游戏引擎、工具与娱乐应用',
    keywords: ['game', 'gaming', 'unity', 'unreal', 'godot', 'emulator', '游戏', '娱乐', '引擎', '玩家'],
  },
  {
    key: 'iot',
    name: '物联网 / 嵌入式',
    description: '嵌入式、固件、硬件与 IoT 平台',
    keywords: [
      'iot', 'embedded', 'firmware', 'arduino', 'raspberry pi', 'esp32', 'mqtt', 'hardware',
      '物联网', '嵌入式', '硬件', '固件', '单片机', '传感器',
    ],
  },
  {
    key: 'blockchain',
    name: '区块链 / Web3',
    description: '区块链、智能合约与 Web3 应用',
    keywords: [
      'blockchain', 'web3', 'ethereum', 'solidity', 'smart contract', 'nft', 'defi', 'crypto',
      '区块链', '智能合约', '以太坊', '链上', '去中心化',
    ],
    languages: ['solidity'],
  },
  {
    key: 'healthcare',
    name: '医疗 / 健康',
    description: '医疗、健康管理与临床系统',
    keywords: [
      'healthcare', 'medical', 'health', 'hospital', 'patient', 'diagnosis',
      '医疗', '健康', '医院', '患者', '诊断', '病历', '临床',
    ],
  },
  {
    key: 'backend-api',
    name: '后端与 API',
    description: 'Web 框架、API 网关与服务端基础设施',
    keywords: [
      'api', 'gateway', 'microservice', 'rest', 'graphql', 'grpc', 'web framework', 'backend',
      'server',
      '后端', '网关', '微服务', '服务端', '接口', '框架',
    ],
  },
]

const FIELD_WEIGHTS: Array<[string, number]> = [
  ['name', 3],
  ['tags', 2],
  ['description', 2],
  ['summary', 1.5],
]
const LANGUAGE_WEIGHT = 0.5
const BASE_SCORE = 0.4
const SCORE_PER_WEIGHT = 0.05
const MAX_SCORE = 0.99
const EVIDENCE_LIMIT = 120

export function normalizeText(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
}

function isAsciiKeyword(keyword: string): boolean {
  return /[a-z0-9]/.test(keyword)
}

export function containsKeyword(text: string, keyword: string): boolean {
  const normalized = normalizeText(text)
  const target = keyword.trim().toLowerCase()
  if (!normalized || !target) return false
  if (!isAsciiKeyword(target)) return normalized.includes(target)
  const escaped = target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(^|[^a-z0-9])${escaped}(?=$|[^a-z0-9])`).test(normalized)
}

function snippet(text: string, keyword: string, limit = EVIDENCE_LIMIT): string {
  const source = (text ?? '').trim()
  if (!source) return ''
  const index = source.toLowerCase().indexOf(keyword.toLowerCase())
  if (index < 0) return source.slice(0, limit) + (source.length > limit ? '…' : '')
  const half = Math.max(20, Math.floor((limit - keyword.length) / 2))
  const start = Math.max(0, index - half)
  const end = Math.min(source.length, index + keyword.length + half)
  const prefix = start > 0 ? '…' : ''
  const suffix = end < source.length ? '…' : ''
  return `${prefix}${source.slice(start, end).trim()}${suffix}`
}

function reasonText(hits: Array<[string, string, number]>): string {
  const labels: Record<string, string> = {
    name: '名称',
    tags: '标签',
    description: '简介',
    summary: '摘要',
    language: '语言',
  }
  const parts: string[] = []
  const seen = new Set<string>()
  for (const [field, keyword] of [...hits].sort((a, b) => b[2] - a[2])) {
    const key = `${field}:${keyword.toLowerCase()}`
    if (seen.has(key)) continue
    seen.add(key)
    parts.push(`${labels[field] ?? field}命中「${keyword}」`)
    if (parts.length >= 3) break
  }
  return parts.length > 0 ? parts.join('；') : '规则命中'
}

function scoreLine(repo: CategorySuggestionRepo, line: BusinessLineRule): LocalCategorySuggestion | null {
  let raw = 0
  const hits: Array<[string, string, number]> = []
  let evidence = ''
  let evidenceWeight = 0

  const values: Array<[string, string]> = [
    ['name', repo.name],
    ['tags', repo.tags.join('、')],
    ['description', repo.description],
    ['summary', repo.summary],
  ]
  for (const [field, value] of values) {
    const weight = FIELD_WEIGHTS.find(([name]) => name === field)?.[1] ?? 0
    for (const keyword of line.keywords) {
      if (!containsKeyword(value, keyword)) continue
      raw += weight
      hits.push([field, keyword, weight])
      if (weight > evidenceWeight) {
        const found = snippet(value, keyword)
        if (found) {
          evidence = found
          evidenceWeight = weight
        }
      }
    }
  }

  const language = normalizeText(repo.language)
  if (language && (line.languages ?? []).some((item) => item.toLowerCase() === language)) {
    raw += LANGUAGE_WEIGHT
    hits.push(['language', repo.language, LANGUAGE_WEIGHT])
  }
  if (raw <= 0) return null

  return {
    categoryName: line.name,
    businessLine: line.key,
    score: Math.round(Math.min(MAX_SCORE, BASE_SCORE + raw * SCORE_PER_WEIGHT) * 1000) / 1000,
    reason: reasonText(hits),
    evidence: evidence || (repo.summary || repo.description || repo.name).slice(0, EVIDENCE_LIMIT),
  }
}

/** 本地兜底：为单个仓库生成按分数降序的分类建议。 */
export function suggestCategoriesLocally(
  repo: CategorySuggestionRepo,
  perRepo = 3,
  minScore = 0.55
): LocalCategorySuggestion[] {
  const limit = Math.min(5, Math.max(1, Math.trunc(perRepo)))
  const threshold = Math.min(1, Math.max(0, minScore))
  const scored: LocalCategorySuggestion[] = []
  for (const line of BUSINESS_LINES) {
    const suggestion = scoreLine(repo, line)
    if (suggestion && suggestion.score >= threshold) scored.push(suggestion)
  }
  scored.sort((a, b) => b.score - a.score || a.categoryName.localeCompare(b.categoryName))
  return scored.slice(0, limit)
}

/** 按业务线 key 取描述（自动建分类时用作说明）。 */
export function businessLineDescription(key: string): string {
  return BUSINESS_LINES.find((line) => line.key === key)?.description ?? ''
}
