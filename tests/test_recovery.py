from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path

from teslacam_app.recovery import (
    RECOVERY_SOURCE_IMAGE,
    RecoveryCandidateResult,
    RecoveryOptions,
    RecoveryTuning,
    TUNING_PRESET_AGGRESSIVE,
    TUNING_PRESET_CONSERVATIVE,
    HardwareProfile,
    format_target_dates,
    matching_time,
    parse_iso_datetime,
    parse_target_dates,
    probe_candidate_and_carve,
    recommended_salvage_size_mb,
    salvage_window,
    tuning_for_preset,
)


class RecoveryHelperTests(unittest.TestCase):
    """Cover the pure recovery helper functions that drive the UI."""

    def setUp(self) -> None:
        self.profile = HardwareProfile(
            logical_cpus=8,
            physical_cpus=4,
            ram_gb=16.0,
            platform_name="TestOS",
        )

    def test_parse_target_dates_handles_comma_separated_input(self) -> None:
        parsed = parse_target_dates("2025-01-24, 2025-01-25, 2025-01-24")

        self.assertEqual(parsed, (date(2025, 1, 24), date(2025, 1, 25)))
        self.assertEqual(format_target_dates(parsed), "2025-01-24, 2025-01-25")

    def test_parse_iso_datetime_accepts_z_suffix(self) -> None:
        parsed = parse_iso_datetime("2025-01-24T19:19:17Z")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.year, 2025)
        self.assertEqual(parsed.minute, 19)

    def test_matching_time_supports_ranges_that_cross_midnight(self) -> None:
        timestamp = datetime(2025, 1, 24, 0, 15, 0)

        self.assertTrue(matching_time(timestamp, time(23, 0), time(1, 0)))
        self.assertFalse(matching_time(timestamp, time(1, 0), time(23, 0)))

    def test_tuning_presets_move_in_expected_directions(self) -> None:
        conservative = tuning_for_preset(TUNING_PRESET_CONSERVATIVE, self.profile)
        aggressive = tuning_for_preset(TUNING_PRESET_AGGRESSIVE, self.profile)

        self.assertLessEqual(conservative.max_workers, self.profile.physical_cpus)
        self.assertGreaterEqual(aggressive.max_workers, conservative.max_workers)
        self.assertGreaterEqual(aggressive.preview_bytes, conservative.preview_bytes)

    def test_candidate_confidence_labels_cover_key_outcomes(self) -> None:
        matched = RecoveryCandidateResult(1, "2025-01-24 19:19:17", True, 1024, "clip.mp4", "matched")
        scan_only = RecoveryCandidateResult(2, "2025-01-24 19:19:17", False, 0, None, "scan_only_match")
        low_confidence = RecoveryCandidateResult(3, None, False, 0, None, "no_timestamp")
        manual = RecoveryCandidateResult(4, "Manual salvage", True, 2048, "salvage.mp4", "manual_salvage")

        self.assertEqual(matched.confidence_label, "Timestamp matched")
        self.assertEqual(scan_only.confidence_label, "Strong candidate")
        self.assertEqual(low_confidence.confidence_label, "Low confidence")
        self.assertEqual(manual.confidence_label, "Manual salvage")

    def test_recommended_salvage_size_scales_with_hardware(self) -> None:
        small = HardwareProfile(logical_cpus=4, physical_cpus=2, ram_gb=8.0, platform_name="Small")
        large = HardwareProfile(logical_cpus=32, physical_cpus=16, ram_gb=96.0, platform_name="Large")

        self.assertEqual(recommended_salvage_size_mb(small), 512)
        self.assertEqual(recommended_salvage_size_mb(large), 2048)
        self.assertEqual(recommended_salvage_size_mb(large, source_size_hint=80 * 1024 * 1024), 80)

    def test_salvage_window_clamps_to_source_size(self) -> None:
        start, length = salvage_window(
            offset=100,
            max_bytes=500,
            total_size_hint=450,
            bytes_before=25,
        )

        self.assertEqual(start, 75)
        self.assertEqual(length, 375)

    def test_probe_candidate_can_report_scan_only_match(self) -> None:
        options = RecoveryOptions(
            source_path="dummy.bin",
            source_label="Image file: dummy.bin",
            output_dir=Path("."),
            target_dates=(date(2025, 1, 24),),
            filter_by_time=False,
            target_time_start=None,
            target_time_end=None,
            tuning=RecoveryTuning(
                chunk_size=1024,
                overlap=32,
                preview_bytes=1024,
                max_carve_bytes=4096,
                max_workers=1,
                max_pending_jobs=1,
            ),
            ffprobe_program="ffprobe",
            scan_only=True,
            source_kind=RECOVERY_SOURCE_IMAGE,
            drive=None,
            total_size_hint=0,
        )

        from unittest.mock import MagicMock, patch

        fake_handle = MagicMock()
        fake_handle.__enter__.return_value = fake_handle
        fake_handle.read.return_value = b"preview"

        with (
            patch("teslacam_app.recovery.open", return_value=fake_handle),
            patch(
                "teslacam_app.recovery.ffprobe_preview",
                return_value={"format": {"tags": {"creation_time": "2025-01-24T19:19:17"}}},
            ),
        ):
            result = probe_candidate_and_carve(
                options=options,
                offset=1234,
                is_cancelled=lambda: False,
            )

        self.assertEqual(result.status, "scan_only_match")
        self.assertIsNone(result.output_path)


if __name__ == "__main__":
    unittest.main()
