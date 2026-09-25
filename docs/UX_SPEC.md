# Argus UX Specification

## Information architecture

Argus uses an evolvable three-panel desktop layout:

- **Navigation panel:** projects, sessions, history, search, and settings.
- **Shared-room panel:** ordered timeline, streaming messages, tool activity, diffs, approvals, errors, and composer.
- **Context panel:** participant roster, assignments, current status, usage, workflow, policy, and emergency controls.

The layout preserves the existing dark, high-density visual direction while prioritizing readable information hierarchy over decorative effects.

Typography uses cross-platform operating-system sans-serif and monospace stacks
through the shared design tokens. The application does not fetch fonts or font
stylesheets at startup, so the hierarchy remains available offline and within
the desktop content-security policy.

## Offline local profile

The navigation footer opens an optional profile stored only on the current
device. Before configuration it says **Set up local profile** and never shows a
fabricated person, subscription plan, or online status. After configuration it
shows initials derived from the backend-confirmed display name. The profile is
personalization, not an account or authorization boundary, and the rest of the
application remains usable without it.

The profile screen has explicit loading, unconfigured, ready, editing, saving,
and unavailable states. Loading uses a stable local skeleton without blocking
the navigation shell. Load failures provide a keyboard-accessible retry. Save
failures retain the draft while the navigation footer continues to show the
last server-confirmed value. Display-name validation is associated with the
field and focused on error; saving exposes busy state and disables duplicate
submission. The avatar uses initials and design tokens, so this flow requests no
filesystem or native image permission.

The navigation shell lists only projects and sessions returned by the local
runtime. It shows compact loading, empty, and retryable error states without
inventing sample projects, account identity, subscription status, or actions
that the runtime does not support. Selecting a project filters the durable
session list; selecting a session opens its real project/session breadcrumb.
When the local catalogue fails and no sessions are cached, the dashboard shows
the retryable error without claiming that no sessions exist. Its first-session
action opens project-session setup, matching the Coordinator and specialist
description shown beside it.

## Shared room

Messages distinguish human, Coordinator, agent, system, and tool participants. Agent output shows a concise intent or decision summary plus the resulting content. Tool calls are collapsible, correlate to the initiating participant, and link to artifacts/diffs.

The composer supports plain messages, explicit `@participant` mentions, and session commands. A human message is appended to the same ordered timeline as every other event.

The Coordinator is the default recipient when no mention is present. Specialist
messages appear in the same timeline and may be collapsed into an assignment
card, but their assignment, handoff, tool, evidence, and result events remain
inspectable. The UI must never imply a private agent conversation that is absent
from the event log.

### Direct chat

The primary **New** action opens a direct chat composer immediately. It does not
show a second choice screen and it does not create a project workspace or a
specialist team. The user may write a draft before a provider is configured;
the send action stays disabled and the screen presents one clear link to
Provider Settings. Returning from Settings preserves that draft.

When at least one provider credential and model are available, Argus creates a
projectless `chat` session using the selected provider/model reference and
opens the normal timeline. The selected reference is remembered locally for
the next direct chat; credentials remain in the operating-system credential
store and never enter browser state or session history. Direct chat uses the
same ordered event timeline and WebSocket transport as a project session, but
its Coordinator response is ordinary text and has no workspace tools.

## Session setup

The target session-configuration contract uses progressive disclosure and
provides these sections:

1. **Goal and workspace:** project, goal, workspace isolation, output language.
2. **Coordinator:** selected versioned definition, model, prompt override, and
   local-skill trust/capability review. Imported skills visibly start disabled;
   the user explicitly enables a reviewed package before assigning it.
3. **Available team:** versioned agent instances (including custom capability-based roles) the Coordinator is permitted to use.
4. **Required roles:** zero or more completion gates, each with success evidence
   and `always`, `when_changes`, or `when_capability_used` applicability.
5. **Limits:** revision, assignment attempt, model iteration, tool call, token,
   cost, wall-clock, and parallel read-only limits. Each value shows its unit,
   default, whether zero disables work, and whether blank means unlimited.
6. **Approvals:** permission profile, approval behavior, pre-authorized
   capabilities, and limit-resolution mode.
7. **Review:** a plain-language summary of who may run, who must run, when the
   app can interrupt, and what remains forbidden.

Coordinator cannot be disabled. Selecting a required role automatically prompts
the user to add an eligible agent to the available team. Invalid or internally
contradictory configurations cannot start.

The current production Alpha setup deliberately exposes a narrower five-part
inspection flow: inspection goal and workspace, Coordinator, read-only
specialist pool, applicable execution limits, and authority review. It fixes
workspace mode to an isolated worktree, allows at most one specialist assignment
per Coordinator turn, and limits workspace tools to the intersection of the
immutable definition allowlist and `read_file`, `list_dir`, and `search_files`.
The UI does not expose presets, skills, required gates, mutation, direct-write,
test or shell authority, capability overrides, or session pre-authorization
until those production worker paths exist. The broader configuration contract
remains reserved for later runtime capabilities; the current setup normalizes
every submitted snapshot to the narrower Alpha authority.

Role editing creates a new definition version rather than mutating a running
session. The runtime snapshots the selected definition's capabilities, tool
allowlist, permission profile, evidence contract, and output language before
the session starts; session-only overrides may narrow those declarations but
cannot expand them.

## Provider settings

