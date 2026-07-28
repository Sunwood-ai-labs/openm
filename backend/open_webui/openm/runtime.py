"""Background task executor for demo and Claude Agent SDK modes."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func

from open_webui.internal.db import get_db
from open_webui.models.openm import (
    OpenMPermissionRequest,
    OpenMProject,
    OpenMTask,
    OpenMTaskEvent,
    new_id,
    now,
)
from open_webui.openm.config import (
    OPENM_AGENT_MODE,
    OPENM_DEFAULT_MAIN_MODEL,
    OPENM_LITELLM_BASE_URL,
    OPENM_LITELLM_TOKEN,
    OPENM_MAX_CONCURRENT_TASKS,
    OPENM_PERMISSION_TIMEOUT_SECONDS,
)
from open_webui.openm.sandbox import (
    SandboxError,
    changed_files,
    git_diff,
    prepare_task_worktree,
)


log = logging.getLogger(__name__)


class OpenMTaskExecutor:
    def __init__(self) -> None:
        self._running: dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(OPENM_MAX_CONCURRENT_TASKS)

    def schedule(self, task_id: str, user_id: str) -> bool:
        running = self._running.get(task_id)
        if running and not running.done():
            return False
        job = asyncio.create_task(self._run_guarded(task_id, user_id))
        self._running[task_id] = job
        job.add_done_callback(lambda _: self._running.pop(task_id, None))
        return True

    def cancel(self, task_id: str) -> bool:
        running = self._running.get(task_id)
        if not running or running.done():
            return False
        running.cancel()
        return True

    async def _run_guarded(self, task_id: str, user_id: str) -> None:
        async with self._semaphore:
            try:
                await self._run(task_id, user_id)
            except asyncio.CancelledError:
                self._set_status(task_id, user_id, "cancelled")
                raise
            except Exception as error:
                log.exception("OpenM task %s failed", task_id)
                self._fail_task(task_id, user_id, str(error))

    async def _run(self, task_id: str, user_id: str) -> None:
        task, project = self._load_task_and_project(task_id, user_id)
        if task.status not in {"queued", "preparing"}:
            return

        self._set_status(task_id, user_id, "preparing")
        self._append_event(
            task_id,
            user_id,
            "agent.text.delta",
            {"text": "ユーザー専用Sandboxを準備しています。"},
        )
        worktree = await asyncio.to_thread(
            prepare_task_worktree,
            user_id,
            project.id,
            task.id,
            project.repository_url,
            project.default_branch,
            task.branch_name,
        )
        self._set_worktree(task_id, user_id, worktree)
        self._set_status(task_id, user_id, "running")

        if OPENM_AGENT_MODE == "live":
            await self._run_claude_agent(task_id, user_id, worktree)
        else:
            await self._run_demo_agent(task_id, user_id, worktree)

    async def _run_demo_agent(self, task_id: str, user_id: str, worktree: Path) -> None:
        task, _ = self._load_task_and_project(task_id, user_id)
        self._append_event(
            task_id,
            user_id,
            "agent.text.delta",
            {
                "text": (
                    "指示を確認しました。まずリポジトリ構成を調べ、"
                    "影響範囲を限定して実装します。"
                )
            },
        )
        await asyncio.sleep(0.5)
        self._append_event(
            task_id,
            user_id,
            "agent.tool.requested",
            {"tool": "Glob", "input": {"pattern": "**/*"}},
        )
        self._append_event(
            task_id,
            user_id,
            "agent.tool.result",
            {"tool": "Glob", "summary": "Repository index loaded"},
        )
        await asyncio.sleep(0.5)

        artifact = worktree / "OPENM_DEMO_RESULT.md"
        artifact.write_text(
            "\n".join(
                [
                    "# OpenM Demo Agent Result",
                    "",
                    f"Task: {task.title}",
                    "",
                    task.prompt,
                    "",
                    "This file proves that the task-specific Git worktree is writable.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self._append_event(
            task_id,
            user_id,
            "agent.file.changed",
            {"path": "OPENM_DEMO_RESULT.md", "operation": "created"},
        )
        self._append_diff_event(task_id, user_id, worktree)

        decision = await self._request_permission(
            task_id,
            user_id,
            tool_use_id=new_id("tool"),
            tool_name="Bash",
            tool_input={"command": "git diff --check"},
            risk_level="medium",
        )
        if decision == "deny":
            raise RuntimeError("User denied the validation command")

        self._set_status(task_id, user_id, "running")
        self._append_event(
            task_id,
            user_id,
            "agent.terminal.output",
            {
                "command": "git diff --check",
                "output": "No whitespace errors",
                "exit_code": 0,
            },
        )
        self._append_event(
            task_id,
            user_id,
            "agent.text.delta",
            {
                "text": (
                    "変更を作成し、worktreeの差分検証まで完了しました。"
                    "右側のChangesで成果を確認できます。"
                )
            },
        )
        self._complete_task(task_id, user_id, cost=0.0)

    async def _run_claude_agent(
        self, task_id: str, user_id: str, worktree: Path
    ) -> None:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            PermissionResultAllow,
            PermissionResultDeny,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            query,
        )

        task, _ = self._load_task_and_project(task_id, user_id)

        async def can_use_tool(tool_name, tool_input, context):
            risk = (
                "high" if tool_name in {"Bash", "WebFetch", "WebSearch"} else "medium"
            )
            decision = await self._request_permission(
                task_id,
                user_id,
                tool_use_id=context.tool_use_id or new_id("tool"),
                tool_name=tool_name,
                tool_input=tool_input,
                risk_level=risk,
            )
            if decision in {"allow_once", "allow_for_task"}:
                return PermissionResultAllow(updated_input=tool_input)
            return PermissionResultDeny(
                message="The user denied this operation in OpenM.", interrupt=False
            )

        options = ClaudeAgentOptions(
            model=task.model,
            fallback_model=OPENM_DEFAULT_MAIN_MODEL,
            cwd=str(worktree),
            tools=["Read", "Glob", "Grep", "Edit", "Write", "Bash"],
            allowed_tools=["Read", "Glob", "Grep", "Edit", "Write"],
            disallowed_tools=[],
            permission_mode="default",
            can_use_tool=can_use_tool,
            max_turns=task.max_turns,
            max_budget_usd=task.max_budget,
            enable_file_checkpointing=True,
            env={
                "ANTHROPIC_BASE_URL": OPENM_LITELLM_BASE_URL,
                "ANTHROPIC_AUTH_TOKEN": OPENM_LITELLM_TOKEN,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": task.model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": OPENM_DEFAULT_MAIN_MODEL,
                "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
            },
        )

        async for message in query(prompt=task.prompt, options=options):
            if isinstance(message, SystemMessage):
                session_id = message.data.get("session_id")
                if session_id:
                    self._set_session(task_id, user_id, session_id)

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        self._append_event(
                            task_id,
                            user_id,
                            "agent.text.delta",
                            {"text": block.text},
                        )
                    elif isinstance(block, ToolUseBlock):
                        self._append_event(
                            task_id,
                            user_id,
                            "agent.tool.requested",
                            {
                                "tool": block.name,
                                "input": block.input,
                                "tool_use_id": block.id,
                            },
                        )
                    elif isinstance(block, ToolResultBlock):
                        self._append_event(
                            task_id,
                            user_id,
                            "agent.tool.result",
                            {
                                "tool_use_id": block.tool_use_id,
                                "content": block.content,
                                "is_error": block.is_error,
                            },
                        )

            if isinstance(message, ResultMessage):
                if message.session_id:
                    self._set_session(task_id, user_id, message.session_id)
                if message.is_error:
                    raise RuntimeError(message.result or "Agent SDK returned an error")
                self._append_diff_event(task_id, user_id, worktree)
                self._complete_task(
                    task_id,
                    user_id,
                    cost=float(message.total_cost_usd or 0.0),
                )
                return

    async def _request_permission(
        self,
        task_id: str,
        user_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        risk_level: str,
    ) -> str:
        request_id = new_id("perm")
        with get_db() as db:
            request = OpenMPermissionRequest(
                id=request_id,
                task_id=task_id,
                user_id=user_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input_json=tool_input,
                risk_level=risk_level,
                status="pending",
                created_at=now(),
            )
            db.add(request)
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if not task:
                raise RuntimeError("Task disappeared while requesting permission")
            previous = task.status
            task.status = "waiting_permission"
            task.updated_at = now()
            self._append_event_in_session(
                db,
                task,
                "agent.permission.required",
                {
                    "request_id": request_id,
                    "tool": tool_name,
                    "input": tool_input,
                    "risk_level": risk_level,
                },
            )
            self._append_event_in_session(
                db,
                task,
                "task.status.changed",
                {"from": previous, "to": "waiting_permission"},
            )
            db.commit()

        deadline = asyncio.get_running_loop().time() + OPENM_PERMISSION_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            with get_db() as db:
                request = (
                    db.query(OpenMPermissionRequest)
                    .filter_by(id=request_id, task_id=task_id, user_id=user_id)
                    .first()
                )
                if request and request.status == "decided":
                    return request.decision or "deny"
        raise TimeoutError("Permission request timed out")

    def _load_task_and_project(
        self, task_id: str, user_id: str
    ) -> tuple[OpenMTask, OpenMProject]:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if not task:
                raise RuntimeError("Task not found")
            project = (
                db.query(OpenMProject)
                .filter_by(id=task.project_id, user_id=user_id)
                .first()
            )
            if not project:
                raise RuntimeError("Project not found")
            db.expunge(task)
            db.expunge(project)
            return task, project

    def _set_status(self, task_id: str, user_id: str, next_status: str) -> None:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return
            previous = task.status
            if previous == next_status:
                return
            task.status = next_status
            task.updated_at = now()
            if next_status == "running" and not task.started_at:
                task.started_at = task.updated_at
            if next_status in {"cancelled", "succeeded", "failed", "timed_out"}:
                task.completed_at = task.updated_at
            self._append_event_in_session(
                db,
                task,
                "task.status.changed",
                {"from": previous, "to": next_status},
            )
            db.commit()

    def _set_worktree(self, task_id: str, user_id: str, worktree: Path) -> None:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if task:
                task.worktree_path = str(worktree)
                task.updated_at = now()
                db.commit()

    def _set_session(self, task_id: str, user_id: str, session_id: str) -> None:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if task:
                task.agent_session_id = session_id
                task.updated_at = now()
                db.commit()

    def _complete_task(self, task_id: str, user_id: str, cost: float) -> None:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return
            previous = task.status
            task.status = "succeeded"
            task.actual_cost = cost
            task.completed_at = now()
            task.updated_at = task.completed_at
            self._append_event_in_session(
                db,
                task,
                "task.status.changed",
                {"from": previous, "to": "succeeded"},
            )
            self._append_event_in_session(
                db,
                task,
                "agent.completed",
                {"cost_usd": cost},
            )
            db.commit()

    def _fail_task(self, task_id: str, user_id: str, message: str) -> None:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return
            previous = task.status
            task.status = "failed"
            task.completed_at = now()
            task.updated_at = task.completed_at
            self._append_event_in_session(
                db,
                task,
                "task.status.changed",
                {"from": previous, "to": "failed"},
            )
            self._append_event_in_session(
                db,
                task,
                "agent.failed",
                {"message": message[:4000]},
            )
            db.commit()

    def _append_diff_event(self, task_id: str, user_id: str, worktree: Path) -> None:
        try:
            diff = git_diff(worktree)
            files = changed_files(worktree)
        except SandboxError as error:
            self._append_event(
                task_id,
                user_id,
                "agent.tool.result",
                {"tool": "Git", "is_error": True, "content": str(error)},
            )
            return
        self._append_event(
            task_id,
            user_id,
            "agent.diff.updated",
            {
                "files": files,
                "file_count": len(files),
                "diff": diff[:250_000],
            },
        )

    def _append_event(
        self, task_id: str, user_id: str, event_type: str, data: dict | None = None
    ) -> None:
        with get_db() as db:
            task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
            if task:
                self._append_event_in_session(db, task, event_type, data)
                db.commit()

    @staticmethod
    def _append_event_in_session(
        db,
        task: OpenMTask,
        event_type: str,
        data: dict | None = None,
    ) -> None:
        sequence = (
            db.query(func.max(OpenMTaskEvent.sequence))
            .filter_by(task_id=task.id)
            .scalar()
            or 0
        ) + 1
        db.add(
            OpenMTaskEvent(
                id=new_id("evt"),
                task_id=task.id,
                user_id=task.user_id,
                sequence=sequence,
                event_type=event_type,
                payload_json=json.loads(json.dumps(data or {}, default=str)),
                created_at=now(),
            )
        )


executor = OpenMTaskExecutor()


def schedule_task(task_id: str, user_id: str) -> bool:
    return executor.schedule(task_id, user_id)


def cancel_running_task(task_id: str) -> bool:
    return executor.cancel(task_id)
