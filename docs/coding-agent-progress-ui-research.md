# OpenM coding-agent progress UI research

Date: 2026-07-29

## Goal

Make a long-running coding task understandable at a glance without forcing the user
to read a raw chat transcript. The UI must answer five questions in under five seconds:

1. What is the agent doing now?
2. How far has it progressed?
3. Does it need me?
4. What changed?
5. What evidence proves the work is complete?

## Product research

### Devin

- The session UI unifies progress updates, shell commands, code edits, and browser
  activity. A progress step can be opened to see the commands that produced it.
- The redesigned session hierarchy highlights Task, Plan, PR, and Summary rather
  than treating every low-level action as equally important.
- Session Insights uses a color-coded timeline: red for high-impact issues, yellow
  for medium-impact issues, green for value delivered, and neutral colors for
  significant events.
- Interactive Planning separates assessment, detailed plan, and approval before
  execution.

Sources:

- https://docs.devin.ai/work-with-devin/devin-session-tools
- https://docs.devin.ai/product-guides/session-insights
- https://docs.devin.ai/work-with-devin/interactive-planning
- https://docs.devin.ai/release-notes/2025

### Manus

- Tasks expose a lifecycle rather than only a message stream: running, waiting,
  stopped, and error.
- Waiting is actionable and typed. The UI can distinguish a command approval,
  deploy approval, secret request, or user question.
- Actions remain visible in an audit trail and the user can stop or take over.
- Projects preserve context across tasks instead of making every task an isolated
  conversation.

Sources:

- https://open.manus.im/docs/v2/task-lifecycle
- https://manus.im/docs/features/browser-operator
- https://manus.im/docs/features/projects

### Cursor background agents

- A compact agent list optimizes for parallel work: status, searchable sessions,
  follow-up instructions, and take-over are always close at hand.
- Agents work on separate branches in isolated environments and create a clean
  hand-off to the repository.
- Follow-up messages can be queued while the current task is still running.

Sources:

- https://docs.cursor.com/background-agent
- https://docs.cursor.com/en/agent/planning

### OpenHands

- Conversation state is explicit: idle, running, paused, waiting for confirmation,
  finished, error, and stuck.
- The event log is append-only and acts as the source for monitoring and
  visualization.
- Agent Canvas emphasizes multiple parallel agents, isolated git worktrees, and a
  single visual workspace.

Sources:

- https://docs.openhands.dev/sdk/arch/conversation
- https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/state.py
- https://www.openhands.dev/product/canvas

## Design conclusions

### Information hierarchy

1. **Run state** — status, current phase, elapsed time, and attention required.
2. **Milestones** — preparation, inspection, implementation, validation, hand-off.
3. **Worklog** — grouped agent/tool/file/terminal events with timestamps.
4. **Evidence** — changed files, diff size, validation output, branch, and cost.
5. **Controls** — stop, resume, approve, deny, and follow-up.

### Interaction rules

- Never bury an approval request inside the event stream.
- Show one human-readable current action above the detailed timeline.
- Treat progress as phase completion, not as a fake token-based percentage.
- Keep raw terminal output available, but collapsed behind the meaningful step
  that produced it.
- Use semantic color sparingly: cyan for active, amber for attention, green for
  verified, red for failure.
- Preserve all low-level events for auditability.

## OpenM implementation

The progress model is derived from existing persisted events, so the backend event
log remains authoritative:

| Phase | Evidence |
| --- | --- |
| Queued | task created |
| Sandbox | `preparing` or workspace preparation event |
| Inspect | `Glob`, `Grep`, or `Read` tool event |
| Implement | file change or diff event |
| Verify | terminal/test command event |
| Deliver | completion event |

The UI uses an operations-console layout:

- left: projects and parallel task queue;
- center: run header, phase rail, attention card, and grouped worklog;
- right: changes, terminal, and run context.

This preserves the current OpenM architecture while making progress legible before
the final result exists.
