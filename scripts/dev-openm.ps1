param(
    [int]$Port = 8080,
    [string]$DataDirectory = ""
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

if (-not $DataDirectory) {
    $DataDirectory = Join-Path $RepositoryRoot ".dev-data"
}

New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null

$env:PYTHONPATH = Join-Path $RepositoryRoot "backend"
$env:DATA_DIR = $DataDirectory
if (-not $env:OPENM_AGENT_MODE) {
    $env:OPENM_AGENT_MODE = "demo"
}

# OpenM does not need the legacy RAG embedding model during agent-workspace
# development. This avoids downloading a local sentence-transformer at startup.
$env:RAG_EMBEDDING_ENGINE = "openai"
$env:RAG_OPENAI_API_BASE_URL = "http://127.0.0.1:9/v1"
$env:RAG_OPENAI_API_KEY = "disabled"
$env:ENABLE_OLLAMA_API = "false"
$env:ENABLE_OPENAI_API = "false"
$env:CORS_ALLOW_ORIGIN = "http://127.0.0.1:5173;http://localhost:5173"

$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "OpenM virtual environment is missing. Run: uv venv .venv; uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt"
}

Set-Location (Join-Path $RepositoryRoot "backend")
& $Python -m uvicorn open_webui.main:app --host 127.0.0.1 --port $Port
