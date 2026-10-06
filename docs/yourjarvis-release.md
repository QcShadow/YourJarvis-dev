# YourJarvis release workflow

This repository is the private development source. The public distribution
repository is `QcShadow/YourJarvis-link`; release ZIP files belong in GitHub
Releases rather than Git history. The domestic mirror is
`QcShadow/your-jarvis-link` on Gitee.

The Windows distribution is built from `D:\Jarvis`:

```powershell
./build-friends-bootstrap.ps1 `
  -Output D:\Jarvis\dist\JARVIS-Friends-Bootstrap-0.1.0.zip `
  -Version 0.1.0 `
  -UpdateManifestUrl https://github.com/QcShadow/YourJarvis-link/releases/latest/download/update-github.json `
  -MirrorUpdateManifestUrl https://gitee.com/QcShadow/your-jarvis-link/raw/main/update.json
```

The bootstrap ZIP excludes model and speech weights. On first use,
`JARVIS-Install.exe` presents a Chinese graphical wizard: directory, model/API
and voice choices, confirmation, automatic ordered installation and self-check.
The legacy CMD entry points all open this same wizard. The desktop launcher
opens it automatically when the Python runtime or configuration is missing.

Before publishing, verify that the ZIP contains `JARVIS.exe`,
`app-version.json`, `JARVIS-Install.exe`, `install-worker.ps1`, the configuration
bridge in `scripts/configure_portable.py`, and the legacy CMD entry points,
and that it does not
contain `data`, credentials, databases, logs or model weights. Publish the ZIP
and `update.json` as assets on a `vX.Y.Z` release, then copy the corresponding
manifest and ZIP to the domestic mirror.

Build release sources from a clean Git snapshot. Concurrent unrelated working
tree edits must not enter the ZIP. Run recipient installation in a separate
directory containing Chinese characters and spaces, with no existing venv.
Exercise API failure, configuration preservation, key clearing, and the actual
GUI process environment (including missing/inherited PSModulePath). Verify
the archive manifest before upload and download both uploaded ZIP assets to
compare their SHA-256. Publish update manifests only after both attachments
are available.
