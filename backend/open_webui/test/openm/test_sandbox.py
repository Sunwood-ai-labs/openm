import subprocess
from pathlib import Path

import pytest

from open_webui.openm import sandbox


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def origin_repository(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-b", "main")
    git(origin, "config", "user.name", "OpenM Test")
    git(origin, "config", "user.email", "openm@example.invalid")
    (origin / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(origin, "add", "README.md")
    git(origin, "commit", "-m", "initial")
    return origin


def test_task_worktrees_are_isolated_per_user_and_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    origin_repository: Path,
) -> None:
    monkeypatch.setattr(sandbox, "OPENM_WORKSPACE_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(sandbox, "OPENM_ALLOW_LOCAL_REPOSITORIES", True)

    first = sandbox.prepare_task_worktree(
        "user-a",
        "project-a",
        "task-a",
        str(origin_repository),
        "main",
        "openm/task-a",
    )
    second = sandbox.prepare_task_worktree(
        "user-a",
        "project-a",
        "task-b",
        str(origin_repository),
        "main",
        "openm/task-b",
    )
    other_user = sandbox.prepare_task_worktree(
        "user-b",
        "project-a",
        "task-a",
        str(origin_repository),
        "main",
        "openm/user-b-task-a",
    )

    assert first != second
    assert first != other_user
    assert (first / ".git").exists()
    assert (second / ".git").exists()
    assert (other_user / ".git").exists()

    (first / "only-in-first.txt").write_text("isolated", encoding="utf-8")
    assert not (second / "only-in-first.txt").exists()
    assert not (other_user / "only-in-first.txt").exists()
    assert sandbox.changed_files(first) == ["only-in-first.txt"]


def test_repository_url_rejects_embedded_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox, "OPENM_ALLOW_LOCAL_REPOSITORIES", False)
    with pytest.raises(sandbox.SandboxError, match="must not contain passwords"):
        sandbox._validate_repository_url("https://user:secret@example.com/repo.git")


def test_workspace_identifier_cannot_escape_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sandbox, "OPENM_WORKSPACE_ROOT", tmp_path / "workspaces")
    workspace = sandbox.user_workspace("../../outside")
    assert workspace.is_relative_to(tmp_path / "workspaces")
