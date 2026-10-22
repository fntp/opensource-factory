import { toast } from 'sonner'
import { apiErrorMessage } from './api'

/** 统一的请求错误提示（页面级错误态另行展示，这里负责全局 toast） */
export function handleServerError(error: unknown) {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log(error)
  }

  if (
    error &&
    typeof error === 'object' &&
    'status' in error &&
    Number(error.status) === 204
  ) {
    toast.error('请求成功但无返回内容')
    return
  }

  toast.error(apiErrorMessage(error, '操作失败，请稍后重试'))
}
