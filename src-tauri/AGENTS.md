# Tauri Guidance

These rules extend the root `AGENTS.md` for the native bridge under `src-tauri/`.

## Required context

Read `docs/ARCHITECTURE.md` and `docs/SECURITY.md` before changing commands,
capabilities, credential access, process lifecycle, or filesystem integration.

## Boundaries

- Keep the bridge narrow and least-privileged; do not duplicate backend business policy in Rust.
- Expose explicit commands with validated inputs instead of general shell or filesystem escape hatches.
- Scope sidecar lifecycle, paths, and permissions to the Argus application and selected workspace.
- Never include credentials in command payloads, logs, errors, frontend state, or configuration files.
- Treat capability changes as security changes and document the user-visible effect.

## Verification

Run `.agents/skills/argus-development/scripts/verify.sh tauri`. If a native
change affects the frontend contract or security posture, run those checks and
update the corresponding documentation too.
