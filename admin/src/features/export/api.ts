import { API_BASE, ApiHttpError, DEMO_MODE, fetchWithFallback } from '@/lib/api'
import type { ExportRequest, ExportSummary } from './types'
import { buildDemoExport, fallbackFileName } from './utils'

/** 演示模式下的导出统计（与演示仓库数据保持一致） */
export const MOCK_EXPORT_SUMMARY: ExportSummary = {
  totalRepos: 4,
  withSummary: 4,
  categoryCount: 3,
  tagCount: 11,
  totalStars: 357270,
  generatedAt: '2026-10-22T10:00:00.000Z',
}

export function fetchExportSummary(): Promise<ExportSummary> {
  return fetchWithFallback<ExportSummary>(
    '/api/export/knowledge/summary',
    MOCK_EXPORT_SUMMARY
  )
}

export interface ExportDownload {
  blob: Blob
  fileName: string
}

function toBlobPart(body: string | Uint8Array): BlobPart {
  if (typeof body === 'string') return body
  return body.buffer.slice(
    body.byteOffset,
    body.byteOffset + body.byteLength
  ) as ArrayBuffer
}

function parseFileName(header: string | null, fallback: string): string {
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

/** 下载知识库导出；演示模式下由前端本地生成同构文件 */
export async function downloadKnowledgeExport(
  request: ExportRequest
): Promise<ExportDownload> {
  const generatedAt = new Date().toISOString()

  if (DEMO_MODE) {
    const demo = buildDemoExport(request, generatedAt)
    return {
      blob: new Blob([toBlobPart(demo.body)], { type: demo.contentType }),
      fileName: demo.fileName,
    }
  }

  const params = new URLSearchParams({
    format: request.format,
    includeSummary: request.includeSummary ? '1' : '0',
    groupBy: request.groupBy,
  })
  const res = await fetch(`${API_BASE}/api/export/knowledge?${params.toString()}`, {
    credentials: 'include',
    headers: { Accept: '*/*' },
  })
  if (!res.ok) {
    throw new ApiHttpError(res.status, res.statusText)
  }
  const fallback = fallbackFileName(request.format, generatedAt)
  return {
    blob: await res.blob(),
    fileName: parseFileName(res.headers.get('Content-Disposition'), fallback),
  }
}

/** 触发浏览器下载并释放临时对象 URL */
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
