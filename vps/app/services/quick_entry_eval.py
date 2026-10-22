"""快捷入口（Raycast / 快捷指令类）评估（REQ-202610-0973 / M8-04）。

把「快捷入口做哪个平台、需要什么 API、先做哪一步」变成可复跑的离线评估，
只依赖标准库，不读取网络 / 数据库，也不采集任何真实令牌：

    cd vps
    python -m app.quick_entry_eval report
    python -m app.quick_entry_eval report --json
    python -m app.quick_entry_eval report --ready all
    python -m app.quick_entry_eval contract --out docs/assets/quick-entry-api-contract.json

口径（与 docs/architecture/quick-entry-evaluation.md 保持一致）：

- 评分维度固定为 8 项，权重合计 1.0；每项 1–5 分，加权分满分 5.0；
- 候选平台只评估「个人用户快捷唤起」场景，不评估企业 / 团队协作；
- 所有平台都依赖 M8-05 的个人令牌开放 API；本模块只评估就绪度，不实现 API；
- 工作量为人日量级估算，含开发、联调、文档与一次真机验收，不含商店审核等待。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

# ── 评估维度 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Criterion:
    """一个评估维度。"""

    key: str
    label: str
    weight: float
    description: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion("reach", "用户覆盖", 0.20, "目标用户规模与跨设备覆盖；只做 macOS 或只做 iOS 会丢一半场景"),
    Criterion("auth", "认证与密钥安全", 0.20, "是否支持个人令牌、能否安全存储、撤销与最小权限"),
    Criterion("ux", "交互效率", 0.15, "全局热键 / 分享面板 / 语音唤起 / 内联结果等快捷体验"),
    Criterion("dev_cost", "开发成本", 0.15, "按人日估算的实现与联调成本，成本越低得分越高"),
    Criterion("maintenance", "维护与发布", 0.10, "商店审核、系统升级、API 变更带来的长期维护成本"),
    Criterion("install", "安装门槛", 0.10, "用户从零到可用的步骤数；系统内置 / 商店一键安装得分更高"),
    Criterion("offline", "离线与降级", 0.05, "断网 / API 不可用时是否仍能给出本地缓存或明确提示"),
    Criterion("ecosystem", "生态与扩展性", 0.05, "插件生态、深链、自动化组合与后续扩展空间"),
)

# ── 候选平台 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlatformSpec:
    """一个候选快捷入口平台。"""

    id: str
    name: str
    os: str
    form: str
    distribution: str
    auth_model: str
    dev_effort_days: int
    scores: Mapping[str, int]
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    verdict: str


PLATFORMS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        id="raycast",
        name="Raycast 扩展",
        os="macOS 12+",
        form="原生扩展（React / TypeScript）",
        distribution="Raycast Store 审核 + 本地 sideload",
        auth_model="扩展偏好中保存个人令牌（password 字段，仅本机）",
        dev_effort_days=4,
        scores={
            "reach": 4,
            "auth": 4,
            "ux": 5,
            "dev_cost": 4,
            "maintenance": 4,
            "install": 4,
            "offline": 2,
            "ecosystem": 5,
        },
        strengths=(
            "全局热键 + 列表式结果 + 动作面板，最接近「秒开秒搜」",
            "TypeScript / React 技术栈与 admin 一致，复用成本低",
            "支持深链、剪贴板、选中文本与后续 AI Command",
        ),
        weaknesses=(
            "仅 macOS，Windows / 移动端覆盖不到",
            "上架 Raycast Store 需要审核；可先 sideload 验证",
            "令牌保存在本机扩展偏好，需要明确告知用户风险",
        ),
        verdict="首发首选：macOS 高频用户的价值最高，MVP 范围可控。",
    ),
    PlatformSpec(
        id="shortcuts",
        name="Apple 快捷指令",
        os="iOS / iPadOS 16+、macOS 13+",
        form="系统快捷指令（HTTP 请求动作）",
        distribution="系统内置，用户手动导入 / 分享",
        auth_model="快捷指令内保存个人令牌；可能随 iCloud 同步",
        dev_effort_days=2,
        scores={
            "reach": 5,
            "auth": 2,
            "ux": 3,
            "dev_cost": 5,
            "maintenance": 5,
            "install": 5,
            "offline": 3,
            "ecosystem": 4,
        },
        strengths=(
            "iPhone / iPad / Mac 全覆盖，系统内置、零安装",
            "可挂到分享面板、Siri、主屏与自动化，触达路径最短",
            "无需代码与商店审核，1–2 人日即可产出可分享的指令",
        ),
        weaknesses=(
            "令牌存在快捷指令里，iCloud 同步与分享都可能泄露",
            "多步表单体验弱，复杂筛选 / 分页不适合",
            "不同 iOS 版本的快捷指令动作存在差异，需要最低版本说明",
        ),
        verdict="第二优先：作为 iOS / 非 Raycast 用户的兜底入口，只做搜索 + 收藏两个动作。",
    ),
    PlatformSpec(
        id="browser-omnibox",
        name="浏览器地址栏（omnibox）",
        os="Chrome / Edge / Firefox",
        form="浏览器扩展的 omnibox 关键字",
        distribution="浏览器扩展商店（复用 M8-02）",
        auth_model="扩展 storage 保存个人令牌",
        dev_effort_days=3,
        scores={
            "reach": 5,
            "auth": 3,
            "ux": 4,
            "dev_cost": 4,
            "maintenance": 4,
            "install": 4,
            "offline": 2,
            "ecosystem": 3,
        },
        strengths=(
            "所有桌面浏览器用户都能用，覆盖面最大",
            "可直接复用 M8-02 浏览器扩展的鉴权、API 与发布链路",
            "地址栏关键字 + 联想结果，输入成本低",
        ),
        weaknesses=(
            "依赖扩展安装，纯移动端不可用",
            "浏览器扩展商店审核与 Manifest 版本升级需要持续维护",
            "令牌存于浏览器扩展，权限边界需要收紧",
        ),
        verdict="不单独立项：作为 M8-02 浏览器扩展的一个 omnibox 入口顺带交付。",
    ),
    PlatformSpec(
        id="vscode",
        name="VS Code 扩展",
        os="Windows / macOS / Linux",
        form="VS Code 扩展（命令面板）",
        distribution="VS Code Marketplace 审核",
        auth_model="扩展设置保存个人令牌（SecretStorage 可选）",
        dev_effort_days=5,
        scores={
            "reach": 3,
            "auth": 4,
            "ux": 4,
            "dev_cost": 3,
            "maintenance": 3,
            "install": 3,
            "offline": 2,
            "ecosystem": 3,
        },
        strengths=(
            "开发者用户与收藏库重合度高",
            "命令面板 / 右键菜单适合「收藏当前仓库」",
            "SecretStorage 可避免令牌明文落配置",
        ),
        weaknesses=(
            "只覆盖开发者，且 VS Code 内已有 GitHub 插件竞争",
            "Marketplace 审核与 Webview / API 兼容性维护成本较高",
            "与 M8-06 CLI 的用户场景重叠",
        ),
        verdict="暂缓：等 M8-06 CLI 落地后复用同一套 API，再评估是否值得做扩展。",
    ),
    PlatformSpec(
        id="alfred",
        name="Alfred Workflow",
        os="macOS",
        form="Workflow（脚本 / 二进制）",
        distribution="自行分发；Powerpack 付费",
        auth_model="Workflow 配置或 Keychain 保存个人令牌",
        dev_effort_days=4,
        scores={
            "reach": 2,
            "auth": 4,
            "ux": 5,
            "dev_cost": 3,
            "maintenance": 4,
            "install": 2,
            "offline": 2,
            "ecosystem": 3,
        },
        strengths=(
            "老牌 macOS 启动器，热键与工作流体验成熟",
            "可直接调用系统 Keychain，令牌存储相对安全",
        ),
        weaknesses=(
            "用户需要购买 Powerpack，安装门槛高",
            "用户规模明显小于 Raycast，投入产出比低",
            "Workflow 脚本维护与 macOS 升级兼容需要长期投入",
        ),
        verdict="暂缓：与 Raycast 用户高度重叠，等 Raycast 验证后再决定是否补位。",
    ),
    PlatformSpec(
        id="utools",
        name="uTools 插件",
        os="macOS / Windows",
        form="uTools 插件（JavaScript）",
        distribution="uTools 插件应用市场审核",
        auth_model="插件配置保存个人令牌",
        dev_effort_days=5,
        scores={
            "reach": 3,
            "auth": 3,
            "ux": 4,
            "dev_cost": 3,
            "maintenance": 3,
            "install": 4,
            "offline": 2,
            "ecosystem": 3,
        },
        strengths=(
            "覆盖 Windows，可补 Raycast 的平台空白",
            "国内用户认知度高，插件安装与更新方便",
        ),
        weaknesses=(
            "插件市场审核与平台规则不透明",
            "API 能力与调试工具不如 Raycast 成熟",
            "Windows 用户是否愿意为收藏工具安装启动器仍待验证",
        ),
        verdict="观察：只有 Windows 需求被真实用户提出时再启动。",
    ),
)

# ── M8-05 API 前置能力 ─────────────────────────────────────────


@dataclass(frozen=True)
class ApiRequirement:
    """M8-05 需要提供的一项能力。"""

    key: str
    label: str
    category: str
    description: str


API_REQUIREMENTS: tuple[ApiRequirement, ...] = (
    ApiRequirement("token.issue", "个人令牌创建", "令牌", "登录后创建令牌，明文只返回一次，服务端只存 SHA-256 摘要"),
    ApiRequirement("token.list", "令牌列表与指纹", "令牌", "列出令牌名称 / 12 位指纹 / 最近使用时间 / 过期时间，不返回明文"),
    ApiRequirement("token.revoke", "令牌撤销", "令牌", "立即撤销单个令牌，撤销后 60 秒内所有客户端失效"),
    ApiRequirement("auth.bearer", "Bearer 认证", "认证", "`Authorization: Bearer <token>` 访问 `/api/v1/*`，与 Cookie 会话并存"),
    ApiRequirement("scope.read", "只读 scope", "认证", "`read:repos` / `read:trending` / `read:recommendations` / `read:search`"),
    ApiRequirement("scope.write", "写入 scope", "认证", "`write:bookmarks` 仅允许收藏 / 取消收藏，不允许删除仓库或改分类"),
    ApiRequirement("rate_limit", "按令牌限流", "可靠性", "读 60 次/分钟、写 20 次/分钟，返回 429 + Retry-After"),
    ApiRequirement("idempotency", "收藏幂等", "可靠性", "`Idempotency-Key` 去重，重复收藏返回同一结果而不是 409"),
    ApiRequirement("search", "统一搜索", "接口", "`GET /api/v1/search?q=&limit=` 返回仓库卡片，语义 / 关键词降级"),
    ApiRequirement("bookmark.create", "收藏写入", "接口", "`POST /api/v1/bookmarks` 接受 URL 或 `owner/name`，返回仓库与分类"),
    ApiRequirement("bookmark.delete", "取消收藏", "接口", "`DELETE /api/v1/bookmarks/{id}`，幂等"),
    ApiRequirement("me", "当前用户 / 连通性", "接口", "`GET /api/v1/me` 用于客户端启动时校验令牌与显示登录用户"),
    ApiRequirement("openapi", "机器可读契约", "接口", "`GET /api/v1/openapi.json` 或 manifest，客户端可据此生成类型 / 做契约测试"),
    ApiRequirement("cors", "浏览器扩展来源白名单", "安全", "仅对 M8-02 扩展来源回显 CORS，不允许任意网页携带令牌调用"),
    ApiRequirement("deep_link", "深链回跳", "体验", "`openfactory://repo/{owner}/{name}` 从快捷入口跳回 admin 详情"),
    ApiRequirement("audit", "令牌使用审计", "安全", "记录令牌指纹、路径、状态码、时间与 IP 哈希，支持按令牌筛选"),
)

_CORE_KEYS: tuple[str, ...] = (
    "token.issue",
    "token.list",
    "token.revoke",
    "auth.bearer",
    "scope.read",
    "scope.write",
    "rate_limit",
    "idempotency",
    "search",
    "bookmark.create",
    "bookmark.delete",
    "me",
    "audit",
)

PLATFORM_REQUIRED_KEYS: Mapping[str, tuple[str, ...]] = {
    "raycast": _CORE_KEYS + ("openapi", "deep_link"),
    "shortcuts": _CORE_KEYS + ("deep_link",),
    "browser-omnibox": _CORE_KEYS + ("openapi", "cors"),
    "vscode": _CORE_KEYS + ("openapi",),
    "alfred": _CORE_KEYS + ("deep_link",),
    "utools": _CORE_KEYS,
}

# 建议的 v1 端点（供 M8-05 实现；本需求不落地）
CONTRACT_ENDPOINTS: tuple[Mapping[str, object], ...] = (
    {
        "method": "POST",
        "path": "/api/v1/tokens",
        "auth": "session",
        "scope": "-",
        "purpose": "创建个人令牌，明文只返回一次",
    },
    {
        "method": "GET",
        "path": "/api/v1/tokens",
        "auth": "session",
        "scope": "-",
        "purpose": "列出令牌指纹 / 最近使用 / 过期时间",
    },
    {
        "method": "DELETE",
        "path": "/api/v1/tokens/{id}",
        "auth": "session",
        "scope": "-",
        "purpose": "撤销令牌",
    },
    {
        "method": "GET",
        "path": "/api/v1/me",
        "auth": "bearer",
        "scope": "read:repos",
        "purpose": "校验令牌并返回当前用户",
    },
    {
        "method": "GET",
        "path": "/api/v1/search",
        "auth": "bearer",
        "scope": "read:search",
        "purpose": "搜索收藏 / 热榜（q / limit / scope）",
    },
    {
        "method": "POST",
        "path": "/api/v1/bookmarks",
        "auth": "bearer",
        "scope": "write:bookmarks",
        "purpose": "按 url 或 fullName 收藏；支持 Idempotency-Key",
    },
    {
        "method": "DELETE",
        "path": "/api/v1/bookmarks/{id}",
        "auth": "bearer",
        "scope": "write:bookmarks",
        "purpose": "取消收藏（幂等）",
    },
    {
        "method": "GET",
        "path": "/api/v1/trending",
        "auth": "bearer",
        "scope": "read:trending",
        "purpose": "热榜列表（limit / language）",
    },
    {
        "method": "GET",
        "path": "/api/v1/recommendations",
        "auth": "bearer",
        "scope": "read:recommendations",
        "purpose": "每日推荐列表（limit）",
    },
    {
        "method": "GET",
        "path": "/api/v1/openapi.json",
        "auth": "bearer",
        "scope": "read:repos",
        "purpose": "机器可读契约",
    },
)

# ── 结果模型 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlatformScore:
    """一个平台的加权评分结果。"""

    platform: PlatformSpec
    weighted_score: float
    grade: str
    rank: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "id": self.platform.id,
            "name": self.platform.name,
            "os": self.platform.os,
            "form": self.platform.form,
            "distribution": self.platform.distribution,
            "authModel": self.platform.auth_model,
            "devEffortDays": self.platform.dev_effort_days,
            "weightedScore": self.weighted_score,
            "grade": self.grade,
            "scores": dict(self.platform.scores),
            "strengths": list(self.platform.strengths),
            "weaknesses": list(self.platform.weaknesses),
            "verdict": self.platform.verdict,
        }


@dataclass(frozen=True)
class RequirementStatus:
    """一项 API 能力的就绪状态。"""

    requirement: ApiRequirement
    required_by: tuple[str, ...]
    ready: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.requirement.key,
            "label": self.requirement.label,
            "category": self.requirement.category,
            "description": self.requirement.description,
            "requiredBy": list(self.required_by),
            "ready": self.ready,
        }


@dataclass(frozen=True)
class PlatformReadiness:
    """一个平台相对 M8-05 的就绪状态。"""

    platform_id: str
    platform_name: str
    state: str
    coverage: int
    missing: tuple[str, ...]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "platformId": self.platform_id,
            "platformName": self.platform_name,
            "state": self.state,
            "coverage": self.coverage,
            "missing": list(self.missing),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class Phase:
    """落地路线中的一个阶段。"""

    id: str
    title: str
    scope: str
    depends_on: str
    effort_days: tuple[int, int]
    deliverable: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "dependsOn": self.depends_on,
            "effortDays": list(self.effort_days),
            "deliverable": self.deliverable,
        }


@dataclass(frozen=True)
class Risk:
    """评估识别的风险。"""

    id: str
    title: str
    impact: str
    likelihood: str
    mitigation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "impact": self.impact,
            "likelihood": self.likelihood,
            "mitigation": self.mitigation,
        }


@dataclass(frozen=True)
class Metric:
    """验收指标。"""

    key: str
    label: str
    target: str
    how: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "target": self.target,
            "how": self.how,
        }


@dataclass(frozen=True)
class QuickEntryEvaluation:
    """一次完整评估的结果。"""

    generated_at: str
    platforms: tuple[PlatformScore, ...]
    api_requirements: tuple[RequirementStatus, ...]
    platform_readiness: tuple[PlatformReadiness, ...]
    phases: tuple[Phase, ...]
    risks: tuple[Risk, ...]
    metrics: tuple[Metric, ...]
    primary: str
    secondary: str
    deferred: tuple[str, ...]
    total_effort_days: tuple[int, int]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "openfactory.quick-entry-evaluation.v1",
            "version": 1,
            "generatedAt": self.generated_at,
            "summary": self.summary,
            "recommendation": {
                "primary": self.primary,
                "secondary": self.secondary,
                "deferred": list(self.deferred),
                "totalEffortDays": list(self.total_effort_days),
            },
            "platforms": [item.to_dict() for item in self.platforms],
            "apiRequirements": [item.to_dict() for item in self.api_requirements],
            "platformReadiness": [item.to_dict() for item in self.platform_readiness],
            "phases": [item.to_dict() for item in self.phases],
            "risks": [item.to_dict() for item in self.risks],
            "metrics": [item.to_dict() for item in self.metrics],
        }


# ── 评分 ────────────────────────────────────────────────────────


def validate_criteria() -> None:
    """权重必须为正且合计为 1，避免评分口径悄悄漂移。"""
    total = sum(item.weight for item in CRITERIA)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"评估权重合计必须为 1.0，当前为 {total:.4f}")
    keys = [item.key for item in CRITERIA]
    if len(keys) != len(set(keys)):
        raise ValueError("评估维度 key 重复")


def grade_for(score: float) -> str:
    """按加权分给出等级；只用于报告可读性，不参与排序。"""
    if score >= 4.0:
        return "A"
    if score >= 3.8:
        return "A-"
    if score >= 3.6:
        return "B+"
    if score >= 3.4:
        return "B"
    if score >= 3.2:
        return "B-"
    return "C"


def score_platform(platform: PlatformSpec) -> PlatformScore:
    """计算单个平台的加权分；缺项或越界直接报错。"""
    missing = [item.key for item in CRITERIA if item.key not in platform.scores]
    if missing:
        raise ValueError(f"{platform.id} 缺少评分项：{', '.join(missing)}")
    extra = [key for key in platform.scores if key not in {item.key for item in CRITERIA}]
    if extra:
        raise ValueError(f"{platform.id} 存在未知评分项：{', '.join(extra)}")

    weighted = 0.0
    for criterion in CRITERIA:
        value = platform.scores[criterion.key]
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"{platform.id}.{criterion.key} 必须是 1–5 的整数")
        weighted += value * criterion.weight

    rounded = round(weighted, 2)
    return PlatformScore(
        platform=platform,
        weighted_score=rounded,
        grade=grade_for(rounded),
    )


def rank_platforms(platforms: Sequence[PlatformSpec] = PLATFORMS) -> tuple[PlatformScore, ...]:
    """按加权分降序排名；同分按 id 稳定排序，保证复跑结果一致。"""
    scored = [score_platform(item) for item in platforms]
    scored.sort(key=lambda item: (-item.weighted_score, item.platform.id))
    return tuple(
        PlatformScore(
            platform=item.platform,
            weighted_score=item.weighted_score,
            grade=item.grade,
            rank=index,
        )
        for index, item in enumerate(scored, start=1)
    )


# ── API 就绪度 ──────────────────────────────────────────────────


def _validate_ready_keys(ready_keys: Iterable[str]) -> frozenset[str]:
    valid = {item.key for item in API_REQUIREMENTS}
    keys = frozenset(str(key).strip() for key in ready_keys if str(key).strip())
    unknown = sorted(keys - valid)
    if unknown:
        raise ValueError(f"未知的 API 能力 key：{', '.join(unknown)}")
    return keys


def assess_api_readiness(ready_keys: Iterable[str] = ()) -> tuple[RequirementStatus, ...]:
    """把已就绪能力映射为完整清单；未列出的能力一律视为未就绪。"""
    ready = _validate_ready_keys(ready_keys)
    statuses = []
    for requirement in API_REQUIREMENTS:
        required_by = tuple(
            platform.id
            for platform in PLATFORMS
            if requirement.key in PLATFORM_REQUIRED_KEYS.get(platform.id, ())
        )
        statuses.append(
            RequirementStatus(
                requirement=requirement,
                required_by=required_by,
                ready=requirement.key in ready,
            )
        )
    return tuple(statuses)


def platform_readiness(
    platform_id: str,
    statuses: Sequence[RequirementStatus],
) -> PlatformReadiness:
    """按平台必需能力计算就绪度与缺失清单。"""
    platform = next((item for item in PLATFORMS if item.id == platform_id), None)
    if platform is None:
        raise ValueError(f"未知平台：{platform_id}")
    required = PLATFORM_REQUIRED_KEYS[platform_id]
    ready_keys = {item.requirement.key for item in statuses if item.ready}
    missing = tuple(key for key in required if key not in ready_keys)
    coverage = round((len(required) - len(missing)) / len(required) * 100)
    if missing:
        state = "blocked"
        summary = f"{platform.name} 被 {len(missing)} 项 API 能力阻塞：{', '.join(missing)}"
    else:
        state = "ready"
        summary = f"{platform.name} 的 {len(required)} 项 API 前置能力已就绪，可进入开发"
    return PlatformReadiness(
        platform_id=platform.id,
        platform_name=platform.name,
        state=state,
        coverage=coverage,
        missing=missing,
        summary=summary,
    )


# ── 报告组装 ────────────────────────────────────────────────────


def _build_phases() -> tuple[Phase, ...]:
    return (
        Phase(
            id="m8-05",
            title="M8-05 开放 API（前置依赖）",
            scope="个人令牌签发 / 列表 / 撤销、Bearer 认证、读写 scope、限流、幂等、搜索 / 收藏 / 热榜 / 推荐 / me、OpenAPI、审计",
            depends_on="M5-05 会话与限流基线",
            effort_days=(4, 6),
            deliverable="`/api/v1/*` 契约与实现、令牌管理页、契约测试",
        ),
        Phase(
            id="raycast-mvp",
            title="Raycast 扩展 MVP",
            scope="搜索收藏 / 热榜、收藏剪贴板 URL、取消收藏、打开 admin 详情、令牌设置与连通性检查",
            depends_on="M8-05",
            effort_days=(3, 4),
            deliverable="可 sideload 的 Raycast 扩展 + 安装说明 + 真机验收记录",
        ),
        Phase(
            id="shortcuts",
            title="Apple 快捷指令",
            scope="分享面板收藏当前链接、Siri 搜索收藏、查看今日推荐；只做两个最小动作",
            depends_on="M8-05",
            effort_days=(1, 2),
            deliverable="可分享的快捷指令文件 + 令牌填写与撤销说明",
        ),
        Phase(
            id="omnibox",
            title="浏览器地址栏（并入 M8-02）",
            scope="在浏览器扩展中注册 omnibox 关键字，复用已有鉴权与 API",
            depends_on="M8-02 浏览器扩展",
            effort_days=(0, 1),
            deliverable="扩展新增 `of` 关键字搜索与收藏命令",
        ),
        Phase(
            id="deferred",
            title="Alfred / uTools / VS Code（暂缓）",
            scope="仅在 Raycast 验证后出现明确平台诉求时再评估",
            depends_on="Raycast MVP 数据",
            effort_days=(0, 0),
            deliverable="不排期；保留平台评分与触发条件",
        ),
    )


def _build_risks() -> tuple[Risk, ...]:
    return (
        Risk(
            id="R1",
            title="令牌泄露（快捷指令 iCloud 同步 / 扩展偏好）",
            impact="高",
            likelihood="中",
            mitigation="只发最小 scope 令牌；默认只读，写令牌单独创建；提供一键撤销与最近使用审计；文档明确禁止把令牌写进 URL / 截图 / 分享的快捷指令",
        ),
        Risk(
            id="R2",
            title="M8-05 延期导致快捷入口无法开工",
            impact="高",
            likelihood="高",
            mitigation="本需求只冻结契约与评分；M8-05 完成前不创建客户端分支；契约变更走版本号",
        ),
        Risk(
            id="R3",
            title="Raycast Store 审核周期不可控",
            impact="中",
            likelihood="中",
            mitigation="先 sideload 给内测用户；商店审核与 MVP 开发解耦，审核不通过不影响自用",
        ),
        Risk(
            id="R4",
            title="快捷指令版本差异导致动作不可用",
            impact="中",
            likelihood="中",
            mitigation="最低版本写进说明（iOS 16 / macOS 13）；提供「复制 API 地址手动请求」的兜底步骤",
        ),
        Risk(
            id="R5",
            title="D1 / 搜索延迟导致快捷入口体感慢",
            impact="中",
            likelihood="中",
            mitigation="客户端 200ms 防抖 + 本地缓存最近结果；服务端分页与 limit 上限；p95 目标 ≤ 800ms",
        ),
        Risk(
            id="R6",
            title="多客户端契约漂移",
            impact="中",
            likelihood="中",
            mitigation="以 `/api/v1/openapi.json` 为唯一契约；每个客户端加契约测试；版本前缀 `/v1` 不兼容变更升 v2",
        ),
    )


def _build_metrics() -> tuple[Metric, ...]:
    return (
        Metric("activation", "激活率", "创建令牌后 7 天内至少调用 1 次", "令牌审计日志按指纹聚合"),
        Metric("wau", "周活跃快捷入口用户", "上线 4 周后 ≥ 10 人", "按令牌指纹去重统计"),
        Metric("success", "命令成功率", "≥ 99%（不含用户取消）", "客户端上报 + 服务端状态码"),
        Metric("latency", "搜索 p95", "≤ 800ms（客户端体感）", "客户端埋点与服务端指标对照"),
        Metric("revoke", "撤销生效时间", "≤ 60 秒", "撤销后立即请求应返回 401"),
        Metric("leak", "明文令牌泄露", "0 起", "日志扫描 + 安全审计"),
    )


def build_evaluation(
    ready_keys: Iterable[str] = (),
    generated_at: str | None = None,
) -> QuickEntryEvaluation:
    """汇总平台排名、API 就绪度、路线、风险与指标。"""
    validate_criteria()
    ranked = rank_platforms()
    statuses = assess_api_readiness(ready_keys)
    readiness = tuple(platform_readiness(item.platform.id, statuses) for item in ranked)
    ready_count = sum(1 for item in statuses if item.ready)
    total = len(statuses)

    primary = ranked[0].platform.id
    secondary = ranked[1].platform.id
    deferred = tuple(item.platform.id for item in ranked[3:])
    phases = _build_phases()
    total_effort = (
        sum(item.effort_days[0] for item in phases),
        sum(item.effort_days[1] for item in phases),
    )

    primary_readiness = next(item for item in readiness if item.platform_id == primary)
    if ready_count == 0:
        summary = (
            "M8-05 开放 API 尚未落地，快捷入口全部被阻塞；"
            f"建议先按契约完成个人令牌与 `/api/v1/*`，再启动 {ranked[0].platform.name} MVP。"
        )
    elif primary_readiness.state == "ready":
        summary = (
            f"API 前置能力 {ready_count}/{total} 已就绪，{ranked[0].platform.name} 可进入开发；"
            f"第二优先为 {ranked[1].platform.name}。"
        )
    else:
        summary = (
            f"API 前置能力 {ready_count}/{total} 已就绪，但 {ranked[0].platform.name} 仍缺 "
            f"{len(primary_readiness.missing)} 项；补齐后再开工。"
        )

    return QuickEntryEvaluation(
        generated_at=generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        platforms=ranked,
        api_requirements=statuses,
        platform_readiness=readiness,
        phases=phases,
        risks=_build_risks(),
        metrics=_build_metrics(),
        primary=primary,
        secondary=secondary,
        deferred=deferred,
        total_effort_days=total_effort,
        summary=summary,
    )


# ── Markdown / 契约渲染 ────────────────────────────────────────


def _platform_name(platform_id: str) -> str:
    return next(item.name for item in PLATFORMS if item.id == platform_id)


def render_markdown(report: QuickEntryEvaluation) -> str:
    """渲染归档报告；表格与结论都来自同一份评估数据。"""
    lines: list[str] = []
    lines.append("# 快捷入口评估 · Raycast / 快捷指令类（M8-04）")
    lines.append("")
    lines.append(
        f"> 需求：REQ-202610-0973 ｜ 评估日期：{report.generated_at} ｜ "
        "复跑：`cd vps && python -m app.quick_entry_eval report`"
    )
    lines.append("")
    lines.append("## 1. 结论摘要")
    lines.append("")
    lines.append(f"**{report.summary}**")
    lines.append("")
    lines.append(
        f"- 首选：**{_platform_name(report.primary)}**（{report.platforms[0].weighted_score:.2f} / 5）"
    )
    lines.append(
        f"- 次选：**{_platform_name(report.secondary)}**（{report.platforms[1].weighted_score:.2f} / 5）"
    )
    lines.append(
        "- 暂缓："
        + "、".join(_platform_name(item) for item in report.deferred)
        + "（等首发平台验证后再评估）"
    )
    lines.append(
        f"- 总工作量估算：**{report.total_effort_days[0]}–{report.total_effort_days[1]} 人日**"
        "（含 M8-05 开放 API；不含商店审核等待）"
    )
    ready_count = sum(1 for item in report.api_requirements if item.ready)
    lines.append(
        f"- M8-05 API 就绪度：**{ready_count}/{len(report.api_requirements)}**；"
        "未就绪时所有快捷入口均被阻塞"
    )
    lines.append("")

    lines.append("## 2. 评估方法与权重")
    lines.append("")
    lines.append("每项 1–5 分，按权重加权求和，满分 5.0；分数越高越适合作为首发入口。")
    lines.append("")
    lines.append("| 维度 | 权重 | 说明 |")
    lines.append("| --- | ---: | --- |")
    for criterion in CRITERIA:
        lines.append(f"| {criterion.label} | {criterion.weight:.0%} | {criterion.description} |")
    lines.append("")

    lines.append("## 3. 候选平台排名")
    lines.append("")
    header = "| 排名 | 平台 | 形态 | 覆盖 | 认证 | 体验 | 开发成本 | 维护 | 安装 | 离线 | 生态 | 加权分 | 等级 |"
    lines.append(header)
    lines.append("| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |")
    for item in report.platforms:
        scores = item.platform.scores
        lines.append(
            f"| {item.rank} | {item.platform.name} | {item.platform.form} | "
            f"{scores['reach']} | {scores['auth']} | {scores['ux']} | {scores['dev_cost']} | "
            f"{scores['maintenance']} | {scores['install']} | {scores['offline']} | "
            f"{scores['ecosystem']} | **{item.weighted_score:.2f}** | {item.grade} |"
        )
    lines.append("")

    lines.append("## 4. 分平台结论")
    lines.append("")
    for item in report.platforms:
        lines.append(f"### 4.{item.rank} {item.platform.name}（{item.weighted_score:.2f} / {item.grade}）")
        lines.append("")
        lines.append(
            f"- 形态：{item.platform.form}；系统：{item.platform.os}；分发：{item.platform.distribution}"
        )
        lines.append(f"- 认证：{item.platform.auth_model}")
        lines.append(f"- 估算工作量：{item.platform.dev_effort_days} 人日")
        lines.append("- 亮点：")
        for strength in item.platform.strengths:
            lines.append(f"  - {strength}")
        lines.append("- 局限：")
        for weakness in item.platform.weaknesses:
            lines.append(f"  - {weakness}")
        lines.append(f"- 结论：{item.platform.verdict}")
        lines.append("")

    lines.append("## 5. M8-05 API 就绪度")
    lines.append("")
    lines.append("| 能力 | 分类 | 说明 | 就绪 | 阻塞平台 |")
    lines.append("| --- | --- | --- | :---: | --- |")
    for item in report.api_requirements:
        ready = "✅" if item.ready else "❌"
        blocked = "、".join(item.required_by) if item.required_by else "—"
        lines.append(
            f"| `{item.requirement.key}` | {item.requirement.category} | "
            f"{item.requirement.description} | {ready} | {blocked} |"
        )
    lines.append("")
    lines.append("按平台的阻塞情况：")
    lines.append("")
    lines.append("| 平台 | 状态 | 覆盖率 | 缺失能力 |")
    lines.append("| --- | :---: | ---: | --- |")
    for item in report.platform_readiness:
        missing = "、".join(f"`{key}`" for key in item.missing) or "—"
        state = "可开工" if item.state == "ready" else "被阻塞"
        lines.append(f"| {item.platform_name} | {state} | {item.coverage}% | {missing} |")
    lines.append("")

    lines.append("## 6. 推荐落地路线")
    lines.append("")
    lines.append("| 阶段 | 范围 | 依赖 | 工作量（人日） | 交付物 |")
    lines.append("| --- | --- | --- | ---: | --- |")
    for phase in report.phases:
        lines.append(
            f"| {phase.title} | {phase.scope} | {phase.depends_on} | "
            f"{phase.effort_days[0]}–{phase.effort_days[1]} | {phase.deliverable} |"
        )
    lines.append("")

    lines.append("## 7. 安全与隐私边界")
    lines.append("")
    lines.append("- 令牌明文只在创建时返回一次，服务端只存 SHA-256 摘要与 12 位指纹；")
    lines.append("- 默认只读 scope；写令牌单独创建，且只能收藏 / 取消收藏；")
    lines.append("- 令牌不得写入 URL、日志、截图或可分享的快捷指令；快捷指令只让用户本机粘贴；")
    lines.append("- 撤销后 60 秒内失效；令牌列表只显示指纹、最近使用时间与过期时间；")
    lines.append("- 浏览器扩展只允许 M8-02 的来源，禁止任意网页携带令牌调用；")
    lines.append("- 所有客户端请求走 HTTPS；服务端按令牌限流并记录审计事件。")
    lines.append("")

    lines.append("## 8. 风险登记")
    lines.append("")
    lines.append("| # | 风险 | 影响 | 概率 | 缓解 |")
    lines.append("| --- | --- | :---: | :---: | --- |")
    for risk in report.risks:
        lines.append(f"| {risk.id} | {risk.title} | {risk.impact} | {risk.likelihood} | {risk.mitigation} |")
    lines.append("")

    lines.append("## 9. 验收指标")
    lines.append("")
    lines.append("| 指标 | 目标 | 采集方式 |")
    lines.append("| --- | --- | --- |")
    for metric in report.metrics:
        lines.append(f"| {metric.label} | {metric.target} | {metric.how} |")
    lines.append("")

    lines.append("## 10. 复跑方式")
    lines.append("")
    lines.append("```bash")
    lines.append("cd vps")
    lines.append("python -m app.quick_entry_eval report")
    lines.append("python -m app.quick_entry_eval report --json")
    lines.append("python -m app.quick_entry_eval report --ready all   # 模拟 M8-05 全部就绪")
    lines.append("python -m app.quick_entry_eval contract --out docs/assets/quick-entry-api-contract.json")
    lines.append("```")
    lines.append("")
    lines.append("> 评分与权重是 2026-10 的产品判断，调整 `CRITERIA` / `PLATFORMS` 后复跑即可；")
    lines.append("> 真机验收（Raycast Store、iPhone 快捷指令、Alfred / uTools）需在对应设备完成。")
    lines.append("")
    return "\n".join(lines)


def render_contract(report: QuickEntryEvaluation) -> dict[str, object]:
    """渲染给 M8-05 的机器可读契约。"""
    return {
        "schema": "openfactory.quick-entry.v1",
        "version": 1,
        "generatedAt": report.generated_at,
        "description": "OpenFactory 快捷入口（Raycast / Apple 快捷指令 / 浏览器 omnibox / VS Code）所需的开放 API 契约；本文件由评估工具生成，供 M8-05 实现参考。",
        "platforms": [
            {
                "id": item.platform.id,
                "name": item.platform.name,
                "os": item.platform.os,
                "form": item.platform.form,
                "distribution": item.platform.distribution,
                "authModel": item.platform.auth_model,
                "devEffortDays": item.platform.dev_effort_days,
                "weightedScore": item.weighted_score,
                "grade": item.grade,
                "rank": item.rank,
            }
            for item in report.platforms
        ],
        "apiRequirements": [item.to_dict() for item in report.api_requirements],
        "endpoints": list(CONTRACT_ENDPOINTS),
        "security": {
            "tokenStorage": "服务端只存 SHA-256 摘要与 12 位指纹；客户端只保存用户粘贴的令牌，不写入 URL / 日志",
            "scopes": [
                "read:repos",
                "read:trending",
                "read:recommendations",
                "read:search",
                "write:bookmarks",
            ],
            "rateLimits": {"read": "60/min", "write": "20/min"},
            "idempotency": "收藏创建支持 Idempotency-Key，重复请求返回同一结果",
            "revocation": "撤销后 60 秒内所有客户端失效",
            "audit": "按令牌指纹记录路径 / 状态码 / 时间 / IP 哈希",
        },
        "errors": {
            "401": "令牌缺失 / 无效 / 已撤销",
            "403": "scope 不足",
            "404": "资源不存在或不属于当前用户",
            "409": "冲突（仅在未提供 Idempotency-Key 时可能出现）",
            "429": "触发令牌限流，返回 Retry-After",
        },
    }


# ── CLI ─────────────────────────────────────────────────────────


def _parse_ready(value: str) -> tuple[str, ...]:
    text = (value or "").strip()
    if not text:
        return ()
    if text == "all":
        return tuple(item.key for item in API_REQUIREMENTS)
    return tuple(part.strip() for part in text.split(",") if part.strip())


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口：report / contract。"""
    parser = argparse.ArgumentParser(
        prog="python -m app.quick_entry_eval",
        description="快捷入口（Raycast / 快捷指令类）评估工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="输出评估报告")
    report_parser.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    report_parser.add_argument("--ready", default="", help="已就绪的 API 能力 key，逗号分隔；all 表示全部就绪")
    report_parser.add_argument("--generated-at", default=None, help="评估日期（默认当天，格式 YYYY-MM-DD）")
    report_parser.add_argument("--out", default=None, help="写入文件而不是 stdout")

    contract_parser = subparsers.add_parser("contract", help="输出机器可读契约 JSON")
    contract_parser.add_argument("--ready", default="", help="已就绪的 API 能力 key，逗号分隔；all 表示全部就绪")
    contract_parser.add_argument("--generated-at", default=None, help="评估日期（默认当天）")
    contract_parser.add_argument("--out", default=None, help="写入文件而不是 stdout")

    args = parser.parse_args(argv)

    try:
        evaluation = build_evaluation(
            ready_keys=_parse_ready(getattr(args, "ready", "")),
            generated_at=getattr(args, "generated_at", None),
        )
        if args.command == "report":
            text = (
                json.dumps(evaluation.to_dict(), ensure_ascii=False, indent=2)
                if args.json
                else render_markdown(evaluation)
            )
        else:
            text = json.dumps(render_contract(evaluation), ensure_ascii=False, indent=2)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        print(f"已写入 {path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
