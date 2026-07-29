"""Authenticated OpenM project, task, event, and permission APIs."""

import asyncio
import json
import re
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from open_webui.internal.db import get_db
from open_webui.models.openm import (
    OpenMPermissionRequest,
    OpenMProject,
    OpenMTask,
    OpenMTaskEvent,
    PermissionDecision,
    PermissionModel,
    ProjectCreate,
    ProjectModel,
    ProjectUpdate,
    TaskCreate,
    TaskEventModel,
    TaskModel,
    ensure_openm_tables,
    new_id,
    now,
)
from open_webui.openm.runtime import cancel_running_task, schedule_task
from open_webui.utils.auth import get_verified_user


router = APIRouter()
ensure_openm_tables()

TERMINAL_STATUSES = {"cancelled", "succeeded", "failed", "timed_out", "archived"}
VALID_PERMISSION_DECISIONS = {"allow_once", "allow_for_task", "deny"}


def _project_or_404(db, project_id: str, user_id: str) -> OpenMProject:
    project = db.query(OpenMProject).filter_by(id=project_id, user_id=user_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _task_or_404(db, task_id: str, user_id: str) -> OpenMTask:
    task = db.query(OpenMTask).filter_by(id=task_id, user_id=user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _branch_name(task_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:42] or "task"
    return f"openm/{task_id.removeprefix('task_')[:8]}-{slug}"


def append_task_event(
    db,
    task: OpenMTask,
    event_type: str,
    data: Optional[dict] = None,
) -> OpenMTaskEvent:
    sequence = (
        db.query(func.max(OpenMTaskEvent.sequence)).filter_by(task_id=task.id).scalar()
        or 0
    ) + 1
    event = OpenMTaskEvent(
        id=new_id("evt"),
        task_id=task.id,
        user_id=task.user_id,
        sequence=sequence,
        event_type=event_type,
        payload_json=data or {},
        created_at=now(),
    )
    db.add(event)
    # Make the assigned sequence visible to subsequent event appends in the
    # same transaction (for example permission + status events).
    db.flush()
    return event


def _event_model(event: OpenMTaskEvent) -> TaskEventModel:
    return TaskEventModel(
        id=event.id,
        task_id=event.task_id,
        sequence=event.sequence,
        timestamp=event.created_at,
        type=event.event_type,
        data=event.payload_json or {},
    )


@router.get("/dashboard")
def get_dashboard(user=Depends(get_verified_user)):
    with get_db() as db:
        projects = (
            db.query(OpenMProject)
            .filter_by(user_id=user.id)
            .order_by(OpenMProject.updated_at.desc())
            .all()
        )
        tasks = (
            db.query(OpenMTask)
            .filter_by(user_id=user.id)
            .order_by(OpenMTask.updated_at.desc())
            .all()
        )
        counts = Counter(task.status for task in tasks)
        return {
            "projects": len(projects),
            "tasks": len(tasks),
            "running": counts["running"],
            "waiting_permission": counts["waiting_permission"],
            "completed": counts["succeeded"],
            "failed": counts["failed"],
            "sandbox": {
                "status": "ready",
                "isolation": "user",
                "active_tasks": counts["running"],
            },
            "recent_projects": [
                ProjectModel.model_validate(project) for project in projects[:5]
            ],
            "recent_tasks": [TaskModel.model_validate(task) for task in tasks[:10]],
        }


@router.get("/projects", response_model=list[ProjectModel])
def list_projects(user=Depends(get_verified_user)):
    with get_db() as db:
        return [
            ProjectModel.model_validate(project)
            for project in db.query(OpenMProject)
            .filter_by(user_id=user.id)
            .order_by(OpenMProject.updated_at.desc())
            .all()
        ]


@router.post(
    "/projects",
    response_model=ProjectModel,
    status_code=status.HTTP_201_CREATED,
)
def create_project(form: ProjectCreate, user=Depends(get_verified_user)):
    timestamp = now()
    project = OpenMProject(
        id=new_id("prj"),
        user_id=user.id,
        name=form.name.strip(),
        repository_url=form.repository_url.strip(),
        default_branch=form.default_branch.strip(),
        settings_json=form.settings_json,
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        with get_db() as db:
            db.add(project)
            db.commit()
            db.refresh(project)
            return ProjectModel.model_validate(project)
    except IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="A project with this name already exists"
        ) from error


@router.get("/projects/{project_id}", response_model=ProjectModel)
def get_project(project_id: str, user=Depends(get_verified_user)):
    with get_db() as db:
        return ProjectModel.model_validate(_project_or_404(db, project_id, user.id))


@router.patch("/projects/{project_id}", response_model=ProjectModel)
def update_project(
    project_id: str,
    form: ProjectUpdate,
    user=Depends(get_verified_user),
):
    with get_db() as db:
        project = _project_or_404(db, project_id, user.id)
        updates = form.model_dump(exclude_none=True)
        for key, value in updates.items():
            setattr(project, key, value.strip() if isinstance(value, str) else value)
        project.updated_at = now()
        try:
            db.commit()
        except IntegrityError as error:
            raise HTTPException(
                status_code=409, detail="A project with this name already exists"
            ) from error
        db.refresh(project)
        return ProjectModel.model_validate(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, user=Depends(get_verified_user)):
    with get_db() as db:
        project = _project_or_404(db, project_id, user.id)
        has_tasks = (
            db.query(OpenMTask.id)
            .filter_by(project_id=project.id, user_id=user.id)
            .first()
        )
        if has_tasks:
            raise HTTPException(
                status_code=409,
                detail="Archive or delete project tasks before deleting the project",
            )
        db.delete(project)
        db.commit()


@router.get("/tasks", response_model=list[TaskModel])
def list_tasks(
    project_id: Optional[str] = None,
    task_status: Optional[str] = Query(default=None, alias="status"),
    user=Depends(get_verified_user),
):
    with get_db() as db:
        query = db.query(OpenMTask).filter_by(user_id=user.id)
        if project_id:
            query = query.filter_by(project_id=project_id)
        if task_status:
            query = query.filter_by(status=task_status)
        return [
            TaskModel.model_validate(task)
            for task in query.order_by(OpenMTask.updated_at.desc()).all()
        ]


@router.post("/tasks", response_model=TaskModel, status_code=status.HTTP_201_CREATED)
async def create_task(form: TaskCreate, user=Depends(get_verified_user)):
    with get_db() as db:
        _project_or_404(db, form.project_id, user.id)
        if form.parent_task_id:
            _task_or_404(db, form.parent_task_id, user.id)
        timestamp = now()
        task_id = new_id("task")
        task = OpenMTask(
            id=task_id,
            user_id=user.id,
            project_id=form.project_id,
            parent_task_id=form.parent_task_id,
            title=form.title.strip(),
            prompt=form.prompt.strip(),
            status="queued",
            branch_name=_branch_name(task_id, form.title),
            model=form.model,
            max_turns=form.max_turns,
            max_budget=form.max_budget,
            actual_cost=0.0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(task)
        append_task_event(
            db,
            task,
            "task.status.changed",
            {"from": "draft", "to": "queued"},
        )
        db.commit()
        db.refresh(task)
        schedule_task(task.id, user.id)
        return TaskModel.model_validate(task)


@router.get("/tasks/{task_id}", response_model=TaskModel)
def get_task(task_id: str, user=Depends(get_verified_user)):
    with get_db() as db:
        return TaskModel.model_validate(_task_or_404(db, task_id, user.id))


@router.post("/tasks/{task_id}/cancel", response_model=TaskModel)
async def cancel_task(task_id: str, user=Depends(get_verified_user)):
    cancel_running_task(task_id)
    with get_db() as db:
        task = _task_or_404(db, task_id, user.id)
        if task.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="Task is already terminal")
        previous = task.status
        task.status = "cancelled"
        task.completed_at = now()
        task.updated_at = task.completed_at
        append_task_event(
            db,
            task,
            "task.status.changed",
            {"from": previous, "to": "cancelled"},
        )
        append_task_event(db, task, "agent.cancelled")
        db.commit()
        db.refresh(task)
        return TaskModel.model_validate(task)


@router.post("/tasks/{task_id}/resume", response_model=TaskModel)
async def resume_task(task_id: str, user=Depends(get_verified_user)):
    with get_db() as db:
        task = _task_or_404(db, task_id, user.id)
        if task.status not in {"cancelled", "failed", "timed_out", "waiting_user"}:
            raise HTTPException(status_code=409, detail="Task cannot be resumed")
        previous = task.status
        task.status = "queued"
        task.started_at = None
        task.completed_at = None
        task.updated_at = now()
        append_task_event(
            db,
            task,
            "task.status.changed",
            {"from": previous, "to": "queued"},
        )
        db.commit()
        db.refresh(task)
        schedule_task(task.id, user.id)
        return TaskModel.model_validate(task)


@router.post("/tasks/{task_id}/retry", response_model=TaskModel)
async def retry_task(task_id: str, user=Depends(get_verified_user)):
    with get_db() as db:
        original = _task_or_404(db, task_id, user.id)
        if original.status not in TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409, detail="Only terminal tasks can be retried"
            )
        timestamp = now()
        retry_id = new_id("task")
        retry = OpenMTask(
            id=retry_id,
            user_id=user.id,
            project_id=original.project_id,
            parent_task_id=original.id,
            title=f"Retry: {original.title}",
            prompt=original.prompt,
            status="queued",
            branch_name=_branch_name(retry_id, original.title),
            model=original.model,
            max_turns=original.max_turns,
            max_budget=original.max_budget,
            actual_cost=0.0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(retry)
        append_task_event(
            db,
            retry,
            "task.status.changed",
            {"from": "draft", "to": "queued", "retry_of": original.id},
        )
        db.commit()
        db.refresh(retry)
        schedule_task(retry.id, user.id)
        return TaskModel.model_validate(retry)


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventModel])
def list_task_events(
    task_id: str,
    after: int = Query(default=0, ge=0),
    user=Depends(get_verified_user),
):
    with get_db() as db:
        _task_or_404(db, task_id, user.id)
        events = (
            db.query(OpenMTaskEvent)
            .filter(
                OpenMTaskEvent.task_id == task_id,
                OpenMTaskEvent.user_id == user.id,
                OpenMTaskEvent.sequence > after,
            )
            .order_by(OpenMTaskEvent.sequence.asc())
            .all()
        )
        return [_event_model(event) for event in events]


