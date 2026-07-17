# Argus Product Definition

## Vision

Argus makes multi-agent software development inspectable and controllable. The
user gives a goal to a visible Coordinator; the Coordinator delegates bounded
assignments to a user-approved team while every meaningful action remains in one
shared room.

## Audience

Developers and small engineering teams who want model/provider flexibility, local project control, and visibility that conventional black-box coding assistants do not provide.

## Primary journey

1. Select a local project.
2. Configure providers, the available agent pool, required roles, execution
   limits, approval behavior, and workspace policy.
3. Give the goal to the Coordinator in the shared room.
4. Watch the Coordinator create assignments, route work, request revisions, and
   invoke required quality gates within the configured team.
5. Intervene with a message, mention, pause, policy decision, participant
   interrupt, or cancellation whenever desired.
6. Review the Coordinator's outcome, evidence, limits reached, and isolated diff.

## Product decisions

- The Coordinator is the default conversational participant and is present in
  every executable session.
- The user selects an **available agent pool**. The Coordinator may use any
  member of that pool when useful and may never silently invoke an excluded
  agent.
- The user may mark pool members as **required roles**. A successful session
  must obtain the required role's completion evidence unless the user changes
  the configuration or explicitly accepts a partial result.
- Agent selection is dynamic, not a fixed Planner-to-Builder-to-Reviewer chain.
  Simple work may use one specialist; complex work may create a bounded tree of
  assignments and revisions.
- The Coordinator is visible and explains routing, handoffs, limit decisions,
  and the final outcome in concise messages.
- Agents expose outputs, action summaries, tool use, diffs, assignments, and handoffs; raw private reasoning is not a transparency requirement.
- The shared room remains the ordered source of collaboration truth. A focused
  view may collapse specialist detail, but it must not create a second hidden
  conversation.
- Users can customize revision, token, tool, duration, cost, concurrency, and
  approval behavior at session creation and through auditable runtime updates.
- A no-interruption mode may pre-authorize policy-allowed work until a terminal
  outcome. It never overrides non-bypassable safety denials.
- At a configured loop or revision limit, the Coordinator may choose among
  allowed recovery actions—reassign within the pool, change approach without
  exceeding the hard limit, deliver the best partial result, or stop with an
  explanation. The deterministic runtime enforces the limit.
- Built-in roles are customizable; custom capability-based roles are first-class.
- Skills are local, validated packages in the MVP. A marketplace is not.
- The default is a balanced, worktree-isolated policy. Users may choose strict, autonomous, or explicitly acknowledged unrestricted modes.
- English is the default technical and agent-output language; users may override output language per session or role.
- Argus is a lightweight desktop tool, not a browser tab wrapped with a bundled
  browser. It uses the operating system webview, starts the visible shell before
  the orchestration runtime is ready, and loads expensive editors, syntax
  highlighting, providers, and agent workers only when needed.
- Windows, macOS, and Linux are equal release targets. A feature is not complete
  when it works on only the developer's platform.
- Responsiveness and resource use are release contracts. Regressions in startup,
  idle CPU, memory, shipped frontend assets, installer size, or long-timeline
  interaction fail the corresponding phase gate.

## MVP success criteria

- A user can complete a project-scoped task by talking to the Coordinator, with
  either automatic specialist selection or a user-restricted team.
- Available and required roles are enforced in the backend and visible in the UI.
- Configurable limits and approval behavior survive reconnect and restart and
  produce deterministic, auditable outcomes.
- The user can observe every user-visible operation in order and intervene while work is running.
- A mutating task is isolated, reviewable as a diff, and recoverable after restart or disconnect.
- A user can customize a built-in role, import a local skill package, and create one custom role without code changes.
- On reference hardware the window becomes interactive within the performance
  budgets in [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md), remains responsive
  with a 10,000-event session, and consumes negligible CPU while idle.
- Signed native installers pass the same core Coordinator workflow on supported
  Windows, macOS, and Linux targets.

## Non-goals

The MVP excludes cloud sync, remote multi-user collaboration, billing,
telemetry, a skill marketplace, a visual workflow editor, arbitrary model-made
permission escalation, and concurrent mutating sessions on the same project.
