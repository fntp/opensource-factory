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
    # 日志目录：留空时仅输出到 stdout（开发 / 测试）；生产指向运行目录 logs/
    LOG_DIR: str = ""

    # 数据库与队列
    DATABASE_URL: str = "sqlite:///./data/opensource_factory.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM：本地 Ollama（首选）
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # M3-01 选型：≤2B 量化模型（q4_K_M），替代超预算的 qwen2.5:7b
    OLLAMA_MODEL: str = "qwen2.5:1.5b-instruct-q4_K_M"
    # 批量摘要结束后自动卸载模型的时间（2m 内无请求即释放 2G 推理预算）
    OLLAMA_KEEP_ALIVE: str = "2m"

    # LLM：DeepSeek 云端（可选降级）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # README 摘要批量队列（2G 预算内串行处理）
    SUMMARY_BATCH_SIZE: int = 10
    SUMMARY_MAX_PER_RUN: int = 200
    SUMMARY_DELAY_MS: int = 500
    SUMMARY_MAX_CHARS: int = 800

    # 摘要质量抽检（M2-04）：按比例留存样本 + 低质量强制留存
    SUMMARY_SAMPLE_RATE: float = 0.1
    SUMMARY_SAMPLE_MAX_PER_RUN: int = 50
    SUMMARY_SAMPLE_ALWAYS_BELOW: float = 60.0
    SUMMARY_QUALITY_PASS_SCORE: float = 70.0
    SUMMARY_QUALITY_MIN_CHARS: int = 40

    # 向量模型（M3-01 选型：bge-m3 + int8 量化；fp16 约 2.3G 超预算）
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_QUANTIZATION: str = "int8"
    EMBEDDING_DEVICE: str = "cpu"
    # 强制使用确定性 hash 兜底向量（CI / 2G 预算紧张 / 未安装重型依赖时）
    EMBEDDING_FORCE_FALLBACK: bool = False

    # AI 推理侧内存预算（MB）；同一时刻仅加载 1 个模型
    MODEL_BUDGET_MB: int = 2048

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

    # 语义搜索（M3-04）
    SEARCH_DEFAULT_TOP_K: int = 10
    SEARCH_MAX_TOP_K: int = 50
    SEARCH_MIN_SCORE: float = 0.0
    # 本地全量余弦扫描的向量上限（超过后依赖 Vectorize）
    SEARCH_MAX_VECTORS: int = 50000
    # 查询理解（M3-10）：同义词 / 技术栈词表扩展
    SEARCH_QUERY_EXPANSION_ENABLED: bool = True
    SEARCH_QUERY_EXPANSION_MAX_TERMS: int = 12

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

    # 推荐质量评估（M3-08）
    # 默认评估折叠数（每个折叠做一次留出集切分）
    RECOMMEND_EVAL_SAMPLE_SIZE: int = 5
    # 每个折叠留出的正样本比例
    RECOMMEND_EVAL_HOLDOUT_RATIO: float = 0.2
    # 评估用 top_k
    RECOMMEND_EVAL_TOP_K: int = 10
    # 每个正样本配的负样本数
    RECOMMEND_EVAL_NEGATIVES_PER_POSITIVE: int = 5
    # 抽样随机种子（同种子结果可复现）
    RECOMMEND_EVAL_SEED: int = 42
    # 阈值扫描网格（逗号分隔，0~1）
    RECOMMEND_EVAL_MIN_SCORE_GRID: str = "0.20,0.25,0.30,0.35,0.40,0.45,0.50"
    # 相似度权重扫描网格（热度权重 = 1 - 该值）
    RECOMMEND_EVAL_WEIGHT_GRID: str = "0.6,0.7,0.8,0.9,1.0"
    # 单次评估的折叠数上限
    RECOMMEND_EVAL_MAX_SAMPLES: int = 20

    # 推荐反馈回流（M3-07）：生成前拉取 edge 反馈、生成后回写 D1
    RECOMMEND_FEEDBACK_SYNC: bool = True

    # 内部接口鉴权（设置后 /api/tasks/*、/api/vector-index/*、/api/search/* 校验 X-Internal-Token）
    INTERNAL_TOKEN: str = ""

    # 本机一体化模式（REQ-202610-0940 / M5-02）
    # 开启后：/local/api/* 提供 edge 兼容只读接口，/ 托管 admin 构建产物
    LOCAL_MODE: bool = False
    LOCAL_USER_ID: str = "local"
    LOCAL_USER_LOGIN: str = "local"
    LOCAL_USER_NAME: str = "本机用户"
    # admin 构建目录；留空时使用仓库内 admin/dist
    LOCAL_ADMIN_DIR: str = ""

    # Celery
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # GitHub
    GITHUB_TOKEN: str = ""

    # 热榜抓取：每日定时 + 多语言页（逗号分隔的 GitHub Trending language slug）
    TRENDING_LANGUAGES: str = (
        "python,javascript,typescript,go,rust,java,cpp,c,php,ruby,swift,kotlin"
    )
    TRENDING_CRAWL_HOUR: int = Field(default=3, ge=0, le=23)
    TRENDING_CRAWL_MINUTE: int = Field(default=27, ge=0, le=59)

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

    # 热榜数据保留（M2-08）：保留窗口 / 归档 / 清理
    TRENDING_RETENTION_DAYS: int = Field(default=90, ge=0, le=3650)
    TRENDING_ARCHIVE_ENABLED: bool = True
    TRENDING_ARCHIVE_DIR: str = "./data/archives"
    TRENDING_ARCHIVE_KEEP_DAYS: int = Field(default=365, ge=0, le=3650)
    TRENDING_RETENTION_HOUR: int = Field(default=4, ge=0, le=23)
    TRENDING_RETENTION_MINUTE: int = Field(default=17, ge=0, le=59)

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
