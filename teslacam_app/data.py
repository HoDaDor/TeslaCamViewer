"""Event metadata and clip discovery helpers for TeslaCam folders.

The viewer relies on this module to turn a raw directory on disk into a clean
``EventMetadata`` object that describes which camera angles exist, which clip
minute should be loaded, and which event details should be shown in the UI.
Keeping this logic separate from the window code makes it easier to test and
reason about the rules Tesla clip folders follow.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .cameras import (
    COMPOSITE_CLIP_KEY,
    choose_primary_camera,
    detect_camera_key,
    sort_camera_keys,
)


VIDEO_EXTENSIONS = frozenset({".mp4", ".mov"})
TIMESTAMP_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})")


@dataclass(slots=True)
class EventMetadata:
    """Normalized description of a TeslaCam event folder.

    Parameters
    ----------
    folder:
        Folder being inspected.
    camera_files:
        Mapping of logical camera keys to the chosen clip files for that event.
    composite_clip:
        Optional combined ``event.mp4`` clip when Tesla exported one.
    raw_event:
        Parsed ``event.json`` payload, if present.
    event_type:
        Human-readable event reason shown in the UI.
    city:
        Event city from ``event.json`` when available.
    camera_id:
        Tesla-reported camera identifier from ``event.json``.
    event_time:
        Parsed event timestamp.
    event_offset_ms:
        Offset from the chosen clip start to the event moment.
    gps_coords:
        Normalized latitude/longitude pair used by the map.
    selected_clip_start:
        Clip-minute timestamp chosen for synchronized playback.
    """

    folder: Path
    camera_files: dict[str, Path] = field(default_factory=dict)
    composite_clip: Path | None = None
    raw_event: dict = field(default_factory=dict)
    event_type: str = "Unknown"
    city: str | None = None
    camera_id: str | None = None
    event_time: datetime | None = None
    event_offset_ms: int = 0
    gps_coords: dict[str, float] | None = None
    selected_clip_start: datetime | None = None

    @property
    def ordered_camera_keys(self) -> list[str]:
        """Return camera keys in a stable UI-friendly order."""

        return sort_camera_keys(self.camera_files)

    @property
    def primary_camera_key(self) -> str | None:
        """Return the best default angle for the main viewer pane."""

        return choose_primary_camera(self.ordered_camera_keys)

    @property
    def has_camera_angles(self) -> bool:
        """Report whether any per-angle camera clips were discovered."""

        return bool(self.camera_files)


def load_event_metadata(folder: Path) -> EventMetadata:
    """Load event metadata and select the best playable clip set.

    Parameters
    ----------
    folder:
        Tesla event directory chosen by the user.

    Returns
    -------
    EventMetadata
        Normalized metadata used by the viewer, export flow, and recovery
        workspace suggestions.
    """

    folder = folder.resolve()
    raw_event = read_event_json(folder)
    event_time = parse_event_time(raw_event) if raw_event else None

    camera_files, composite_clip, selected_clip_start = discover_video_files(folder, event_time)
    metadata = EventMetadata(
        folder=folder,
        camera_files=camera_files,
        composite_clip=composite_clip,
        raw_event=dict(raw_event or {}),
        event_time=event_time,
        selected_clip_start=selected_clip_start,
    )

    if not raw_event:
        return metadata

    metadata.event_type = raw_event.get("reason", "Unknown")
    metadata.city = _safe_str(raw_event.get("city"))
    metadata.camera_id = _safe_str(raw_event.get("camera"))
    metadata.gps_coords = extract_gps_coords(raw_event)
    metadata.event_offset_ms = compute_event_offset_ms(
        clip_start_time=metadata.selected_clip_start,
        event_time=metadata.event_time,
    )
    return metadata


def discover_video_files(
    folder: Path, event_time: datetime | None
) -> tuple[dict[str, Path], Path | None, datetime | None]:
    """Find camera clips in a TeslaCam event folder.

    The folder may contain multiple clip minutes plus an optional composite
    export. We group per-angle clips by their timestamp, then choose the clip
    minute that most likely contains the event.
    """

    grouped_clips: dict[datetime, dict[str, Path]] = defaultdict(dict)
    composite_clip: Path | None = None

    for file_path in folder.iterdir():
        if file_path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        camera_key = detect_camera_key(file_path.stem)
        if camera_key is None:
            continue

        resolved_path = file_path.resolve()
        if camera_key == COMPOSITE_CLIP_KEY:
            composite_clip = resolved_path
            continue

        clip_start = parse_clip_timestamp(file_path.stem)
        if clip_start is None:
            continue

        grouped_clips[clip_start][camera_key] = resolved_path

    selected_clip_start = choose_clip_start(grouped_clips, event_time)
    selected_clips = dict(grouped_clips.get(selected_clip_start, {})) if selected_clip_start else {}
    return selected_clips, composite_clip, selected_clip_start


def choose_clip_start(
    grouped_clips: dict[datetime, dict[str, Path]], event_time: datetime | None
) -> datetime | None:
    """Choose the clip minute that best matches the event timestamp."""

    if not grouped_clips:
        return None

    clip_starts = sorted(grouped_clips)
    if event_time is None:
        return clip_starts[-1]

    candidate_starts = [clip_start for clip_start in clip_starts if clip_start <= event_time]
    if candidate_starts:
        return candidate_starts[-1]

    return min(
        clip_starts,
        key=lambda clip_start: abs((clip_start - event_time).total_seconds()),
    )


def read_event_json(folder: Path) -> dict | None:
    """Load the first JSON metadata file found in an event folder."""

    json_file = next(folder.glob("*.json"), None)
    if json_file is None:
        return None

    with json_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_event_time(data: dict | None) -> datetime | None:
    """Parse the event timestamp stored in ``event.json``."""

    if not data:
        return None

    timestamp = data.get("timestamp")
    if not timestamp:
        return None

    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


def extract_gps_coords(data: dict) -> dict[str, float] | None:
    """Extract validated latitude and longitude values from raw metadata."""

    latitude = _safe_float(data.get("est_lat"))
    longitude = _safe_float(data.get("est_lon"))
    if latitude is None or longitude is None:
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    return {"lat": latitude, "lon": longitude}


def compute_event_offset_ms(
    clip_start_time: datetime | None, event_time: datetime | None
) -> int:
    """Compute the seek position of the event within the chosen clip."""

    if clip_start_time is None or event_time is None:
        return 0

    return max(0, int((event_time - clip_start_time).total_seconds() * 1000))


def parse_clip_timestamp(filename: str) -> datetime | None:
    """Parse a Tesla clip timestamp from its filename stem."""

    match = TIMESTAMP_RE.search(filename)
    if match is None:
        return None

    date_part = match.group("date")
    time_part = match.group("time").replace("-", ":")
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}")
    except ValueError:
        return None


def _safe_float(value) -> float | None:
    """Convert a value to ``float`` without raising on bad metadata."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value) -> str | None:
    """Convert a metadata value to a stripped string or ``None``."""

    if value is None:
        return None

    text = str(value).strip()
    return text or None
