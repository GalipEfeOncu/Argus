# Privacy statement

## What stays local

Argus is local-first. Project files, the collaboration timeline, configuration,
approval history, diffs, usage summaries, and runtime diagnostics remain on the
user's machine by default. Argus has no built-in advertising, analytics, or
automatic support-bundle upload. Provider credentials are stored by the
operating-system credential service; SQLite stores only non-secret references.

## What can leave the device

When the user configures and uses a model provider, Argus sends that provider
the bounded conversation, instructions, and tool context needed for the chosen
task. The provider's own privacy, retention, and regional-processing terms
apply. Network-enabled tools or dependency commands can also contact their
declared services after the applicable permission policy allows them.

The user may explicitly export a patch or redacted support bundle. Support
bundles contain configuration shapes, event-type counts, health facts, and
redacted logs; they exclude credentials, raw prompts, private model reasoning,
project paths, event bodies, and project file contents. Exporting a file does
not upload it.

## Storage and deletion

Application metadata is stored under the current user's Argus data directory,
currently `~/.argus/` on supported clients. Isolated workspaces remain until the
user chooses cleanup. Uninstall behavior and whether local data is preserved are
verified and stated for each published installer. Migration backups are local,
checksummed, never uploaded automatically, and can be deleted by the user after
the upgraded version is verified.

Argus cannot delete copies already sent to a model provider or another external
tool. Requests concerning those copies must follow the external service's
policy. See [OPERATIONS.md](OPERATIONS.md) for local recovery and cleanup and
[SECURITY.md](SECURITY.md) for enforcement boundaries.
