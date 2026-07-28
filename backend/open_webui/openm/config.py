"""Environment-backed OpenM runtime configuration."""

import os
from pathlib import Path

from open_webui.env import DATA_DIR


OPENM_WORKSPACE_ROOT = Path(
    os.environ.get("OPENM_WORKSPACE_ROOT", str(Path(DATA_DIR) / "openm-workspaces"))
).resolve()
OPENM_AGENT_MODE = os.environ.get("OPENM_AGENT_MODE", "demo").strip().lower()
OPENM_LITELLM_BASE_URL = os.environ.get(
    "OPENM_LITELLM_BASE_URL", "http://litellm:4000"
).rstrip("/")
OPENM_LITELLM_TOKEN = os.environ.get("OPENM_LITELLM_TOKEN", "")
OPENM_DEFAULT_MODEL = os.environ.get("OPENM_DEFAULT_MODEL", "claude-glm-code")
OPENM_DEFAULT_MAIN_MODEL = os.environ.get("OPENM_DEFAULT_MAIN_MODEL", "claude-glm-main")
OPENM_MAX_CONCURRENT_TASKS = int(os.environ.get("OPENM_MAX_CONCURRENT_TASKS", "2"))
OPENM_PERMISSION_TIMEOUT_SECONDS = int(
    os.environ.get("OPENM_PERMISSION_TIMEOUT_SECONDS", "600")
)
OPENM_ALLOW_LOCAL_REPOSITORIES = (
    os.environ.get("OPENM_ALLOW_LOCAL_REPOSITORIES", "false").lower() == "true"
)

if OPENM_AGENT_MODE not in {"demo", "live"}:
    raise ValueError("OPENM_AGENT_MODE must be either 'demo' or 'live'")

OPENM_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
