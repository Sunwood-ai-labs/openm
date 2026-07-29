# OpenM v0.1.0 Release QA Inventory

## Release Context

- repository: `Sunwood-ai-labs/openm`
- release tag: `v0.1.0`
- compare range: `90ff3c9de9cf4f622f60ad2d9daf2aed0016b15f..12b7b73feca7f3573b721892cf160833c6d9c6b6`
- base context: the lower bound imports a tree identical to upstream Open WebUI `v0.6.5`
- requested outputs: GitHub release body, repository release notes, companion setup walkthrough
- validation commands run: `git diff --check`; `$env:PYTHONPATH = 'backend'; .venv\Scripts\python.exe -m pytest backend/open_webui/test/openm -q`; `npm run build`; `docker compose --env-file .env.openm.example -f docker-compose.openm.yaml config --quiet`; live browser validation recorded in `docs/openm-validation.md`
- release URL: `https://github.com/Sunwood-ai-labs/openm/releases/tag/v0.1.0`
- published at: `2026-07-29T13:00:28Z`

## Claim Matrix

| claim | code refs | validation refs | docs surfaces touched | scope |
| --- | --- | --- | --- | --- |
| Users have persistent workspaces and tasks execute in dedicated Git worktrees | `backend/open_webui/openm/sandbox.py`, `backend/open_webui/openm/runtime.py`, `backend/open_webui/routers/openm.py` | OpenM pytest suite; live write and diff check in `docs/openm-validation.md` | `README.md`, `docs/openm-specification.md`, `docs/releases/v0.1.0.md`, `docs/guides/openm-v0.1.0-walkthrough.md` | OpenM task runtime |
| Claude Agent SDK text and task events stream incrementally over authenticated SSE | `backend/open_webui/openm/runtime.py`, `backend/open_webui/routers/openm.py`, `src/lib/apis/openm/index.ts`, `src/routes/(app)/openm/+page.svelte` | 47 incremental response updates and completed-message check in `docs/openm-validation.md`; production build | `docs/openm-specification.md`, `docs/openm-validation.md`, `docs/releases/v0.1.0.md` | OpenM task page |
| Tool permission requests support one-time allow, task-scoped allow, and deny | `backend/open_webui/openm/runtime.py`, `backend/open_webui/routers/openm.py`, `src/routes/(app)/openm/+page.svelte` | OpenM pytest suite; code-path inspection | `docs/openm-specification.md`, `docs/releases/v0.1.0.md`, `docs/guides/openm-v0.1.0-walkthrough.md` | Claude Agent SDK tool requests |
| The bundled LiteLLM aliases route Claude-compatible requests to GLM 4.5 Flash | `config/litellm.yaml`, `docker-compose.openm.yaml` | Compose configuration validation; implementation inspection | `README.md`, `docs/openm-specification.md`, `docs/releases/v0.1.0.md`, `docs/guides/openm-v0.1.0-walkthrough.md` | bundled v0.1.0 Compose configuration |
| Final agent replies render through the inherited Open WebUI Markdown component | `src/routes/(app)/openm/+page.svelte` | Markdown DOM check in `docs/openm-validation.md`; production build | `docs/openm-validation.md`, `docs/releases/v0.1.0.md` | OpenM final-answer surface |

## Steady-State Docs Review

| surface | status | evidence |
| --- | --- | --- |
| `README.md` | pass | Added the v0.1.0 release pointer and links to both release documents |
| `docs/openm-specification.md` | pass | Synchronized SSE behavior, SDK event mapping, and actual LiteLLM model routing |
| `docs/openm-validation.md` | pass | Recorded live SDK/GLM streaming, file-change, Markdown DOM, and mobile checks |
| `docs/releases/v0.1.0.md` | pass | Added implementation-backed release notes, setup, validation, and known scope |
| `docs/guides/openm-v0.1.0-walkthrough.md` | pass | Added the GLM setup and first live file-writing workflow |

## QA Inventory

| criterion_id | status | evidence |
| --- | --- | --- |
| compare_range | pass | Reviewed the OpenM delta from the Open WebUI v0.6.5-equivalent import at `90ff3c9d` through tagged commit `12b7b73f` |
| release_claims_backed | pass | Claims are mapped to implementation and validation evidence in the Claim Matrix |
| docs_release_notes | pass | `docs/releases/v0.1.0.md` |
| companion_walkthrough | pass | `docs/guides/openm-v0.1.0-walkthrough.md` |
| operator_claims_extracted | pass | Runtime, streaming, permissions, model routing, and Markdown claims are listed above |
| impl_sensitive_claims_verified | pass | Runtime, router, frontend, Compose, and LiteLLM configuration paths were inspected |
| steady_state_docs_reviewed | pass | All operator-facing surfaces reviewed are listed above |
| claim_scope_precise | pass | Claims are limited to the OpenM task surface and the bundled single-host v0.1.0 configuration |
| latest_release_links_updated | pass | `README.md` links to the v0.1.0 GitHub Release and both release documents |
| svg_assets_validated | not_applicable | No versioned OpenM SVG release artwork exists; the inherited embedded-raster favicon is not suitable release artwork |
| docs_assets_committed_before_tag | pass | Release notes and walkthrough were committed in `12b7b73f` before the annotated tag was created |
| docs_deployed_live | not_applicable | This repository has no separate docs deployment; both canonical GitHub document URLs were verified with HTTP 200 |
| tag_local_remote | pass | Local and origin `v0.1.0` both peel to `12b7b73feca7f3573b721892cf160833c6d9c6b6` |
| github_release_verified | pass | GitHub Release is public, non-draft, non-prerelease, titled `OpenM v0.1.0 — Initial Release`, and returns HTTP 200 |
| validation_commands_recorded | pass | Commands and browser evidence are recorded in Release Context |
| publish_date_verified | pass | GitHub API reports `publishedAt` as `2026-07-29T13:00:28Z` |

## Notes

- blockers: none
- waivers: none
- follow-up docs tasks: add versioned OpenM SVG release artwork if a formal visual identity is introduced
