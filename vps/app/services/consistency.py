"""数据一致性巡检：D1 主数据 ↔ 本机 SQLite 镜像对账。

设计要点：

- **只读**：只执行 SELECT / PRAGMA，不修改任何一侧的数据；
- **列交集**：D1 与本机表结构会随迭代演进，只有双方都存在的列才参与比较，
  缺失列进入 ``skippedFields`` 说明，避免把「本地尚未镜像该列」误报为差异；
- **纯函数**：归一化、对账、报告渲染均不依赖 FastAPI / SQLAlchemy，便于单测；
- **多数据源**：D1 快照可来自 edge 内部接口（在线）、wrangler 导出的 SQLite 文件、
  或 JSON 快照（离线 / 归档）。

命令行入口见 ``vps/scripts/consistency_audit.py``。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AuditInputError(RuntimeError):
    """输入 / 连接错误（CLI 以退出码 2 上报）。"""


@dataclass(frozen=True)
class FieldSpec:
    """一个可比字段：D1 列名、本地列名（缺省同名）与归一化类型。"""

    name: str
    local: str | None = None
    kind: str = "text"  # text | int | float | datetime
    default: Any = None

    @property
    def local_name(self) -> str:
        return self.local or self.name


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: str
    label: str
    fields: tuple[FieldSpec, ...]


TABLE_SPECS: dict[str, TableSpec] = {
    "my_repositories": TableSpec(
        name="my_repositories",
        key="id",
        label="我的仓库",
        fields=(
            FieldSpec("id"),
            FieldSpec("platform"),
            FieldSpec("name"),
            FieldSpec("description"),
            FieldSpec("html_url"),
            FieldSpec("stars", kind="int", default=0),
            FieldSpec("language"),
            FieldSpec("readme_summary"),
            FieldSpec("category_id"),
            FieldSpec("created_at", kind="datetime"),
            FieldSpec("user_id"),
            FieldSpec("owner"),
            FieldSpec("forks", kind="int", default=0),
            FieldSpec("updated_at", kind="datetime"),
            FieldSpec("synced_at", kind="datetime"),
        ),
    ),
    "categories": TableSpec(
        name="categories",
        key="id",
        label="分类",
        fields=(
            FieldSpec("id"),
            FieldSpec("name"),
            FieldSpec("parent_id"),
            FieldSpec("description"),
            FieldSpec("sort_order", kind="int", default=0),
        ),
    ),
    "trending_repositories": TableSpec(
        name="trending_repositories",
        key="id",
        label="热榜仓库",
        fields=(
            FieldSpec("id"),
            FieldSpec("platform"),
            FieldSpec("name"),
            FieldSpec("html_url"),
            FieldSpec("stars_today", kind="int", default=0),
            FieldSpec("description"),
            FieldSpec("tech_stack"),
            FieldSpec("crawled_at", kind="datetime"),
            FieldSpec("owner"),
            FieldSpec("language"),
            FieldSpec("stars", kind="int", default=0),
        ),
    ),
    "users": TableSpec(
        name="users",
        key="id",
        label="用户",
        fields=(
            FieldSpec("id"),
            FieldSpec("login", local="username"),
            FieldSpec("name"),
            FieldSpec("email"),
            FieldSpec("avatar_url"),
            FieldSpec("created_at", kind="datetime"),
        ),
    ),
    "recommendations": TableSpec(
        name="recommendations",
        key="id",
        label="推荐",
        fields=(
            FieldSpec("id"),
            FieldSpec("user_id"),
            FieldSpec("owner"),
            FieldSpec("name"),
            FieldSpec("description"),
            FieldSpec("language"),
            FieldSpec("stars", kind="int", default=0),
            FieldSpec("score", kind="float", default=0.0),
            FieldSpec("reason"),
            FieldSpec("based_on"),
            FieldSpec("url"),
            FieldSpec("status"),
            FieldSpec("created_at", kind="datetime"),
        ),
    ),
}

DEFAULT_TABLES: tuple[str, ...] = tuple(TABLE_SPECS)


# ── 归一化 ──────────────────────────────────────────────────────


def normalize_datetime(value: Any) -> str:
    """把 D1 / SQLite / Python 的时间统一为 ``YYYY-MM-DDTHH:MM:SS``（UTC）。"""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip()
        if not text:
            return ""
        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(candidate)
            except ValueError:
                return text
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def normalize_value(value: Any, kind: str = "text", default: Any = None) -> Any:
    """按字段类型归一化，消除 D1 / SQLite 驱动的表示差异。"""
    if kind == "text":
        return "" if value is None else str(value).strip()
    if kind == "int":
        if value is None or value == "":
            return int(default or 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value).strip()
    if kind == "float":
        if value is None or value == "":
            return float(default or 0.0)
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return str(value).strip()
    if kind == "datetime":
        return normalize_datetime(value)
    return value


def _row_get(row: Mapping[str, Any] | sqlite3.Row, name: str) -> Any:
    if isinstance(row, sqlite3.Row):
        return row[name] if name in row.keys() else None
    return row.get(name)


def _row_keys(row: Mapping[str, Any] | sqlite3.Row) -> set[str]:
    return set(row.keys())


def _index_rows(
    rows: Iterable[Mapping[str, Any] | sqlite3.Row], key: str
) -> tuple[dict[str, Mapping[str, Any] | sqlite3.Row], list[str], list[str]]:
    """按主键建索引，返回 (索引, 重复主键, 非法主键)。"""
    indexed: dict[str, Mapping[str, Any] | sqlite3.Row] = {}
    duplicates: list[str] = []
    invalid: list[str] = []
    for row in rows:
        raw = _row_get(row, key)
        key_value = "" if raw is None else str(raw).strip()
        if not key_value:
            invalid.append("")
            continue
        if key_value in indexed:
            duplicates.append(key_value)
            continue
        indexed[key_value] = row
    return indexed, sorted(set(duplicates)), sorted(set(invalid))


# ── 对账 ────────────────────────────────────────────────────────


def audit_table(
    spec: TableSpec,
    d1_rows: Sequence[Mapping[str, Any] | sqlite3.Row],
    local_rows: Sequence[Mapping[str, Any] | sqlite3.Row],
    *,
    d1_columns: Iterable[str] | None = None,
    local_columns: Iterable[str] | None = None,
    ignore_fields: Iterable[str] = (),
    sample_limit: int = 10,
) -> dict[str, Any]:
    """比较单张表，返回结构化结果。"""
    d1_cols = set(d1_columns or ()) or _collect_columns(d1_rows)
    local_cols = set(local_columns or ()) or _collect_columns(local_rows)
    ignored = set(ignore_fields)

    compared: list[FieldSpec] = []
    skipped: list[dict[str, str]] = []
    for field in spec.fields:
        if f"{spec.name}.{field.name}" in ignored:
            skipped.append({"field": field.name, "reason": "ignored"})
        elif field.name not in d1_cols:
            skipped.append({"field": field.name, "reason": "d1_column_missing"})
        elif field.local_name not in local_cols:
            skipped.append({"field": field.name, "reason": "local_column_missing"})
        else:
            compared.append(field)

    d1_map, d1_dupes, d1_invalid = _index_rows(d1_rows, spec.key)
    local_map, local_dupes, local_invalid = _index_rows(local_rows, spec.key)

    missing_in_local = sorted(set(d1_map) - set(local_map))
    missing_in_d1 = sorted(set(local_map) - set(d1_map))

    mismatches: list[dict[str, Any]] = []
    mismatch_fields: dict[str, int] = {}
    for key in sorted(set(d1_map) & set(local_map)):
        d1_row = d1_map[key]
        local_row = local_map[key]
        for field in compared:
            d1_value = normalize_value(_row_get(d1_row, field.name), field.kind, field.default)
            local_value = normalize_value(
                _row_get(local_row, field.local_name), field.kind, field.default
            )
            if d1_value != local_value:
                mismatch_fields[field.name] = mismatch_fields.get(field.name, 0) + 1
                if len(mismatches) < sample_limit:
                    mismatches.append(
                        {
                            "key": key,
                            "field": field.name,
                            "d1": d1_value,
                            "local": local_value,
                        }
                    )

    mismatch_count = sum(mismatch_fields.values())
    has_difference = bool(
        missing_in_local
        or missing_in_d1
        or mismatch_count
        or d1_dupes
        or local_dupes
        or d1_invalid
        or local_invalid
    )
    return {
        "table": spec.name,
        "label": spec.label,
        "key": spec.key,
        "d1Count": len(d1_rows),
        "localCount": len(local_rows),
        "d1UniqueKeys": len(d1_map),
        "localUniqueKeys": len(local_map),
        "missingInLocal": missing_in_local[:sample_limit],
        "missingInLocalCount": len(missing_in_local),
        "missingInD1": missing_in_d1[:sample_limit],
        "missingInD1Count": len(missing_in_d1),
        "duplicateKeys": d1_dupes[:sample_limit],
        "duplicateKeyCount": len(d1_dupes) + len(local_dupes),
        "localDuplicateKeys": local_dupes[:sample_limit],
        "invalidKeys": (d1_invalid + local_invalid)[:sample_limit],
        "invalidKeyCount": len(d1_invalid) + len(local_invalid),
        "mismatches": mismatches,
        "mismatchCount": mismatch_count,
        "mismatchFields": dict(sorted(mismatch_fields.items())),
        "comparedFields": [field.name for field in compared],
        "skippedFields": skipped,
        "status": "differences" if has_difference else "consistent",
    }


def _collect_columns(rows: Sequence[Mapping[str, Any] | sqlite3.Row]) -> set[str]:
    columns: set[str] = set()
    for row in rows:
        columns.update(_row_keys(row))
    return columns


def run_audit(
    d1_tables: Mapping[str, Sequence[Mapping[str, Any] | sqlite3.Row]],
    local_tables: Mapping[str, Sequence[Mapping[str, Any] | sqlite3.Row]],
    *,
    tables: Sequence[str] = DEFAULT_TABLES,
    d1_columns: Mapping[str, Iterable[str]] | None = None,
    local_columns: Mapping[str, Iterable[str]] | None = None,
    ignore_fields: Iterable[str] = (),
    sample_limit: int = 10,
    source: str = "",
    local_db: str = "",
) -> dict[str, Any]:
    """对多张表执行对账并汇总。"""
    table_reports: list[dict[str, Any]] = []
    for name in tables:
        spec = TABLE_SPECS.get(name)
        if spec is None:
            raise AuditInputError(f"不支持的对账表: {name}（可选：{', '.join(DEFAULT_TABLES)}）")
        table_reports.append(
            audit_table(
                spec,
                d1_tables.get(name, []),
                local_tables.get(name, []),
                d1_columns=(d1_columns or {}).get(name),
                local_columns=(local_columns or {}).get(name),
                ignore_fields=ignore_fields,
                sample_limit=sample_limit,
            )
        )

    summary = {
        "tables": len(table_reports),
        "consistent": sum(1 for item in table_reports if item["status"] == "consistent"),
        "differences": sum(1 for item in table_reports if item["status"] == "differences"),
        "missingInLocal": sum(item["missingInLocalCount"] for item in table_reports),
        "missingInD1": sum(item["missingInD1Count"] for item in table_reports),
        "mismatches": sum(item["mismatchCount"] for item in table_reports),
        "duplicateKeys": sum(item["duplicateKeyCount"] for item in table_reports),
    }
    return {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "localDb": local_db,
        "tables": table_reports,
        "summary": summary,
        "status": "consistent" if summary["differences"] == 0 else "differences",
    }


# ── 数据源：SQLite / JSON 快照 / edge 接口 ──────────────────────


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise AuditInputError(f"SQLite 文件不存在: {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - 文件存在时极少触发
        raise AuditInputError(f"无法打开 SQLite: {path}（{exc}）") from exc
    conn.row_factory = sqlite3.Row
    return conn


def load_sqlite_table(db_path: str | Path, table: str) -> tuple[list[str], list[dict[str, Any]]]:
    """从 SQLite（本机镜像或 D1 导出库）读取一张表。"""
    spec = TABLE_SPECS.get(table)
    if spec is None:
        raise AuditInputError(f"不支持的对账表: {table}")
    conn = _connect_readonly(db_path)
    try:
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        if not columns:
            raise AuditInputError(f"表不存在或为空结构: {table}（{db_path}）")
        rows = [
            {key: row[key] for key in row.keys()}
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY {spec.key} ASC")
        ]
    except sqlite3.Error as exc:
        raise AuditInputError(f"读取 {table} 失败（{db_path}）：{exc}") from exc
    finally:
        conn.close()
    return columns, rows


def load_json_snapshot(path: str | Path, table: str) -> tuple[list[str], list[dict[str, Any]]]:
    """读取 JSON 快照。

    支持三种格式：
    1. 汇总格式：``{"tables": {"my_repositories": [...]}, "columns": {...}}``；
    2. 单表格式：``{"table": "my_repositories", "columns": [...], "rows": [...]}``；
    3. wrangler 输出：``[{"results": [...], "success": true}]``（需单表）。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise AuditInputError(f"快照文件不存在: {file_path}")
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditInputError(f"快照解析失败（{file_path}）：{exc}") from exc

    columns: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("tables"), dict):
        rows = payload["tables"].get(table)
        if rows is None:
            raise AuditInputError(f"快照中缺少表: {table}")
        column_map = payload.get("columns")
        if isinstance(column_map, dict):
            columns = list(column_map.get(table) or [])
    elif isinstance(payload, dict) and "rows" in payload:
        snapshot_table = payload.get("table")
        if snapshot_table and snapshot_table != table:
            raise AuditInputError(f"快照表名不匹配：期望 {table}，实际 {snapshot_table}")
        rows = payload.get("rows")
        columns = list(payload.get("columns") or [])
    elif isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "results" in payload[0]:
            rows = []
            for item in payload:
                if isinstance(item, dict) and isinstance(item.get("results"), list):
                    rows.extend(item["results"])
        else:
            rows = payload
    else:
        raise AuditInputError(f"无法识别的快照格式（{file_path}）")

    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise AuditInputError(f"快照行数据格式错误（{file_path}）")
    if not columns:
        inferred: set[str] = set()
        for row in rows:
            inferred.update(row.keys())
        columns = sorted(inferred)
    return columns, rows


