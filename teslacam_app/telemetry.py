"""Tesla dashcam telemetry extraction helpers.

Tesla's newer dashcam clips can carry vehicle telemetry as protobuf data inside
SEI NAL units. This module keeps that parsing logic out of the main Qt window
so the UI layer can simply ask for decoded samples and display them.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path


GEAR_LABELS = {
    0: "Park",
    1: "Drive",
    2: "Reverse",
    3: "Neutral",
}

AUTOPILOT_LABELS = {
    0: "Off",
    1: "FSD",
    2: "Autosteer",
    3: "TACC",
}


@dataclass(slots=True)
class TelemetrySample:
    """One decoded SEI telemetry sample from a Tesla dashcam clip."""

    version: int | None = None
    gear_state: int | None = None
    frame_seq_no: int | None = None
    vehicle_speed_mps: float | None = None
    accelerator_pedal_position: float | None = None
    steering_wheel_angle: float | None = None
    blinker_on_left: bool | None = None
    blinker_on_right: bool | None = None
    brake_applied: bool | None = None
    autopilot_state: int | None = None
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    heading_deg: float | None = None
    linear_acceleration_mps2_x: float | None = None
    linear_acceleration_mps2_y: float | None = None
    linear_acceleration_mps2_z: float | None = None


@dataclass(slots=True)
class TelemetrySeries:
    """Decoded telemetry series for one playable video clip."""

    source_path: Path
    samples: tuple[TelemetrySample, ...]

    @property
    def has_data(self) -> bool:
        """Return whether any telemetry samples were decoded."""

        return bool(self.samples)

    def sample_for_position(self, position_ms: int, duration_ms: int) -> TelemetrySample | None:
        """Return the sample that best matches a playback position."""

        if not self.samples:
            return None

        if len(self.samples) == 1 or duration_ms <= 0:
            return self.samples[0]

        clamped_position = min(max(position_ms, 0), duration_ms)
        ratio = clamped_position / duration_ms
        index = min(len(self.samples) - 1, max(0, round(ratio * (len(self.samples) - 1))))
        return self.samples[index]


def load_telemetry_series(video_path: Path) -> TelemetrySeries | None:
    """Decode all supported telemetry samples embedded in a dashcam clip."""

    try:
        with video_path.open("rb") as handle:
            offset, size = find_mdat(handle)
            samples = [
                sample
                for nal in iter_nals(handle, offset, size)
                if (sample := parse_sei_metadata(extract_proto_payload(nal) or b"")) is not None
            ]
    except OSError:
        return None
    except RuntimeError:
        return None

    if not samples:
        return None

    return TelemetrySeries(source_path=video_path.resolve(), samples=tuple(samples))


def parse_sei_metadata(payload: bytes) -> TelemetrySample | None:
    """Decode Tesla's published protobuf payload without extra dependencies."""

    if not payload:
        return None

    sample = TelemetrySample()
    offset = 0
    payload_length = len(payload)

    try:
        while offset < payload_length:
            key, offset = read_varint(payload, offset)
            field_number = key >> 3
            wire_type = key & 0x07

            if wire_type == 0:
                value, offset = read_varint(payload, offset)
            elif wire_type == 1:
                value, offset = read_fixed64(payload, offset)
            elif wire_type == 5:
                value, offset = read_fixed32(payload, offset)
            elif wire_type == 2:
                value, offset = read_length_delimited(payload, offset)
            else:
                return None

            assign_field(sample, field_number, wire_type, value)
    except (IndexError, ValueError, struct.error):
        return None

    if all(
        value is None
        for value in (
            sample.version,
            sample.gear_state,
            sample.frame_seq_no,
            sample.vehicle_speed_mps,
            sample.accelerator_pedal_position,
            sample.steering_wheel_angle,
            sample.blinker_on_left,
            sample.blinker_on_right,
            sample.brake_applied,
            sample.autopilot_state,
            sample.latitude_deg,
            sample.longitude_deg,
            sample.heading_deg,
            sample.linear_acceleration_mps2_x,
            sample.linear_acceleration_mps2_y,
            sample.linear_acceleration_mps2_z,
        )
    ):
        return None

    return sample


