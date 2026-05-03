# Architecture Overview

TeslaCamViewer is organized as a small PySide6 shell over a set of focused helper modules. The goal is to keep the large, stateful Qt window understandable by pushing data parsing, export logic, mapping, and recovery primitives into separate files.

## Runtime Flow

1. `qtTeslaCam.py` launches `teslacam_app.main.run()`.
2. `teslacam_app.main` applies a few Qt multimedia environment defaults before creating `QApplication`.
3. `teslacam_app.viewer.TeslaCamViewer` builds the window, wires menus and tabs, and owns the live UI state.
4. When a folder is loaded:
   - `teslacam_app.data` reads `event.json`, detects camera files, and chooses the clip minute to play.
   - `teslacam_app.viewer` creates `QMediaPlayer` instances for the detected angles.
   - `teslacam_app.map_renderer` generates inline Leaflet HTML if GPS coordinates exist.
   - `teslacam_app.telemetry` checks the selected front clip for embedded vehicle data.
5. When evidence is exported:
   - `teslacam_app.export_dialog` gathers user export choices.
   - `teslacam_app.exporter` creates annotated stills/clips plus a manifest.
6. When recovery mode is used:
   - `teslacam_app.recovery_dialog` hosts the recovery workspace UI.
   - `teslacam_app.recovery` provides hardware detection, tuning presets, probing helpers, and carve primitives.
   - Extra Salvage can recover a larger bounded block from a selected result or
     manually entered offset while keeping the UI responsive.

## Module Responsibilities

### Entry and Application Shell

- `teslacam_app.main`
  - Process bootstrap and `QApplication` startup.
  - Keeps environment defaults out of the viewer class.

- `teslacam_app.viewer`
  - Main application window.
  - Playback orchestration, map display, event labels, export entry point, and recovery-tab hosting.

- `teslacam_app.ui`
  - Generated / assembled widget structure for the main window.
  - Keeps layout scaffolding separate from behavioral code.

### Tesla Event Discovery

- `teslacam_app.cameras`
  - Camera-key detection, ordering, and display labels.

- `teslacam_app.data`
  - Tesla folder inspection.
  - `event.json` parsing.
  - Clip-minute selection and normalized `EventMetadata`.

### Viewer Helpers

- `teslacam_app.video_surface`
  - Paint-based video surface used by the viewer panes.

- `teslacam_app.widgets`
  - Custom widgets such as sliders with event markers.

- `teslacam_app.map_renderer`
  - Self-contained Leaflet HTML generation for embedded maps.

- `teslacam_app.telemetry`
  - Extracts and normalizes Tesla telemetry samples from newer MP4 files.

- `teslacam_app.telemetry_visuals`
  - Draws compact steering, pedal, and g-meter widgets for the viewer.

### Export Workflow

- `teslacam_app.export_dialog`
  - User-facing export options dialog.

- `teslacam_app.exporter`
  - Manifest creation, overlays, still export, clip export, and source-copy behavior.

### Recovery Workflow

- `teslacam_app.recovery_dialog`
  - Dedicated recovery tab UI, validation, progress display, Extra Salvage
    workflow, and settings round-trip.

- `teslacam_app.recovery`
  - Hardware-aware tuning, candidate probing, timestamp extraction, bounded
    carving, and larger salvage helpers.

### Persistence

- `teslacam_app.settings_store`
  - YAML-backed user settings storage outside the repo.

## Design Notes

### Viewer State Coordination

The viewer is where most live UI state naturally converges: loaded folder,
players, camera-pane ownership, event markers, map state, and menu/tab behavior.
The code is kept manageable by moving non-UI logic into sibling modules and
documenting the important orchestration paths.

### Human-Readable Settings

The project stores preferences in a human-readable YAML file so users can
inspect, back up, or edit recovery preferences with normal text tools.

### Dedicated Recovery Workspace

Recovery mode deals with raw devices, tuning presets, and long-running scans.
Keeping it in a dedicated workspace makes the recovery flow clearer while
leaving normal clip viewing focused and simple.

The normal recovery path keeps carve sizes bounded so scan results stay
manageable. Extra Salvage is a second step for a promising offset: it copies a
larger bounded block from the same source while leaving the source media
untouched.

### Custom Video Surface

Qt Multimedia handles decoding and playback, while `VideoFrameWidget` owns the
final paint step. That gives the viewer enough control to keep camera panes
filled, add a small visual inset around the image, and avoid excessive black
letterboxing in the multi-angle layout.
