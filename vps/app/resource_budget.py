"""资源预算实测 CLI 入口。

用法：

    cd vps
    python -m app.resource_budget check
    python -m app.resource_budget check --json
    python -m app.resource_budget check --no-services

业务逻辑在 ``app.services.resource_budget``，本文件只做入口转发。
"""
from __future__ import annotations

import sys

from app.services.resource_budget import main

if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
