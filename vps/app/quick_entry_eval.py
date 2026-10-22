"""快捷入口评估 CLI 入口。

用法：

    cd vps
    python -m app.quick_entry_eval report
    python -m app.quick_entry_eval report --json
    python -m app.quick_entry_eval report --ready all
    python -m app.quick_entry_eval contract --out docs/assets/quick-entry-api-contract.json

业务逻辑在 ``app.services.quick_entry_eval``，本文件只做入口转发。
"""
from __future__ import annotations

import sys

from app.services.quick_entry_eval import main

if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
