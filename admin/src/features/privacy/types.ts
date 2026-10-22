/** 数据保留与隐私策略（与 edge GET /api/privacy/policy 对齐）。 */

export interface RetentionPolicy {
  key: string
  category: string
  storage: string
  purpose: string
  retentionDays: number | null
  retentionLabel: string
  action: string
  note?: string
}

export interface PrivacyRight {
  key: string
  title: string
  description: string
  endpoint: string
}

export interface OutboundTransfer {
  target: string
  purpose: string
  data: string
}

export interface PrivacyPolicyDocument {
  version: string
  updatedAt: string
  controller: string
  contact: string
  retention: RetentionPolicy[]
  rights: PrivacyRight[]
  outbound: OutboundTransfer[]
  notes: string[]
}

export interface PersonalDataDownload {
  blob: Blob
  fileName: string
}

export interface AccountDeletionResult {
  status: 'deleted'
  deletedAt: string
  policyVersion: string
}