def assign_field(sample: TelemetrySample, field_number: int, wire_type: int, value):
    """Map a parsed protobuf field into the ``TelemetrySample`` dataclass."""

    if field_number == 1 and wire_type == 0:
        sample.version = int(value)
    elif field_number == 2 and wire_type == 0:
        sample.gear_state = int(value)
    elif field_number == 3 and wire_type == 0:
        sample.frame_seq_no = int(value)
    elif field_number == 4 and wire_type == 5:
        sample.vehicle_speed_mps = value
    elif field_number == 5 and wire_type == 5:
        sample.accelerator_pedal_position = value
    elif field_number == 6 and wire_type == 5:
        sample.steering_wheel_angle = value
    elif field_number == 7 and wire_type == 0:
        sample.blinker_on_left = bool(value)
    elif field_number == 8 and wire_type == 0:
        sample.blinker_on_right = bool(value)
    elif field_number == 9 and wire_type == 0:
        sample.brake_applied = bool(value)
    elif field_number == 10 and wire_type == 0:
        sample.autopilot_state = int(value)
    elif field_number == 11 and wire_type == 1:
        sample.latitude_deg = value
    elif field_number == 12 and wire_type == 1:
        sample.longitude_deg = value
    elif field_number == 13 and wire_type == 1:
        sample.heading_deg = value
    elif field_number == 14 and wire_type == 1:
        sample.linear_acceleration_mps2_x = value
    elif field_number == 15 and wire_type == 1:
        sample.linear_acceleration_mps2_y = value
    elif field_number == 16 and wire_type == 1:
        sample.linear_acceleration_mps2_z = value


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read one protobuf varint starting at ``offset``."""

    result = 0
    shift = 0

    while True:
        if offset >= len(data):
            raise IndexError("Truncated varint")

        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift

        if not (byte & 0x80):
            return result, offset

        shift += 7
        if shift > 63:
            raise ValueError("Varint is too large")


def read_fixed32(data: bytes, offset: int) -> tuple[float, int]:
    """Read a protobuf fixed32 value and decode it as ``float``."""

    end = offset + 4
    return struct.unpack("<f", data[offset:end])[0], end


def read_fixed64(data: bytes, offset: int) -> tuple[float, int]:
    """Read a protobuf fixed64 value and decode it as ``double``."""

    end = offset + 8
    return struct.unpack("<d", data[offset:end])[0], end


def read_length_delimited(data: bytes, offset: int) -> tuple[bytes, int]:
    """Read a protobuf length-delimited field."""

    length, offset = read_varint(data, offset)
    end = offset + length
    if end > len(data):
        raise IndexError("Truncated length-delimited field")
    return data[offset:end], end


def iter_nals(handle, offset: int, size: int):
    """Yield SEI user-data NAL units from a Tesla dashcam ``mdat`` atom."""

    sei_nal_type = 6
    sei_user_data_type = 5

    handle.seek(offset)
    consumed = 0

    while size == 0 or consumed < size:
        header = handle.read(4)
        if len(header) < 4:
            break

        nal_size = struct.unpack(">I", header)[0]
        if nal_size < 2:
            handle.seek(nal_size, 1)
            consumed += 4 + nal_size
            continue

        first_two = handle.read(2)
        if len(first_two) != 2:
            break

        if (first_two[0] & 0x1F) != sei_nal_type or first_two[1] != sei_user_data_type:
            handle.seek(nal_size - 2, 1)
            consumed += 4 + nal_size
            continue

        rest = handle.read(nal_size - 2)
        if len(rest) != nal_size - 2:
            break

        consumed += 4 + nal_size
        yield first_two + rest


def extract_proto_payload(nal: bytes) -> bytes | None:
    """Extract the protobuf payload from Tesla's user-data SEI NAL format."""

    if len(nal) < 4:
        return None

    for index in range(3, len(nal) - 1):
        marker = nal[index]
        if marker == 0x42:
            continue
        if marker == 0x69 and index > 2:
            return strip_emulation_prevention_bytes(nal[index + 1 : -1])
        break

    return None


