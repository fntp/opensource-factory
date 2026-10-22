"""自动分类建议（M7-02）：按业务线把仓库归类为可执行的分类建议。

设计要点：

- **纯函数**：不访问数据库 / 网络，便于单测与在 edge 侧降级复用同一套口径；
- **可解释**：每条建议保留命中字段、关键词与摘要片段，用户可人工复核；
- **业务线优先**：语言只作为弱信号，主信号是名称 / 标签 / 简介 / 摘要中的业务关键词；
- **克制输出**：同一仓库最多 ``per_repo`` 条（1~5），低于 ``min_score`` 的建议直接丢弃。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class BusinessLine:
    """一条业务线及其分类展示名。"""

    key: str
    name: str
    description: str
    keywords: tuple[str, ...]
    languages: tuple[str, ...] = ()


# 首批业务线词表。关键词同时覆盖英文别名与中文常用说法；
# 英文 / 数字关键词按词边界匹配，避免 ``ai`` 命中 ``email``、``react`` 命中 ``reactive``。
BUSINESS_LINES: tuple[BusinessLine, ...] = (
    BusinessLine(
        key="ai",
        name="AI / 大模型",
        description="大模型、机器学习、推理框架与 AI 应用",
        keywords=(
            "ai",
            "artificial intelligence",
            "machine learning",
            "deep learning",
            "llm",
            "gpt",
            "transformer",
            "diffusion",
            "stable diffusion",
            "rag",
            "embedding",
            "embedding vector",
            "agent",
            "prompt",
            "nlp",
            "natural language",
            "computer vision",
            "ocr",
            "speech recognition",
            "大模型",
            "人工智能",
            "机器学习",
            "深度学习",
            "推理",
            "微调",
            "训练",
            "智能体",
            "提示词",
            "自然语言",
            "计算机视觉",
            "语音识别",
            "向量",
        ),
    ),
    BusinessLine(
        key="fintech",
        name="金融 / 支付",
        description="支付、账务、风控与金融科技",
        keywords=(
            "payment",
            "payments",
            "fintech",
            "banking",
            "finance",
            "financial",
            "wallet",
            "stripe",
            "paypal",
            "ledger",
            "accounting",
            "billing",
            "invoice",
            "checkout",
            "支付",
            "金融",
            "银行",
            "账务",
            "钱包",
            "对账",
            "结算",
            "交易",
            "信贷",
            "保险",
            "理财",
            "证券",
            "计费",
            "发票",
        ),
    ),
    BusinessLine(
        key="ecommerce",
        name="电商 / 零售",
        description="商城、订单、库存与零售业务",
        keywords=(
            "ecommerce",
            "e-commerce",
            "shop",
            "store",
            "cart",
            "checkout",
            "order",
            "orders",
            "inventory",
            "retail",
            "marketplace",
            "product",
            "电商",
            "商城",
            "购物车",
            "订单",
            "库存",
            "零售",
            "商品",
            "店铺",
            "促销",
            "会员",
            "供应链",
        ),
    ),
    BusinessLine(
        key="saas",
        name="企业服务 / SaaS",
        description="多租户 SaaS、CRM / ERP、审批与工单",
        keywords=(
            "saas",
            "crm",
            "erp",
            "hr",
            "oa",
            "bpm",
            "workflow",
            "tenant",
            "multi-tenant",
            "multitenant",
            "admin dashboard",
            "enterprise",
            "customer",
            "ticket",
            "企业",
            "多租户",
            "客户关系",
            "办公",
            "审批",
            "工单",
            "人力",
            "财务系统",
            "后台管理",
            "管理后台",
            "中台",
            "协同",
        ),
    ),
    BusinessLine(
        key="devtools",
        name="开发工具",
        description="CLI、SDK、编辑器、构建与测试工具",
        keywords=(
            "cli",
            "sdk",
            "ide",
            "editor",
            "compiler",
            "linter",
            "formatter",
            "debugger",
            "testing",
            "test framework",
            "package manager",
            "scaffold",
            "boilerplate",
            "developer tool",
            "devtool",
            "开发工具",
            "编辑器",
            "编译器",
            "调试",
            "测试框架",
            "脚手架",
            "命令行",
            "代码生成",
            "插件",
            "构建工具",
        ),
    ),
    BusinessLine(
        key="data-infra",
        name="数据工程",
        description="数据库、缓存、消息队列、ETL 与数据分析",
        keywords=(
            "database",
            "sql",
            "nosql",
            "cache",
            "redis",
            "kafka",
            "queue",
            "etl",
            "data pipeline",
            "warehouse",
            "olap",
            "analytics",
            "storage engine",
            "数据库",
            "缓存",
            "消息队列",
            "数据管道",
            "数据仓库",
            "数据分析",
            "存储引擎",
            "分布式",
            "数据同步",
            "数据治理",
        ),
    ),
    BusinessLine(
        key="cloud-devops",
        name="DevOps / 云原生",
        description="容器、Kubernetes、CI/CD、部署与可观测性",
        keywords=(
            "kubernetes",
            "k8s",
            "docker",
            "container",
            "devops",
            "ci/cd",
            "cicd",
            "terraform",
            "ansible",
            "serverless",
            "observability",
            "monitoring",
            "logging",
            "microservice",
            "云原生",
            "容器",
            "编排",
            "部署",
            "运维",
            "监控",
            "日志",
            "可观测",
            "网关",
            "微服务",
            "持续集成",
        ),
    ),
    BusinessLine(
        key="security",
        name="安全 / 合规",
        description="认证授权、加密、漏洞与隐私合规",
        keywords=(
            "security",
            "auth",
            "authentication",
            "authorization",
            "oauth",
            "jwt",
            "encryption",
            "vulnerability",
            "penetration",
            "zero trust",
            "privacy",
            "compliance",
            "安全",
            "认证",
            "授权",
            "加密",
            "漏洞",
            "渗透",
            "合规",
            "隐私",
            "审计",
            "权限",
        ),
    ),
    BusinessLine(
        key="web-frontend",
        name="前端开发",
        description="Web 框架、组件库、样式与设计系统",
        keywords=(
            "react",
            "vue",
            "angular",
            "svelte",
            "next.js",
            "nuxt",
            "tailwind",
            "css",
            "html",
            "frontend",
            "front-end",
            "ui component",
            "design system",
            "前端",
            "组件库",
            "样式",
            "页面",
            "设计系统",
            "可视化",
        ),
        languages=("javascript", "typescript", "html", "css"),
    ),
    BusinessLine(
        key="mobile",
        name="移动端",
        description="iOS / Android / 跨平台移动应用",
        keywords=(
            "ios",
            "android",
            "flutter",
            "react native",
            "swift",
            "kotlin",
            "mobile",
            "移动端",
            "安卓",
            "苹果",
            "小程序",
            "跨平台",
            "手机",
        ),
        languages=("swift", "kotlin", "dart", "objective-c"),
    ),
    BusinessLine(
        key="content-media",
        name="内容 / 媒体",
        description="CMS、博客、文档、音视频与知识库",
        keywords=(
            "cms",
            "blog",
            "markdown",
            "wiki",
            "documentation",
            "podcast",
            "video",
            "audio",
            "image",
            "photo",
            "media",
            "内容",
            "博客",
            "文档",
            "知识库",
            "媒体",
            "视频",
            "音频",
            "图片",
            "相册",
            "写作",
            "笔记",
        ),
    ),
    BusinessLine(
        key="education",
        name="教育 / 学习",
        description="课程、教程、题库与学习资源",
        keywords=(
            "education",
            "learning",
            "course",
            "tutorial",
            "teaching",
            "quiz",
            "exam",
            "教育",
            "学习",
            "教程",
            "课程",
            "考试",
            "题库",
            "知识",
            "培训",
            "面试",
        ),
    ),
    BusinessLine(
        key="productivity",
        name="效率 / 办公",
        description="待办、日历、邮件、自动化与办公效率",
        keywords=(
            "productivity",
            "todo",
            "task",
            "calendar",
            "email",
            "office",
            "automation",
            "shortcut",
            "效率",
            "待办",
            "日历",
            "邮件",
            "办公",
            "自动化",
            "快捷",
            "工作流",
        ),
    ),
    BusinessLine(
        key="gaming",
        name="游戏 / 娱乐",
        description="游戏引擎、工具与娱乐应用",
        keywords=(
            "game",
            "gaming",
            "unity",
            "unreal",
            "godot",
            "emulator",
            "游戏",
            "娱乐",
            "引擎",
            "玩家",
        ),
    ),
    BusinessLine(
        key="iot",
        name="物联网 / 嵌入式",
        description="嵌入式、固件、硬件与 IoT 平台",
        keywords=(
            "iot",
            "embedded",
            "firmware",
            "arduino",
            "raspberry pi",
            "esp32",
            "mqtt",
            "hardware",
            "物联网",
            "嵌入式",
            "硬件",
            "固件",
            "单片机",
            "传感器",
        ),
    ),
    BusinessLine(
        key="blockchain",
        name="区块链 / Web3",
        description="区块链、智能合约与 Web3 应用",
        keywords=(
            "blockchain",
            "web3",
            "ethereum",
            "solidity",
            "smart contract",
            "nft",
            "defi",
            "crypto",
            "区块链",
            "智能合约",
            "以太坊",
            "链上",
            "去中心化",
        ),
        languages=("solidity",),
    ),
    BusinessLine(
        key="healthcare",
        name="医疗 / 健康",
        description="医疗、健康管理与临床系统",
        keywords=(
            "healthcare",
            "medical",
            "health",
            "hospital",
            "patient",
            "diagnosis",
            "医疗",
            "健康",
            "医院",
            "患者",
            "诊断",
            "病历",
            "临床",
        ),
    ),
    BusinessLine(
        key="backend-api",
        name="后端与 API",
        description="Web 框架、API 网关与服务端基础设施",
        keywords=(
            "api",
            "gateway",
            "microservice",
            "rest",
            "graphql",
            "grpc",
            "web framework",
            "backend",
            "server",
            "后端",
            "网关",
            "微服务",
            "服务端",
            "接口",
            "框架",
        ),
    ),
)

# 字段权重：名称 > 标签 ≈ 简介 > 摘要；语言只做弱信号。
FIELD_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("name", 3.0),
    ("tags", 2.0),
    ("description", 2.0),
    ("summary", 1.5),
)
LANGUAGE_WEIGHT = 0.5
BASE_SCORE = 0.40
SCORE_PER_WEIGHT = 0.05
MAX_SCORE = 0.99
EVIDENCE_LIMIT = 120


@dataclass(frozen=True)
class RepoSnapshot:
    """参与分类的仓库快照（由 edge 内联传入，VPS 不依赖用户表）。"""

    repo_id: str
    name: str = ""
    description: str = ""
    language: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategorySuggestion:
    """单条分类建议。"""

    category_name: str
    business_line: str
    score: float
    reason: str
    evidence: str

    def to_dict(self) -> dict[str, object]:
        return {
            "categoryName": self.category_name,
            "businessLine": self.business_line,
            "score": self.score,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def normalize_text(value: str | None) -> str:
    """归一化文本：小写、压缩空白。"""
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _is_ascii_keyword(keyword: str) -> bool:
    """是否按英文词边界匹配（含字母 / 数字 / 空格的词）。"""
    return bool(re.search(r"[a-z0-9]", keyword))


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])")


def contains_keyword(text: str, keyword: str) -> bool:
    """判断文本是否命中关键词：英文按词边界，中文按包含匹配。"""
    normalized = normalize_text(text)
    if not normalized or not keyword:
        return False
    lowered = keyword.lower()
    if _is_ascii_keyword(lowered):
        return _keyword_pattern(lowered).search(normalized) is not None
    return lowered in normalized


def _snippet(text: str, keyword: str, limit: int = EVIDENCE_LIMIT) -> str:
    """截取关键词附近的证据片段，最多 ``limit`` 个字符。"""
    source = (text or "").strip()
    if not source:
        return ""
    lowered = source.lower()
    index = lowered.find(keyword.lower())
    if index < 0:
        return source[:limit] + ("…" if len(source) > limit else "")
    half = max(20, (limit - len(keyword)) // 2)
    start = max(0, index - half)
    end = min(len(source), index + len(keyword) + half)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(source) else ""
    return f"{prefix}{source[start:end].strip()}{suffix}"


def _field_values(repo: RepoSnapshot) -> tuple[tuple[str, str], ...]:
    return (
        ("name", repo.name),
        ("tags", "、".join(repo.tags)),
        ("description", repo.description),
        ("summary", repo.summary),
    )


def _score_line(repo: RepoSnapshot, line: BusinessLine) -> CategorySuggestion | None:
    """对单条业务线打分；无命中返回 None。"""
    raw = 0.0
    hits: list[tuple[str, str, float]] = []
    best_evidence = ""
    best_evidence_weight = 0.0

    for field_name, value in _field_values(repo):
        weight = dict(FIELD_WEIGHTS)[field_name]
        for keyword in line.keywords:
            if not contains_keyword(value, keyword):
                continue
            raw += weight
            hits.append((field_name, keyword, weight))
            if weight > best_evidence_weight:
                snippet = _snippet(value, keyword)
                if snippet:
                    best_evidence = snippet
                    best_evidence_weight = weight

    language = normalize_text(repo.language)
    if language and any(language == item.lower() for item in line.languages):
        raw += LANGUAGE_WEIGHT
        hits.append(("language", repo.language, LANGUAGE_WEIGHT))

    if raw <= 0:
        return None

    score = round(min(MAX_SCORE, BASE_SCORE + raw * SCORE_PER_WEIGHT), 3)
    reason = _reason_text(hits)
    return CategorySuggestion(
        category_name=line.name,
        business_line=line.key,
        score=score,
        reason=reason,
        evidence=best_evidence or _fallback_evidence(repo),
    )


def _reason_text(hits: Sequence[tuple[str, str, float]]) -> str:
    """把命中项压缩成一句可读理由（最多 3 项）。"""
    labels = {
        "name": "名称",
        "tags": "标签",
        "description": "简介",
        "summary": "摘要",
        "language": "语言",
    }
    parts: list[str] = []
    seen: set[str] = set()
    for field_name, keyword, _ in sorted(hits, key=lambda item: -item[2]):
        key = f"{field_name}:{keyword.lower()}"
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{labels.get(field_name, field_name)}命中「{keyword}」")
        if len(parts) >= 3:
            break
    return "；".join(parts) if parts else "规则命中"


def _fallback_evidence(repo: RepoSnapshot) -> str:
    for value in (repo.summary, repo.description, repo.name):
        text = (value or "").strip()
        if text:
            return text[:EVIDENCE_LIMIT] + ("…" if len(text) > EVIDENCE_LIMIT else "")
    return ""


def suggest_categories(
    repo: RepoSnapshot,
    *,
    per_repo: int = 3,
    min_score: float = 0.55,
) -> list[CategorySuggestion]:
    """为单个仓库生成分类建议（按分数降序）。"""
    limit = min(5, max(1, int(per_repo)))
    threshold = min(1.0, max(0.0, float(min_score)))
    scored: list[CategorySuggestion] = []
    for line in BUSINESS_LINES:
        suggestion = _score_line(repo, line)
        if suggestion is not None and suggestion.score >= threshold:
            scored.append(suggestion)
    scored.sort(key=lambda item: (-item.score, item.category_name))
    return scored[:limit]


def suggest_for_repos(
    repos: Iterable[RepoSnapshot],
    *,
    per_repo: int = 3,
    min_score: float = 0.55,
) -> tuple[list[dict[str, object]], int, int, int]:
    """批量生成建议。

    返回 ``(items, scanned, suggested, skipped)``：

    - ``items``：仅包含有建议的仓库，形如 ``{repoId, suggestions: [...]}``；
    - ``scanned``：有可分析文本的仓库数；
    - ``suggested``：建议总条数；
    - ``skipped``：无文本或未命中任何业务线的仓库数。
    """
    items: list[dict[str, object]] = []
    scanned = 0
    suggested = 0
    skipped = 0
    for repo in repos:
        if not any((repo.name, repo.description, repo.summary, "、".join(repo.tags))):
            skipped += 1
            continue
        scanned += 1
        suggestions = suggest_categories(repo, per_repo=per_repo, min_score=min_score)
        if not suggestions:
            skipped += 1
            continue
        suggested += len(suggestions)
        items.append(
            {
                "repoId": repo.repo_id,
                "suggestions": [item.to_dict() for item in suggestions],
            }
        )
    return items, scanned, suggested, skipped


def business_line_description(key: str) -> str:
    """按业务线 key 取描述（edge 自动建分类时用作说明）。"""
    for line in BUSINESS_LINES:
        if line.key == key:
            return line.description
    return ""
