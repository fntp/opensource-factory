#!/usr/bin/env python3
"""数据一致性巡检 CLI：D1 ↔ 本机 SQLite 镜像。

用法示例：

    # 1) 在线：从 edge 内部快照接口拉取 D1（推荐）
    .venv/bin/python scripts/consistency_audit.py \
        --edge-url https://<worker-domain> --token "$INTERNAL_TOKEN"

    # 2) 离线：读取 wrangler d1 export 生成的 SQLite
    .venv/bin/python scripts/consistency_audit.py --d1-db /tmp/d1-export.db

    # 3) 离线：读取 JSON 快照（汇总 / 单表 / wrangler --json 输出）
    .venv/bin/python scripts/consistency_audit.py --snapshot /tmp/d1-snapshot.json \
        --tables my_repositories

退出码：0 = 一致；1 = 发现差异；2 = 输入 / 连接错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

VPS_ROOT = Path(__file__).resolve().parents[1]
if str(VPS_ROOT) not in sys.path:
    sys.path.insert(0, str(VPS_ROOT))

from app.services.consistency import (  # noqa: E402
    DEFAULT_TABLES,
    TABLE_SPECS,
    AuditInputError,
    fetch_edge_table,
    load_json_snapshot,
    load_local_tables,
    load_sqlite_table,
    render_markdown,
    render_summary_text,
    run_audit,
)


def _default_local_db() -> Path:
    """从 DATABASE_URL 解析 SQLite 路径；缺省为 vps/data/opensource_factory.db。"""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :].split("?", 1)[0]
        if raw and raw != ":memory:":
            path = Path(raw)
            return path if path.is_absolute() else (VPS_ROOT / path).resolve()
    return VPS_ROOT / "data" / "opensource_factory.db"


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_ignore_fields(values: list[str]) -> set[str]:
    ignored: set[str] = set()
    for value in values:
        for item in _parse_csv(value):
            if "." not in item:
                raise AuditInputError(f"--ignore-fields 需为 table.field 格式: {item}")
            ignored.add(item)
    return ignored


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D1 ↔ 本机 SQLite 镜像数据一致性巡检（只读）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/consistency_audit.py --edge-url https://api.example.com --token $INTERNAL_TOKEN\n"
            "  python scripts/consistency_audit.py --d1-db /tmp/d1-export.db --report /tmp/report.md\n"
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--edge-url", help="edge Worker 地址（在线拉取 D1 快照）")
    source.add_argument("--d1-db", help="D1 导出后的 SQLite 文件路径")
    source.add_argument("--snapshot", help="D1 JSON 快照文件路径")
    parser.add_argument(
        "--token",
        default=os.environ.get("INTERNAL_TOKEN", ""),
        help="内部令牌（默认读 INTERNAL_TOKEN 环境变量）",
    )
    parser.add_argument(
        "--local-db",
        default=None,
        help="本机镜像 SQLite 路径（默认读 DATABASE_URL，否则 vps/data/opensource_factory.db）",
    )
    parser.add_argument(
        "--tables",
        default=",".join(DEFAULT_TABLES),
        help=f"对账表，逗号分隔（默认：{','.join(DEFAULT_TABLES)}）",
    )
    parser.add_argument(
        "--ignore-fields",
        action="append",
        default=[],
        help="忽略字段，格式 table.field；可重复或用逗号分隔（如 my_repositories.synced_at）",
    )
    parser.add_argument("--sample-limit", type=int, default=10, help="每类差异保留的样例条数（默认 10）")
    parser.add_argument("--page-size", type=int, default=500, help="在线拉取分页大小（默认 500，上限 1000）")
    parser.add_argument("--timeout", type=float, default=30.0, help="在线拉取单次请求超时秒数（默认 30）")
    parser.add_argument("--report", help="输出 Markdown 报告路径")
    parser.add_argument("--json-out", help="输出 JSON 报告路径")
    parser.add_argument("--allow-diff", action="store_true", help="发现差异时仍返回退出码 0（仅告警场景）")
    parser.add_argument("--quiet", action="store_true", help="不打印摘要（仅写报告）")
    return parser


def _load_d1(
    args: argparse.Namespace, tables: list[str]
) -> tuple[dict[str, list[dict]], dict[str, list[str]], str]:
    rows: dict[str, list[dict]] = {}
    columns: dict[str, list[str]] = {}
    if args.edge_url:
        for table in tables:
            columns[table], rows[table] = fetch_edge_table(
                args.edge_url,
                table,
                args.token,
                page_size=args.page_size,
                timeout=args.timeout,
            )
        return rows, columns, f"edge {args.edge_url.rstrip('/')}"
    if args.d1_db:
        for table in tables:
            columns[table], rows[table] = load_sqlite_table(args.d1_db, table)
        return rows, columns, f"D1 导出库 {args.d1_db}"
    for table in tables:
        columns[table], rows[table] = load_json_snapshot(args.snapshot, table)
    return rows, columns, f"JSON 快照 {args.snapshot}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        tables = _parse_csv(args.tables)
        if not tables:
            raise AuditInputError("--tables 不能为空")
        unknown = [table for table in tables if table not in TABLE_SPECS]
        if unknown:
            raise AuditInputError(
                f"不支持的对账表: {', '.join(unknown)}（可选：{', '.join(DEFAULT_TABLES)}）"
            )
        if args.sample_limit < 0:
            raise AuditInputError("--sample-limit 不能为负数")
        ignored = _parse_ignore_fields(args.ignore_fields)

        local_db = Path(args.local_db) if args.local_db else _default_local_db()
        if not local_db.exists():
            raise AuditInputError(
                f"本机镜像库不存在: {local_db}（可用 --local-db 指定，或先启动 vps 初始化数据库）"
            )

        d1_rows, d1_columns, source = _load_d1(args, tables)
        local_rows, local_columns = load_local_tables(local_db, tables)
        report = run_audit(
            d1_rows,
            local_rows,
            tables=tables,
            d1_columns=d1_columns,
            local_columns=local_columns,
            ignore_fields=ignored,
            sample_limit=args.sample_limit,
            source=source,
            local_db=str(local_db),
        )

        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(render_markdown(report), encoding="utf-8")
        if args.json_out:
            json_path = Path(args.json_out)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        if not args.quiet:
            print(render_summary_text(report))
            if args.report:
                print(f"\nMarkdown 报告: {args.report}")
            if args.json_out:
                print(f"JSON 报告: {args.json_out}")

        if report["status"] != "consistent" and not args.allow_diff:
            return 1
        return 0
    except AuditInputError as exc:
        print(f"巡检失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
