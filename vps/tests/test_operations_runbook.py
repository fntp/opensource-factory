"""运维手册与诊断脚本一致性测试（REQ-202610-0945 / M5-07）。

只读文档与脚本，不访问网络、不依赖 systemd；保证运维手册的关键章节、命令、
索引链接和诊断脚本契约不会在后续迭代中漂移。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs" / "guides" / "operations-runbook.md"
DIAGNOSE = ROOT / "deploy" / "scripts" / "ops-diagnose.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runbook_exists_and_has_required_sections() -> None:
    assert RUNBOOK.is_file(), f"缺少运维手册：{RUNBOOK}"
    text = _text(RUNBOOK)
    for heading in (
        "## 3. 日常巡检 SOP",
        "## 4. 部署 SOP",
        "## 5. 升级 SOP",
        "## 6. 回滚 SOP",
        "## 7. 故障处理 SOP",
        "## 8. 备份与恢复 SOP",
        "## 9. 安全与密钥 SOP",
        "## 10. 监控与告警",
    ):
        assert heading in text, f"运维手册缺少章节：{heading}"


def test_runbook_covers_key_commands_and_decisions() -> None:
    text = _text(RUNBOOK)
    for command in (
        "deploy/scripts/deploy-all.sh",
        "deploy/scripts/preflight.sh",
        "deploy/scripts/smoke-test.sh",
        "deploy/scripts/doctor.sh",
        "deploy/scripts/resource-budget.sh",
        "deploy/scripts/ops-diagnose.sh",
        "wrangler deployments list",
        "wrangler rollback",
        "systemctl restart openfactory-api",
        "PRAGMA integrity_check",
        "wrangler d1 export",
    ):
        assert command in text, f"运维手册缺少关键命令：{command}"
    for keyword in ("P0", "P1", "P2", "P3", "回滚决策矩阵", "事故复盘模板", "变更单"):
        assert keyword in text, f"运维手册缺少关键概念：{keyword}"


def test_runbook_does_not_contain_plaintext_secrets() -> None:
    text = _text(RUNBOOK)
    patterns = (
        r"sk-[A-Za-z0-9]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"CLOUDFLARE_API_TOKEN=[A-Za-z0-9]{20,}",
        r"bwotp_[A-Za-z0-9_-]{10,}",
    )
    for pattern in patterns:
        assert not re.search(pattern, text), f"运维手册疑似包含明文密钥：{pattern}"


def test_docs_index_and_planning_links() -> None:
    docs_index = _text(ROOT / "docs" / "README.md")
    assert "operations-runbook.md" in docs_index
    assert "plan-req-202610-0945-operations-runbook.md" in docs_index

    backlog = _text(ROOT / "docs" / "requirements" / "backlog.md")
    assert "M5-07" in backlog and "REQ-202610-0945" in backlog and "已完成" in backlog

    task_planning = _text(ROOT / "docs" / "planning" / "task-planning.md")
    assert "IT-0028" in task_planning and "REQ-202610-0945" in task_planning

    roadmap = _text(ROOT / "docs" / "planning" / "roadmap.md")
    assert "运维手册" in roadmap and "2026-10-22" in roadmap


def test_ops_diagnose_script_is_read_only_and_has_help() -> None:
    assert DIAGNOSE.is_file(), f"缺少诊断脚本：{DIAGNOSE}"
    assert os.access(DIAGNOSE, os.X_OK), "ops-diagnose.sh 需要可执行权限"
    subprocess.run(["bash", "-n", str(DIAGNOSE)], check=True, capture_output=True, text=True)
    proc = subprocess.run(
        ["bash", str(DIAGNOSE), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "用法" in proc.stdout
    assert "只读" in proc.stdout
    text = _text(DIAGNOSE)
    assert "systemctl restart" not in text, "诊断脚本必须只读，不得重启服务"
    assert ".env" not in text or "不读取 .env 明文" in text


def test_ops_diagnose_no_services_smoke(tmp_path: Path) -> None:
    out = tmp_path / "diag"
    proc = subprocess.run(
        [
            "bash",
            str(DIAGNOSE),
            "--no-services",
            "--output",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(out) in proc.stdout
    assert (out / "summary.txt").is_file()
    summary = (out / "summary.txt").read_text(encoding="utf-8")
    assert "基本信息" in summary
    assert "健康检查" in summary
    assert "资源预算" in summary
