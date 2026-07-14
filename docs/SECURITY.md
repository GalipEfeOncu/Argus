# Argus Security Model

## Scope

Argus runs model-selected work against local projects. That makes provider credentials, filesystem access, shell execution, and unintended changes the primary security concerns.

## Defaults

- Use a session-specific git worktree and branch when possible.
- Restrict tools to the session workspace.
- Store provider credentials in the operating-system credential store; persist references only.
- Treat all tool requests as structured, auditable events.
- Do not emit secrets in logs, events, exports, errors, or SQLite payloads.
- Use a project-level writer lock and a per-session writer lease.

## Permission profiles

| Profile | Behavior |
| --- | --- |
| Strict | Request approval for every tool action. |
| Balanced | Auto-allow reads, search, and safe diagnostics; request scope approval before writes, dependency changes, networked commands, risky shell commands, and git mutations. |
| Autonomous | Allow workspace-scoped actions automatically. |
| Expert unrestricted | Require an explicit acknowledgement before allowing unrestricted execution. |

Users can override a decision once, for a bounded scope, or for a session. Policy changes are themselves recorded as events.

## Enforcement

The backend, not an agent prompt, enforces workspace bounds, command policy, approval state, timeouts, and cancellation. Prompts must not be treated as a security boundary.

## Reporting

Until a dedicated security contact is published, report vulnerabilities privately to the repository owner and do not include exploitable details in public issues.
