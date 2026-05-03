"""Evidence package creation for TeslaCam stills and clip excerpts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2

from .cameras import camera_label
from .data import EventMetadata
from .export_dialog import ExportOptions


MANIFEST_FILENAME = "manifest.json"
README_FILENAME = "README.txt"


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Paths created by one export operation."""

    package_dir: Path
    manifest_path: Path


class EvidencePackageExporter:
    """Create a folder of derived media plus a manifest for one event."""

    def __init__(
        self,
        *,
        metadata: EventMetadata,
        loaded_video_files: dict[str, Path],
        current_main_key: str | None,
    ):
        self.metadata = metadata
        self.loaded_video_files = dict(loaded_video_files)
        self.current_main_key = current_main_key

    def export(self, options: ExportOptions) -> ExportResult:
        """Run the selected export workflow and return the created paths."""

        package_dir = self._create_package_dir(options.output_root, options.package_name)
        originals_dir = package_dir / "originals"
        stills_dir = package_dir / "stills"
        clips_dir = package_dir / "clips"

        selected_keys = self._selected_camera_keys(options.scope)
        anchor_position_ms = self._anchor_position_ms(options)

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "package_type": "teslacam_evidence_export",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "warning": (
                "Derived exports may contain annotations and should not replace the original "
                "Tesla media. Preserve the original clips and event.json for authenticity."
            ),
            "event": self._event_manifest(anchor_position_ms),
            "export_options": {
                "scope": options.scope,
                "anchor_mode": options.anchor_mode,
                "anchor_position_ms": anchor_position_ms,
                "include_originals": options.include_originals,
                "include_stills": options.include_stills,
                "include_clips": options.include_clips,
                "include_overlay": options.include_overlay,
                "image_format": options.image_format,
                "clip_before_seconds": options.clip_before_seconds,
                "clip_after_seconds": options.clip_after_seconds,
            },
            "files": [],
        }

        if options.include_originals:
            originals_dir.mkdir(parents=True, exist_ok=True)
            self._copy_event_json(originals_dir, manifest)

        if options.include_stills:
            stills_dir.mkdir(parents=True, exist_ok=True)

        if options.include_clips:
            clips_dir.mkdir(parents=True, exist_ok=True)

        for camera_key in selected_keys:
            source_path = self.loaded_video_files[camera_key]
            source_hash = self._sha256(source_path)
            file_manifest: dict[str, Any] = {
                "camera_key": camera_key,
                "angle_label": camera_label(camera_key),
                "source_path": str(source_path),
                "source_sha256": source_hash,
            }

            if options.include_originals:
                copied_source = originals_dir / source_path.name
                shutil.copy2(source_path, copied_source)
                file_manifest["copied_original_path"] = copied_source.name

            if options.include_stills:
                still_path = self._export_still(
                    source_path=source_path,
                    output_dir=stills_dir,
                    camera_key=camera_key,
                    position_ms=anchor_position_ms,
                    image_format=options.image_format,
                    include_overlay=options.include_overlay,
                    source_hash=source_hash,
                )
                file_manifest["still_path"] = still_path.relative_to(package_dir).as_posix()
                file_manifest["still_sha256"] = self._sha256(still_path)

            if options.include_clips:
                clip_path, clip_range = self._export_clip_excerpt(
                    source_path=source_path,
                    output_dir=clips_dir,
                    camera_key=camera_key,
                    anchor_position_ms=anchor_position_ms,
                    clip_before_seconds=options.clip_before_seconds,
                    clip_after_seconds=options.clip_after_seconds,
                    include_overlay=options.include_overlay,
                    source_hash=source_hash,
                )
                file_manifest["clip_path"] = clip_path.relative_to(package_dir).as_posix()
                file_manifest["clip_sha256"] = self._sha256(clip_path)
                file_manifest["clip_range_ms"] = {
                    "start": clip_range[0],
                    "end": clip_range[1],
                }

            manifest["files"].append(file_manifest)

        manifest_path = package_dir / MANIFEST_FILENAME
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self._write_readme(package_dir, manifest_path)
        return ExportResult(package_dir=package_dir, manifest_path=manifest_path)

    def _selected_camera_keys(self, scope: str) -> list[str]:
        """Choose which loaded camera angles should be exported."""

        if scope == "main" and self.current_main_key in self.loaded_video_files:
            return [self.current_main_key]
        return list(self.metadata.ordered_camera_keys or self.loaded_video_files.keys())

    def _anchor_position_ms(self, options: ExportOptions) -> int:
        """Pick the frame timestamp used for stills and clip windows."""

        if options.anchor_mode == "event" and options.event_position_ms is not None:
            return max(0, int(options.event_position_ms))
        return max(0, int(options.current_position_ms))

    def _event_manifest(self, anchor_position_ms: int) -> dict[str, Any]:
        """Build the event metadata section written to ``manifest.json``."""

        return {
            "folder": str(self.metadata.folder),
            "city": self.metadata.city,
            "camera_id": self.metadata.camera_id,
            "event_type": self.metadata.event_type,
            "event_time": self.metadata.event_time.isoformat() if self.metadata.event_time else None,
            "selected_clip_start": (
                self.metadata.selected_clip_start.isoformat()
                if self.metadata.selected_clip_start
                else None
            ),
            "event_offset_ms": self.metadata.event_offset_ms,
            "anchor_position_ms": anchor_position_ms,
            "gps_coords": self.metadata.gps_coords,
            "raw_event": self.metadata.raw_event,
        }

    def _copy_event_json(self, originals_dir: Path, manifest: dict[str, Any]):
        """Copy ``event.json`` into the originals folder when it exists."""

        event_json_path = self.metadata.folder / "event.json"
        if not event_json_path.exists():
            return

        copied_path = originals_dir / event_json_path.name
        shutil.copy2(event_json_path, copied_path)
        manifest["event_json"] = {
            "source_path": str(event_json_path),
            "copied_path": copied_path.name,
            "sha256": self._sha256(event_json_path),
        }

    def _export_still(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        camera_key: str,
        position_ms: int,
        image_format: str,
        include_overlay: bool,
        source_hash: str,
    ) -> Path:
        """Export one frame from a source clip."""

        capture = cv2.VideoCapture(str(source_path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
        frame_number = max(0, int(round((position_ms / 1000.0) * fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            raise RuntimeError(f"Unable to capture still frame from {source_path.name}")

        if include_overlay:
            frame = self._annotate_frame(
                frame,
                camera_key=camera_key,
                source_path=source_path,
                position_ms=position_ms,
                source_hash=source_hash,
                derived_label="Annotated Still",
            )

        suffix = ".png" if image_format == "png" else ".jpg"
        output_path = output_dir / self._safe_filename(
            f"{camera_key}_{self._timecode_label(position_ms)}{suffix}"
        )
        cv2.imwrite(str(output_path), frame)
        return output_path

    def _export_clip_excerpt(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        camera_key: str,
        anchor_position_ms: int,
        clip_before_seconds: int,
        clip_after_seconds: int,
        include_overlay: bool,
        source_hash: str,
    ) -> tuple[Path, tuple[int, int]]:
        """Export a short video window around the chosen anchor timestamp."""

        capture = cv2.VideoCapture(str(source_path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width <= 0 or height <= 0:
            capture.release()
            raise RuntimeError(f"Unable to read video dimensions from {source_path.name}")

        max_duration_ms = int((total_frames / fps) * 1000) if total_frames > 0 else anchor_position_ms
        start_ms = max(0, anchor_position_ms - (clip_before_seconds * 1000))
        end_ms = max(start_ms, min(max_duration_ms, anchor_position_ms + (clip_after_seconds * 1000)))
        start_frame = max(0, int(round((start_ms / 1000.0) * fps)))
        end_frame = max(start_frame, int(round((end_ms / 1000.0) * fps)))

        clip_stem = self._safe_filename(
            f"{camera_key}_{self._timecode_label(start_ms)}_to_{self._timecode_label(end_ms)}"
        )
        output_path, writer = self._create_video_writer(output_dir / f"{clip_stem}.mp4", fps, width, height)
        if writer is None:
            capture.release()
            raise RuntimeError(f"Unable to create clip writer for {source_path.name}")

        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_index = start_frame
        while frame_index <= end_frame:
            ok, frame = capture.read()
            if not ok or frame is None:
                break

            current_ms = int((frame_index / fps) * 1000)
            output_frame = frame
            if include_overlay:
                output_frame = self._annotate_frame(
                    frame,
                    camera_key=camera_key,
                    source_path=source_path,
                    position_ms=current_ms,
                    source_hash=source_hash,
                    derived_label="Annotated Clip",
                )
            writer.write(output_frame)
            frame_index += 1

        capture.release()
        writer.release()
        return output_path, (start_ms, end_ms)

    def _annotate_frame(
        self,
        frame,
        *,
        camera_key: str,
        source_path: Path,
        position_ms: int,
        source_hash: str,
        derived_label: str,
    ):
        """Draw a compact metadata overlay onto a copied frame."""

        overlay = frame.copy()
        info_lines = self._overlay_lines(
            camera_key=camera_key,
            source_path=source_path,
            position_ms=position_ms,
            source_hash=source_hash,
            derived_label=derived_label,
        )

        margin = 20
        line_height = 28
        box_height = margin * 2 + line_height * len(info_lines)
        cv2.rectangle(
            overlay,
            (margin, margin),
            (frame.shape[1] - margin, min(frame.shape[0] - margin, box_height)),
            (10, 10, 10),
            thickness=-1,
        )
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

        y_pos = margin + 26
        for index, line in enumerate(info_lines):
            color = (255, 255, 255) if index != 0 else (102, 216, 255)
            cv2.putText(
                frame,
                line,
                (margin + 10, y_pos),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                color,
                2,
                cv2.LINE_AA,
            )
            y_pos += line_height
        return frame

    def _overlay_lines(
        self,
        *,
        camera_key: str,
        source_path: Path,
        position_ms: int,
        source_hash: str,
        derived_label: str,
    ) -> list[str]:
        """Format the overlay text shown on exported stills and clips."""

        frame_time = self._frame_time_for(position_ms)
        event_time_text = (
            self.metadata.event_time.strftime("%Y-%m-%d %H:%M:%S")
            if self.metadata.event_time
            else "Unknown"
        )
        frame_time_text = (
            frame_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            if frame_time is not None
            else "Unknown"
        )
        gps_text = "Unknown"
        if self.metadata.gps_coords:
            gps_text = (
                f"{self.metadata.gps_coords['lat']:.6f}, "
                f"{self.metadata.gps_coords['lon']:.6f}"
            )

        return [
            f"{derived_label} | Angle: {camera_label(camera_key)} | Source: {source_path.name}",
            f"Frame Time: {frame_time_text} | Event Time: {event_time_text}",
            f"City: {self.metadata.city or 'Unknown'} | GPS: {gps_text} | Reason: {self._humanize_reason(self.metadata.event_type)}",
            f"Camera ID: {self.metadata.camera_id or 'Unknown'} | Position: {self._format_timecode(position_ms)} | Hash: {source_hash[:16]}...",
        ]

    def _frame_time_for(self, position_ms: int) -> datetime | None:
        """Convert a clip-relative timestamp into an approximate wall time."""

        if self.metadata.selected_clip_start is None:
            return None
        return self.metadata.selected_clip_start + timedelta(milliseconds=position_ms)

    @staticmethod
    def _humanize_reason(reason: str | None) -> str:
        """Convert a raw Tesla event reason into display text."""

        if not reason:
            return "Unknown"
        return reason.replace("_", " ").title()

    @staticmethod
    def _format_timecode(milliseconds: int) -> str:
        """Format milliseconds as ``HH:MM:SS.mmm``."""

        whole_seconds, ms = divmod(max(0, int(milliseconds)), 1000)
        minutes, seconds = divmod(whole_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"

    @staticmethod
    def _timecode_label(milliseconds: int) -> str:
        """Return a filesystem-safe version of a timecode."""

        return EvidencePackageExporter._format_timecode(milliseconds).replace(":", "-").replace(".", "_")

    @staticmethod
    def _safe_filename(value: str) -> str:
        """Remove characters that do not belong in simple export filenames."""

        return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "export"

    @staticmethod
    def _create_package_dir(output_root: Path, package_name: str) -> Path:
        """Create a unique export package directory."""

        output_root.mkdir(parents=True, exist_ok=True)
        base_name = EvidencePackageExporter._safe_filename(package_name)
        package_dir = output_root / base_name
        suffix = 1
        while package_dir.exists():
            package_dir = output_root / f"{base_name}_{suffix:02d}"
            suffix += 1
        package_dir.mkdir(parents=True, exist_ok=False)
        return package_dir

    @staticmethod
    def _create_video_writer(path: Path, fps: float, width: int, height: int) -> tuple[Path, Any]:
        """Create a video writer, falling back to AVI/MJPG when MP4 fails."""

        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if writer.isOpened():
            return path, writer
        writer.release()

        fallback_path = path.with_suffix(".avi")
        fallback_writer = cv2.VideoWriter(
            str(fallback_path),
            cv2.VideoWriter_fourcc(*"MJPG"),
            fps,
            (width, height),
        )
        if fallback_writer.isOpened():
            return fallback_path, fallback_writer
        fallback_writer.release()
        return path, None

    @staticmethod
    def _sha256(path: Path) -> str:
        """Hash a file in chunks so large clips do not load into memory."""

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_readme(self, package_dir: Path, manifest_path: Path):
        """Write a short note explaining how to handle the export package."""

        readme_text = "\n".join(
            [
                "TeslaCam Evidence Export",
                "",
                "This package contains original Tesla source media when that option was enabled,",
                "plus derived stills or clip excerpts with burned-in context overlays.",
                "",
                "Recommendations:",
                "1. Preserve the original Tesla files and event.json unchanged.",
                "2. Keep this manifest with the exported media so hashes and source paths stay attached.",
                "3. Treat the annotated exports as demonstrative copies, not replacements for the originals.",
                "4. If counsel, an adjuster, or a court requests the original recording, provide the untouched source files too.",
                "",
                f"Manifest: {manifest_path.name}",
            ]
        )
        (package_dir / README_FILENAME).write_text(readme_text, encoding="utf-8")
