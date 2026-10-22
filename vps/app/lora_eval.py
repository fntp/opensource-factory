"""个人数据 LoRA 微调评估 CLI 入口。

用法：

    cd vps
    python -m app.lora_eval report
    python -m app.lora_eval report --repos 120 --summaries 80 --feedback 20 --json
    python -m app.lora_eval compare --baseline baseline.json --tuned tuned.json

业务逻辑在 ``app.services.lora_eval``，本文件只做入口转发。
"""
from __future__ import annotations

import sys

from app.services.lora_eval import main

if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
