from pathlib import Path

import pytest

from app.schemas.operation import OperationProposal
from app.services.operation_service import OperationService


def test_builds_create_project_conda_proposal_only_with_approval_mode(tmp_path):
    service = OperationService(playground_root=tmp_path)
    question = "帮我在playground新建一个项目命名为test并创建一个新的conda虚拟环境test，安装python3.12"

    assert service.build_proposal(question, permission_mode="read_only") is None

    proposal = service.build_proposal(question, permission_mode="approve_execute")

    assert proposal["project_name"] == "test"
    assert proposal["env_name"] == "test"
    assert proposal["python_version"] == "3.12"
    assert proposal["requires_approval"] is True
    assert proposal["commands"] == [
        f"mkdir -p {tmp_path / 'test'}",
        "conda create -n test python=3.12 -y",
    ]


def test_rejects_unsafe_operation_names(tmp_path):
    service = OperationService(playground_root=tmp_path)

    with pytest.raises(ValueError, match="项目名"):
        service.execute(
            OperationProposal(
                operation_type="create_project_conda_env",
                title="bad",
                summary="bad",
                project_name="../bad",
                env_name="test",
                python_version="3.12",
                cwd=str(tmp_path),
                commands=[],
            )
        )


def test_execute_creates_project_and_runs_conda_command(monkeypatch, tmp_path):
    service = OperationService(playground_root=tmp_path)
    calls = []

    class DummyResult:
        returncode = 0
        stdout = "created"
        stderr = ""

    monkeypatch.setattr(service, "_find_conda", lambda: "/opt/conda/bin/conda")

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return DummyResult()

    monkeypatch.setattr("app.services.operation_service.subprocess.run", fake_run)

    result = service.execute(
        OperationProposal(
            operation_type="create_project_conda_env",
            title="create",
            summary="create",
            project_name="test",
            env_name="test",
            python_version="3.12",
            cwd=str(tmp_path),
            commands=[],
        )
    )

    assert (tmp_path / "test").is_dir()
    assert calls[0][0] == ["/opt/conda/bin/conda", "create", "-n", "test", "python=3.12", "-y"]
    assert calls[0][1]["cwd"] == str(Path(tmp_path).resolve())
    assert result["status"] == "success"
