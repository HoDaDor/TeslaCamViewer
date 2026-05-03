# PySide6 / Qt Licensing Notes

Last reviewed: 2026-05-02

TeslaCamViewer source code is MIT licensed. PySide6, Qt, and Qt-bundled
third-party components are separate projects with separate license terms. This
document is a practical engineering checklist for this repo, not legal advice.

## Current Upstream Snapshot

- PySide6 latest PyPI release checked during this review: `6.11.0`.
- PySide6 PyPI metadata lists the license expression
  `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`.
- Qt's current online documentation reviewed here is Qt `6.11`.
- Qt is available under commercial licensing, LGPLv3/GPLv3 open-source terms,
  and Qt Marketplace terms depending on the component and use case.
- Qt notes that some open-source Qt modules are GPL-only rather than LGPL.
- Starting with Qt 6.8, Qt publishes SBOM information for third-party
  components in SPDX format.

## Qt Modules Used By This App

The application uses PySide6 modules for:

- `QtCore`
- `QtGui`
- `QtWidgets`
- `QtMultimedia`
- `QtMultimediaWidgets`
- `QtWebEngineWidgets`

`QtMultimedia` and `QtWebEngineWidgets` matter most for packaging because they
can bring additional Qt runtime files and third-party notices into a deployed
desktop build.

## Source Repository Baseline

For the source repository, the project keeps:

- the MIT project license in `LICENSE`
- a dependency notice file in `THIRD_PARTY_NOTICES.md`
- this PySide6 / Qt compliance note
- the bundled Leaflet BSD-2-Clause license in `licenses/`

That is a reasonable source-only baseline. It does not replace a release pass
for standalone binaries.

## Binary Release Checklist

Before publishing an `.exe`, installer, `.app`, `.dmg`, or similar packaged
release:

1. Build from a clean environment and record exact versions of Python, PySide6,
   Qt, OpenCV, PyYAML, psutil, and packaging tools.
2. Keep this project's `LICENSE` with the source distribution and release
   notes.
3. Include Qt / PySide6 license notices copied by the deployment tooling.
4. Include notices for Qt modules and third-party Qt components actually
   shipped in the bundle.
5. Include Leaflet's BSD-2-Clause license when the bundled `leaflet/` assets are
   included.
6. If FFmpeg or `ffprobe` is bundled, include the matching FFmpeg license and
   source-offer materials for that exact build.
7. Prefer dynamic Qt/PySide6 runtime components unless there is a reviewed
   reason to do otherwise.
8. Add or update an in-app About / Licenses screen before a public binary
   release.

## Practical Notes

- Do not treat PySide6 or Qt as MIT just because this app's source is MIT.
- Do not assume all Qt modules have the same open-source license terms.
- Keep release notices tied to the exact files distributed, especially for
  WebEngine and multimedia-related runtime files.
- A source-only GitHub repo and a bundled desktop installer have different
  compliance needs.

## Official References

- PySide6 PyPI metadata: <https://pypi.org/project/PySide6/>
- Qt Licensing: <https://doc.qt.io/qt-6/licensing.html>
- Qt for Python license inventory: <https://doc.qt.io/qtforpython-6/licenses.html>
- Qt third-party code: <https://doc.qt.io/qt-6/licenses-used-in-qt.html>
- Qt SBOM information: <https://doc.qt.io/qt-6/sbom.html>
- Qt for Python deployment: <https://doc.qt.io/qtforpython-6/deployment/index.html>