def fetch_edge_table(
    base_url: str,
    table: str,
    token: str,
    *,
    page_size: int = 500,
    timeout: float = 30.0,
    opener: Callable[..., Any] = urlopen,
) -> tuple[list[str], list[dict[str, Any]]]:
    """从 edge 内部快照接口分页拉取一张表。"""
    if not token:
        raise AuditInputError("--edge-url 模式必须提供 --token 或 INTERNAL_TOKEN")
    if page_size < 1 or page_size > 1000:
        raise AuditInputError("page_size 需为 1~1000")
    base = base_url.rstrip("/")
    offset = 0
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    total: int | None = None
    while True:
        query = urlencode({"table": table, "limit": page_size, "offset": offset})
        url = f"{base}/api/internal/consistency/snapshot?{query}"
        request = Request(url, headers={"X-Internal-Token": token, "Accept": "application/json"})
        try:
            with opener(request, timeout=timeout) as response:  # type: ignore[attr-defined]
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # pragma: no cover - 读取错误体失败时忽略
                pass
            raise AuditInputError(f"快照接口返回 HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AuditInputError(f"无法连接快照接口 {base}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AuditInputError(f"快照接口返回非 JSON（{base}）：{exc}") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise AuditInputError("快照接口响应缺少 rows")
        if payload.get("table") != table:
            raise AuditInputError(f"快照接口表名不匹配：期望 {table}，实际 {payload.get('table')}")
        if not columns:
            columns = list(payload.get("columns") or [])
        page_rows = payload["rows"]
        rows.extend(page_rows)
        total = int(payload.get("total") or 0)
        offset += len(page_rows)
        if not payload.get("hasMore") or not page_rows:
            break
        if offset > 1_000_000:  # pragma: no cover - 防御异常接口
            raise AuditInputError("快照分页超过 100 万行，已中止")
    if total is not None and total != len(rows):
        raise AuditInputError(f"快照行数不一致：接口 total={total}，实际拉取 {len(rows)}")
    return columns, rows


def load_local_tables(
    db_path: str | Path, tables: Sequence[str]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    columns: dict[str, list[str]] = {}
    for table in tables:
        columns[table], rows[table] = load_sqlite_table(db_path, table)
    return rows, columns


# ── 报告渲染 ────────────────────────────────────────────────────


def render_summary_text(report: Mapping[str, Any]) -> str:
    """命令行摘要（固定宽度，便于日志检索）。"""
    lines = [
        "数据一致性巡检 · D1 ↔ 本机镜像",
        f"数据源: {report.get('source') or '—'}",
        f"本地库: {report.get('localDb') or '—'}",
        f"生成时间: {report.get('generatedAt')}",
        "",
        f"{'表':<24}{'D1':>7}{'本地':>7}{'本机缺失':>10}{'D1缺失':>9}{'字段差异':>10}{'状态':>8}",
    ]
    for item in report.get("tables", []):
        lines.append(
            f"{item['table']:<24}{item['d1Count']:>7}{item['localCount']:>7}"
            f"{item['missingInLocalCount']:>10}{item['missingInD1Count']:>9}"
            f"{item['mismatchCount']:>10}{('一致' if item['status'] == 'consistent' else '差异'):>8}"
        )
    summary = report.get("summary", {})
    lines.extend(
        [
            "",
            (
                "结论: 未发现差异"
                if report.get("status") == "consistent"
                else (
                    "结论: 发现差异 "
                    f"（本机缺失 {summary.get('missingInLocal', 0)} · "
                    f"D1 缺失 {summary.get('missingInD1', 0)} · "
                    f"字段差异 {summary.get('mismatches', 0)}）"
                )
            ),
        ]
    )
    return "\n".join(lines)


def _md_value(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 120 else text[:117] + "..."


def render_markdown(report: Mapping[str, Any]) -> str:
    """Markdown 报告：汇总表 + 逐表明细。"""
    lines = [
        "# 数据一致性巡检报告（D1 ↔ 本机镜像）",
        "",
        f"- 生成时间：{report.get('generatedAt')}",
        f"- 数据源：{report.get('source') or '—'}",
        f"- 本地库：{report.get('localDb') or '—'}",
        f"- 总体状态：{'✅ 一致' if report.get('status') == 'consistent' else '⚠️ 存在差异'}",
        "",
        "## 汇总",
        "",
        "| 表 | D1 行数 | 本地行数 | 本机缺失 | D1 缺失 | 字段差异 | 状态 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("tables", []):
        lines.append(
            f"| `{item['table']}`（{item['label']}） | {item['d1Count']} | {item['localCount']} | "
            f"{item['missingInLocalCount']} | {item['missingInD1Count']} | {item['mismatchCount']} | "
            f"{'✅ 一致' if item['status'] == 'consistent' else '⚠️ 差异'} |"
        )

    summary = report.get("summary", {})
    lines.extend(
        [
            "",
            f"合计：{summary.get('tables', 0)} 张表，{summary.get('consistent', 0)} 张一致，"
            f"{summary.get('differences', 0)} 张存在差异。",
            "",
            "## 明细",
            "",
        ]
    )

    for item in report.get("tables", []):
        if item["status"] == "consistent":
            continue
        lines.append(f"### `{item['table']}`（{item['label']}）")
        lines.append("")
        if item["missingInLocalCount"]:
            lines.append(f"- 本机缺失（D1 有、本地无）{item['missingInLocalCount']} 条：")
            lines.append("")
            lines.append("```text")
            lines.extend(item["missingInLocal"] or ["（样例超出限制）"])
            lines.append("```")
            lines.append("")
        if item["missingInD1Count"]:
            lines.append(f"- D1 缺失（本地有、D1 无）{item['missingInD1Count']} 条：")
            lines.append("")
            lines.append("```text")
            lines.extend(item["missingInD1"] or ["（样例超出限制）"])
            lines.append("```")
            lines.append("")
        if item["mismatchCount"]:
            lines.append(f"- 字段差异 {item['mismatchCount']} 处（按字段统计：")
            lines.append(
                "，".join(f"`{name}` × {count}" for name, count in item["mismatchFields"].items())
                + "）："
            )
            lines.append("")
            lines.append("| 主键 | 字段 | D1 | 本机 |")
            lines.append("| --- | --- | --- | --- |")
            for mismatch in item["mismatches"]:
                lines.append(
                    f"| `{_md_value(mismatch['key'])}` | `{mismatch['field']}` | "
                    f"{_md_value(mismatch['d1'])} | {_md_value(mismatch['local'])} |"
                )
            lines.append("")
        if item["duplicateKeyCount"] or item["invalidKeyCount"]:
            lines.append(
                f"- 数据质量：重复主键 {item['duplicateKeyCount']} 个，非法主键 {item['invalidKeyCount']} 个。"
            )
            lines.append("")
        if item["skippedFields"]:
            skipped = "，".join(
                f"`{entry['field']}`（{entry['reason']}）" for entry in item["skippedFields"]
            )
            lines.append(f"- 未比较字段：{skipped}")
            lines.append("")

    if report.get("status") == "consistent":
        lines.extend(["未发现差异。", ""])
    lines.extend(
        [
            "---",
            "",
            "> 本报告由只读巡检工具生成，不会修改 D1 或本机镜像。",
            "> 修复建议：先确认主数据方向（D1 为主），再按差异类型重新同步或补齐。",
            "",
        ]
    )
    return "\n".join(lines)
