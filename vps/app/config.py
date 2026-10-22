"""应用配置（pydantic-settings）。

所有配置项均可通过环境变量或 `.env`（位于 `vps/` 根目录）覆盖；
真实密钥只存在于本地 `.env`，模板见 `.env.example`。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# vps/ 根目录（本文件位于 vps/app/config.py）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """节点配置。字段名即环境变量名（大小写不敏感）。"""

    APP_NAME: str = "OpenFactory VPS Node"
    VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # 数据库与队列
    DATABASE_URL: str = "sqlite:///./data/opensource_factory.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM：本地 Ollama（首选）
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"

    # LLM：DeepSeek 云端（可选降级）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # 向量模型
    EMBEDDING_MODEL: str = "BAAI/bge-m3"

    # 内部接口鉴权（设置后 /api/tasks/* 校验 X-Internal-Token）
    INTERNAL_TOKEN: str = ""

    # Celery
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # GitHub
    GITHUB_TOKEN: str = ""

    # 热榜抓取语言页（逗号分隔的 GitHub Trending language slug；留空只抓全局页）
    TRENDING_LANGUAGES: str = (
        "python,javascript,typescript,go,rust,java,cpp,c,php,ruby,swift,kotlin"
    )

    # 热榜抓取容错（M2-02）：仅对超时 / 429 / 5xx 重试
    TRENDING_RETRY_MAX: int = Field(default=3, ge=1, le=10)
    TRENDING_RETRY_BASE_DELAY: float = Field(default=1.0, ge=0, le=60)
    TRENDING_RETRY_MAX_DELAY: float = Field(default=8.0, ge=0, le=120)
    # 页面结构变更判定：条数低于上次成功条数的比例（基线至少 N 条才判定）
    TRENDING_COUNT_DROP_RATIO: float = Field(default=0.3, ge=0, le=1)
    TRENDING_COUNT_DROP_MIN_BASELINE: int = Field(default=5, ge=1)
    # 告警去重窗口与可选 webhook（留空则只落库 + 日志）
    TRENDING_ALERT_COOLDOWN_MINUTES: int = Field(default=360, ge=0)
    TRENDING_ALERT_WEBHOOK_URL: str = ""

    # CORS（开发默认允许全部来源）
    CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（带缓存）。"""
    return Settings()
