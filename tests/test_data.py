from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from teslacam_app.data import choose_clip_start, compute_event_offset_ms, load_event_metadata


class EventMetadataTests(unittest.TestCase):
    """Cover the event metadata rules used by the viewer."""

    def test_choose_clip_start_prefers_latest_clip_before_event(self) -> None:
        grouped_clips = {
            datetime(2025, 1, 24, 19, 18, 23): {"front": Path("front-a.mp4")},
            datetime(2025, 1, 24, 19, 19, 23): {"front": Path("front-b.mp4")},
        }

        selected = choose_clip_start(grouped_clips, datetime(2025, 1, 24, 19, 19, 17))

        self.assertEqual(selected, datetime(2025, 1, 24, 19, 18, 23))

    def test_load_event_metadata_merges_helper_results_into_view_model(self) -> None:
        folder = Path("X:/ExampleTeslaCam/TeslaCam/SentryClips/2025-01-24_19-19-17")
        raw_event = {
            "timestamp": "2025-01-24T19:19:17",
            "reason": "user_requested",
            "city": "Example City",
            "camera": "6",
            "est_lat": 12.3456,
            "est_lon": -45.6789,
        }
        selected_start = datetime(2025, 1, 24, 19, 18, 23)
        camera_files = {
            "front": folder / "2025-01-24_19-18-23-front.mp4",
            "left_repeater": folder / "2025-01-24_19-18-23-left_repeater.mp4",
        }

        with (
            patch("teslacam_app.data.read_event_json", return_value=raw_event),
            patch(
                "teslacam_app.data.discover_video_files",
                return_value=(camera_files, None, selected_start),
            ),
        ):
            metadata = load_event_metadata(folder)

        self.assertEqual(metadata.city, "Example City")
        self.assertEqual(metadata.camera_id, "6")
        self.assertEqual(metadata.primary_camera_key, "front")
        self.assertEqual(metadata.selected_clip_start, selected_start)
        self.assertEqual(metadata.event_offset_ms, 54_000)
        self.assertSetEqual(set(metadata.camera_files), {"front", "left_repeater"})

    def test_compute_event_offset_never_returns_negative_time(self) -> None:
        self.assertEqual(
            compute_event_offset_ms(
                clip_start_time=datetime(2025, 1, 24, 19, 19, 30),
                event_time=datetime(2025, 1, 24, 19, 19, 17),
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
