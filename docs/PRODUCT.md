# Argus Product Definition

## Vision

Argus makes multi-agent software development inspectable and controllable. A user chooses models and local projects; a visible team of agents collaborates in one room; the user can intervene at every meaningful point.

## Audience

Developers and small engineering teams who want model/provider flexibility, local project control, and visibility that conventional black-box coding assistants do not provide.

## Primary journey

1. Select a local project.
2. Choose a safety policy, providers, roles, and skills.
3. Describe work in the shared room.
4. Watch the Coordinator assign work and agents discuss, inspect, edit, review, and test.
5. Intervene with a message, mention, pause, policy decision, or cancellation.
6. Review and accept the isolated changes.

## Product decisions

- The Coordinator is visible and explains routing in concise messages.
- Agents expose outputs, action summaries, tool use, diffs, assignments, and handoffs; raw private reasoning is not a transparency requirement.
- Built-in roles are customizable; custom capability-based roles are first-class.
- Skills are local, validated packages in the MVP. A marketplace is not.
- The default is a balanced, worktree-isolated policy. Users may choose strict, autonomous, or explicitly acknowledged unrestricted modes.
- English is the default technical and agent-output language; users may override output language per session or role.

## MVP success criteria

- A user can complete a project-scoped task with a chosen provider, Coordinator, and at least two agents.
- The user can observe every user-visible operation in order and intervene while work is running.
- A mutating task is isolated, reviewable as a diff, and recoverable after restart or disconnect.
- A user can customize a built-in role, import a local skill package, and create one custom role without code changes.

## Non-goals

The MVP excludes cloud sync, remote multi-user collaboration, billing, telemetry, a skill marketplace, a visual workflow editor, and concurrent mutating sessions on the same project.
