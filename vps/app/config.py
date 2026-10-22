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
    VERSION: str = "1.0.0"
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

    # README 全文检索（M6-01，本地镜像先行）
    FTS_ENABLED: bool = True
    FTS_DEFAULT_TOP_K: int = 10
    FTS_MAX_TOP_K: int = 50
    FTS_SNIPPET_TOKENS: int = 32
    FTS_MAX_README_CHARS: int = 50000
    FTS_SYNC_BATCH_SIZE: int = 10
    FTS_SYNC_MAX_PER_RUN: int = 200
    FTS_AUTO_INDEX: bool = True  # 摘要 / 抓取后自动落 README 镜像
    FTS_SYNC_HOUR: int = 4  # 每日补索引时刻（Asia/Shanghai）
    FTS_SYNC_MINUTE: int = 47
    # 重复 / 相似项目检测（M6-03）
    DUPLICATE_MAX_REPOS: int = 500  # 单次参与扫描的仓库上限（收藏库 + 热榜）
    DUPLICATE_NAME_THRESHOLD: float = 0.86  # 名称相似度阈值
    DUPLICATE_DESCRIPTION_THRESHOLD: float = 0.75  # 简介 token 相似度阈值
    DUPLICATE_VECTOR_THRESHOLD: float = 0.88  # 向量余弦复核阈值
    DUPLICATE_MIN_CONFIDENCE: float = 0.70  # 低于该置信度的命中丢弃
    DUPLICATE_MAX_CLUSTERS: int = 50  # 单次返回的重复簇上限
    # 依赖分析（M6-07）：清单扫描与聚合
    DEPENDENCY_ANALYSIS_TOP: int = 20  # 聚合默认返回的热门依赖数
    DEPENDENCY_SCAN_MAX_REPOS: int = 100  # 单次扫描仓库上限
    DEPENDENCY_SCAN_TTL_HOURS: int = 24  # 非强制扫描的跳过窗口
    DEPENDENCY_SCAN_TIMEOUT_SECONDS: float = 15.0  # 单份清单拉取超时
    DEPENDENCY_MANIFEST_MAX_BYTES: int = 512000  # 单份清单大小上限

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

    # 每日评估（M4-01）
    # 匹配度硬门槛：原始余弦相似度低于该值的推荐直接 filtered
    EVAL_MATCH_THRESHOLD: float = 0.35
    # 综合质量分门槛：仓库内容质量 × 权重 + 推荐理由质量 × 权重
    EVAL_QUALITY_THRESHOLD: float = 0.55
    EVAL_REPO_WEIGHT: float = 0.7
    EVAL_REASON_WEIGHT: float = 0.3

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

    # 推送偏好（M4-06）
    # 未保存过偏好的用户使用以下默认值；时间按用户时区解释。
    PUSH_DEFAULT_TIME: str = "09:00"
    PUSH_DEFAULT_TIMEZONE: str = "Asia/Shanghai"
    PUSH_DEFAULT_MIN_SCORE: float = 0.35
    PUSH_DEFAULT_MIN_QUALITY_SCORE: float = 0.55
    # 定时任务每 10 分钟运行一次，推送窗口略大于调度间隔以避免漏推。
    PUSH_TIME_WINDOW_MINUTES: int = 10
    # 从 edge 拉取偏好的超时（秒）
    PUSH_PREFERENCES_TIMEOUT_SECONDS: float = 10.0

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

    # 内部接口鉴权（设置后 /api/tasks/*、/api/push/*、/api/vector-index/*、/api/search/* 校验 X-Internal-Token）
    INTERNAL_TOKEN: str = ""
    # 内部令牌轮换（M5-05）：过渡期同时接受上一枚令牌；验证完成后清空
    INTERNAL_TOKEN_PREVIOUS: str = ""
    # 接口限流（M5-05）：进程内滑动窗口；单节点部署
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1, le=3600)
    RATE_LIMIT_MAX_REQUESTS: int = Field(default=600, ge=1, le=100000)
    RATE_LIMIT_HEAVY_MAX_REQUESTS: int = Field(default=120, ge=1, le=100000)
    RATE_LIMIT_TRUST_PROXY: bool = True

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

    # 项目健康度（M6-05）：最后提交 / issue 活跃 / 归档标记
    REPO_HEALTH_ENABLED: bool = True
    # 最后提交距今天数分档：≤ active 为活跃，≤ attention 为需关注，≤ stale 为停滞
    REPO_HEALTH_ACTIVE_DAYS: int = Field(default=90, ge=1, le=3650)
    REPO_HEALTH_ATTENTION_DAYS: int = Field(default=180, ge=1, le=3650)
    REPO_HEALTH_STALE_DAYS: int = Field(default=365, ge=1, le=3650)
    # 单次刷新最多处理的仓库数（GitHub API 配额保护）
    REPO_HEALTH_MAX_PER_RUN: int = Field(default=200, ge=1, le=1000)
    # 每日元数据刷新时刻（Asia/Shanghai）
    REPO_HEALTH_HOUR: int = Field(default=6, ge=0, le=23)
    REPO_HEALTH_MINUTE: int = Field(default=12, ge=0, le=59)

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

    # 备份与恢复（M5-04 / REQ-202610-0942）
    # 每日 SQLite 快照 + 每周恢复演练；目录建议放在运行目录 backups/ 下
    BACKUP_ENABLED: bool = True
    BACKUP_DIR: str = "./data/backups"
    BACKUP_RETENTION_COUNT: int = Field(default=7, ge=1, le=365)
    # 备份总量上限（MB）；0 = 不限制。资源规划预算 3 GB。
    BACKUP_MAX_TOTAL_MB: int = Field(default=3072, ge=0)
    BACKUP_DRILL_ENABLED: bool = True
    BACKUP_HOUR: int = Field(default=3, ge=0, le=23)
    BACKUP_MINUTE: int = Field(default=50, ge=0, le=59)
    BACKUP_DRILL_HOUR: int = Field(default=4, ge=0, le=23)
    BACKUP_DRILL_MINUTE: int = Field(default=20, ge=0, le=59)
    # 监控与告警（M5-03）：健康检查 / 4G / 15G 资源红线 / 日志治理
    MONITOR_ENABLED: bool = True
    # 定时检查间隔（分钟，1~60）；Celery beat 按该间隔轮询
    MONITOR_INTERVAL_MINUTES: int = Field(default=5, ge=1, le=60)
    # 运行目录；留空时依次使用 OPENFACTORY_HOME、/opt/openfactory
    MONITOR_HOME: str = ""
    # 内存红线（MB）：项目预算 4G，3.5G 预警、4G 严重
    MONITOR_MEMORY_BUDGET_MB: int = Field(default=4096, ge=128)
    MONITOR_MEMORY_WARN_MB: int = Field(default=3584, ge=128)
    MONITOR_MEMORY_CRITICAL_MB: int = Field(default=4096, ge=128)
    # 磁盘红线（MB）：项目预算 15G，13G 预警、15G 严重
    MONITOR_DISK_BUDGET_MB: int = Field(default=15360, ge=128)
    MONITOR_DISK_WARN_MB: int = Field(default=13312, ge=128)
    MONITOR_DISK_CRITICAL_MB: int = Field(default=15360, ge=128)
    # 日志：占用预算与保留天数
    MONITOR_LOG_BUDGET_MB: int = Field(default=1024, ge=16)
    MONITOR_LOG_RETENTION_DAYS: int = Field(default=14, ge=1, le=3650)
    # 检查历史保留天数（0 = 不清理）
    MONITOR_HISTORY_RETENTION_DAYS: int = Field(default=30, ge=0, le=3650)
    # 告警去重冷却窗口与可选 webhook（留空则只落库 + 日志）
    MONITOR_ALERT_COOLDOWN_MINUTES: int = Field(default=60, ge=0)
    MONITOR_ALERT_WEBHOOK_URL: str = ""
    # 依赖探测超时
    MONITOR_EDGE_TIMEOUT_SECONDS: float = Field(default=3.0, ge=0.2, le=30)
    MONITOR_REDIS_TIMEOUT_SECONDS: float = Field(default=2.0, ge=0.1, le=10)
    # 进程 RSS 回退口径：逗号分隔，每项用 + 连接多个关键字（如 uvicorn+app.main:app）
    MONITOR_PROCESS_PATTERNS: str = (
        "uvicorn+app.main:app,celery+app.tasks.celery_app+worker,celery+beat,redis-server,ollama"
    )

    # CORS（安全默认：仅本机管理后台 dev server；生产通过环境变量改为实际域名）
    CORS_ORIGINS: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（带缓存）。"""
    return Settings()
