"""个人数据 LoRA 微调预算与效果评估（REQ-202610-0967 / M7-08）。

本模块把「个人数据能不能微调、要花多少钱、效果怎么证明」变成可复跑的离线评估，
只依赖标准库，不引入 torch / GPU 依赖：

    cd vps
    python -m app.lora_eval report
    python -m app.lora_eval report --repos 120 --summaries 80 --feedback 20 --json
    python -m app.lora_eval compare --baseline baseline.json --tuned tuned.json

口径（与 docs/architecture/lora-finetuning-evaluation.md 保持一致）：

- 训练按 QLoRA（4bit 底座 + LoRA 适配器）估算，GPU 小时含 25% 数据加载 / 验证开销；
- 本机 AI 推理预算 2048 MB，同一时刻只加载 1 个模型；
- 费用为 2026-10 公开云 GPU 时价的量级估算，下单前需按供应商实际报价复核；
- 效果评估采用配对评分 + 精确二项符号检验，默认最小可感知差异 5 分（百分制）、α=0.05。
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

# 本机 AI 推理预算（MB），与 app.services.model_budget 的默认值一致
LOCAL_AI_BUDGET_MB = 2048
# 单次云端试验的费用上限（元）；超过则不建议直接开跑
CLOUD_TRIAL_BUDGET_CNY = 300.0
# 效果门槛：百分制评分的最小可感知差异
MIN_EFFECT = 5.0
# 显著性水平
ALPHA = 0.05
# 数据门槛：最低可训 / 推荐样本量
MIN_SAMPLES = 500
RECOMMENDED_SAMPLES = 2000

DatasetLevel = Literal["insufficient", "minimum", "recommended"]
EffectVerdict = Literal["improved", "regressed", "no_significant_difference"]
Decision = Literal["collect_data", "cloud_trial", "pilot", "defer"]


@dataclass(frozen=True)
class BaseModelSpec:
    """候选底座模型的训练 / 推理规格。"""

    id: str
    name: str
    parameters_b: float
    hidden_size: int
    layers: int
    license: str
    qlora_train_vram_gb: float
    q4_inference_ram_gb: float
    adapter_mb: int
    merged_disk_gb: float
    note: str = ""


@dataclass(frozen=True)
class GpuSpec:
    """训练算力规格；tokens_per_sec_7b 为 7B 模型上的实测吞吐量级。"""

    id: str
    name: str
    vram_gb: float
    hourly_cost_cny: float
    tokens_per_sec_7b: float
    note: str = ""


# 数值口径见评估报告 §4；改动需同步文档与测试。
MODEL_CATALOG: dict[str, BaseModelSpec] = {
    "qwen2.5-1.5b": BaseModelSpec(
        id="qwen2.5-1.5b",
        name="Qwen2.5-1.5B-Instruct",
        parameters_b=1.5,
        hidden_size=1536,
        layers=28,
        license="Apache-2.0",
        qlora_train_vram_gb=3.5,
        q4_inference_ram_gb=1.3,
        adapter_mb=40,
        merged_disk_gb=1.0,
        note="本机 2G 推理预算内可部署；适合风格 / 格式适配",
    ),
    "qwen2.5-3b": BaseModelSpec(
        id="qwen2.5-3b",
        name="Qwen2.5-3B-Instruct",
        parameters_b=3.0,
        hidden_size=2048,
        layers=36,
        license="Apache-2.0",
        qlora_train_vram_gb=5.0,
        q4_inference_ram_gb=2.1,
        adapter_mb=80,
        merged_disk_gb=2.1,
        note="q4 推理约 2.1G，略超 2G 预算，需压缩上下文或调整预算",
    ),
    "qwen2.5-7b": BaseModelSpec(
        id="qwen2.5-7b",
        name="Qwen2.5-7B-Instruct",
        parameters_b=7.0,
        hidden_size=3584,
        layers=28,
        license="Apache-2.0",
        qlora_train_vram_gb=8.0,
        q4_inference_ram_gb=4.7,
        adapter_mb=160,
        merged_disk_gb=4.7,
        note="效果上限更高，但 q4 推理 4.7G 超出本机 2G 预算，只能云端推理",
    ),
    "llama-3.1-8b": BaseModelSpec(
        id="llama-3.1-8b",
        name="Llama 3.1 8B Instruct",
        parameters_b=8.0,
        hidden_size=4096,
        layers=32,
        license="Llama 3.1 Community",
        qlora_train_vram_gb=9.0,
        q4_inference_ram_gb=5.0,
        adapter_mb=180,
        merged_disk_gb=5.0,
        note="中文摘要需额外评测；许可证有商用条款",
    ),
}

GPU_CATALOG: dict[str, GpuSpec] = {
    "cpu-local": GpuSpec(
        id="cpu-local",
        name="本机 CPU（无独显）",
        vram_gb=0.0,
        hourly_cost_cny=0.0,
        tokens_per_sec_7b=12.0,
        note="零租金但无 GPU 显存，只能做极小模型 / 极慢训练",
    ),
    "rtx4090-24g": GpuSpec(
        id="rtx4090-24g",
        name="RTX 4090 24G",
        vram_gb=24.0,
        hourly_cost_cny=2.5,
        tokens_per_sec_7b=1800.0,
        note="性价比首选，适合 1.5B / 7B QLoRA",
    ),
    "a100-40g": GpuSpec(
        id="a100-40g",
        name="A100 40G",
        vram_gb=40.0,
        hourly_cost_cny=8.0,
        tokens_per_sec_7b=3500.0,
        note="大 batch / 更长上下文；单价较高",
    ),
    "a100-80g": GpuSpec(
        id="a100-80g",
        name="A100 80G",
        vram_gb=80.0,
        hourly_cost_cny=12.0,
        tokens_per_sec_7b=4000.0,
        note="仅 7B 全参或 14B+ QLoRA 才需要",
    ),
}


@dataclass(frozen=True)
class TrainingConfig:
    """一次 LoRA 训练的参数。"""

    model_id: str = "qwen2.5-1.5b"
    gpu_id: str = "rtx4090-24g"
    samples: int = MIN_SAMPLES
    epochs: int = 3
    avg_tokens_per_sample: int = 800
    lora_rank: int = 16
    batch_size: int = 1
    grad_accum: int = 16


@dataclass(frozen=True)
class TrainingEstimate:
    """训练成本与可行性估算。"""

    model_id: str
    model_name: str
    gpu_id: str
    gpu_name: str
    samples: int
    epochs: int
    tokens_total: int
    steps: int
    gpu_hours: float
    cost_cny: float
    trainable_params: int
    trainable_ratio: float
    storage_mb: int
    fits_gpu: bool
    fits_local_inference: bool
    viable: bool
    summary: str


@dataclass(frozen=True)
class DatasetProfile:
    """个人数据画像。"""

    repositories: int
    summaries: int
    feedback_pairs: int
    usable_samples: int
    level: DatasetLevel
    meets_minimum: bool
    meets_recommended: bool
    summary: str


@dataclass(frozen=True)
class EffectReport:
    """配对评分的效果对比结果。"""

    samples: int
    baseline_mean: float
    tuned_mean: float
    delta: float
    wins: int
    ties: int
    losses: int
    win_rate: float
    p_value: float
    significant: bool
    verdict: EffectVerdict
    summary: str


@dataclass(frozen=True)
class Scenario:
    """一个训练场景。"""

    id: str
    label: str
    estimate: TrainingEstimate


@dataclass(frozen=True)
class FeasibilityReport:
    """预算 + 效果双评估的汇总。"""

    dataset: DatasetProfile
    scenarios: tuple[Scenario, ...]
    cloud_trial_cost_cny: float
    within_trial_budget: bool
    local_training_feasible: bool
    deployment_model_id: str | None
    deployment_ram_gb: float
    effect: EffectReport | None
    decision: Decision
    summary: str


def resolve_model(model_id: str) -> BaseModelSpec:
    """按 id 查找底座模型；未知模型直接报错，避免静默按错误规格估算。"""
    try:
        return MODEL_CATALOG[model_id]
    except KeyError as exc:
        raise ValueError(f"未知底座模型：{model_id}") from exc


def resolve_gpu(gpu_id: str) -> GpuSpec:
    """按 id 查找 GPU；未知 GPU 直接报错。"""
    try:
        return GPU_CATALOG[gpu_id]
    except KeyError as exc:
        raise ValueError(f"未知 GPU：{gpu_id}") from exc


def estimate_training(config: TrainingConfig) -> TrainingEstimate:
    """估算 QLoRA 训练的 token 量、GPU 小时、费用与显存可行性。"""
    model = resolve_model(config.model_id)
    gpu = resolve_gpu(config.gpu_id)

    if config.samples <= 0:
        raise ValueError("samples 必须大于 0")
    if config.epochs <= 0:
        raise ValueError("epochs 必须大于 0")
    if config.avg_tokens_per_sample <= 0:
        raise ValueError("avg_tokens_per_sample 必须大于 0")
    if config.lora_rank <= 0:
        raise ValueError("lora_rank 必须大于 0")
    if config.batch_size <= 0 or config.grad_accum <= 0:
        raise ValueError("batch_size / grad_accum 必须大于 0")

    tokens_total = config.samples * config.epochs * config.avg_tokens_per_sample
    steps = math.ceil(
        config.samples * config.epochs / (config.batch_size * config.grad_accum)
    )

    # 吞吐随参数量近似反比缩放；0.85 为经验指数，再乘 0.85 的框架效率。
    tokens_per_sec = (
        gpu.tokens_per_sec_7b
        * (7.0 / model.parameters_b) ** 0.85
        * 0.85
    )
    gpu_hours = tokens_total / tokens_per_sec / 3600 * 1.25
    cost_cny = gpu_hours * gpu.hourly_cost_cny

    # LoRA 可训练参数 ≈ 2 × rank × hidden × layers × 7 个投影矩阵。
    trainable_params = int(2 * config.lora_rank * model.hidden_size * model.layers * 7)
    trainable_ratio = trainable_params / (model.parameters_b * 1_000_000_000)

    fits_gpu = gpu.vram_gb >= model.qlora_train_vram_gb
    fits_local_inference = model.q4_inference_ram_gb * 1024 <= LOCAL_AI_BUDGET_MB
    viable = fits_gpu and gpu_hours <= 24

    if not fits_gpu:
        summary = (
            f"{gpu.name} 显存 {gpu.vram_gb:.0f}G < {model.name} QLoRA 所需 "
            f"{model.qlora_train_vram_gb:.1f}G，不可训练"
        )
    elif not viable:
        summary = f"预计 {gpu_hours:.1f} GPU 小时，超过 24 小时可接受上限"
    else:
        summary = (
            f"预计 {gpu_hours:.2f} GPU 小时 / ¥{cost_cny:.2f}，"
            f"可训练参数 {trainable_params / 1_000_000:.1f}M（{trainable_ratio:.2%}）"
        )

    return TrainingEstimate(
        model_id=model.id,
        model_name=model.name,
        gpu_id=gpu.id,
        gpu_name=gpu.name,
        samples=config.samples,
        epochs=config.epochs,
        tokens_total=tokens_total,
        steps=steps,
        gpu_hours=round(gpu_hours, 2),
        cost_cny=round(cost_cny, 2),
        trainable_params=trainable_params,
        trainable_ratio=round(trainable_ratio, 6),
        storage_mb=model.adapter_mb * 2 + 64,
        fits_gpu=fits_gpu,
        fits_local_inference=fits_local_inference,
        viable=viable,
        summary=summary,
    )


def assess_dataset(
    repositories: int,
    summaries: int,
    feedback_pairs: int,
) -> DatasetProfile:
    """按收藏 / 摘要 / 反馈偏好对评估数据是否够训。"""
    if repositories < 0 or summaries < 0 or feedback_pairs < 0:
        raise ValueError("数据量不能为负数")

    usable = summaries + feedback_pairs
    if usable >= RECOMMENDED_SAMPLES:
        level: DatasetLevel = "recommended"
    elif usable >= MIN_SAMPLES:
        level = "minimum"
    else:
        level = "insufficient"

    if level == "recommended":
        summary = f"可用样本 {usable} ≥ {RECOMMENDED_SAMPLES}，达到推荐训练量"
    elif level == "minimum":
        summary = f"可用样本 {usable} ≥ {MIN_SAMPLES}，达到最低训练量"
    else:
        summary = f"可用样本 {usable} < {MIN_SAMPLES}，不足以训练有意义的 LoRA"

    return DatasetProfile(
        repositories=repositories,
        summaries=summaries,
        feedback_pairs=feedback_pairs,
        usable_samples=usable,
        level=level,
        meets_minimum=usable >= MIN_SAMPLES,
        meets_recommended=usable >= RECOMMENDED_SAMPLES,
        summary=summary,
    )


def load_dataset_profile(
    db_path: str | Path,
    feedback_pairs: int = 0,
) -> DatasetProfile:
    """从本机 SQLite 读取收藏 / 摘要数量；表不存在时按 0 计。

    ``recommendation_feedback`` 在 edge D1，不在本机库，反馈偏好对需通过参数传入。
    """
    path = Path(db_path)
    if not path.is_file():
        raise ValueError(f"数据库不存在：{path}")

    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"无法打开数据库 {path}: {exc}") from exc

    def scalar(sql: str) -> int:
        try:
            row = connection.execute(sql).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0]) if row and row[0] is not None else 0

    try:
        repositories = scalar("SELECT COUNT(*) FROM my_repositories")
        summaries = scalar(
            "SELECT COUNT(*) FROM my_repositories "
            "WHERE readme_summary IS NOT NULL AND TRIM(readme_summary) <> ''"
        )
    finally:
        connection.close()

    return assess_dataset(repositories, summaries, feedback_pairs)


def _sign_test_p_value(wins: int, losses: int) -> float:
    """精确二项符号检验（双侧，p=0.5）；无有效配对时返回 1。"""
    decisive = wins + losses
    if decisive == 0:
        return 1.0
    tail = sum(
        math.comb(decisive, index) for index in range(min(wins, losses) + 1)
    ) / (2**decisive)
    return min(1.0, 2 * tail)


def compare_effect(
    baseline: Sequence[float],
    tuned: Sequence[float],
    min_effect: float = MIN_EFFECT,
    alpha: float = ALPHA,
) -> EffectReport:
    """比较基线 / 微调模型的配对评分（百分制），给出显著性结论。"""
    if len(baseline) != len(tuned):
        raise ValueError("baseline 与 tuned 样本数必须一致")
    if not baseline:
        raise ValueError("至少需要 1 个配对样本")
    if min_effect < 0:
        raise ValueError("min_effect 不能为负数")

    baseline_values = [float(value) for value in baseline]
    tuned_values = [float(value) for value in tuned]
    for value in baseline_values + tuned_values:
        if not math.isfinite(value):
            raise ValueError("评分必须是有限数值")

    wins = ties = losses = 0
    for before, after in zip(baseline_values, tuned_values):
        if after > before:
            wins += 1
        elif after < before:
            losses += 1
        else:
            ties += 1

    baseline_mean = sum(baseline_values) / len(baseline_values)
    tuned_mean = sum(tuned_values) / len(tuned_values)
    delta = tuned_mean - baseline_mean
    decisive = wins + losses
    win_rate = wins / decisive if decisive else 0.0
    p_value = _sign_test_p_value(wins, losses)
    significant = p_value < alpha and abs(delta) >= min_effect

    if significant and delta > 0:
        verdict: EffectVerdict = "improved"
        summary = (
            f"微调后均值 +{delta:.1f} 分，胜率 {win_rate:.0%}，"
            f"p={p_value:.4f}，效果显著"
        )
    elif significant and delta < 0:
        verdict = "regressed"
        summary = (
            f"微调后均值 {delta:.1f} 分，胜率 {win_rate:.0%}，"
            f"p={p_value:.4f}，效果显著变差"
        )
    else:
        verdict = "no_significant_difference"
        summary = (
            f"均值差 {delta:+.1f} 分，胜率 {win_rate:.0%}，"
            f"p={p_value:.4f}，未达到显著提升门槛"
        )

    return EffectReport(
        samples=len(baseline_values),
        baseline_mean=round(baseline_mean, 2),
        tuned_mean=round(tuned_mean, 2),
        delta=round(delta, 2),
        wins=wins,
        ties=ties,
        losses=losses,
        win_rate=round(win_rate, 4),
        p_value=round(p_value, 6),
        significant=significant,
        verdict=verdict,
        summary=summary,
    )


def build_feasibility_report(
    dataset: DatasetProfile | None = None,
    effect: EffectReport | None = None,
) -> FeasibilityReport:
    """汇总本机 / 云端训练场景，给出预算与效果的最终决策。"""
    profile = dataset or assess_dataset(0, 0, 0)
    planning_samples = max(profile.usable_samples, MIN_SAMPLES)

    scenarios = (
        Scenario(
            id="local-1.5b",
            label=f"本机 CPU · 1.5B QLoRA（{planning_samples} 样本）",
            estimate=estimate_training(
                TrainingConfig(
                    model_id="qwen2.5-1.5b",
                    gpu_id="cpu-local",
                    samples=planning_samples,
                )
            ),
        ),
        Scenario(
            id="cloud-1.5b-min",
            label=f"云端 4090 · 1.5B QLoRA（{MIN_SAMPLES} 样本）",
            estimate=estimate_training(
                TrainingConfig(
                    model_id="qwen2.5-1.5b",
                    gpu_id="rtx4090-24g",
                    samples=MIN_SAMPLES,
                )
            ),
        ),
        Scenario(
            id="cloud-1.5b-rec",
            label=f"云端 4090 · 1.5B QLoRA（{RECOMMENDED_SAMPLES} 样本）",
            estimate=estimate_training(
                TrainingConfig(
                    model_id="qwen2.5-1.5b",
                    gpu_id="rtx4090-24g",
                    samples=RECOMMENDED_SAMPLES,
                )
            ),
        ),
        Scenario(
            id="cloud-7b-rec",
            label=f"云端 4090 · 7B QLoRA（{RECOMMENDED_SAMPLES} 样本）",
            estimate=estimate_training(
                TrainingConfig(
                    model_id="qwen2.5-7b",
                    gpu_id="rtx4090-24g",
                    samples=RECOMMENDED_SAMPLES,
                )
            ),
        ),
    )

    cloud_trial_cost = max(
        scenario.estimate.cost_cny
        for scenario in scenarios
        if scenario.estimate.gpu_id != "cpu-local"
        and scenario.estimate.model_id == "qwen2.5-1.5b"
    )
    within_trial_budget = cloud_trial_cost <= CLOUD_TRIAL_BUDGET_CNY
    local_training_feasible = scenarios[0].estimate.viable

    deploy_model = MODEL_CATALOG["qwen2.5-1.5b"]
    deployment_model_id: str | None = deploy_model.id
    deployment_ram_gb = deploy_model.q4_inference_ram_gb

    if effect is not None and effect.significant and effect.delta > 0 and profile.meets_minimum:
        decision: Decision = "pilot"
        summary = "已有显著正向效果且数据达标，可进入小流量试点并注册到模型路由。"
    elif not profile.meets_minimum:
        decision = "collect_data"
        summary = (
            f"当前可用样本 {profile.usable_samples} < {MIN_SAMPLES}，先补数据；"
            f"云端 1.5B 试验成本约 ¥{cloud_trial_cost:.2f}，预算不是瓶颈。"
        )
    elif not within_trial_budget:
        decision = "defer"
        summary = (
            f"云端试验估算 ¥{cloud_trial_cost:.2f} > ¥{CLOUD_TRIAL_BUDGET_CNY:.0f}，暂缓。"
        )
    else:
        decision = "cloud_trial"
        summary = (
            f"数据达到最低样本量，建议先做一次 ≤¥{CLOUD_TRIAL_BUDGET_CNY:.0f} 的"
            "云端 1.5B QLoRA 对照实验，再决定是否上线。"
        )

    return FeasibilityReport(
        dataset=profile,
        scenarios=scenarios,
        cloud_trial_cost_cny=round(cloud_trial_cost, 2),
        within_trial_budget=within_trial_budget,
        local_training_feasible=local_training_feasible,
        deployment_model_id=deployment_model_id,
        deployment_ram_gb=deployment_ram_gb,
        effect=effect,
        decision=decision,
        summary=summary,
    )


def render_report(report: FeasibilityReport) -> str:
    """把评估报告渲染成便于终端阅读的文本。"""
    profile = report.dataset
    lines = [
        "LoRA 微调可行性评估（REQ-202610-0967 / M7-08）",
        (
            f"数据：收藏 {profile.repositories} / 摘要 {profile.summaries} / "
            f"反馈偏好对 {profile.feedback_pairs} → 可用样本 {profile.usable_samples}"
            f"（{profile.level}）"
        ),
        f"数据结论：{profile.summary}",
        "训练场景：",
    ]
    for scenario in report.scenarios:
        estimate = scenario.estimate
        status = "可行" if estimate.viable else "不可行"
        lines.append(
            f"- {scenario.label}：{estimate.gpu_hours:.2f} GPU 小时 / "
            f"¥{estimate.cost_cny:.2f} / {status}"
        )
        lines.append(f"  {estimate.summary}")
    lines.extend(
        [
            (
                f"云端 1.5B 试验预算：¥{report.cloud_trial_cost_cny:.2f}"
                f"（上限 ¥{CLOUD_TRIAL_BUDGET_CNY:.0f}，"
                f"{'通过' if report.within_trial_budget else '超限'}）"
            ),
            (
                f"本机训练：{'可行' if report.local_training_feasible else '不可行'}；"
                f"本机可部署模型：{report.deployment_model_id or '无'}"
                f"（q4 驻留 {report.deployment_ram_gb:.1f}G / 预算 2G）"
            ),
        ]
    )
    if report.effect is not None:
        lines.append(f"效果：{report.effect.summary}")
    else:
        lines.append("效果：尚无实测留出集，按报告 §5 的评测协议执行。")
    lines.append(f"决策：{report.decision} — {report.summary}")
    return "\n".join(lines)


def render_effect(effect: EffectReport) -> str:
    """渲染效果对比结果。"""
    return "\n".join(
        [
            "LoRA 效果对比（配对评分，百分制）",
            (
                f"样本 {effect.samples}：基线 {effect.baseline_mean:.2f} / "
                f"微调 {effect.tuned_mean:.2f} / 差值 {effect.delta:+.2f}"
            ),
            (
                f"胜 {effect.wins} / 平 {effect.ties} / 负 {effect.losses}，"
                f"胜率 {effect.win_rate:.0%}，p={effect.p_value:.4f}"
            ),
            f"结论：{effect.verdict} — {effect.summary}",
        ]
    )


def _load_scores(path: Path) -> list[float]:
    """读取 JSON 评分数组；允许 {"scores": [...]} 包装。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} 不是合法 JSON: {exc}") from exc

    if isinstance(payload, dict):
        payload = payload.get("scores")
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{path} 必须是评分数组，或包含 scores 数组的对象")
    return [float(value) for value in payload]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.lora_eval",
        description="个人数据 LoRA 微调预算与效果评估（M7-08）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report", help="输出预算 / 数据 / 部署可行性报告")
    report.add_argument("--db", type=Path, default=None, help="本机 SQLite 路径（自动统计收藏 / 摘要）")
    report.add_argument("--repos", type=int, default=0, help="收藏仓库数（未指定 --db 时使用）")
    report.add_argument("--summaries", type=int, default=0, help="可用 README 摘要数（未指定 --db 时使用）")
    report.add_argument("--feedback", type=int, default=0, help="反馈偏好对数")
    report.add_argument("--json", action="store_true", help="以 JSON 输出")

    compare = subparsers.add_parser("compare", help="比较基线 / 微调的配对评分")
    compare.add_argument("--baseline", type=Path, required=True, help="基线评分 JSON 数组")
    compare.add_argument("--tuned", type=Path, required=True, help="微调评分 JSON 数组")
    compare.add_argument("--min-effect", type=float, default=MIN_EFFECT, help="最小可感知差异")
    compare.add_argument("--json", action="store_true", help="以 JSON 输出")

    args = parser.parse_args(argv)

    try:
        if args.command == "report":
            if args.db is not None:
                profile = load_dataset_profile(args.db, args.feedback)
            else:
                profile = assess_dataset(args.repos, args.summaries, args.feedback)
            result = build_feasibility_report(profile)
            if args.json:
                print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            else:
                print(render_report(result))
            return 0

        if args.command == "compare":
            effect = compare_effect(
                _load_scores(args.baseline),
                _load_scores(args.tuned),
                min_effect=args.min_effect,
            )
            if args.json:
                print(json.dumps(asdict(effect), ensure_ascii=False, indent=2))
            else:
                print(render_effect(effect))
            return 0
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    return 2  # pragma: no cover - argparse 已限制


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
