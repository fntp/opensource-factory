/**
 * GET /api/repos 查询参数解析与 SQL 片段构建。
 *
 * 纯函数模块：不依赖 D1 / Hono，便于用 node:test 直接覆盖边界条件。
 * 所有用户输入只作为绑定参数进入 SQL；排序字段 / 方向走白名单映射。
 */

export type RepoSortField = 'stars' | 'updated' | 'created' | 'name' | 'forks';
export type SortOrder = 'asc' | 'desc';
export type SqlParam = string | number | null;

export interface RepoQuery {
  q: string;
  categoryId: string;
  tagNames: string[];
  tagIds: number[];
  languages: string[];
  starsMin: number | null;
  starsMax: number | null;
  updatedAfter: string;
  updatedBefore: string;
  sort: RepoSortField;
  order: SortOrder;
}

export type RepoQueryParseResult =
  | { ok: true; query: RepoQuery }
  | { ok: false; field: string; message: string };

export interface CategoryNode {
  id: string;
  parent_id: string | null;
}

export interface RepoWhere {
  where: string[];
  params: SqlParam[];
}

const SORT_FIELDS: readonly RepoSortField[] = [
  'stars',
  'updated',
  'created',
  'name',
  'forks',
];
const SORT_ORDERS: readonly SortOrder[] = ['asc', 'desc'];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function readText(searchParams: URLSearchParams, key: string): string {
  return searchParams.get(key)?.trim() ?? '';
}

function readCsv(searchParams: URLSearchParams, key: string): string[] {
  return readText(searchParams, key)
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function parseNonNegativeInt(
  raw: string,
  field: string
): { ok: true; value: number | null } | { ok: false; field: string; message: string } {
  if (raw === '') return { ok: true, value: null };
  if (!/^\d+$/.test(raw)) {
    return { ok: false, field, message: `${field} 必须是非负整数` };
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) {
    return { ok: false, field, message: `${field} 超出安全整数范围` };
  }
  return { ok: true, value };
}

function isValidDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

/** 解析查询参数；非法值返回可定位到字段的错误，而不是静默忽略。 */
export function parseRepoQuery(searchParams: URLSearchParams): RepoQueryParseResult {
  const starsMinResult = parseNonNegativeInt(readText(searchParams, 'starsMin'), 'starsMin');
  if (!starsMinResult.ok) return starsMinResult;
  const starsMaxResult = parseNonNegativeInt(readText(searchParams, 'starsMax'), 'starsMax');
  if (!starsMaxResult.ok) return starsMaxResult;

  const starsMin = starsMinResult.value;
  const starsMax = starsMaxResult.value;
  if (starsMin !== null && starsMax !== null && starsMin > starsMax) {
    return { ok: false, field: 'starsMin', message: 'starsMin 不能大于 starsMax' };
  }

  const updatedAfter = readText(searchParams, 'updatedAfter');
  const updatedBefore = readText(searchParams, 'updatedBefore');
  if (updatedAfter && !isValidDate(updatedAfter)) {
    return { ok: false, field: 'updatedAfter', message: 'updatedAfter 必须是 YYYY-MM-DD' };
  }
  if (updatedBefore && !isValidDate(updatedBefore)) {
    return { ok: false, field: 'updatedBefore', message: 'updatedBefore 必须是 YYYY-MM-DD' };
  }
  if (updatedAfter && updatedBefore && updatedAfter > updatedBefore) {
    return { ok: false, field: 'updatedAfter', message: 'updatedAfter 不能晚于 updatedBefore' };
  }

  const rawTagIds = readCsv(searchParams, 'tagIds');
  const tagIds: number[] = [];
  for (const raw of rawTagIds) {
    if (!/^\d+$/.test(raw)) {
      return { ok: false, field: 'tagIds', message: 'tagIds 必须是逗号分隔的正整数' };
    }
    tagIds.push(Number(raw));
  }

  const sortRaw = readText(searchParams, 'sort') || 'stars';
  if (!SORT_FIELDS.includes(sortRaw as RepoSortField)) {
    return { ok: false, field: 'sort', message: `sort 只支持 ${SORT_FIELDS.join(' / ')}` };
  }
  const orderRaw = readText(searchParams, 'order') || 'desc';
  if (!SORT_ORDERS.includes(orderRaw as SortOrder)) {
    return { ok: false, field: 'order', message: 'order 只支持 asc / desc' };
  }

  return {
    ok: true,
    query: {
      q: readText(searchParams, 'q'),
      categoryId: readText(searchParams, 'categoryId'),
      tagNames: readCsv(searchParams, 'tags'),
      tagIds,
      // 兼容单数形式 ?language=，同时支持多选 ?languages=a,b
      languages: Array.from(
        new Set([...readCsv(searchParams, 'languages'), ...readCsv(searchParams, 'language')])
      ),
      starsMin,
      starsMax,
      updatedAfter,
      updatedBefore,
      sort: sortRaw as RepoSortField,
      order: orderRaw as SortOrder,
    },
  };
}

/** 转义 LIKE 通配符，用户输入中的 % / _ / \ 按字面量匹配。 */
export function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (char) => `\\${char}`);
}

