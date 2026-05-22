import re
import shutil
import subprocess
from pathlib import Path

from app.config import BASE_DIR
from app.schemas.operation import OperationProposal


PLAYGROUND_ROOT = BASE_DIR.parent
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PYTHON_VERSION_PATTERN = re.compile(r"^(?:3\.12(?:\.\d+)?)$")


class OperationService:
    """Build and execute user-approved local operations."""

    def __init__(self, playground_root: Path = PLAYGROUND_ROOT):
        self.playground_root = playground_root.resolve()

    def build_proposal(self, question: str, permission_mode: str = "read_only") -> dict | None:
        if permission_mode != "approve_execute":
            return None
        if not self._looks_like_project_conda_request(question):
            return None

        project_name = self._extract_project_name(question)
        env_name = self._extract_env_name(question) or project_name
        python_version = self._extract_python_version(question) or "3.12"
        if not project_name or not env_name:
            return None

        self._validate_name(project_name, "项目名")
        self._validate_name(env_name, "环境名")
        self._validate_python_version(python_version)

        project_path = self.playground_root / project_name
        proposal = OperationProposal(
            operation_type="create_project_conda_env",
            title=f"创建项目 {project_name} 并配置 conda 环境",
            summary=(
                f"将在 {self.playground_root} 下创建项目目录 {project_name}，"
                f"并创建 conda 环境 {env_name}，Python 版本为 {python_version}。"
            ),
            project_name=project_name,
            env_name=env_name,
            python_version=python_version,
            cwd=str(self.playground_root),
            commands=[
                f"mkdir -p {project_path}",
                f"conda create -n {env_name} python={python_version} -y",
            ],
        )
        return proposal.model_dump()

    def execute(self, proposal: OperationProposal) -> dict:
        if proposal.operation_type != "create_project_conda_env":
            raise ValueError(f"不支持的操作类型: {proposal.operation_type}")
        self._validate_name(proposal.project_name, "项目名")
        self._validate_name(proposal.env_name, "环境名")
        self._validate_python_version(proposal.python_version)

        project_path = (self.playground_root / proposal.project_name).resolve()
        if self.playground_root not in project_path.parents and project_path != self.playground_root:
            raise ValueError("项目路径必须位于 Playground 目录下")

        steps = []
        project_path.mkdir(parents=True, exist_ok=True)
        steps.append(
            {
                "command": f"mkdir -p {project_path}",
                "returncode": 0,
                "stdout": f"项目目录已准备: {project_path}",
                "stderr": "",
            }
        )

        conda = self._find_conda()
        result = subprocess.run(
            [conda, "create", "-n", proposal.env_name, f"python={proposal.python_version}", "-y"],
            cwd=str(self.playground_root),
            capture_output=True,
            text=True,
            timeout=900,
        )
        steps.append(
            {
                "command": f"conda create -n {proposal.env_name} python={proposal.python_version} -y",
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            }
        )

        return {
            "status": "success" if result.returncode == 0 else "failed",
            "operation_type": proposal.operation_type,
            "project_path": str(project_path),
            "env_name": proposal.env_name,
            "python_version": proposal.python_version,
            "steps": steps,
        }

    def _looks_like_project_conda_request(self, question: str) -> bool:
        lowered = question.lower()
        return (
            ("项目" in question or "project" in lowered)
            and ("conda" in lowered or "虚拟环境" in question or "环境" in question)
            and "python" in lowered
        )

    def _extract_project_name(self, question: str) -> str | None:
        patterns = [
            r"项目(?:命名为|名为|叫做|叫|为)?\s*([A-Za-z0-9_-]+)",
            r"新建(?:一个)?(?:名为|叫做)?\s*([A-Za-z0-9_-]+)\s*项目",
            r"create\s+(?:a\s+)?project\s+(?:named\s+)?([A-Za-z0-9_-]+)",
        ]
        return self._extract_first(question, patterns)

    def _extract_env_name(self, question: str) -> str | None:
        patterns = [
            r"(?:conda)?(?:虚拟)?环境(?:命名为|名为|叫做|叫|为)?\s*([A-Za-z0-9_-]+)",
            r"conda\s+(?:env|environment)\s+(?:named\s+)?([A-Za-z0-9_-]+)",
        ]
        return self._extract_first(question, patterns)

    def _extract_python_version(self, question: str) -> str | None:
        match = re.search(r"python\s*=?\s*([0-9]+(?:\.[0-9]+){1,2})", question, re.I)
        return match.group(1) if match else None

    def _extract_first(self, question: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, question, re.I)
            if match:
                return match.group(1)
        return None

    def _validate_name(self, value: str, label: str) -> None:
        if not NAME_PATTERN.match(value):
            raise ValueError(f"{label}只能包含字母、数字、下划线和短横线，且必须以字母或数字开头")

    def _validate_python_version(self, version: str) -> None:
        if not PYTHON_VERSION_PATTERN.match(version):
            raise ValueError("当前批准执行只允许创建 Python 3.12 系列环境")

    def _find_conda(self) -> str:
        import os
        # 优先使用 CONDA_EXE 环境变量
        conda_exe = os.environ.get("CONDA_EXE")
        if conda_exe and Path(conda_exe).exists():
            return conda_exe
        conda = shutil.which("conda")
        if conda:
            return conda
        for fallback in ("/opt/anaconda3/bin/conda", "/opt/homebrew/bin/conda",
                         "/usr/local/anaconda3/bin/conda", "/usr/local/miniconda3/bin/conda"):
            if Path(fallback).exists():
                return fallback
        raise ValueError("未找到 conda 命令，无法创建 conda 环境")
