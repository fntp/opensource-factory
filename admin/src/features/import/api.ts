import { ApiHttpError, DEMO_MODE, apiFetch, fetchWithFallback } from '@/lib/api'
import type {
  ImportHistoryResponse,
  ImportPreview,
  ImportRequest,
  ImportResult,
} from './types'
import { MOCK_IMPORT_HISTORY, buildDemoPreview, buildDemoResult } from './utils'

function postImport<T>(path: string, request: ImportRequest): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

/** 预览导入：只解析与比对，不写库 */
export async function previewImport(
  request: ImportRequest
): Promise<ImportPreview> {
  if (DEMO_MODE) return buildDemoPreview(request)
  return postImport<ImportPreview>('/api/import/preview', request)
}

/** 执行导入：服务端会重新解析同一份内容 */
export async function executeImport(
  request: ImportRequest
): Promise<ImportResult> {
  if (DEMO_MODE) {
    return buildDemoResult(buildDemoPreview(request))
  }
  return postImport<ImportResult>('/api/import/execute', request)
}

/** 最近导入历史；接口不可用时回退演示数据 */
export function fetchImportHistory(): Promise<ImportHistoryResponse> {
  return fetchWithFallback<ImportHistoryResponse>('/api/import/history', MOCK_IMPORT_HISTORY)
}

/** 把接口错误码翻译成可操作的提示 */
export function importErrorMessage(error: unknown): string {
  if (error instanceof ApiHttpError) {
    switch (error.code) {
      case 'content_too_large':
        return '内容超过 2 MB 上限，请拆分后再导入'
      case 'content_required':
        return '请先选择文件或粘贴导入内容'
      case 'unsupported_format':
        return '不支持的文件格式，请选择 JSON / CSV / 浏览器书签 HTML'
      case 'invalid_body':
        return '请求格式不正确，请刷新页面后重试'
      case 'invalid_json':
        return '请求体不是合法 JSON'
      case 'rate_limited':
        return '操作过于频繁，请稍后再试'
      case 'unauthorized':
        return '登录已过期，请重新登录'
      default:
        break
    }
    if (error.status === 401) return '登录已过期，请重新登录'
    if (error.status === 413) return '内容超过 2 MB 上限，请拆分后再导入'
  }
  return '导入失败，请检查文件内容后重试'
}
