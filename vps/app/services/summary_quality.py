"""摘要质量评分与抽检（REQ-202610-0912 / M2-04）。

设计目标：
1. 用可解释的启发式规则给中文摘要打分（长度 / 中文占比 / 三要素覆盖 / 降级标记 / 噪声 / 重复）；
2. 按「批次 + 仓库」确定性抽样，保证同一批次重跑时样本稳定；
3. 低质量摘要强制留存，避免只抽到好样本；
4. 样本落 `summary_quality_samples`，支持人工复核与质量统计。

本模块不依赖网络与模型，所有函数均可离线单测。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, SummaryQualitySample, TrendingRepository

_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_WHITESPACE_RE = re.compile(r"\s+")

# 摘要三要素关键词（命中任意一组即算覆盖该要素）
_COVERAGE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("功能", ("功能", "用途", "用于", "提供", "支持", "实现", "帮助", "工具", "平台", "系统", "服务")),
    (
        "技术",
        (
            "技术",
            "框架",
            "语言",
            "基于",
            "使用",
            "采用",
            "技术栈",
            "python",
            "java",
            "go",
            "rust",
            "typescript",
            "javascript",
            "react",
            "vue",
            "node",
        ),
    ),
    ("场景", ("适用", "场景", "适合", "用户", "团队", "业务", "开发者", "企业", "个人")),
)


@dataclass(frozen=True)
class QualityCheck:
    """单项质量检查结果。"""

    key: str
    label: str
    weight: int
    critical: bool
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "critical": self.critical,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class QualityReport:
    """摘要质量报告。"""

    score: float
    verdict: str  # pass | fail
    checks: list[QualityCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "checks": [check.to_dict() for check in self.checks],
        }


def _visible_length(text: str) -> int:
    return len(_WHITESPACE_RE.sub("", text or ""))


def _chinese_ratio(text: str) -> float:
    visible = _visible_length(text)
    if visible == 0:
        return 0.0
    return len(_CJK_RE.findall(text)) / visible


def _coverage_count(text: str) -> int:
    lowered = (text or "").lower()
    return sum(1 for _, keywords in _COVERAGE_GROUPS if any(word in lowered for word in keywords))


def _repetition_ratio(text: str, window: int = 10) -> float:
    """10 字符滑窗重复率：重复窗口数 / 总窗口数（0 表示完全不重复）。"""
    compact = _WHITESPACE_RE.sub("", text or "")
    if len(compact) < window * 2:
        return 0.0
    windows = [compact[i : i + window] for i in range(len(compact) - window + 1)]
    if not windows:
        return 0.0
    return 1.0 - len(set(windows)) / len(windows)


def evaluate_summary(
    summary: str,
    *,
    max_chars: int = 800,
    source: str = "",
    min_chars: Optional[int] = None,
    pass_score: Optional[float] = None,
) -> QualityReport:
    """按启发式规则评估摘要质量，返回 0~100 分与检查明细。"""
    settings = get_settings()
    min_chars_value = max(1, int(min_chars if min_chars is not None else settings.SUMMARY_QUALITY_MIN_CHARS))
    pass_score_value = float(
        pass_score if pass_score is not None else settings.SUMMARY_QUALITY_PASS_SCORE
    )
    text = (summary or "").strip()
    length = len(text)
    chinese_ratio = _chinese_ratio(text)
    coverage = _coverage_count(text)
    repetition = _repetition_ratio(text)
    fallback_marker = "LLM 暂不可用" in text

    checks = [
        QualityCheck(
            key="non_empty",
            label="非空",
            weight=15,
            critical=True,
            passed=length >= 20,
            detail=f"长度 {length} 字符（要求 ≥ 20）",
        ),
        QualityCheck(
            key="length",
            label="长度适中",
            weight=15,
            critical=False,
            passed=min_chars_value <= length <= int(max_chars * 1.1),
            detail=f"长度 {length} 字符（要求 {min_chars_value}~{int(max_chars * 1.1)}）",
        ),
        QualityCheck(
            key="chinese",
            label="中文为主",
            weight=25,
            critical=True,
            passed=chinese_ratio >= 0.30,
            detail=f"中文占比 {chinese_ratio:.0%}（要求 ≥ 30%）",
        ),
        QualityCheck(
            key="coverage",
            label="三要素覆盖",
            weight=20,
            critical=False,
            passed=coverage >= 2,
            detail=f"覆盖 {coverage}/3 个要素（功能 / 技术栈 / 适用场景，要求 ≥ 2）",
        ),
        QualityCheck(
            key="no_fallback",
            label="非降级输出",
            weight=15,
            critical=True,
            passed=(source != "truncated" and not fallback_marker),
            detail="来源为截断降级" if source == "truncated" or fallback_marker else "来源正常",
        ),
        QualityCheck(
            key="no_noise",
            label="无 Markdown 噪声",
            weight=5,
            critical=False,
            passed=not any(token in text for token in ("```", "![", "<img", "<p>", "</")),
            detail="未发现代码围栏 / 图片 / HTML 标签" if not any(
                token in text for token in ("```", "![", "<img", "<p>", "</")
            ) else "包含代码围栏 / 图片 / HTML 标签",
        ),
        QualityCheck(
            key="not_repetitive",
            label="无明显重复",
            weight=5,
            critical=False,
            passed=repetition <= 0.25,
            detail=f"10 字符滑窗重复率 {repetition:.0%}（要求 ≤ 25%）",
        ),
    ]

    total_weight = sum(check.weight for check in checks)
    earned = sum(check.weight for check in checks if check.passed)
    score = round(earned * 100.0 / total_weight, 1) if total_weight else 0.0
    critical_failed = any(check.critical and not check.passed for check in checks)
    if critical_failed:
        score = min(score, 40.0)
    verdict = "pass" if score >= pass_score_value and not critical_failed else "fail"
    return QualityReport(score=score, verdict=verdict, checks=checks)


def sample_bucket(*, batch_id: str, repo_source: str, repo_id: str) -> float:
    """把「批次 + 来源 + 仓库」映射到稳定的 [0, 1) 桶，便于确定性抽样。"""
    key = f"{batch_id}:{repo_source}:{repo_id}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def should_sample(
    *,
    batch_id: str,
    repo_source: str,
    repo_id: str,
    rate: Optional[float] = None,
    score: float = 100.0,
    always_below: Optional[float] = None,
) -> bool:
    """判断是否留存样本：常规按比例确定性抽样，低质量样本强制留存。"""
    settings = get_settings()
    rate_value = float(rate if rate is not None else settings.SUMMARY_SAMPLE_RATE)
    rate_value = min(1.0, max(0.0, rate_value))
    below_value = float(
        always_below if always_below is not None else settings.SUMMARY_SAMPLE_ALWAYS_BELOW
    )
    if score < below_value:
        return True
    if rate_value <= 0:
        return False
    if rate_value >= 1:
        return True
    return sample_bucket(batch_id=batch_id, repo_source=repo_source, repo_id=repo_id) < rate_value


def record_quality_sample(
    db: Session,
    *,
    batch_id: str,
    repo_id: str,
    repo_source: str,
    summary: str,
    source: str,
    model: str,
    max_chars: int,
    report: QualityReport,
) -> SummaryQualitySample:
    """把一次抽检结果写入样本表；同批次同仓库重跑时更新原样本。"""
    existing = db.execute(
        select(SummaryQualitySample).where(
            SummaryQualitySample.batch_id == batch_id,
            SummaryQualitySample.repo_source == repo_source,
            SummaryQualitySample.repo_id == repo_id,
        )
    ).scalar_one_or_none()
    checks_json = json.dumps([check.to_dict() for check in report.checks], ensure_ascii=False)
    if existing is None:
        sample = SummaryQualitySample(
            id=_new_sample_id(),
            batch_id=batch_id,
            repo_id=repo_id,
            repo_source=repo_source,
            summary=summary,
            source=source,
            model=model,
            max_chars=max_chars,
            score=report.score,
            verdict=report.verdict,
            checks=checks_json,
            status="pending",
        )
        db.add(sample)
        db.flush()
        return sample

    changed = existing.summary != summary
    existing.repo_source = repo_source
    existing.summary = summary
    existing.source = source
    existing.model = model
    existing.max_chars = max_chars
    existing.score = report.score
    existing.verdict = report.verdict
    existing.checks = checks_json
    if changed:
        # 摘要内容变化后，原人工复核结论失效，重新进入待复核队列
        existing.status = "pending"
        existing.reviewer = None
        existing.review_note = None
        existing.reviewed_at = None
    db.flush()
    return existing


def _new_sample_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def sample_quality(
    db: Session,
    *,
    batch_id: str,
    repo_id: str,
    repo_source: str,
    summary: str,
    source: str,
    model: str,
    max_chars: int,
    sampled_count: int,
) -> Optional[SummaryQualitySample]:
    """评估并（按需）留存一条样本；返回样本或 None。"""
    settings = get_settings()
    if sampled_count >= max(0, int(settings.SUMMARY_SAMPLE_MAX_PER_RUN)):
        return None
    report = evaluate_summary(summary, max_chars=max_chars, source=source)
    if not should_sample(
        batch_id=batch_id,
        repo_source=repo_source,
        repo_id=repo_id,
        score=report.score,
    ):
        return None
    return record_quality_sample(
        db,
        batch_id=batch_id,
        repo_id=repo_id,
        repo_source=repo_source,
        summary=summary,
        source=source,
        model=model,
        max_chars=max_chars,
        report=report,
    )


def sample_existing_summaries(
    db: Session,
    *,
    source: str = "my",
    limit: int = 200,
    rate: Optional[float] = None,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    """对存量摘要补抽样（用于历史数据评估），返回结构化统计。"""
    from uuid import uuid4

    settings = get_settings()
    source_value = (source or "my").strip().lower()
    if source_value not in ("my", "trending", "all"):
        source_value = "my"
    batch_value = (batch_id or f"backfill-{uuid4().hex[:12]}").strip()
    max_samples = max(0, int(settings.SUMMARY_SAMPLE_MAX_PER_RUN))
    targets = ("my", "trending") if source_value == "all" else (source_value,)
    total = 0
    sampled = 0
    samples: list[str] = []
    quality_scores: list[float] = []

    for item_source in targets:
        model = MyRepository if item_source == "my" else TrendingRepository
        rows = list(
            db.execute(
                select(model)
                .where(model.readme_summary.isnot(None))
                .order_by(model.id.asc())
                .limit(max(1, int(limit)))
            )
            .scalars()
            .all()
        )
        for row in rows:
            summary = (row.readme_summary or "").strip()
            if not summary:
                continue
            total += 1
            report = evaluate_summary(summary, source="existing")
            quality_scores.append(report.score)
            if sampled >= max_samples:
                continue
            if should_sample(
                batch_id=batch_value,
                repo_source=item_source,
                repo_id=row.id,
                rate=rate,
                score=report.score,
            ):
                sample = record_quality_sample(
                    db,
                    batch_id=batch_value,
                    repo_id=row.id,
                    repo_source=item_source,
                    summary=summary,
                    source="existing",
                    model="",
                    max_chars=len(summary),
                    report=report,
                )
                sampled += 1
                samples.append(sample.id)
    db.commit()
    return {
        "status": "ok",
        "source": source_value,
        "batchId": batch_value,
        "total": total,
        "sampled": sampled,
        "samples": samples,
        "avgScore": round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0.0,
    }
