"""应用配置（pydantic-settings）。

所有配置项均可通过环境变量或 `.env`（位于 `vps/` 根目录）覆盖；
真实密钥只存在于本地 `.env`，模板见 `.env.example`。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# vps/ 根目录（本文件位于 vps/app/config.py）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """节点配置。字段名即环境变量名（大小写不敏感）。"""

    APP_NAME: str = "OpenFactory VPS Node"
    VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    # 日志目录：留空时仅输出到 stdout（开发 / 测试）；生产指向运行目录 logs/
    LOG_DIR: str = ""

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
    # 强制使用确定性 hash 兜底向量（CI / 2G 预算紧张 / 未安装重型依赖时）
    EMBEDDING_FORCE_FALLBACK: bool = False

    # 向量化管线
    VECTORIZE_BATCH_SIZE: int = 32  # 每批编码 / 提交条数
    VECTORIZE_MAX_PER_RUN: int = 1000  # 单次默认上限
    VECTORIZE_AUTO: bool = True  # 同步 / 抓取完成后自动入队增量任务

    # Vectorize 索引同步（M3-03）
    # edge 地址与内部令牌：两者都配置后才能同步（VPS 不持有 Cloudflare 凭据）
    EDGE_BASE_URL: str = ""
    VECTORIZE_SYNC_ENABLED: bool = True
    VECTORIZE_INDEX_NAME: str = "opensource-factory-vectors"
    # 索引维度需与 Cloudflare Vectorize 索引一致（BGE-M3 = 1024；0 表示不校验）
    VECTORIZE_INDEX_DIM: int = 1024
    VECTORIZE_SYNC_BATCH_SIZE: int = 100
    VECTORIZE_SYNC_MAX_PER_RUN: int = 1000
    VECTORIZE_SYNC_MAX_RETRIES: int = 3
    VECTORIZE_SYNC_RETRY_BASE_MS: int = 500
    VECTORIZE_SYNC_TIMEOUT_SECONDS: float = 30.0
    VECTORIZE_SYNC_DELETE_ORPHANS: bool = False
    VECTORIZE_SYNC_MAX_ORPHANS: int = 100

    # 推荐生成（M3-05）
    # 最终得分最低阈值（0~1）：相似度 × 权重 + 热榜热度 × 权重
    RECOMMEND_MIN_SCORE: float = 0.30
    # 每日任务每个用户最多生成的推荐数
    RECOMMEND_DAILY_TOP_K: int = 20
    # 单次参与打分的热榜候选上限
    RECOMMEND_CANDIDATE_LIMIT: int = 500
    # 相似度 / 热榜热度权重（均为 0 时退化为纯相似度）
    RECOMMEND_SIMILARITY_WEIGHT: float = 0.8
    RECOMMEND_TRENDING_WEIGHT: float = 0.2

    # 每日评估（M4-01）
    # 匹配度硬门槛：原始余弦相似度低于该值的推荐直接 filtered
    EVAL_MATCH_THRESHOLD: float = 0.35
    # 综合质量分门槛：仓库内容质量 × 权重 + 推荐理由质量 × 权重
    EVAL_QUALITY_THRESHOLD: float = 0.55
    EVAL_REPO_WEIGHT: float = 0.7
    EVAL_REASON_WEIGHT: float = 0.3

    # 推送去重与静默（M4-07）
    # 总开关；关闭时 daily_push 保持旧行为（只把 qualified 标记为 pushed）。
    PUSH_POLICY_ENABLED: bool = True
    # 静默时段（用户本地时区，HH:MM）；留空或开始 / 结束相同表示不静默。
    PUSH_QUIET_HOURS_START: str = "22:00"
    PUSH_QUIET_HOURS_END: str = "08:00"
    PUSH_TIMEZONE: str = "Asia/Shanghai"
    # 每用户每日最多推送条数（按去重仓库计数；0 表示不限）。
    PUSH_DAILY_LIMIT: int = 3
    # 同一用户同一仓库的去重窗口（天；0 表示只做当日幂等）。
    PUSH_DEDUPE_DAYS: int = 7
    # true 时跨通道去重；false 时仅同通道去重。
    PUSH_DEDUPE_CROSS_CHANNEL: bool = True
    # 静默结束后的重试任务间隔（分钟）。
    PUSH_RETRY_INTERVAL_MINUTES: int = 30

    # 内部接口鉴权（设置后 /api/tasks/* 校验 X-Internal-Token）
    INTERNAL_TOKEN: str = ""

    # Celery
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # GitHub
    GITHUB_TOKEN: str = ""

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
