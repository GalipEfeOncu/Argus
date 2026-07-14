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

## Intervention

The user can pause/resume/cancel a session, interrupt an individual participant, mention a participant, resolve an approval, and change session policy. The UI must immediately show a pending command state and resolve it only from a server event.

## Required states

Every screen handling a session must define empty, loading, connected, reconnecting, paused, waiting-for-approval, failed, cancelled, and completed states. The Phase 1 event simulator must exercise all of them.

## Accessibility

- Keyboard access and visible focus for all controls.
- Announced live updates without excessive screen-reader noise.
- Dialog focus traps and Escape handling.
- Sufficient text contrast and color-independent status indicators.
- Reduced-motion behavior for streaming and workflow animations.
