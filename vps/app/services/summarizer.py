"""README 摘要生成。

优先级：本地 Ollama → DeepSeek（OpenAI 兼容，可选）→ 截断原文降级。
任何 LLM 不可用场景都**不抛异常**，保证任务与接口始终可用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services.model_budget import DEFAULT_BUDGET_MB, resolve_llm_spec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryResult:
    """摘要生成结果（含来源，便于批量任务统计与降级观测）。"""

    text: str
    source: str  # ollama | deepseek | truncated | empty
    model: str = ""


# 传给 LLM 的原文上限（字符），避免超长 README 撑爆上下文
_MAX_INPUT_CHARS = 6000
# 单次 LLM 调用超时
_LLM_TIMEOUT = httpx.Timeout(120.0, connect=5.0)

_PROMPT_TEMPLATE = """你是一个开源项目分析助手。请阅读下面的项目 README 内容，输出一段简洁的中文摘要（不超过 {max_chars} 字），必须覆盖三个部分：
1. 核心功能：这个项目是做什么的；
2. 技术栈：主要语言、框架与关键技术；
3. 适用场景：适合哪些用户或业务场景。
直接输出摘要正文，不要重复标题，不要输出 Markdown 代码块。

README 内容：
{text}"""


def _build_prompt(text: str, max_chars: int) -> str:
    """构造中文摘要提示词（原文截断后注入）。"""
    return _PROMPT_TEMPLATE.format(max_chars=max_chars, text=text[:_MAX_INPUT_CHARS])


def is_llm_over_budget(settings: object | None = None) -> bool:
    """判断 Ollama 摘要模型是否超出本地推理预算（未收录模型不阻断）。"""
    current = settings or get_settings()
    spec = resolve_llm_spec(str(getattr(current, "OLLAMA_MODEL", "") or ""))
    if spec is None:
        return False
    budget = int(getattr(current, "MODEL_BUDGET_MB", 0) or DEFAULT_BUDGET_MB)
    return spec.resident_mb > budget


def truncated_summary(text: str, *, max_chars: int = 800) -> str:
    """最终降级：截断清洗后的原文，并标注 LLM 不可用。"""
    text = (text or "").strip()
    if not text:
        return ""
    return f"（LLM 暂不可用，以下为项目原文截断）\n{text[:max_chars]}"


def _summarize_with_ollama(text: str, max_chars: int) -> str:
    """尝试本地 Ollama；不可用时返回空字符串。"""
    settings = get_settings()
    base_url = (settings.OLLAMA_BASE_URL or "").strip().rstrip("/")
    if not base_url:
        return ""
    if is_llm_over_budget(settings):
        logger.warning(
            "Ollama 模型 %s 超出 %d MB 推理预算，跳过本地摘要（降级）",
            settings.OLLAMA_MODEL,
            int(settings.MODEL_BUDGET_MB or DEFAULT_BUDGET_MB),
        )
        return ""
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": _build_prompt(text, max_chars),
        "stream": False,
        "options": {"temperature": 0.3},
        "keep_alive": settings.OLLAMA_KEEP_ALIVE or "2m",
    }
    try:
        with httpx.Client(timeout=_LLM_TIMEOUT) as client:
            resp = client.post(f"{base_url}/api/generate", json=payload)
        if resp.status_code != 200:
            logger.warning("Ollama 摘要返回状态 %s", resp.status_code)
            return ""
        output = str((resp.json() or {}).get("response") or "").strip()
        return output[:max_chars] if output else ""
    except Exception as exc:  # noqa: BLE001 - LLM 不可用属于预期降级路径
        logger.info("Ollama 摘要失败（降级）: %s", exc)
        return ""


def _summarize_with_deepseek(text: str, max_chars: int) -> str:
    """尝试 DeepSeek（OpenAI 兼容）；未配置或失败时返回空字符串。"""
    settings = get_settings()
    api_key = (settings.DEEPSEEK_API_KEY or "").strip()
    if not api_key:
        return ""
    url = f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": _build_prompt(text, max_chars)}],
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    try:
        with httpx.Client(timeout=_LLM_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code != 200:
            logger.warning("DeepSeek 摘要返回状态 %s", resp.status_code)
            return ""
        choices = (resp.json() or {}).get("choices") or []
        output = str((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
        return output[:max_chars] if output else ""
    except Exception as exc:  # noqa: BLE001 - 同上，云端仅作可选降级
        logger.info("DeepSeek 摘要失败（降级）: %s", exc)
        return ""


def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔包在外层的 Markdown 代码围栏。"""
    text = (text or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def summarize_with_source(text: str, *, max_chars: int = 800) -> SummaryResult:
    """生成摘要并标记来源：Ollama → DeepSeek → 截断原文。

    任何外部依赖失败都降级返回，不抛异常；`source` 供批量任务统计与排查。
    """
    text = (text or "").strip()
    if not text:
        return SummaryResult(text="", source="empty")

    settings = get_settings()
    result = _strip_code_fence(_summarize_with_ollama(text, max_chars))
    if result:
        return SummaryResult(text=result[:max_chars], source="ollama", model=settings.OLLAMA_MODEL)

    result = _strip_code_fence(_summarize_with_deepseek(text, max_chars))
    if result:
        return SummaryResult(text=result[:max_chars], source="deepseek", model=settings.DEEPSEEK_MODEL)

    # 最终降级：截断的清洗后文本 + 说明
    # 最终降级：截断的清洗后文本 + 说明
    return SummaryResult(text=truncated_summary(text, max_chars=max_chars), source="truncated")


def summarize(text: str, *, max_chars: int = 800) -> str:
    """生成项目摘要；LLM 全部不可用时返回截断原文并附说明。"""
    return summarize_with_source(text, max_chars=max_chars).text
