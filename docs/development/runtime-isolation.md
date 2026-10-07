# Local desktop runtime isolation

Each desktop installation is an independent runtime boundary. Development and
portable friend installations may run concurrently on the same Windows account
without sharing a service, state file, WebView profile, or model process.

## Current contract

- `OPENJARVIS_HOME` is the installation root, so configuration, credentials,
  databases, logs, locks, temporary files, and desktop browser data stay under
  that root.
- The API and managed Ollama service bind to independently selected loopback
  ports. Their actual addresses live in that root's `logs/*-runtime.json`.
- API readiness requires a per-launch `X-Jarvis-Instance` response header.
  A healthy service on another port or from another installation is never
  adopted.
- Process ownership requires the expected root, executable path, PID, and
  process start time. Shutdown only terminates a process tree after all four
  match.
- Managed Qwen voice workers receive their own loopback address and the API
  launch identity. A worker from another launch is rejected even if it exposes
  the same health route.
- The desktop single-instance mutex and WebView2 data directory are derived
  from the installation root. Development builds are identified by
  `development-runtime.json` and do not run friend-release update checks.

The checked-in runtime templates under `deploy/share/runtime` are canonical for
portable packages. `D:\Jarvis\build-desktop.ps1` delegates to the canonical
launcher build under `deploy/yourjarvis`; do not restore a second launcher
implementation at the data-root level.

## Remaining long-term work

1. Give every auxiliary service the same supervised lifecycle metadata rather
   than relying on parent process-tree shutdown alone.
2. Add an automated two-install end-to-end test that starts both desktops,
   exercises API and optional voice paths, stops either side, and verifies the
   other remains healthy.
3. Separate immutable application resources from mutable user state so updates
   can replace program files without touching identity, credentials, models, or
   conversation data.
4. Add explicit runtime schema versions and migration checks for state files,
   then surface ownership/port diagnostics in the desktop recovery UI.
5. Keep fixed ports only for deliberately public server modes; desktop-local
   helpers must remain random loopback listeners with authenticated identity.
