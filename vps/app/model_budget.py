"""模型预算校验 CLI 入口。

用法：

    cd vps
    python -m app.model_budget check
    python -m app.model_budget check --probe --json

业务逻辑在 ``app.services.model_budget``，本文件只做入口转发。
"""
from __future__ import annotations

import sys

from app.services.model_budget import main

if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