@router.get("/tasks/{task_id}/events/stream")
async def stream_task_events(
    request: Request,
    task_id: str,
    after: int = Query(default=0, ge=0),
    user=Depends(get_verified_user),
):
    with get_db() as db:
        _task_or_404(db, task_id, user.id)

    async def event_stream():
        cursor = after
        idle_ticks = 0
        while not await request.is_disconnected():
            with get_db() as db:
                task = _task_or_404(db, task_id, user.id)
                task_status = task.status
                task_events = (
                    db.query(OpenMTaskEvent)
                    .filter(
                        OpenMTaskEvent.task_id == task_id,
                        OpenMTaskEvent.user_id == user.id,
                        OpenMTaskEvent.sequence > cursor,
                    )
                    .order_by(OpenMTaskEvent.sequence.asc())
                    .all()
                )
                payloads = [
                    _event_model(event).model_dump(mode="json") for event in task_events
                ]

            if payloads:
                idle_ticks = 0
                for payload in payloads:
                    cursor = max(cursor, int(payload["sequence"]))
                    yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                idle_ticks += 1

            if task_status in TERMINAL_STATUSES and not payloads:
                yield f"event: done\ndata: {json.dumps({'status': task_status})}\n\n"
                return

            if idle_ticks >= 20:
                idle_ticks = 0
                yield ": keepalive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/tasks/{task_id}/permissions",
    response_model=list[PermissionModel],
)
def list_permissions(task_id: str, user=Depends(get_verified_user)):
    with get_db() as db:
        _task_or_404(db, task_id, user.id)
        return [
            PermissionModel.model_validate(request)
            for request in db.query(OpenMPermissionRequest)
            .filter_by(task_id=task_id, user_id=user.id)
            .order_by(OpenMPermissionRequest.created_at.desc())
            .all()
        ]