def strip_emulation_prevention_bytes(data: bytes) -> bytes:
    """Remove ``0x03`` bytes inserted after ``0x00 0x00`` in H.264 streams."""

    stripped = bytearray()
    zero_count = 0

    for byte in data:
        if zero_count >= 2 and byte == 0x03:
            zero_count = 0
            continue

        stripped.append(byte)
        zero_count = zero_count + 1 if byte == 0x00 else 0

    return bytes(stripped)


def find_mdat(handle) -> tuple[int, int]:
    """Return the payload offset and size of the first ``mdat`` atom."""

    handle.seek(0)

    while True:
        header = handle.read(8)
        if len(header) < 8:
            raise RuntimeError("mdat atom not found")

        size32, atom_type = struct.unpack(">I4s", header)
        if size32 == 1:
            extended_size = handle.read(8)
            if len(extended_size) != 8:
                raise RuntimeError("truncated extended atom size")
            atom_size = struct.unpack(">Q", extended_size)[0]
            header_size = 16
        else:
            atom_size = size32
            header_size = 8

        if atom_type == b"mdat":
            payload_size = atom_size - header_size if atom_size else 0
            return handle.tell(), payload_size

        if atom_size and atom_size < header_size:
            raise RuntimeError("invalid MP4 atom size")

        handle.seek(atom_size - header_size, 1)


def gear_label(value: int | None) -> str:
    """Return a readable gear-state label."""

    return GEAR_LABELS.get(value, "Unknown")


def autopilot_label(value: int | None) -> str:
    """Return a readable driver-assist label."""

    return AUTOPILOT_LABELS.get(value, "Unknown")


def speed_label(speed_mps: float | None) -> str:
    """Return a dual-unit speed string."""

    if speed_mps is None:
        return "Not available"

    mph = speed_mps * 2.23694
    kmh = speed_mps * 3.6
    return f"{mph:.1f} mph ({kmh:.1f} km/h)"


def pedal_label(sample: TelemetrySample) -> str:
    """Summarize accelerator and brake activity in one short string."""

    accelerator_value = sample.accelerator_pedal_position
    if accelerator_value is None:
        accelerator_text = "Throttle unavailable"
    else:
        normalized = accelerator_value * 100 if accelerator_value <= 1.0 else accelerator_value
        accelerator_text = f"Throttle {normalized:.0f}%"

    brake_text = "Brake on" if sample.brake_applied else "Brake off"
    if sample.brake_applied is None:
        brake_text = "Brake unavailable"

    return f"{accelerator_text} | {brake_text}"


def signals_label(sample: TelemetrySample) -> str:
    """Summarize turn-signal state in a readable way."""

    left = bool(sample.blinker_on_left)
    right = bool(sample.blinker_on_right)

    if sample.blinker_on_left is None and sample.blinker_on_right is None:
        return "Not available"
    if left and right:
        return "Hazards / both"
    if left:
        return "Left"
    if right:
        return "Right"
    return "Off"


def angle_label(angle_deg: float | None) -> str:
    """Format steering or heading angles consistently."""

    if angle_deg is None or math.isnan(angle_deg):
        return "Not available"
    return f"{angle_deg:.1f}°"


def position_label(sample: TelemetrySample) -> str:
    """Format latitude and longitude when they are available."""

    if sample.latitude_deg is None or sample.longitude_deg is None:
        return "Not available"
    return f"{sample.latitude_deg:.6f}, {sample.longitude_deg:.6f}"


def acceleration_label(sample: TelemetrySample) -> str:
    """Format the linear acceleration vector for compact display."""

    axes = (
        sample.linear_acceleration_mps2_x,
        sample.linear_acceleration_mps2_y,
        sample.linear_acceleration_mps2_z,
    )
    if any(value is None for value in axes):
        return "Not available"

    return "x {0:.2f} | y {1:.2f} | z {2:.2f} m/s²".format(*axes)
