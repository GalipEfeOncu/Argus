# Operations, backup, and recovery

## Current data layout

Argus keeps durable non-secret application state in `~/.argus/argus.db` unless
`ARGUS_DB_PATH` overrides it. Provider secrets remain in the operating-system
credential store and are not copied into database backups. Session worktrees or
managed snapshots are separate project data and are retained or removed only by
the user's explicit acceptance/cleanup choice.

## Migration backup contract

Before applying any pending schema migration to an existing database, startup:

1. runs SQLite's integrity check and stops without migrating on failure;
2. creates a consistent SQLite backup through the SQLite backup API;
3. writes the backup and JSON manifest under the current user's data directory,
   using owner-only `0600` mode on POSIX and the user profile's inherited ACL on
   Windows; and
4. records source/destination schema versions, size, creation time, and SHA-256.

A fresh or already-current database does not create a redundant backup. Backups
are not automatically pruned because retention is an operator choice.

## Roll back or recover

Stop Argus completely before recovery. Locate the manifest matching the last
known-good pre-migration backup, keep both its `.json` and `.db` files together,
and run from the repository or packaged support environment:

```bash
python scripts/restore-backup.py ~/.argus/backups/<manifest>.json --confirm
```

Use `--database <path>` only when restoring an explicitly configured database.
The command verifies both checksum and SQLite integrity, refuses symlinked
inputs/destinations, installs the replacement through same-filesystem renames,
and retains the replaced database and any stale SQLite journal/WAL companions
with a `.pre-restore-<timestamp>` suffix. An OS crash between renames can leave
the active database path absent; in that case keep Argus stopped and repeat the
same verified restore command. Restart the same application
version that understands the restored schema, verify sessions and settings, and
only then remove retained files. Restoring the SQLite database does not roll
back accepted project changes, credential-store entries, or provider-side data.

## Troubleshooting

- **Sidecar unavailable:** close all Argus windows, confirm no Argus sidecar is
  left running, restart the app, and review the local runtime health panel.
- **Database locked:** close duplicate processes and backup/sync software that
  holds the database. Do not delete journal files while Argus is running.
- **Database integrity alert:** do not retry migrations repeatedly. Preserve the
  database and backups, export a redacted support bundle if possible, and use
  the verified recovery procedure above.
- **Low disk space:** free space on the filesystem containing the database and
  isolated workspace before resuming; a failed disk check never grants a write.
- **Credential store unavailable:** unlock or repair the native credential
  service. Do not put provider keys into `.env`, project files, or support data.
- **Provider failure:** verify network/service status and model configuration.
  Argus does not silently replay an operation whose outcome is unknown.

The runtime health view and explicit support-bundle export are the preferred
diagnostic sources. Reports must follow the private process in
[the repository security policy](../SECURITY.md).

## Known limits

- No stable release or automatic update channel exists yet; `0.1.0` is a
  development baseline.
- Local metadata is not application-encrypted at rest; use OS account and disk
  encryption controls.
- An already-compromised OS account is outside the application sandbox model.
- Provider data handling is controlled by the selected provider after bounded
  context leaves the device.
- Native keychain variants, suspend/resume, screen-reader pairings, signed
  install/upgrade/uninstall, and reference-hardware performance require the
  per-release checks in [PUBLISH_CHECKLIST.md](PUBLISH_CHECKLIST.md).
- Linux ARM64 and distributions outside the declared matrix are not supported.
- Linux packaging currently inherits Tauri's GTK3 Rust binding chain. RustSec
  marks that chain unmaintained and reports an upstream `glib` iterator
  soundness warning; Argus retains and reviews this warning while continuing to
  fail CI on vulnerability advisories.
