# Deployment Notes

Last reviewed: 2026-05-03

This project includes baseline Qt for Python deployment files for desktop builds.
The helpers are focused on repeatable desktop packages that can be attached to
GitHub Releases.

## Desktop Builds

### Windows

- Use `build.ps1`
- The deployed output should land under `dist/`.
- Use `.\build.ps1 -Force -Installer` to create a Windows setup executable
  under `dist/installer/`.

### macOS

- Use `build-macos.sh`
- The deployed output should land under `dist/`.
- Use `./build-macos.sh --force --dmg` to create a DMG package under
  `dist/installer/`.
- If `hdiutil` is unavailable, `./build-macos.sh --force --zip` creates a zip
  package from the generated `.app` bundle.
- GitHub Releases build both Apple Silicon and Intel packages on GitHub-hosted
  macOS runners.

## Included Deployment Files

- `teslacamviewer.pyproject`
  - Qt for Python project file used by deployment tooling

- `pysidedeploy.spec`
  - Baseline configuration for `pyside6-deploy`

- `build.ps1`
  - Windows helper script

- `build-macos.sh`
  - macOS helper script

## Deployment Approach

Qt for Python ships official desktop deployment tooling. The current
scaffolding follows that supported path and keeps the build flow easy to review
while packaging work is still early.

Before publishing an installer, do a release-specific check of the bundled Qt
files, third-party notices, and license texts. See `PYSIDE6-LICENSING.md`.

## Release Documentation Checklist

Before publishing a build outside the source repo:

- record exact versions of Python, PySide6, Qt, OpenCV, PyYAML, psutil, and the
  packaging tool
- confirm whether FFmpeg / `ffprobe` is bundled or expected to be installed by
  the user
- include `LICENSE`, `THIRD_PARTY_NOTICES.md`, and the bundled Leaflet license
- include Qt / PySide6 notice files generated or copied by the deployment tool
- add an About / Licenses screen or a clearly linked license file in the app
  bundle
- smoke-test viewer playback, map rendering, evidence export, and recovery
  Scan Only mode from a clean install

## GitHub Releases

Pushing a version tag such as `v0.1.0` runs the release workflow. The workflow
builds the Windows setup executable with `build.ps1 -Force -Installer`, builds
Apple Silicon and Intel macOS DMGs with `build-macos.sh --force --dmg`, uploads
the packages as workflow artifacts, and attaches them to the GitHub Release for
that tag.

## iPhone / iPad

An iPhone app is better treated as a separate companion app than as a direct packaging target for this desktop recovery tool.

The current desktop app is built around:

- Qt Widgets desktop UI
- direct file-system workflows
- image-file and raw-media recovery steps designed for desktop access

So the realistic path is:

1. package the desktop app for Windows and macOS
2. refine the signed/notarized macOS release process when needed
3. decide later whether a separate iOS viewer/export companion is worth building

That future iOS app would likely focus on viewing, bookmarking, and export
workflows, with raw-media recovery remaining in the desktop tool.

## Official References

- Qt for Python deployment overview: https://doc.qt.io/qtforpython-6/deployment/index.html
- `pyside6-deploy`: https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
- `pyside6-project`: https://doc.qt.io/qtforpython-6/tools/pyside-project.html
- Qt SBOM information: https://doc.qt.io/qt-6/sbom.html
- Qt for iOS overview: https://doc.qt.io/qt-6/ios.html
