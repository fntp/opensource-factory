/**
 * 标签名称归一化 / 校验 / 查询参数解析（纯逻辑，便于 node:test 单测）。
 *
 * 规则：
 * - 去首尾空白，连续空白压缩为单个空格；
 * - 长度 1~50（按 Unicode 码点计）；
 * - 禁止逗号（仓库列表用逗号拼接标签名）与控制字符。
 */

export const TAG_NAME_MAX_LENGTH = 50;

export type TagNameError =
  | 'tag_name_required'
  | 'tag_name_too_long'
  | 'tag_name_invalid_chars';

export type TagNameValidation =
  | { ok: true; name: string }
  | { ok: false; error: TagNameError };

export type TagSort = 'name' | 'count';
export type SortOrder = 'asc' | 'desc';

export interface TagListQuery {
  q: string;
  sort: TagSort;
  order: SortOrder;
}

/** 归一化标签名（非字符串返回空串） */
export function normalizeTagName(raw: unknown): string {
  if (typeof raw !== 'string') return '';
  return raw.replace(/\s+/g, ' ').trim();
}

/** 是否包含 ASCII 控制字符（避免使用 control-char 正则） */
export function hasControlChars(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f) return true;
  }
  return false;
}

/** 校验并返回归一化后的标签名 */
export function validateTagName(raw: unknown): TagNameValidation {
  const name = normalizeTagName(raw);
  if (!name) return { ok: false, error: 'tag_name_required' };
  if ([...name].length > TAG_NAME_MAX_LENGTH) {
    return { ok: false, error: 'tag_name_too_long' };
  }
  // 逗号会破坏仓库列表的 GROUP_CONCAT 分隔；控制字符会破坏展示与日志
  if (name.includes(',') || hasControlChars(name)) {
    return { ok: false, error: 'tag_name_invalid_chars' };
  }
  return { ok: true, name };
}

/** 解析路径参数中的标签 id（正整数） */
export function parseTagId(raw: string | undefined | null): number | null {
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}

/** 解析列表查询参数，非法值回落到默认（count / desc） */
export function parseTagListQuery(
  q: string | undefined,
  sort: string | undefined,
  order: string | undefined
): TagListQuery {
  return {
    q: (q ?? '').trim(),
    sort: sort === 'name' ? 'name' : 'count',
    order: order === 'asc' ? 'asc' : 'desc',
  };
}

/** 转义 LIKE 通配符，避免用户输入的 % / _ 扩大匹配范围 */
export function escapeLikePattern(raw: string): string {
  return raw.replace(/[\\%_]/g, (ch) => `\\${ch}`);
}
