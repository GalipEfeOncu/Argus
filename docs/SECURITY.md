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

Every grant is durable but bounded: it records the requested capability, a
canonical workspace-relative scope, grant kind (`once`, `scope`, or `session`),
expiry, and the configuration policy hash that authorized it. A grant is
revoked when its policy hash becomes stale; a once grant is consumed atomically
with the request it authorizes. A human resolution may only grant the exact
pending capability and scope, never a Coordinator-supplied expansion.

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

## Local skill packages

Local skill package files are untrusted model context, not executable policy.
Import accepts only a non-symlink local directory, rejects traversal and all
symbolic links inside it, validates every manifest reference, and copies the
validated UTF-8 contents into SQLite with content hashes. The runtime never
uses the source directory after import, so a later filesystem change cannot
alter a running session. Packages begin disabled and require an explicit trust
review enablement. Their declared tools and permissions must be subsets of the
target session agent's already-snapshotted authority; package instructions,
including prompt-injection text, cannot grant tools, permissions, or alter
session policy.

## Provider credentials

The Settings webview may submit a newly typed credential only to a Tauri command
that writes it to the operating-system credential service. It never stores a
provider key in Zustand, browser storage, SQLite, agent/session snapshots, or
the public provider REST contract. SQLite holds an opaque credential reference
only. A random token is injected into the sidecar process at launch; the Tauri
process uses it to resolve the OS-store entry and pass a five-minute in-memory
credential lease to that exact local sidecar. Neither the webview nor a normal
REST caller can resolve a reference. Provider failures and discovery errors are
normalized summaries, never SDK or HTTP exception bodies.

Workspace paths are canonicalized before registration and every tool target is
resolved relative to the selected session workspace. Parent traversal and
symbolic-link paths are denied. Shell execution accepts an argument vector, not
a shell expression; destructive commands and shell interpreters are denied and
credential-like environment variables are not forwarded. Commands that can run
project-controlled code (tests, package scripts, build tools) require an
OS-level workspace sandbox; when that sandbox is unavailable they are denied
rather than run unsandboxed. Lease acquisition, renewal, expiry recovery, and
release are durable audit records.

After a backend or sidecar restart, no previously in-memory writer lease or
capacity reservation remains live. The runtime releases those abandoned guards,
rebuilds projections from immutable events, and recovers worker checkpoints.
An interrupted mutating tool or provider request is recorded as an unknown
outcome and cannot be retried merely because its response was lost. A later
retry must pass the usual scheduler, budget, workspace, and approval checks.

## Local diagnostics and support exports

Runtime observability records bounded, process-local structured logs using
redacted event names and metadata. Request bodies, headers, query values,
credentials, raw prompts/messages, private reasoning, project paths, and file
contents are not diagnostic-log fields. Health and support-bundle endpoints are
read-only and cannot resolve credential-store references or trigger provider,
tool, workspace, or retry actions.

The desktop shell may probe whether the operating-system credential service can
create an entry, but that probe never reads, writes, or exposes a credential.

Support bundles contain only configuration shapes, event-type counts, and
redacted runtime/log metadata. They exclude all credential material (including
references), raw prompt/message text, private reasoning, project paths, event
payload bodies, and project file contents. Export is an explicit user action;
there is no automatic upload or telemetry path.

## Applying reviewed work

Only a human acceptance action may copy an isolated worktree or snapshot back
to the registered original project. The backend requires terminal session
state, current `original_project.write` authority, a session writer lease, a bounded
text patch preflight, and a compare-and-swap checksum of the original project
captured before workspace creation. Source drift, binary/oversized changes,
missing baselines, direct-write mode, or a failed preflight fail closed: no
automatic merge or write occurs. The user may export the patch or retain the
isolated workspace for manual conflict resolution. Cleanup is an explicit,
audited user choice; a crash during apply is marked unknown and never replayed.

## Reporting

Until a dedicated security contact is published, report vulnerabilities privately to the repository owner and do not include exploitable details in public issues.
