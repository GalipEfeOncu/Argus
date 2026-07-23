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

## Approval behavior

Approval behavior is separate from orchestration limits. A session chooses one
of these behaviors and may add capability-specific overrides:

| Behavior | Runtime effect |
| --- | --- |
| `ask_each_time` | Ask for every otherwise-allowable capability request. |
| `ask_by_policy` | Use the selected permission profile and request only actions requiring approval. |
| `preauthorize_session` | Pre-authorize selected workspace-scoped capabilities for the session; run without interruption while they remain in scope. |
| `deny_interactive` | Never open an approval prompt; deny requests not already allowed and let the Coordinator adapt or stop. |

`preauthorize_session` is the supported “do not ask until the task is done”
mode. Before starting, the UI displays the exact capability and workspace scope,
requires acknowledgement for Autonomous or Expert unrestricted access, and
persists the resulting grant. Lack of a prompt never means implicit approval.

The following are non-bypassable in Strict, Balanced, and Autonomous modes:

- access outside the resolved session workspace;
- known secret extraction or credential disclosure;
- destructive host-level operations;
- silently writing the original project when a worktree or snapshot was chosen;
- an agent expanding its own pool, limits, tools, or permissions.

Expert unrestricted may expose additional operations only after explicit user
acknowledgement and per-command confirmation where the permission matrix
requires it. Coordinator initiative cannot satisfy a human confirmation.

## Policy updates and precedence

The backend evaluates requests in this order: non-bypassable denial, workspace
scope, session permission profile, capability override, stored grant, approval
behavior. The most restrictive applicable result wins. Updates affect future
actions only, use an idempotent command, and emit the old and new policy hashes.
Reducing authority immediately cancels or interrupts newly disallowed work;
increasing authority never retries an operation without a new scheduler action.

## Enforcement

The backend, not an agent prompt, enforces agent-pool membership, required-role
eligibility, workspace bounds, command policy, approval state, budgets,
timeouts, and cancellation. Prompts must not be treated as a security boundary.

Workspace paths are canonicalized before registration and every tool target is
resolved relative to the selected session workspace. Parent traversal and
symbolic-link paths are denied. Shell execution accepts an argument vector, not
a shell expression; destructive commands and shell interpreters are denied and
credential-like environment variables are not forwarded. Commands that can run
project-controlled code (tests, package scripts, build tools) require an
OS-level workspace sandbox; when that sandbox is unavailable they are denied
rather than run unsandboxed. Lease acquisition, renewal, expiry recovery, and
release are durable audit records.

## Reporting

Until a dedicated security contact is published, report vulnerabilities privately to the repository owner and do not include exploitable details in public issues.
