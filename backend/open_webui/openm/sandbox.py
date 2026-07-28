"""User-isolated workspace and Git worktree lifecycle."""

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from open_webui.openm.config import (
    OPENM_ALLOW_LOCAL_REPOSITORIES,
    OPENM_WORKSPACE_ROOT,
)


class SandboxError(RuntimeError):
    pass


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^a-zA-Z0-9_.-]", "_", value)
    if not segment or segment in {".", ".."}:
        raise SandboxError("Invalid workspace identifier")
    return segment[:160]


def _inside(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise SandboxError("Workspace path escaped its isolation root") from error
    return resolved_candidate


def user_workspace(user_id: str) -> Path:
    path = OPENM_WORKSPACE_ROOT / _safe_segment(user_id)
    path.mkdir(parents=True, exist_ok=True)
    for name in ("projects", "worktrees", "artifacts", "cache", "skills"):
        (path / name).mkdir(exist_ok=True)
    return path


def project_repository(user_id: str, project_id: str) -> Path:
    root = user_workspace(user_id)
    return _inside(root, root / "projects" / _safe_segment(project_id) / "repo")


def task_worktree(user_id: str, task_id: str) -> Path:
    root = user_workspace(user_id)
    return _inside(root, root / "worktrees" / _safe_segment(task_id))


def _validate_repository_url(repository_url: str) -> None:
    parsed = urlparse(repository_url)
    if parsed.scheme in {"https", "ssh"}:
        if parsed.password:
            raise SandboxError("Repository URLs must not contain passwords")
        return
    if repository_url.startswith("git@"):
        return
    if OPENM_ALLOW_LOCAL_REPOSITORIES:
        local_path = Path(repository_url).expanduser()
        if local_path.exists():
            return
    raise SandboxError("Only HTTPS or SSH Git repository URLs are allowed")


def _git(*args: str, cwd: Path | None = None, timeout: int = 180) -> str:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise SandboxError(message or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def ensure_project_clone(
    user_id: str,
    project_id: str,
    repository_url: str,
    default_branch: str,
) -> Path:
    _validate_repository_url(repository_url)
    repo = project_repository(user_id, project_id)
    repo.parent.mkdir(parents=True, exist_ok=True)

    if not (repo / ".git").exists():
        if any(repo.iterdir()) if repo.exists() else False:
            raise SandboxError("Project repository directory is not empty")
        _git(
            "clone",
            "--depth",
            "1",
            "--branch",
            default_branch,
            "--single-branch",
            repository_url,
            str(repo),
            timeout=600,
        )
    else:
        remote = _git("remote", "get-url", "origin", cwd=repo)
        if remote != repository_url:
            raise SandboxError("Existing clone remote does not match the project")
        _git("fetch", "--prune", "origin", default_branch, cwd=repo, timeout=300)

    return repo


def prepare_task_worktree(
    user_id: str,
    project_id: str,
    task_id: str,
    repository_url: str,
    default_branch: str,
    branch_name: str,
) -> Path:
    repo = ensure_project_clone(user_id, project_id, repository_url, default_branch)
    worktree = task_worktree(user_id, task_id)

    if worktree.exists() and (worktree / ".git").exists():
        return worktree
    if worktree.exists() and any(worktree.iterdir()):
        raise SandboxError("Task worktree directory is not empty")

    worktree.parent.mkdir(parents=True, exist_ok=True)
    base_ref = f"origin/{default_branch}"
    existing_branch = _git("branch", "--list", branch_name, cwd=repo)
    if existing_branch:
        _git("worktree", "add", str(worktree), branch_name, cwd=repo, timeout=300)
    else:
        _git(
            "worktree",
            "add",
            "-b",
            branch_name,
            str(worktree),
            base_ref,
            cwd=repo,
            timeout=300,
        )
    return worktree


def git_diff(worktree: Path) -> str:
    return _git("diff", "--no-ext-diff", "--", cwd=worktree)


def changed_files(worktree: Path) -> list[str]:
    output = _git("status", "--short", cwd=worktree)
    return [line[3:] for line in output.splitlines() if len(line) > 3]
