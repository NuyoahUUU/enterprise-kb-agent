from typing import Literal

from pydantic import BaseModel, Field


class OperationProposal(BaseModel):
    operation_type: Literal["create_project_conda_env"]
    title: str
    summary: str
    project_name: str
    env_name: str
    python_version: str
    cwd: str
    commands: list[str] = Field(default_factory=list)
    requires_approval: bool = True


class OperationExecuteRequest(BaseModel):
    operation: OperationProposal


class OperationStepResult(BaseModel):
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""


class OperationExecuteData(BaseModel):
    status: Literal["success", "failed"]
    operation_type: str
    project_path: str
    env_name: str
    python_version: str
    steps: list[OperationStepResult]
