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

    # Email 通道（M4-05）
    # 总开关；关闭时任务与测试接口返回 disabled，不发起任何 SMTP 连接
    EMAIL_ENABLED: bool = False
    EMAIL_SMTP_HOST: str = ""
    # 587 = STARTTLS（默认）；465 通常配合 EMAIL_SSL=true 且 EMAIL_STARTTLS=false
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USERNAME: str = ""
    EMAIL_SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_FROM_NAME: str = "OpenFactory"
    # 默认收件人：逗号 / 分号分隔，最多 20 个
    EMAIL_TO: str = ""
    EMAIL_STARTTLS: bool = True
    EMAIL_SSL: bool = False
    EMAIL_TIMEOUT_SECONDS: float = 15.0
    EMAIL_MAX_RETRIES: int = 2
    EMAIL_RETRY_BASE_SECONDS: float = 0.5
    # 单封摘要最多包含的推荐数 / 摘要回溯窗口
    EMAIL_DAILY_LIMIT: int = 10
    EMAIL_DIGEST_WINDOW_HOURS: int = 24

    # Bark 推送通道（M4-03）
    # 总开关；关闭时定时任务直接 skipped，不发起任何外部请求
    BARK_ENABLED: bool = False
    # Bark 服务地址（默认官方服务；自建服务同样走 POST {server}/push）
    BARK_SERVER_URL: str = "https://api.day.app"
    # Bark device key（密钥，仅存 .env，接口不回显）
    BARK_DEVICE_KEY: str = ""
    BARK_GROUP: str = "OpenFactory"
    BARK_SOUND: str = ""
    BARK_ICON: str = ""
    # active | timeSensitive | passive | critical
    BARK_LEVEL: str = "active"
    BARK_TIMEOUT_SECONDS: float = 10.0
    # 单次任务最多投递条数，避免一次刷屏
    BARK_MAX_PER_RUN: int = 5
    # 试运行：只生成消息不发送、不写投递标记
    BARK_DRY_RUN: bool = False

    # Telegram 推送通道（M4-04）
    # 总开关：关闭时任务直接跳过，不发任何请求
    TELEGRAM_ENABLED: bool = False
    # BotFather 颁发的 Bot Token（机密，只存本机 .env）
    TELEGRAM_BOT_TOKEN: str = ""
    # 接收消息的私聊 / 群组 id（群组为负数）
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    TELEGRAM_TIMEOUT_SECONDS: float = 10.0
    # 网络异常 / 429 / 5xx 的最大重试次数（不含首次请求）
    TELEGRAM_MAX_RETRIES: int = 3
    # 指数退避基数（秒）；429 优先使用 Telegram 返回的 retry_after
    TELEGRAM_RETRY_BASE_SECONDS: float = 0.5
    # 单条摘要最多包含的推荐数
    TELEGRAM_DAILY_LIMIT: int = 10
    # 摘要只取最近 N 小时内进入 pushed 的推荐
    TELEGRAM_DIGEST_WINDOW_HOURS: int = 24

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