@router.post(
    "/tasks/{task_id}/permissions/{request_id}",
    response_model=PermissionModel,
)
def decide_permission(
    task_id: str,
    request_id: str,
    form: PermissionDecision,
    user=Depends(get_verified_user),
):
    if form.decision not in VALID_PERMISSION_DECISIONS:
        raise HTTPException(status_code=422, detail="Invalid permission decision")
    with get_db() as db:
        task = _task_or_404(db, task_id, user.id)
        request = (
            db.query(OpenMPermissionRequest)
            .filter_by(id=request_id, task_id=task_id, user_id=user.id)
            .first()
        )
        if not request:
            raise HTTPException(status_code=404, detail="Permission request not found")
        if request.status != "pending":
            raise HTTPException(status_code=409, detail="Permission already decided")
        request.status = "decided"
        request.decision = form.decision
        request.decided_by = user.id
        request.decided_at = now()
        append_task_event(
            db,
            task,
            "agent.permission.decided",
            {
                "request_id": request.id,
                "decision": form.decision,
                "reason": form.reason,
            },
        )
        if task.status == "waiting_permission":
            task.status = "queued" if form.decision != "deny" else "failed"
            task.updated_at = now()
        db.commit()
        db.refresh(request)
        return PermissionModel.model_validate(request)
