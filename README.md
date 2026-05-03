# TeslaCamViewer

TeslaCamViewer is a PySide6 desktop app for reviewing Tesla dashcam and Sentry
Mode clips. It focuses on the common workflow of opening a TeslaCam event
folder, reviewing the available camera angles together, checking the event
metadata, and exporting useful stills or short clips.

The app also includes a separate recovery workspace for advanced users who need
to scan a raw TeslaCam USB device or disk image for recoverable MP4 fragments.
The recovery workspace includes guided setup, scan filters, progress reporting,
and extra-salvage tools for promising results.

## Highlights

- Multi-angle playback for the camera feeds found in each event folder
- Front, repeater, and rear view swapping from a responsive camera layout
- Event bookmark support for jumping to the recorded incident moment
- Embedded map and event details from `event.json` when metadata is available
- Vehicle telemetry panel for supported clips with embedded speed and input data
- Evidence-oriented export of still frames, clip excerpts, and manifests
- Separate recovery tab with guided settings, YAML-backed preferences, and
  targeted extra-salvage recovery for promising scan results

## Screenshots

### Viewer Workspace

![Viewer workspace](docs/screenshots/viewer-overview.png)

### Recovery Workspace

![Recovery workspace](docs/screenshots/recovery-workspace.png)

## Feature Overview

### Multi-Angle Review

- Detects available Tesla camera angles dynamically
- Automatically lays out the camera views found in the selected folder
- Lets users promote an auxiliary angle into the main playback view
- Keeps the event timeline visible in both the main and synced angle controls

### Event Context

- Uses `event.json` metadata when available
- Shows location details such as city, event type, time, and coordinates
- Supports an event bookmark marker in the playback sliders
- Shows frame-synced speed, steering, pedal, and acceleration data when present

### Evidence Export

- Exports still frames and/or short clip excerpts
- Can include contextual overlays such as timestamps, GPS, source filename, and
  event reason
- Writes a manifest with source hashes and event metadata so exported files stay
  tied back to the original clips

The export tools are meant to help organize and explain footage. They do not
replace preserving the original Tesla files.

### Recovery Mode

- Scan either a live TeslaCam USB drive or a raw image file
- Filter candidate recoveries by date and optional local time window
- Leverage Qt-native threading for responsive, efficient recovery scans
- Review likely matches and recovered clips in a dedicated results area
- Recover a larger block from a selected result when a clip looks truncated
- Provide advanced controls for raw offsets, carve sizes, and worker tuning

Recovery scans are read-oriented, but live-device recovery should still be run
carefully. If the footage matters, working from a disk image is safer than
working directly from the USB drive. Recovery speed also depends heavily on the
source USB port, the source drive, and the output drive; a USB 2.0 path can take
much longer than USB 3.x or a fast internal SSD.

## Tech Stack

- Python 3.11+
- PySide6
- OpenCV
- PyYAML
- psutil
- FFmpeg / `ffprobe`

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Running

```powershell
python qtTeslaCam.py
```

Or after installation:

```powershell
teslacam-viewer
```

## Project Layout

- `qtTeslaCam.py`: launcher entrypoint
- `teslacam_app/`: main application package
- `leaflet/`: bundled map assets
- `tests/`: unit tests for metadata, settings, recovery helpers, and telemetry
- `docs/screenshots/`: screenshot assets used by this README

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): module responsibilities and runtime flow
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): desktop build and packaging notes
- [docs/PYSIDE6-LICENSING.md](docs/PYSIDE6-LICENSING.md): practical licensing/compliance notes for PySide6 and Qt
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): dependency license and notice summary
- [docs/github-metadata.md](docs/github-metadata.md): GitHub description, topics, and publishing notes

## Packaging

- Windows setup build: `.\build.ps1 -Force -Installer`
- macOS DMG build: `./build-macos.sh --force --dmg`
  - GitHub Releases build separate Apple Silicon and Intel packages.
- Desktop deployment notes: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## Recovery Notes

- Live USB recovery is Windows-oriented and usually requires Administrator access.
- `ffprobe` must be available on `PATH` for recovery workflows.
- Recovery settings are stored in the user's config directory as YAML, not in the repository.
- Avoid writing anything to the source TeslaCam media while attempting recovery.

## License

- Project source: [MIT](LICENSE)
- Additional dependency notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Qt / PySide6 compliance notes: [docs/PYSIDE6-LICENSING.md](docs/PYSIDE6-LICENSING.md)
