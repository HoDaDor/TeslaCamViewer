"""Qt-friendly recovery engine helpers for overwritten TeslaCam footage.

The recovery workspace intentionally keeps raw-device scanning logic out of the
viewer module. This module contains the pure data and probing helpers that the
Qt UI orchestrates with threads, making the recovery feature easier to tune,
test, and document without tangling it with widget code.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import threading
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable

import psutil


DEFAULT_OVERLAP = 32
FFPROBE_CANDIDATES = ("ffprobe.exe", "ffprobe")
RECOVERY_SOURCE_DRIVE = "drive"
RECOVERY_SOURCE_IMAGE = "image"
TUNING_PRESET_RECOMMENDED = "recommended"
TUNING_PRESET_CONSERVATIVE = "conservative"
TUNING_PRESET_AGGRESSIVE = "aggressive"
MIN_EXTRA_SALVAGE_MB = 256
MAX_EXTRA_SALVAGE_MB = 4096


@dataclass(frozen=True, slots=True)
class DriveInfo:
    """Description of one mounted drive candidate for recovery scanning."""

    device: str
    mountpoint: str
    fstype: str
    total_gb: float
    used_gb: float

    @property
    def display_name(self) -> str:
        """Return a concise label suitable for combo boxes and logs."""

        return (
            f"{self.device}  ({self.fstype}, {self.total_gb:.1f} GB total, "
            f"{self.used_gb:.1f} GB used)"
        )


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """Snapshot of the local machine used for auto-tuning recovery settings."""

    logical_cpus: int
    physical_cpus: int
    ram_gb: float
    platform_name: str

    @property
    def summary(self) -> str:
        """Return a human-readable system summary for the recovery UI."""

        return (
            f"{self.platform_name} | logical CPU: {self.logical_cpus}, "
            f"physical CPU: {self.physical_cpus}, RAM: {self.ram_gb:.1f} GB"
        )


@dataclass(frozen=True, slots=True)
class RecoveryTuning:
    """Low-level performance knobs for the recovery scanner."""

    chunk_size: int
    overlap: int
    preview_bytes: int
    max_carve_bytes: int
    max_workers: int
    max_pending_jobs: int

    def to_settings_dict(self) -> dict[str, int]:
        """Serialize tuning values into the YAML-friendly settings shape."""

        return {
            "chunk_size_mb": self.chunk_size // (1024 * 1024),
            "overlap_bytes": self.overlap,
            "preview_bytes_mb": self.preview_bytes // (1024 * 1024),
            "max_carve_bytes_mb": self.max_carve_bytes // (1024 * 1024),
            "max_workers": self.max_workers,
            "max_pending_jobs": self.max_pending_jobs,
        }

    @classmethod
    def from_settings_dict(
        cls,
        data: dict,
        *,
        fallback: "RecoveryTuning",
    ) -> "RecoveryTuning":
        """Create a tuning object from persisted settings with sane fallbacks."""

        return cls(
            chunk_size=max(1, int(data.get("chunk_size_mb", fallback.chunk_size // (1024 * 1024))))
            * 1024
            * 1024,
            overlap=max(1, int(data.get("overlap_bytes", fallback.overlap))),
            preview_bytes=max(
                1,
                int(data.get("preview_bytes_mb", fallback.preview_bytes // (1024 * 1024))),
            )
            * 1024
            * 1024,
            max_carve_bytes=max(
                1,
                int(data.get("max_carve_bytes_mb", fallback.max_carve_bytes // (1024 * 1024))),
            )
            * 1024
            * 1024,
            max_workers=max(1, int(data.get("max_workers", fallback.max_workers))),
            max_pending_jobs=max(
                1,
                int(data.get("max_pending_jobs", fallback.max_pending_jobs)),
            ),
        )


@dataclass(frozen=True, slots=True)
class RecoveryOptions:
    """Validated runtime options for a recovery scan session."""

    source_path: str
    source_label: str
    output_dir: Path
    target_dates: tuple[date, ...]
    filter_by_time: bool
    target_time_start: time | None
    target_time_end: time | None
    tuning: RecoveryTuning
    ffprobe_program: str
    scan_only: bool = False
    source_kind: str = RECOVERY_SOURCE_DRIVE
    drive: DriveInfo | None = None
    total_size_hint: int = 0


@dataclass(frozen=True, slots=True)
class RecoveryCandidateResult:
    """Outcome of probing one plausible MP4 header candidate."""

    offset: int
    timestamp_text: str | None
    matched: bool
    bytes_written: int
    output_path: str | None
    status: str

    @property
    def confidence_label(self) -> str:
        """Return a simple user-facing confidence label for the result."""

        if self.status == "matched":
            return "Timestamp matched"
        if self.status == "scan_only_match":
            return "Strong candidate"
        if self.status == "manual_salvage":
            return "Manual salvage"
        if self.status in {"time_mismatch", "date_mismatch"}:
            return "Filtered out"
        if self.status == "no_timestamp":
            return "Low confidence"
        return "Uncertain"


class RecoverySharedState:
    """Thread-safe counters shared between the UI coordinator and workers."""

    def __init__(self):
        self._lock = threading.Lock()
        self.pending_jobs = 0
        self.total_candidates = 0
        self.carved_count = 0
        self.match_count = 0
        self.total_output_bytes = 0
        self.processed_jobs = 0

    def note_candidate_seen(self):
        """Record that a plausible MP4 candidate has been queued for probing."""

        with self._lock:
            self.total_candidates += 1
            self.pending_jobs += 1

    def note_candidate_finished(self, result: RecoveryCandidateResult):
        """Apply the result of one finished probe-and-carve worker task."""

        with self._lock:
            self.pending_jobs = max(0, self.pending_jobs - 1)
            self.processed_jobs += 1
            if result.status in {"matched", "scan_only_match"}:
                self.match_count += 1
            if result.matched:
                self.carved_count += 1
                self.total_output_bytes += result.bytes_written

    def snapshot(self) -> dict[str, int]:
        """Return a stable copy of the current aggregate progress counters."""

        with self._lock:
            return {
                "pending_jobs": self.pending_jobs,
                "total_candidates": self.total_candidates,
                "carved_count": self.carved_count,
                "match_count": self.match_count,
                "total_output_bytes": self.total_output_bytes,
                "processed_jobs": self.processed_jobs,
            }


def detect_hardware_profile() -> HardwareProfile:
    """Inspect CPU and memory capacity for automatic recovery tuning."""

    import platform

    logical = psutil.cpu_count(logical=True) or 4
    physical = psutil.cpu_count(logical=False) or max(2, logical // 2)
    ram_gb = psutil.virtual_memory().total / (1024**3)
    return HardwareProfile(
        logical_cpus=logical,
        physical_cpus=physical,
        ram_gb=ram_gb,
        platform_name=platform.platform(),
    )


def recommended_tuning(profile: HardwareProfile | None = None) -> RecoveryTuning:
    """Choose a balanced recovery tuning profile for the current machine.

    The goal here is to be conservative enough for typical desktops while
    still scaling up reasonably on higher-core, higher-memory systems.
    """

    profile = profile or detect_hardware_profile()
    ram_gb = profile.ram_gb
    physical = profile.physical_cpus

    if ram_gb < 8:
        chunk_mb, preview_mb, carve_mb, workers = 8, 4, 32, 2
    elif ram_gb < 16:
        chunk_mb, preview_mb, carve_mb, workers = 12, 8, 48, min(3, physical)
    elif ram_gb < 32:
        chunk_mb, preview_mb, carve_mb, workers = 16, 12, 64, min(4, physical)
    elif ram_gb < 64:
        chunk_mb, preview_mb, carve_mb, workers = 24, 16, 80, min(6, physical)
    else:
        chunk_mb, preview_mb, carve_mb, workers = 32, 24, 96, min(8, physical)

    pending_jobs = max(8, workers * 6)
    return RecoveryTuning(
        chunk_size=chunk_mb * 1024 * 1024,
        overlap=DEFAULT_OVERLAP,
        preview_bytes=preview_mb * 1024 * 1024,
        max_carve_bytes=carve_mb * 1024 * 1024,
        max_workers=max(1, workers),
        max_pending_jobs=max(1, pending_jobs),
    )


def recommended_salvage_size_mb(
    profile: HardwareProfile | None = None,
    *,
    source_size_hint: int = 0,
) -> int:
    """Choose a practical larger-carve size for extra salvage attempts.

    Normal recovery carves small bounded clips so bad candidates do not dump a
    huge amount of data. Extra salvage is the fallback path for a promising
    offset, so it can be larger while still staying conservative enough for
    ordinary users and slower external drives.
    """

    profile = profile or detect_hardware_profile()
    if profile.ram_gb >= 64 and profile.logical_cpus >= 16:
        size_mb = 2048
    elif profile.ram_gb >= 32 and profile.logical_cpus >= 8:
        size_mb = 1024
    else:
        size_mb = 512

    size_mb = max(MIN_EXTRA_SALVAGE_MB, min(MAX_EXTRA_SALVAGE_MB, size_mb))
    if source_size_hint > 0:
        source_mb = max(1, (source_size_hint + 1024 * 1024 - 1) // (1024 * 1024))
        size_mb = min(size_mb, source_mb)
    return size_mb


def tuning_for_preset(
    preset: str,
    profile: HardwareProfile | None = None,
) -> RecoveryTuning:
    """Return tuning values for a named UI preset."""

    profile = profile or detect_hardware_profile()
    base = recommended_tuning(profile)

    if preset == TUNING_PRESET_CONSERVATIVE:
        workers = max(1, min(base.max_workers, profile.physical_cpus // 2 or 1))
        return RecoveryTuning(
            chunk_size=max(4, base.chunk_size // (1024 * 1024) // 2) * 1024 * 1024,
            overlap=base.overlap,
            preview_bytes=max(4, base.preview_bytes // (1024 * 1024) // 2) * 1024 * 1024,
            max_carve_bytes=max(24, int(base.max_carve_bytes / (1024 * 1024) * 0.75))
            * 1024
            * 1024,
            max_workers=workers,
            max_pending_jobs=max(4, workers * 4),
        )

    if preset == TUNING_PRESET_AGGRESSIVE:
        workers = min(max(base.max_workers + 2, profile.physical_cpus), profile.logical_cpus)
        return RecoveryTuning(
            chunk_size=min(64, int(base.chunk_size / (1024 * 1024) * 1.5)) * 1024 * 1024,
            overlap=base.overlap,
            preview_bytes=min(64, int(base.preview_bytes / (1024 * 1024) * 1.5)) * 1024 * 1024,
            max_carve_bytes=min(192, int(base.max_carve_bytes / (1024 * 1024) * 1.5))
            * 1024
            * 1024,
            max_workers=max(1, workers),
            max_pending_jobs=max(8, workers * 8),
        )

    return base


def list_windows_drives() -> list[DriveInfo]:
    """Enumerate mounted Windows drives that could contain TeslaCam media."""

    drives: list[DriveInfo] = []
    for partition in psutil.disk_partitions(all=False):
        if not partition.fstype:
            continue

        try:
            usage = psutil.disk_usage(partition.mountpoint)
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
        except Exception:
            total_gb = 0.0
            used_gb = 0.0

        drives.append(
            DriveInfo(
                device=partition.device,
                mountpoint=partition.mountpoint,
                fstype=partition.fstype,
                total_gb=total_gb,
                used_gb=used_gb,
            )
        )
    return drives


def build_raw_path_from_mount(mountpoint: str) -> str:
    """Convert a Windows drive mount into the raw device path syntax."""

    drive_letter = mountpoint[0].upper()
    return f"\\\\.\\{drive_letter}:"


def drive_size_hint(drive: DriveInfo) -> int:
    """Estimate the total readable byte size of a mounted drive."""

    try:
        return int(psutil.disk_usage(drive.mountpoint).total)
    except Exception:
        return int(drive.total_gb * (1024**3))


def image_size_hint(image_path: Path) -> int:
    """Return the size of a raw image file used as a recovery source."""

    try:
        return int(image_path.stat().st_size)
    except OSError:
        return 0


def ffprobe_program() -> str | None:
    """Locate an ``ffprobe`` executable on the current ``PATH``."""

    for candidate in FFPROBE_CANDIDATES:
        if resolved := shutil.which(candidate):
            return resolved
    return None


def is_windows_admin() -> bool:
    """Report whether the current Windows process has administrator rights."""

    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def parse_target_dates(text: str) -> tuple[date, ...]:
    """Parse comma-separated recovery dates from the UI text field."""

    parts = [part.strip() for part in text.split(",") if part.strip()]
    parsed: list[date] = []
    for part in parts:
        parsed.append(datetime.strptime(part, "%Y-%m-%d").date())
    return tuple(dict.fromkeys(parsed))


def format_target_dates(target_dates: tuple[date, ...] | list[date]) -> str:
    """Format target dates for redisplay in the recovery UI."""

    return ", ".join(target_date.isoformat() for target_date in target_dates)


def format_bytes(num: float) -> str:
    """Format a byte count using compact human-readable units."""

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def is_plausible_mp4_header(buf: bytes, idx: int) -> bool:
    """Apply a cheap sanity check before sending a candidate to ``ffprobe``."""

    if idx < 4:
        return False

    size = struct.unpack(">I", buf[idx - 4 : idx])[0]
    if size < 28:
        return False
    if size > 1024 * 1024 * 1024:
        return False

    if idx + 8 > len(buf):
        return False

    brand = buf[idx + 4 : idx + 8]
    return all(32 <= byte <= 126 for byte in brand)


def probe_candidate_and_carve(
    *,
    options: RecoveryOptions,
    offset: int,
    is_cancelled: Callable[[], bool],
) -> RecoveryCandidateResult:
    """Probe one candidate offset and carve it when it matches the filters.

    The workflow is intentionally staged:

    1. read only a preview window from the raw source
    2. ask ``ffprobe`` whether that preview looks like a real clip
    3. apply date/time filters
    4. carve a bounded output file only for matches
    """

    if is_cancelled():
        return RecoveryCandidateResult(offset, None, False, 0, None, "cancelled")

    try:
        with open(options.source_path, "rb") as device_handle:
            device_handle.seek(offset, os.SEEK_SET)
            preview = device_handle.read(options.tuning.preview_bytes)
    except OSError as exc:
        return RecoveryCandidateResult(offset, f"READ_ERROR: {exc}", False, 0, None, "read_error")

    if not preview:
        return RecoveryCandidateResult(offset, None, False, 0, None, "empty_preview")

    metadata = ffprobe_preview(preview, options.ffprobe_program)
    if metadata is None:
        return RecoveryCandidateResult(offset, None, False, 0, None, "no_timestamp")

    timestamp = extract_creation_timestamp(metadata)
    if timestamp is None:
        return RecoveryCandidateResult(offset, None, False, 0, None, "no_timestamp")

    timestamp_text = display_timestamp(timestamp)
    if matching_date(timestamp) not in options.target_dates:
        return RecoveryCandidateResult(offset, timestamp_text, False, 0, None, "date_mismatch")
    if options.filter_by_time and not matching_time(
        timestamp,
        options.target_time_start,
        options.target_time_end,
    ):
        return RecoveryCandidateResult(offset, timestamp_text, False, 0, None, "time_mismatch")

    if is_cancelled():
        return RecoveryCandidateResult(offset, timestamp_text, False, 0, None, "cancelled")

    if options.scan_only:
        return RecoveryCandidateResult(
            offset=offset,
            timestamp_text=timestamp_text,
            matched=False,
            bytes_written=0,
            output_path=None,
            status="scan_only_match",
        )

    output_path = options.output_dir / f"carved_off{offset}.mp4"
    bytes_written = carve_clip(
        source_path=options.source_path,
        output_path=output_path,
        offset=offset,
        max_bytes=options.tuning.max_carve_bytes,
        chunk_size=options.tuning.chunk_size,
        is_cancelled=is_cancelled,
    )
    return RecoveryCandidateResult(
        offset=offset,
        timestamp_text=timestamp_text,
        matched=bytes_written > 0,
        bytes_written=bytes_written,
        output_path=str(output_path) if bytes_written > 0 else None,
        status="matched" if bytes_written > 0 else "cancelled",
    )


def ffprobe_preview(preview: bytes, program: str) -> dict | None:
    """Run ``ffprobe`` against in-memory preview bytes and parse its JSON."""

    try:
        result = subprocess.run(
            [
                program,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-i",
                "pipe:0",
            ],
            input=preview,
            capture_output=True,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0 or not result.stdout:
        return None

    try:
        return json.loads(result.stdout.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return None


def extract_creation_timestamp(metadata: dict) -> datetime | None:
    """Extract the most useful creation timestamp from ``ffprobe`` output."""

    tags = metadata.get("format", {}).get("tags", {}) or {}
    candidates = [
        tags.get("creation_time"),
        tags.get("com.apple.quicktime.creationdate"),
    ]
    for raw_value in candidates:
        if not raw_value:
            continue

        parsed = parse_iso_datetime(raw_value.strip())
        if parsed is not None:
            return parsed
    return None


def parse_iso_datetime(value: str) -> datetime | None:
    """Parse Tesla/FFmpeg-style ISO-like timestamps with tolerant fallbacks."""

    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass

    for separator in ("+", "-"):
        if separator in candidate[10:]:
            base = candidate.split(separator, 1)[0]
            try:
                return datetime.fromisoformat(base)
            except ValueError:
                continue
    return None


def matching_date(value: datetime) -> date:
    """Convert a timestamp into the local date used for user filtering."""

    if value.tzinfo is not None:
        return value.astimezone().date()
    return value.date()


def display_timestamp(value: datetime) -> str:
    """Format a timestamp for logs and recovered-results tables."""

    if value.tzinfo is not None:
        return value.astimezone().isoformat(sep=" ", timespec="seconds")
    return value.isoformat(sep=" ", timespec="seconds")


def matching_time(value: datetime, start: time | None, end: time | None) -> bool:
    """Evaluate whether a timestamp falls within the optional time filter."""

    if start is None or end is None:
        return True

    local_time = value.astimezone().time() if value.tzinfo is not None else value.time()
    if start <= end:
        return start <= local_time <= end
    return local_time >= start or local_time <= end


def salvage_window(
    *,
    offset: int,
    max_bytes: int,
    total_size_hint: int = 0,
    bytes_before: int = 0,
) -> tuple[int, int]:
    """Return the bounded byte range for a manual/extra salvage carve.

    ``offset`` is normally the beginning of a plausible MP4 header. The optional
    ``bytes_before`` value is kept for future deep-recovery use, but the UI uses
    zero by default so the output still starts at the detected MP4 header.
    """

    if offset < 0:
        raise ValueError("offset must be zero or greater")
    if max_bytes <= 0:
        return max(0, offset - max(0, bytes_before)), 0

    start_offset = max(0, offset - max(0, bytes_before))
    end_offset = start_offset + max_bytes
    if total_size_hint > 0:
        end_offset = min(end_offset, total_size_hint)
    return start_offset, max(0, end_offset - start_offset)


def carve_clip(
    *,
    source_path: str,
    output_path: Path,
    offset: int,
    max_bytes: int,
    chunk_size: int,
    is_cancelled: Callable[[], bool],
    total_size_hint: int = 0,
    bytes_before: int = 0,
) -> int:
    """Copy a bounded byte range from the source into a carved MP4 file.

    The carve step is intentionally size-limited so a bad candidate cannot
    cause the tool to dump arbitrarily large data into the output directory.
    """

    bytes_written = 0
    start_offset, remaining = salvage_window(
        offset=offset,
        max_bytes=max_bytes,
        total_size_hint=total_size_hint,
        bytes_before=bytes_before,
    )
    with open(source_path, "rb") as source_handle:
        source_handle.seek(start_offset, os.SEEK_SET)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as destination_handle:
            while remaining > 0 and not is_cancelled():
                to_read = min(chunk_size, remaining)
                data = source_handle.read(to_read)
                if not data:
                    break
                destination_handle.write(data)
                remaining -= len(data)
                bytes_written += len(data)

    if is_cancelled() and output_path.exists() and bytes_written == 0:
        output_path.unlink(missing_ok=True)
    return bytes_written
