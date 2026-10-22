/**
 * 轻量类型化 D1 查询辅助：first / all / run 三个包装函数。
 * 用法示例：
 *   const row = await first<UserRow>(db, 'SELECT * FROM users WHERE id = ?', [id]);
 */
type Param = string | number | null;

/** 取第一行（无结果返回 null） */
export async function first<T>(
  db: D1Database,
  sql: string,
  params: Param[] = []
): Promise<T | null> {
  const stmt = db.prepare(sql).bind(...params);
  return (await stmt.first<T>()) ?? null;
}

/** 取全部行 */
export async function all<T>(
  db: D1Database,
  sql: string,
  params: Param[] = []
): Promise<T[]> {
  const stmt = db.prepare(sql).bind(...params);
  const res = await stmt.all<T>();
  return res.results ?? [];
}

/** 执行写语句，返回 D1 结果（meta.changes / meta.last_row_id 可用） */
export async function run(
  db: D1Database,
  sql: string,
  params: Param[] = []
): Promise<D1Result> {
  const stmt = db.prepare(sql).bind(...params);
  return await stmt.run();
}

/** 计数辅助：SELECT COUNT(*) AS n ... */
export async function count(
  db: D1Database,
  sql: string,
  params: Param[] = []
): Promise<number> {
  const row = await first<{ n: number }>(db, sql, params);
  return row?.n ?? 0;
}