/** 日期起点（含当天 00:00:00 UTC）。 */
export function startOfDate(date: string): string {
  return `${date}T00:00:00.000Z`;
}

/** 次日起点（不含），用于「截止某天」的闭区间语义。 */
export function endOfDateExclusive(date: string): string {
  const next = new Date(`${date}T00:00:00.000Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString();
}

/** 展开分类及其全部子孙分类 id（无限级）；根不存在时至少保留根 id。 */
export function collectCategoryIds(nodes: CategoryNode[], rootId: string): string[] {
  const children = new Map<string, string[]>();
  for (const node of nodes) {
    if (!node.parent_id) continue;
    const list = children.get(node.parent_id) ?? [];
    list.push(node.id);
    children.set(node.parent_id, list);
  }

  const result: string[] = [];
  const seen = new Set<string>();
  const stack = [rootId];
  while (stack.length > 0) {
    const id = stack.pop();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    result.push(id);
    const descendants = children.get(id);
    if (descendants) stack.push(...descendants);
  }
  return result;
}

/** 构建 WHERE 子句与绑定参数（user_id 永远作为第一个参数）。 */
export function buildRepoWhere(
  query: RepoQuery,
  userId: string,
  categoryIds: string[] = []
): RepoWhere {
  const where: string[] = ['r.user_id = ?'];
  const params: SqlParam[] = [userId];

  if (query.q) {
    const like = `%${escapeLike(query.q)}%`;
    where.push(`(
      r.name LIKE ? ESCAPE '\\'
      OR r.id LIKE ? ESCAPE '\\'
      OR r.owner LIKE ? ESCAPE '\\'
      OR r.description LIKE ? ESCAPE '\\'
      OR r.readme_summary LIKE ? ESCAPE '\\'
      OR r.language LIKE ? ESCAPE '\\'
      OR cat.name LIKE ? ESCAPE '\\'
      OR EXISTS (
        SELECT 1 FROM repo_tags qrt
        JOIN tags qt ON qt.id = qrt.tag_id
        WHERE qrt.repo_id = r.id AND qt.name LIKE ? ESCAPE '\\'
      )
    )`);
    params.push(like, like, like, like, like, like, like, like);
  }

  if (query.categoryId) {
    const ids = categoryIds.length > 0 ? categoryIds : [query.categoryId];
    where.push(`r.category_id IN (${ids.map(() => '?').join(', ')})`);
    params.push(...ids);
  }

  // 多个标签为 AND：每个标签都必须存在对应关联。
  for (const tagName of query.tagNames) {
    where.push(`EXISTS (
      SELECT 1 FROM repo_tags rt
      JOIN tags t ON t.id = rt.tag_id
      WHERE rt.repo_id = r.id AND t.name = ? COLLATE NOCASE
    )`);
    params.push(tagName);
  }
  for (const tagId of query.tagIds) {
    where.push(`EXISTS (
      SELECT 1 FROM repo_tags rt
      WHERE rt.repo_id = r.id AND rt.tag_id = ?
    )`);
    params.push(tagId);
  }

  if (query.languages.length > 0) {
    where.push(`r.language COLLATE NOCASE IN (${query.languages.map(() => '?').join(', ')})`);
    params.push(...query.languages);
  }

  if (query.starsMin !== null) {
    where.push('COALESCE(r.stars, 0) >= ?');
    params.push(query.starsMin);
  }
  if (query.starsMax !== null) {
    where.push('COALESCE(r.stars, 0) <= ?');
    params.push(query.starsMax);
  }

  if (query.updatedAfter) {
    where.push('r.updated_at >= ?');
    params.push(startOfDate(query.updatedAfter));
  }
  if (query.updatedBefore) {
    where.push('r.updated_at < ?');
    params.push(endOfDateExclusive(query.updatedBefore));
  }

  return { where, params };
}

const SORT_SQL: Record<RepoSortField, string> = {
  stars: 'COALESCE(r.stars, 0)',
  updated: "COALESCE(r.updated_at, r.synced_at, '')",
  created: "COALESCE(r.created_at, '')",
  name: 'r.name COLLATE NOCASE',
  forks: 'COALESCE(r.forks, 0)',
};

/** 排序子句：字段 / 方向白名单映射，追加 id 作为稳定次序。 */
export function buildRepoOrderBy(sort: RepoSortField, order: SortOrder): string {
  const direction = order === 'asc' ? 'ASC' : 'DESC';
  return `${SORT_SQL[sort]} ${direction}, r.id ASC`;
}
