# Argus UX Specification

## Information architecture

Argus uses an evolvable three-panel desktop layout:

- **Navigation panel:** projects, sessions, history, search, and settings.
- **Shared-room panel:** ordered timeline, streaming messages, tool activity, diffs, approvals, errors, and composer.
- **Context panel:** participant roster, assignments, current status, usage, workflow, policy, and emergency controls.

The layout preserves the existing dark, high-density visual direction while prioritizing readable information hierarchy over decorative effects.

## Shared room

Messages distinguish human, Coordinator, agent, system, and tool participants. Agent output shows a concise intent or decision summary plus the resulting content. Tool calls are collapsible, correlate to the initiating participant, and link to artifacts/diffs.

The composer supports plain messages, explicit `@participant` mentions, and session commands. A human message is appended to the same ordered timeline as every other event.

The Coordinator is the default recipient when no mention is present. Specialist
messages appear in the same timeline and may be collapsed into an assignment
card, but their assignment, handoff, tool, evidence, and result events remain
inspectable. The UI must never imply a private agent conversation that is absent
from the event log.

## Session setup

Session creation uses progressive disclosure and provides these sections:

1. **Goal and workspace:** project, goal, workspace isolation, output language.
2. **Coordinator:** model, prompt override, and enabled skills.
3. **Available team:** agent instances the Coordinator is permitted to use.
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
