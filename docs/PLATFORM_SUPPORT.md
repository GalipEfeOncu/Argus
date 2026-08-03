# Desktop platform support

This guide records the current developer and release-quality prerequisites for
the native Argus shell. The supported-target contract remains authoritative in
[Implementation Specification section 13](IMPLEMENTATION_SPEC.md#13-supported-desktop-targets).

## Supported target matrix

| Platform | Architecture | Minimum/runtime baseline | Native packages |
| --- | --- | --- | --- |
| Windows | x86_64 | Windows 10 22H2 or Windows 11; WebView2 Evergreen | NSIS |
| macOS | arm64 and x86_64 | macOS 12 or newer; system WebKit | signed app bundle and DMG |
| Linux | x86_64 | Ubuntu 22.04-compatible glibc and WebKitGTK 4.1 | AppImage and Debian package |

Linux ARM64 remains planned. It is not a supported release target until a
native runner passes the same quality and performance gates.

Argus builds each target on its native operating system. The Windows installer
embeds the small WebView2 bootstrapper so a missing Evergreen runtime can be
installed during setup. The macOS deployment target is 12.0. Linux artifacts
are built on Ubuntu 22.04; current Ubuntu and Debian stable are compatibility
test targets.

The application identifier is `com.argus.desktop`; the native credential
service uses `com.argus.desktop.provider`. This pre-release baseline replaces
the earlier development-only `.app`-suffixed identifier, so credentials stored
by an older development checkout must be entered again. No released user data
migration is implied.

## Git and shell prerequisites

Git is recommended but not mandatory. When Git is available, Argus creates an
isolated managed worktree by default. A project without Git uses an isolated
snapshot instead. Direct-write mode remains an explicit, visibly acknowledged
choice; missing Git never silently enables it.

Argus executes approved tools as argument arrays inside the selected workspace;
it does not pass model text to a command shell. Development and user-selected
test commands require PowerShell on Windows or a POSIX `/bin/sh` environment on
macOS/Linux. Git, Node.js, Rust, Python, and `uv` are development prerequisites
only and are not bundled as user-facing shell permissions.

## Native quality evidence

The `Native quality` workflow builds a target-triple frozen sidecar, runs its
authenticated lifecycle smoke test, executes the frontend/backend/Rust and
platform probes, and produces release-equivalent native bundles for:

- Windows Server 2022 x86_64 as the native Windows build environment;
- macOS 15 Intel and macOS 14 Apple Silicon;
- Ubuntu 22.04 x86_64, plus compatibility probes on Ubuntu 24.04 and Debian
  stable.

The platform probe checks Unicode and spaced paths, paths over 300 characters,
filesystem case behavior, LF/CRLF preservation, POSIX executable bits where
applicable, symlink identity, bounded child-process cancellation, system shell,
Git availability/fallback, and the native webview prerequisite. Accessibility
CI combines axe structural checks, keyboard-operable recovery controls, WCAG AA
semantic-token contrast, global reduced-motion handling, screen-reader live
regions, native zoom hotkeys with a scalable viewport, and the existing
10,000-event virtualization bound.

Hosted build runners do not certify Windows 10/11 client installation,
hardware keychain variants, real suspend/resume, screen-reader application
pairings, signed/notarized distribution, or packaged performance on reference
hardware. Those checks require clean client machines and release credentials;
they are mandatory publication gates in the
[pre-publish checklist](PUBLISH_CHECKLIST.md), rather than roadmap phase gates.

Run the host-appropriate local gates with:

```bash
npm run platform:quality -- --require-webview
npm run accessibility:quality
npm run test:platform-quality
npm run test:accessibility-quality
```
