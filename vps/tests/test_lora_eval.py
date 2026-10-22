"""LoRA 微调评估测试（REQ-202610-0967）。

全部用例离线执行，不依赖 GPU / torch / 网络。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.services.lora_eval import (
    CLOUD_TRIAL_BUDGET_CNY,
    MIN_SAMPLES,
    RECOMMENDED_SAMPLES,
    TrainingConfig,
    assess_dataset,
    build_feasibility_report,
    compare_effect,
    estimate_training,
    load_dataset_profile,
    main,
    render_report,
)


def test_dataset_levels() -> None:
    empty = assess_dataset(0, 0, 0)
    assert empty.level == "insufficient"
    assert not empty.meets_minimum

    minimum = assess_dataset(120, 400, 100)
    assert minimum.usable_samples == 500
    assert minimum.level == "minimum"
    assert minimum.meets_minimum
    assert not minimum.meets_recommended

    recommended = assess_dataset(500, 1800, 200)
    assert recommended.usable_samples == 2000
    assert recommended.level == "recommended"
    assert recommended.meets_recommended


def test_dataset_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        assess_dataset(-1, 0, 0)


def test_load_dataset_profile_from_sqlite(tmp_path) -> None:
    db = tmp_path / "factory.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE my_repositories (id TEXT, readme_summary TEXT)")
    connection.executemany(
        "INSERT INTO my_repositories VALUES (?, ?)",
        [("1", "摘要一"), ("2", "摘要二"), ("3", ""), ("4", None)],
    )
    connection.commit()
    connection.close()

    profile = load_dataset_profile(db, feedback_pairs=3)
    assert profile.repositories == 4
    assert profile.summaries == 2
    assert profile.feedback_pairs == 3
    assert profile.usable_samples == 5
    assert profile.level == "insufficient"


def test_load_dataset_profile_handles_missing_table(tmp_path) -> None:
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    profile = load_dataset_profile(db)
    assert profile.repositories == 0
    assert profile.summaries == 0
    assert profile.level == "insufficient"


def test_load_dataset_profile_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(ValueError):
        load_dataset_profile(tmp_path / "missing.db")


def test_local_cpu_training_is_not_feasible() -> None:
    estimate = estimate_training(
        TrainingConfig(model_id="qwen2.5-1.5b", gpu_id="cpu-local", samples=500)
    )
    assert not estimate.fits_gpu
    assert not estimate.viable
    assert "不可训练" in estimate.summary


def test_cloud_1_5b_training_fits_budget() -> None:
    estimate = estimate_training(
        TrainingConfig(model_id="qwen2.5-1.5b", gpu_id="rtx4090-24g", samples=500)
    )
    assert estimate.fits_gpu
    assert estimate.viable
    assert estimate.tokens_total == 1_200_000
    assert estimate.steps == 94
    assert estimate.cost_cny < CLOUD_TRIAL_BUDGET_CNY
    assert estimate.fits_local_inference
    assert estimate.trainable_params == 9_633_792


def test_7b_training_fits_gpu_but_not_local_inference_budget() -> None:
    estimate = estimate_training(
        TrainingConfig(model_id="qwen2.5-7b", gpu_id="rtx4090-24g", samples=2000)
    )
    assert estimate.fits_gpu
    assert estimate.viable
    assert not estimate.fits_local_inference
    assert estimate.trainable_params == 22_478_848


def test_unknown_model_or_gpu_is_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_training(TrainingConfig(model_id="unknown"))
    with pytest.raises(ValueError):
        estimate_training(TrainingConfig(gpu_id="unknown"))


def test_invalid_training_config() -> None:
    with pytest.raises(ValueError):
        estimate_training(TrainingConfig(samples=0))
    with pytest.raises(ValueError):
        estimate_training(TrainingConfig(epochs=0))
    with pytest.raises(ValueError):
        estimate_training(TrainingConfig(batch_size=0))


def test_compare_effect_detects_significant_improvement() -> None:
    baseline = [70.0] * 100
    tuned = [76.0] * 100
    report = compare_effect(baseline, tuned)

    assert report.wins == 100
    assert report.losses == 0
    assert report.delta == 6.0
    assert report.significant
    assert report.verdict == "improved"
    assert report.p_value < 0.05


def test_compare_effect_without_difference_is_not_significant() -> None:
    baseline = [70.0, 80.0, 90.0, 60.0]
    tuned = [72.0, 78.0, 91.0, 59.0]
    report = compare_effect(baseline, tuned)

    assert report.wins == 2
    assert report.losses == 2
    assert report.delta == 0.0
    assert not report.significant
    assert report.verdict == "no_significant_difference"


def test_compare_effect_detects_regression() -> None:
    report = compare_effect([80.0] * 50, [70.0] * 50)
    assert report.significant
    assert report.verdict == "regressed"
    assert report.delta < 0


def test_compare_effect_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        compare_effect([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        compare_effect([], [])
    with pytest.raises(ValueError):
        compare_effect([float("nan")], [1.0])


def test_report_decisions() -> None:
    empty = build_feasibility_report(assess_dataset(0, 0, 0))
    assert empty.decision == "collect_data"
    assert not empty.local_training_feasible
    assert empty.within_trial_budget
    assert empty.deployment_model_id == "qwen2.5-1.5b"

    ready = build_feasibility_report(assess_dataset(200, MIN_SAMPLES, 0))
    assert ready.decision == "cloud_trial"

    effect = compare_effect([70.0] * 100, [78.0] * 100)
    pilot = build_feasibility_report(assess_dataset(200, MIN_SAMPLES, 0), effect)
    assert pilot.decision == "pilot"


def test_report_mentions_budget_and_deployment() -> None:
    text = render_report(build_feasibility_report(assess_dataset(0, 0, 0)))
    assert "云端 1.5B 试验预算" in text
    assert "本机可部署模型：qwen2.5-1.5b" in text
    assert "决策：collect_data" in text


def test_cli_report_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["report", "--repos", "10", "--summaries", "5", "--feedback", "2", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"]["usable_samples"] == 7
    assert payload["decision"] == "collect_data"
    assert payload["scenarios"][0]["estimate"]["gpu_id"] == "cpu-local"


def test_cli_report_from_db(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "factory.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE my_repositories (id TEXT, readme_summary TEXT)")
    connection.execute("INSERT INTO my_repositories VALUES ('1', '摘要')")
    connection.commit()
    connection.close()

    code = main(["report", "--db", str(db), "--feedback", "4", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"]["repositories"] == 1
    assert payload["dataset"]["summaries"] == 1
    assert payload["dataset"]["usable_samples"] == 5


def test_cli_compare_with_files(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    tuned = tmp_path / "tuned.json"
    baseline.write_text(json.dumps([60.0] * 60), encoding="utf-8")
    tuned.write_text(json.dumps([70.0] * 60), encoding="utf-8")

    code = main(["compare", "--baseline", str(baseline), "--tuned", str(tuned), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "improved"
    assert payload["samples"] == 60


def test_cli_rejects_invalid_scores(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    code = main(["compare", "--baseline", str(bad), "--tuned", str(bad)])
    assert code == 2
    assert "不是合法 JSON" in capsys.readouterr().err


def test_recommended_samples_constant_is_above_minimum() -> None:
    assert RECOMMENDED_SAMPLES > MIN_SAMPLES
