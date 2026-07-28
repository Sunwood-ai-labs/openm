"""Persistence models for the OpenM coding-agent workspace."""

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, Column, Float, Integer, JSON, Text, UniqueConstraint

from open_webui.internal.db import Base, engine


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class OpenMProject(Base):
    __tablename__ = "openm_project"

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False, index=True)
    name = Column(Text, nullable=False)
    repository_url = Column(Text, nullable=False)
    default_branch = Column(Text, nullable=False, default="main")
    settings_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_openm_project_user_name"),
    )


class OpenMTask(Base):
    __tablename__ = "openm_task"

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False, index=True)
    project_id = Column(Text, nullable=False, index=True)
    parent_task_id = Column(Text, nullable=True)
    title = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="draft", index=True)
    branch_name = Column(Text, nullable=False)
    worktree_path = Column(Text, nullable=True)
    agent_session_id = Column(Text, nullable=True)
    model = Column(Text, nullable=False, default="claude-glm-code")
    max_turns = Column(Integer, nullable=False, default=40)
    max_budget = Column(Float, nullable=False, default=5.0)
    actual_cost = Column(Float, nullable=False, default=0.0)
    started_at = Column(BigInteger, nullable=True)
    completed_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)


class OpenMTaskEvent(Base):
    __tablename__ = "openm_task_event"

    id = Column(Text, primary_key=True)
    task_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(Text, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "task_id", "sequence", name="uq_openm_task_event_sequence"
        ),
    )


class OpenMPermissionRequest(Base):
    __tablename__ = "openm_permission_request"

    id = Column(Text, primary_key=True)
    task_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False, index=True)
    tool_use_id = Column(Text, nullable=False)
    tool_name = Column(Text, nullable=False)
    tool_input_json = Column(JSON, nullable=False, default=dict)
    risk_level = Column(Text, nullable=False, default="medium")
    status = Column(Text, nullable=False, default="pending", index=True)
    decision = Column(Text, nullable=True)
    decided_by = Column(Text, nullable=True)
    decided_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    repository_url: str = Field(min_length=1, max_length=2048)
    default_branch: str = Field(default="main", min_length=1, max_length=200)
    settings_json: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    repository_url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    default_branch: Optional[str] = Field(default=None, min_length=1, max_length=200)
    settings_json: Optional[dict[str, Any]] = None


class ProjectModel(BaseModel):
    id: str
    user_id: str
    name: str
    repository_url: str
    default_branch: str
    settings_json: dict[str, Any]
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=100_000)
    parent_task_id: Optional[str] = None
    model: str = Field(default="claude-glm-code", min_length=1, max_length=200)
    max_turns: int = Field(default=40, ge=1, le=500)
    max_budget: float = Field(default=5.0, ge=0, le=10_000)


class TaskModel(BaseModel):
    id: str
    user_id: str
    project_id: str
    parent_task_id: Optional[str]
    title: str
    prompt: str
    status: str
    branch_name: str
    worktree_path: Optional[str]
    agent_session_id: Optional[str]
    model: str
    max_turns: int
    max_budget: float
    actual_cost: float
    started_at: Optional[int]
    completed_at: Optional[int]
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


class TaskEventModel(BaseModel):
    id: str
    task_id: str
    sequence: int
    timestamp: int
    type: str
    data: dict[str, Any]


class PermissionDecision(BaseModel):
    decision: str
    reason: Optional[str] = Field(default=None, max_length=2000)


class PermissionModel(BaseModel):
    id: str
    task_id: str
    tool_use_id: str
    tool_name: str
    tool_input_json: dict[str, Any]
    risk_level: str
    status: str
    decision: Optional[str]
    decided_by: Optional[str]
    decided_at: Optional[int]
    created_at: int

    model_config = ConfigDict(from_attributes=True)


def ensure_openm_tables() -> None:
    """Create additive OpenM tables for installs that predate formal migrations."""

    Base.metadata.create_all(
        bind=engine,
        tables=[
            OpenMProject.__table__,
            OpenMTask.__table__,
            OpenMTaskEvent.__table__,
            OpenMPermissionRequest.__table__,
        ],
    )


def now() -> int:
    return int(time.time())
