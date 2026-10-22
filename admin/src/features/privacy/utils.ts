import type { PrivacyPolicyDocument, RetentionPolicy } from './types'

/** 演示模式下的策略快照（与边缘默认值保持一致，仅用于离线预览）。 */
export const DEMO_PRIVACY_POLICY: PrivacyPolicyDocument = {
  version: '2026-10-22',
  updatedAt: '2026-10-22T00:00:00.000Z',
  controller: 'OpenFactory（个人开源资产管理与智能推荐系统）',
  contact: '通过 GitHub 账号登录后在「设置 → 隐私与数据」发起请求',
  retention: [
    {
      key: 'account',
      category: '账号资料',
      storage: 'D1 · users',
      purpose: 'GitHub OAuth 登录、账号展示与数据归属',
      retentionDays: null,
      retentionLabel: '保留至账号删除',
      action: '账号删除时立即清除',
      note: '仅包含 GitHub 公开资料与邮箱，不采集密码、支付信息或精确位置。',
    },
    {
      key: 'sessions',
      category: '登录会话',
      storage: 'D1 · sessions（仅存 token 的 SHA-256）',
      purpose: '维持登录态',
      retentionDays: 0,
      retentionLabel: '会话过期即清理（最长 30 天）',
      action: '过期后删除',
    },
    {
      key: 'login_attempts',
      category: '登录审计',
      storage: 'D1 · login_attempts（仅存 IP 哈希）',
      purpose: '防暴力破解与登录防护',
      retentionDays: 30,
      retentionLabel: '30 天',
      action: '到期删除',
    },
    {
      key: 'security_events',
      category: '安全事件',
      storage: 'D1 · security_events（仅存身份哈希）',
      purpose: '限流、锁定与内部令牌使用审计',
      retentionDays: 90,
      retentionLabel: '90 天',
      action: '到期删除',
    },
    {
      key: 'recommendations',
      category: '推荐记录',
      storage: 'D1 · recommendations',
      purpose: '生成个性化推荐与效果评估',
      retentionDays: 90,
      retentionLabel: '未收藏 90 天 / 已收藏 365 天',
      action: '到期删除',
    },
    {
      key: 'notifications',
      category: '站内通知',
      storage: 'D1 · notifications',
      purpose: '推荐与系统消息提醒',
      retentionDays: 180,
      retentionLabel: '已读 180 天 / 未读 365 天',
      action: '到期删除',
    },
    {
      key: 'repo_updates',
      category: '项目更新提醒',
      storage: 'D1 · repo_updates',
      purpose: '收藏项目的 Release / 重大变更提醒',
      retentionDays: 180,
      retentionLabel: '已读 180 天 / 未读 365 天',
      action: '到期删除',
    },
    {
      key: 'reports',
      category: '精选报告',
      storage: 'D1 · curated_reports',
      purpose: '周报 / 月报归档与下载',
      retentionDays: 365,
      retentionLabel: '365 天',
      action: '到期删除',
    },
    {
      key: 'extension_tokens',
      category: '浏览器扩展令牌',
      storage: 'D1 · extension_tokens（仅存 SHA-256 与提示片段）',
      purpose: '浏览器扩展一键收藏鉴权',
      retentionDays: 30,
      retentionLabel: '有效期内保留；撤销后 30 天',
      action: '撤销满 30 天删除',
    },
    {
      key: 'telegram',
      category: 'Telegram 绑定',
      storage: 'D1 · telegram_links / telegram_link_codes',
      purpose: 'Telegram Bot 查询入口',
      retentionDays: null,
      retentionLabel: '保留至解绑 / 账号删除；绑定码 10 分钟',
      action: '解绑或账号删除时清除',
    },
    {
      key: 'privacy_events',
      category: '隐私审计',
      storage: 'D1 · privacy_events（仅存用户 id 哈希）',
      purpose: '证明导出 / 删除 / 清理已执行',
      retentionDays: 365,
      retentionLabel: '365 天',
      action: '到期删除',
    },
  ],
  rights: [
    {
      key: 'access',
      title: '访问与导出',
      description: '随时下载账号下的全部个人数据（JSON）。',
      endpoint: 'GET /api/privacy/export',
    },
    {
      key: 'erasure',
      title: '删除账号',
      description: '删除账号及其个人数据；删除不可恢复。',
      endpoint: 'DELETE /api/privacy/account',
    },
    {
      key: 'rectification',
      title: '更正资料',
      description: 'GitHub 资料在下次登录时自动刷新。',
      endpoint: 'GET /api/auth/me',
    },
    {
      key: 'restriction',
      title: '限制处理',
      description: '可在通知 / 推送设置中关闭非必要处理。',
      endpoint: 'GET /api/push-preferences',
    },
  ],
  outbound: [
    {
      target: 'github.com / api.github.com',
      purpose: 'OAuth 登录、仓库与 Star 同步',
      data: 'OAuth code、公开仓库元数据',
    },
    {
      target: 'localhost:11434（Ollama）',
      purpose: '本地摘要与向量化',
      data: 'README 文本，不出机器',
    },
    {
      target: 'api.deepseek.com（可选降级）',
      purpose: '云端摘要降级',
      data: 'README 文本（不含用户身份）',
    },
    {
      target: 'Cloudflare（D1 / Workers / Pages / Vectorize）',
      purpose: '边缘 API、会话、向量存储',
      data: '上述 D1 数据与向量',
    },
  ],
  notes: [
    '不采集密码、支付信息、通讯录或精确位置。',
    '登录审计只保存 IP 哈希，安全事件只保存身份哈希。',
    '删除账号会同时清除边缘 D1 主数据与 VPS 本地镜像中的用户关联记录。',
  ],
}

/** 保留期展示文案；null 表示保留至账号删除。 */
export function retentionText(policy: RetentionPolicy): string {
  if (policy.retentionDays === null) return '保留至账号删除'
  return policy.retentionLabel || `${policy.retentionDays} 天`
}

/** 策略日期格式化为 YYYY-MM-DD（无效值回退原文）。 */
export function formatPolicyDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '—'
  return date.toISOString().slice(0, 10)
}

/** 从 Content-Disposition 解析文件名，兼容 filename* 与普通 filename。 */
export function parseFileName(header: string | null, fallback: string): string {
  if (!header) return fallback
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // 忽略非法编码，继续尝试普通 filename
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain?.[1]?.trim() || fallback
}

/** 个人数据导出文件名（UTC 日期）。 */
export function personalDataFileName(generatedAt: string): string {
  const date = new Date(generatedAt)
  const safe = Number.isNaN(date.getTime())
    ? generatedAt.slice(0, 10)
    : date.toISOString().slice(0, 10)
  return `openfactory-personal-data-${safe}.json`
}

/** 演示模式导出内容：结构与边缘导出一致，但不含真实个人数据。 */
export function buildDemoPersonalData(generatedAt: string): string {
  return JSON.stringify(
    {
      schemaVersion: 'openfactory.personal-data.v1',
      policyVersion: DEMO_PRIVACY_POLICY.version,
      generatedAt,
      subject: {
        id: 'demo-user',
        login: 'demo',
        name: '演示用户',
        email: null,
        avatarUrl: null,
        createdAt: '2026-01-01T00:00:00.000Z',
      },
      counts: {},
      data: {},
      notes: [
        '当前为演示模式，未连接后端；此文件仅用于预览导出格式。',
      ],
    },
    null,
    2
  )
}
