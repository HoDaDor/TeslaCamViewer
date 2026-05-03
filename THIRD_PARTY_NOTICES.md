# Third-Party Notices

Last reviewed: 2026-05-02

TeslaCamViewer source code is released under the MIT license. Runtime
dependencies, bundled static assets, and optional external tools keep their own
license terms. This file is a practical source-repo inventory; a packaged
installer should still be checked against the exact files included in that
release.

## Direct Python Dependencies

| Dependency | Current repo use | License notes | Upstream |
| --- | --- | --- | --- |
| PySide6 | Qt desktop UI, multimedia playback, WebEngine map view | PyPI metadata lists `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; commercial Qt licensing is also available from Qt | <https://pypi.org/project/PySide6/> |
| OpenCV / `opencv-python` | Frame extraction and export helpers | OpenCV 4.5.0 and newer are Apache-2.0; PyPI wheels may include their own third-party components | <https://opencv.org/license/> |
| PyYAML | Human-readable settings files | MIT | <https://pypi.org/project/PyYAML/> |
| psutil | Hardware detection and drive inspection for recovery mode | BSD-3-Clause | <https://pypi.org/project/psutil/> |

## External Tools

### FFmpeg / `ffprobe`

- Purpose: probing candidate MP4 fragments during recovery workflows.
- Bundled in this repository: no.
- Expected at runtime: `ffprobe` should be available on `PATH` for recovery.
- License notes: FFmpeg is LGPL-2.1-or-later by default, but builds that enable
  GPL components are governed by GPL terms for the whole FFmpeg build.
- Upstream: <https://ffmpeg.org/>
- Legal notes: <https://www.ffmpeg.org/legal.html>

If a future installer bundles FFmpeg or `ffprobe`, include the matching FFmpeg
license notices, source-offer details, and build configuration for the exact
binary being distributed.

## Bundled Static Assets

### Leaflet

- Purpose: event map rendering in the embedded map view.
- Location in repo: `leaflet/`
- License: BSD 2-Clause.
- License text in repo: `licenses/LEAFLET-BSD-2-Clause.txt`
- Upstream: <https://leafletjs.com/>

Leaflet's bundled license applies to the files under `leaflet/`, not to the
rest of the project.

## Qt / PySide6 Notes

Qt and Qt for Python include additional third-party components. The source repo
documents the main dependency and links to Qt's license inventory, but a binary
release should copy the license and notice files that correspond to the exact Qt
runtime files shipped.

Useful Qt references:

- Qt Licensing: <https://doc.qt.io/qt-6/licensing.html>
- Qt for Python license inventory: <https://doc.qt.io/qtforpython-6/licenses.html>
- Third-party code used in Qt: <https://doc.qt.io/qt-6/licenses-used-in-qt.html>
- Qt SBOM information: <https://doc.qt.io/qt-6/sbom.html>

## Release Checklist Reminder

Before publishing a standalone app bundle or installer:

1. Record the exact dependency versions used for the build.
2. Include this project's `LICENSE`.
3. Include notices for bundled Leaflet files.
4. Include Qt / PySide6 license notices and any deployment-generated notice
   files.
5. If FFmpeg is bundled, include FFmpeg license/source-offer materials for that
   exact binary.
6. Keep third-party notices visible in release documentation or an in-app
   About / Licenses screen.
