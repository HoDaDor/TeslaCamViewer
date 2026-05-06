"""Tests for TeslaCam camera angle naming helpers."""

from __future__ import annotations

import unittest

from teslacam_app.cameras import camera_label, detect_camera_key, sort_camera_keys


class CameraNamingTests(unittest.TestCase):
    """Cover known and future-facing TeslaCam angle detection."""

    def test_detects_pillar_and_repeater_angles(self) -> None:
        self.assertEqual(
            detect_camera_key("2026-01-24_18-40-57-left_pillar"),
            "left_pillar",
        )
        self.assertEqual(
            detect_camera_key("2026-01-24_18-40-57-right_repeater"),
            "right_repeater",
        )

    def test_detects_newer_front_and_interior_aliases(self) -> None:
        self.assertEqual(
            detect_camera_key("2026-01-24_18-40-57-front_bumper"),
            "front_bumper",
        )
        self.assertEqual(
            detect_camera_key("2026-01-24_18-40-57-interior"),
            "cabin",
        )

    def test_timestamped_unknown_angle_is_kept_as_future_camera_key(self) -> None:
        camera_key = detect_camera_key("2026-01-24_18-40-57-left_fender")

        self.assertEqual(camera_key, "left_fender")
        self.assertEqual(camera_label(camera_key), "Left Fender")

    def test_non_teslacam_names_are_ignored(self) -> None:
        self.assertIsNone(detect_camera_key("holiday_video"))

    def test_known_angles_sort_before_future_unknown_angles(self) -> None:
        self.assertEqual(
            sort_camera_keys(["left_fender", "rear", "front_bumper"]),
            ["front_bumper", "rear", "left_fender"],
        )


if __name__ == "__main__":
    unittest.main()
