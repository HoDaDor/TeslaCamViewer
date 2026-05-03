from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from teslacam_app.settings_store import AppSettingsStore


class SettingsStoreTests(unittest.TestCase):
    """Verify the YAML settings store behaves predictably."""

    def test_load_returns_empty_dict_for_missing_file(self) -> None:
        missing_path = MagicMock()
        missing_path.exists.return_value = False
        store = AppSettingsStore(missing_path)

        self.assertEqual(store.load(), {})

    def test_update_section_preserves_other_sections(self) -> None:
        store = AppSettingsStore(Path("settings.yaml"))
        with patch.object(
            AppSettingsStore,
            "load",
            return_value={"recovery": {"preset": "recommended"}},
        ):
            with patch.object(AppSettingsStore, "save") as mocked_save:
                store.update_section("viewer", {"speed": "2x"})

        mocked_save.assert_called_once_with(
            {"recovery": {"preset": "recommended"}, "viewer": {"speed": "2x"}}
        )


if __name__ == "__main__":
    unittest.main()
