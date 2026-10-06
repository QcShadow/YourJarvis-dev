# YourJarvis release workflow

Build friend releases from a clean Git snapshot. The public program repositories
are QcShadow/YourJarvis-link on GitHub and QcShadow/your-jarvis-link on Gitee.
Version 0.1.3 ships one graphical JARVIS-Setup-0.1.3.exe: users do not unzip or
run bootstrap commands.

Build the frontend, compile deploy/yourjarvis/scripts/build-desktop.ps1, copy
the desktop output and pinned resource index into dist/share-desktop, build the
internal program ZIP with deploy/share/build_package.py --desktop, then embed it
with deploy/yourjarvis/scripts/build-setup.ps1.

Use deploy/share/build_resources.py for redistributable runtime/model packs.
Preserve upstream licenses. Publish every indexed part with its exact name before
enabling update manifests. Gitee limits each attachment to 100 MB and each
ordinary repository to 1 GB, so runtime and speech parts use your-jarvis-runtime
and your-jarvis-speech. GitHub hosts all parts in the main release. The installer
verifies sizes and SHA-256, resumes downloads and uses Gitee first with fallback.

Keep unrelated worktree edits out of releases. Verify the program manifest,
native downloader fallback/resume, clean EXE extraction and installation in a
directory with Chinese characters and spaces. Installation must exercise the
real backend, HTML and selected model; voice installs must load recognition
models and produce audio offline. Check Windows PowerShell with an empty
PSModulePath. Publish update.json/update-github.json with the final EXE checksum
only when both hosts and resource parts are ready. Preserve user config,
credentials, models, conversations and memory during repair/upgrade.