Provider settings list a provider name, preset, endpoint, model catalogue, and
whether a credential is configured. Adding a provider uses a masked,
non-autocompleted field; after saving, the typed value is cleared and never
appears in application state or browser storage. API-key providers require the
Tauri desktop client and its operating-system credential store; the web
development client must explain this boundary instead of showing a generic
save failure. Ollama is a local, no-key preset. Model discovery is optional and
may report that a credential is unavailable or that a capability is unknown.
Users can enter an explicit model ID, but the UI must present unknown
tools/structured-output support as unsupported until the runtime can confirm it.

The last selected provider/model reference for direct chat is remembered as a
non-secret local preference. An unconfigured provider is a blocking send
condition, not a reason to discard the user's draft.

Presets (`Quick`, `Balanced`, `Thorough`, and `Custom`) populate fields but do
not hide their resolved values. Changing any resolved value marks the preset as
Custom.

## Runtime status and decisions

The context panel groups participants as Available, Active, Waiting, and Done.
It separately displays required gates, remaining budgets, current writer, active
grants, and the next likely Coordinator action. A fixed emergency control keeps
Pause and Cancel reachable without scrolling.

Limit warnings identify the counter, current value, threshold, affected
assignment, and configured response. When the Coordinator is allowed to decide,
its visible decision card shows one of: reassign, change approach, deliver
partial, or stop. It includes evidence and remaining budget, but not private
reasoning.

`completed` requires all applicable required gates. `completed_partial` clearly
lists unmet gates, limits reached, skipped verification, and how the user can
resume in a new assignment or session.

## Local diagnostics and degraded mode

The context panel provides a compact, keyboard-accessible local diagnostics
section. It shows runtime health plus bounded queue, lease, provider-latency,
event-lag, and usage facts on demand. A provider outage, low disk space,
database lock, corrupt event, unavailable credential store, or unavailable
sidecar becomes a clear degraded-state alert with a safe next action; it never
pretends a request was retried or a mutation completed.

Users can explicitly download a redacted support bundle. Its visible privacy
note states that it contains only configuration shapes, event summaries, and
redacted diagnostics—not credentials, raw prompts, private reasoning, project
paths, or project file contents. A support export must not silently include
project data.

## Diff review and acceptance

At a completed or human-accepted partial result, the context panel provides one
keyboard-accessible review card. It lists a bounded changed-file tree, artifact
evidence, validated and unmet gates, limit history, normalized usage, and the
visible Coordinator summary. The card clearly distinguishes a completed result
from one with unmet gates.

Apply, reject, export patch, and start-follow-up are explicit human actions.
Before apply or reject, the user chooses whether to retain or clean up the
isolated workspace; retain is the safe default. Apply remains disabled until
the server confirms the current policy/grant, writer availability, and original
project checksum. If the original project drifted, the UI explains that no
files were written and offers patch export, retained-workspace review, reject,
or a fresh follow-up session rather than an automatic merge. Action status is
visible and refreshed from the durable server result.

## Intervention

The user can pause/resume/cancel a session, interrupt an individual participant,
mention a participant, resolve an approval, and change future limits, team, gate,
or permission policy. The UI must immediately show a pending command state and
resolve it only from a server event. A change that would invalidate active work
requires a consequence preview and is applied by the scheduler, never only in
client state.

## Required states

Every screen handling a session must define empty, loading, connected,
reconnecting, paused, waiting-for-approval, waiting-for-decision,
completed-partial, failed, cancelled, and completed states. The event simulator
must exercise all of them, including required-gate failure and a no-prompt
session.

## Accessibility

- Keyboard access and visible focus for all controls.
- Announced live updates without excessive screen-reader noise.
- Dialog focus traps and Escape handling.
- Sufficient text contrast and color-independent status indicators.
- Reduced-motion behavior for streaming and workflow animations.

The application applies reduced-motion suppression globally, exposes sidecar
recovery as a native keyboard-operable control, and checks semantic text/status
tokens against WCAG AA contrast thresholds. Automated structural checks and the
10,000-event DOM bound complement, but do not replace, native keyboard-only and
screen-reader pairing smoke tests described in
[Desktop platform support](PLATFORM_SUPPORT.md).

## Responsiveness and perceived performance

- Show the native window and functional navigation shell without waiting for the
  Python sidecar, provider discovery, session history, or syntax highlighter.
- Use stable skeletons only where persisted data is still loading; never block
  the entire window with a splash screen after the shell can accept input.
- Sending a message, Pause, Cancel, approval, and decision actions show local
  pending feedback within the interaction budget, then resolve only from events.
- Virtualize long timelines, file trees, and diffs while preserving keyboard
  navigation, focus restoration, find/jump behavior, and live-region semantics.
- Load syntax highlighting, large diff content, tool details, and old timeline
  pages on demand. Preserve plain-text/code readability while an enhancement is
  loading or unavailable.
- Streaming updates are visually batched without losing persisted tokens. Do not
  auto-scroll when the user has moved away from the latest event; show an
  inexpensive unread-count control instead.
- Animations use transform/opacity where possible, stop off-screen, respect
  reduced motion, and never communicate state by motion alone.
- Sidecar startup, idle shutdown, and transparent restart have explicit compact
  states; they must not freeze navigation or discard a drafted prompt.

When an idle native sidecar stops, the shell remains navigable. The next live
session transport attempt restarts it and reconnects from the last confirmed
sequence; the composer draft remains in the mounted shell throughout this
cycle. Sidecar idleness is permitted only when no active session, pending
approval or decision, tool/provider work, writer lease, recovery work, or live
room connection remains.
