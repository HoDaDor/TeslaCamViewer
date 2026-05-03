"""Tests for Tesla dashcam telemetry extraction."""

from __future__ import annotations

import struct
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from teslacam_app.telemetry import (
    TelemetrySample,
    TelemetrySeries,
    load_telemetry_series,
    parse_sei_metadata,
    strip_emulation_prevention_bytes,
)


def encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint for synthetic test payloads."""

    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte | 0x80)
        else:
            encoded.append(byte)
            return bytes(encoded)


def encode_key(field_number: int, wire_type: int) -> bytes:
    """Encode a protobuf field key."""

    return encode_varint((field_number << 3) | wire_type)


def build_payload() -> bytes:
    """Create one synthetic Tesla telemetry protobuf payload."""

    return b"".join(
        [
            encode_key(1, 0),
            encode_varint(1),
            encode_key(2, 0),
            encode_varint(1),
            encode_key(3, 0),
            encode_varint(42),
            encode_key(4, 5),
            struct.pack("<f", 15.5),
            encode_key(5, 5),
            struct.pack("<f", 0.25),
            encode_key(6, 5),
            struct.pack("<f", -8.5),
            encode_key(7, 0),
            encode_varint(1),
            encode_key(9, 0),
            encode_varint(0),
            encode_key(10, 0),
            encode_varint(2),
            encode_key(11, 1),
            struct.pack("<d", 12.345678),
            encode_key(12, 1),
            struct.pack("<d", -45.678901),
            encode_key(13, 1),
            struct.pack("<d", 185.0),
            encode_key(14, 1),
            struct.pack("<d", 0.1),
            encode_key(15, 1),
            struct.pack("<d", -0.2),
            encode_key(16, 1),
            struct.pack("<d", 9.8),
        ]
    )


def build_sei_mp4(payload: bytes) -> bytes:
    """Wrap a payload in a minimal MP4 ``mdat`` atom for parser tests."""

    nal = b"\x06\x05\x00\x69" + payload + b"\x80"
    nal_block = struct.pack(">I", len(nal)) + nal
    atom_size = 8 + len(nal_block)
    return struct.pack(">I4s", atom_size, b"mdat") + nal_block


class TelemetryTests(unittest.TestCase):
    """Cover the Tesla-specific telemetry parsing helpers."""

    def test_parse_sei_metadata_decodes_expected_fields(self):
        sample = parse_sei_metadata(build_payload())

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample.frame_seq_no, 42)
        self.assertAlmostEqual(sample.vehicle_speed_mps or 0.0, 15.5, places=3)
        self.assertAlmostEqual(sample.accelerator_pedal_position or 0.0, 0.25, places=3)
        self.assertAlmostEqual(sample.steering_wheel_angle or 0.0, -8.5, places=3)
        self.assertTrue(sample.blinker_on_left)
        self.assertFalse(sample.brake_applied)
        self.assertEqual(sample.autopilot_state, 2)
        self.assertAlmostEqual(sample.latitude_deg or 0.0, 12.345678, places=6)
        self.assertAlmostEqual(sample.longitude_deg or 0.0, -45.678901, places=6)

    def test_load_telemetry_series_reads_synthetic_mp4(self):
        payload = build_payload()
        video_path = Path("sample-front.mp4")
        fake_file = BytesIO(build_sei_mp4(payload))
        with mock.patch.object(Path, "open", return_value=fake_file):
            series = load_telemetry_series(video_path)

        self.assertIsNotNone(series)
        assert series is not None
        self.assertEqual(len(series.samples), 1)
        self.assertEqual(series.samples[0].frame_seq_no, 42)

    def test_sample_for_position_uses_reasonable_indexing(self):
        series = TelemetrySeries(
            source_path=Path("sample.mp4"),
            samples=(
                TelemetrySample(frame_seq_no=1),
                TelemetrySample(frame_seq_no=2),
                TelemetrySample(frame_seq_no=3),
            ),
        )

        self.assertEqual(series.sample_for_position(0, 900).frame_seq_no, 1)
        self.assertEqual(series.sample_for_position(450, 900).frame_seq_no, 2)
        self.assertEqual(series.sample_for_position(900, 900).frame_seq_no, 3)

    def test_strip_emulation_prevention_bytes_removes_inserted_markers(self):
        raw = b"\x00\x00\x03\x69\x00\x00\x03\x01"
        self.assertEqual(strip_emulation_prevention_bytes(raw), b"\x00\x00\x69\x00\x00\x01")


if __name__ == "__main__":
    unittest.main()
