"""Camera naming helpers for TeslaCam clip folders.

Tesla filenames are mostly consistent, but newer vehicles and exported clips
can include angle names that older viewers do not recognize. This module keeps
those aliases in one place so folder discovery, display labels, and layout
ordering stay in sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


COMPOSITE_CLIP_KEY = "event_clip"
COMPOSITE_CLIP_LABEL = "Event Clip"
TIMESTAMPED_CAMERA_RE = re.compile(
    r"\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_(?P<camera>[a-z0-9_]+)$"
)


@dataclass(frozen=True, slots=True)
class CameraAngle:
    """Known Tesla camera angle and the aliases that identify it.

    Parameters
    ----------
    key:
        Stable internal name used by the viewer.
    label:
        User-facing label shown in the UI.
    aliases:
        Filename fragments that can identify this angle.
    layout_priority:
        Sort order for the multi-angle grid.
    main_priority:
        Preference order when choosing the default main view.
    """

    key: str
    label: str
    aliases: tuple[str, ...]
    layout_priority: int
    main_priority: int


CAMERA_ANGLES: tuple[CameraAngle, ...] = (
    CameraAngle("front_narrow", "Front Narrow", ("front_narrow", "narrow"), 5, 0),
    CameraAngle("front_fisheye", "Front Fisheye", ("front_fisheye", "fisheye"), 10, 1),
    CameraAngle(
        "front_bumper",
        "Front Bumper",
        ("front_bumper", "bumper_front", "bumper"),
        12,
        2,
    ),
    CameraAngle("front_wide", "Front Wide", ("front_wide", "wide"), 14, 3),
    CameraAngle("front", "Front", ("front",), 15, 4),
    CameraAngle("left_pillar", "Left Pillar", ("left_pillar", "leftpillar"), 20, 5),
    CameraAngle("left_repeater", "Left Repeater", ("left_repeater", "left"), 25, 6),
    CameraAngle("rear", "Rear", ("rear", "back"), 30, 7),
    CameraAngle("right_pillar", "Right Pillar", ("right_pillar", "rightpillar"), 35, 8),
    CameraAngle("right_repeater", "Right Repeater", ("right_repeater", "right"), 40, 9),
    CameraAngle("cabin", "Cabin", ("cabin", "interior", "inside"), 45, 10),
)

CAMERA_BY_KEY = {camera.key: camera for camera in CAMERA_ANGLES}


def detect_camera_key(filename: str) -> str | None:
    """Return the logical camera key for a Tesla clip filename.

    Parameters
    ----------
    filename:
        Filename or stem to inspect.

    Returns
    -------
    str | None
        Matching camera key, the composite event key, or ``None`` when the
        filename does not look like a supported camera clip.
    """

    normalized = filename.lower().replace("-", "_")
    if "event" in normalized:
        return COMPOSITE_CLIP_KEY

    timestamped_camera = detect_timestamped_camera_suffix(normalized)
    if timestamped_camera:
        for camera in CAMERA_ANGLES:
            if timestamped_camera == camera.key or timestamped_camera in camera.aliases:
                return camera.key
        return timestamped_camera

    for camera in CAMERA_ANGLES:
        if any(alias in normalized for alias in camera.aliases):
            return camera.key

    return None


def detect_timestamped_camera_suffix(normalized_filename: str) -> str | None:
    """Return an unknown camera suffix from a timestamped Tesla filename.

    This keeps the viewer forward-compatible with new Tesla camera names. A
    future file such as ``2026-01-01_12-00-00-new_angle.mp4`` can still load
    even before the app has a dedicated label for that camera.
    """

    match = TIMESTAMPED_CAMERA_RE.search(normalized_filename)
    if match is None:
        return None

    camera_key = match.group("camera").strip("_")
    return camera_key or None


def camera_label(camera_key: str | None) -> str:
    """Return a readable label for a camera key."""

    if camera_key == COMPOSITE_CLIP_KEY:
        return COMPOSITE_CLIP_LABEL

    if camera_key in CAMERA_BY_KEY:
        return CAMERA_BY_KEY[camera_key].label

    if not camera_key:
        return "Unknown"

    return camera_key.replace("_", " ").title()


def sort_camera_keys(camera_keys: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Sort camera keys into the preferred dashboard order."""

    return sorted(
        camera_keys,
        key=lambda key: (
            CAMERA_BY_KEY.get(key).layout_priority if key in CAMERA_BY_KEY else 10_000,
            key,
        ),
    )


def choose_primary_camera(camera_keys: list[str] | tuple[str, ...] | set[str]) -> str | None:
    """Choose the best default camera for the main viewer pane."""

    if not camera_keys:
        return None

    return min(
        camera_keys,
        key=lambda key: (
            CAMERA_BY_KEY.get(key).main_priority if key in CAMERA_BY_KEY else 10_000,
            key,
        ),
    )
