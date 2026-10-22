"""降级路径自检 CLI（REQ-202610-0927 / M3-09）。

    cd vps
    python -m app.degradation check
    python -m app.degradation check --json

退出码：全部 PASS 为 0，存在 FAIL 为 1。检查不加载真实模型、不访问网络。
"""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from app.services.degradation import run_degradation_checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.degradation",
        description="OpenFactory 降级路径自检（模型缺失 / 超预算）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="执行降级路径自检")
    check.add_argument("--json", action="store_true", help="以 JSON 输出")

    args = parser.parse_args(argv)
    report = run_degradation_checks()

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("降级路径自检（模型缺失 / 超预算 → hash 向量 / 截断摘要）")
        for item in report.checks:
            print(f"[{'PASS' if item.ok else 'FAIL'}] {item.name}: {item.detail}")
        print(
            f"当前配置：embedding={report.embedding_model} "
            f"[{report.embedding_quantization}] 预期后端={report.embedding_expected_backend}；"
            f"llm={report.llm_model}；预算={report.budget_mb} MB"
        )
        print(f"结论：{report.summary}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
