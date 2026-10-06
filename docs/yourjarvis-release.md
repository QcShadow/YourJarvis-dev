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
`bootstrap.cmd` installs the runtime and `setup-jarvis.cmd` checks the selected
backend and downloads a local model only when the user chooses one.

Before publishing, verify that the ZIP contains `JARVIS.exe`,
`app-version.json`, `bootstrap.cmd` and `setup-jarvis.cmd`, and that it does not
contain `data`, credentials, databases, logs or model weights. Publish the ZIP
and `update.json` as assets on a `vX.Y.Z` release, then copy the corresponding
manifest and ZIP to the domestic mirror.
