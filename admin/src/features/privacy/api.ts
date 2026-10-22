/**
 * 数据保留与隐私 API（M9-06）。
 *
 * - 策略公开读取，演示模式回退到本地快照；
 * - 导出走会话 Cookie，返回 JSON 附件；
 * - 删除账号需要精确输入 DELETE，成功后服务端清除会话。
 */
import {
  API_BASE,
  ApiHttpError,
  DEMO_MODE,
  apiFetch,
  fetchWithFallback,
} from '@/lib/api'
import type {
  AccountDeletionResult,
  PersonalDataDownload,
  PrivacyPolicyDocument,
} from './types'
import {
  buildDemoPersonalData,
  DEMO_PRIVACY_POLICY,
  parseFileName,
  personalDataFileName,
} from './utils'

export function fetchPrivacyPolicy(): Promise<PrivacyPolicyDocument> {
  return fetchWithFallback<PrivacyPolicyDocument>(
    '/api/privacy/policy',
    DEMO_PRIVACY_POLICY
  )
}

/** 下载个人数据 JSON；演示模式下生成结构一致的示例文件。 */
export async function downloadPersonalData(): Promise<PersonalDataDownload> {
  const generatedAt = new Date().toISOString()
  if (DEMO_MODE) {
    return {
      blob: new Blob([buildDemoPersonalData(generatedAt)], {
        type: 'application/json;charset=utf-8',
      }),
      fileName: personalDataFileName(generatedAt),
    }
  }

  const res = await fetch(`${API_BASE}/api/privacy/export`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    throw new ApiHttpError(res.status, res.statusText)
  }
  return {
    blob: await res.blob(),
    fileName: parseFileName(
      res.headers.get('Content-Disposition'),
      personalDataFileName(generatedAt)
    ),
  }
}

/** 删除当前账号；confirmation 必须为 DELETE。 */
export async function deleteAccount(
  confirmation: string
): Promise<AccountDeletionResult> {
  return apiFetch<AccountDeletionResult>('/api/privacy/account', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmation }),
  })
}

/** 触发浏览器下载并释放临时对象 URL。 */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
