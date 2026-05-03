"""YAML-backed application settings storage.

This module deliberately keeps settings persistence lightweight and explicit.
The viewer and recovery workspace both rely on it, so future maintenance is
much easier when the storage rules live in one small, well-documented file
instead of being spread across UI code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


APP_DIR_NAME = "QtTeslaCam"
SETTINGS_FILENAME = "settings.yaml"


@dataclass(slots=True)
class AppSettingsStore:
    """Persist structured application settings to a YAML file.

    Parameters
    ----------
    path:
        Absolute path to the settings file used by the application.
    """

    path: Path

    @classmethod
    def default(cls) -> "AppSettingsStore":
        """Build a store that points at the platform-appropriate config file."""

        return cls(path=default_settings_path())

    def load(self) -> dict[str, Any]:
        """Load the full settings document.

        Returns
        -------
        dict[str, Any]
            Parsed settings data. Invalid or missing files are treated as an
            empty configuration so the UI can recover gracefully.
        """

        if not self.path.exists():
            return {}

        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]):
        """Write the full settings document to disk.

        Parameters
        ----------
        data:
            Complete settings payload to serialize as YAML.
        """

        self.path.parent.mkdir(parents=True, exist_ok=True)
        yaml.safe_dump(
            data,
            self.path.open("w", encoding="utf-8"),
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )

    def get_section(self, section: str) -> dict[str, Any]:
        """Return one top-level section from the settings document.

        Parameters
        ----------
        section:
            Section name such as ``"viewer"`` or ``"recovery"``.

        Returns
        -------
        dict[str, Any]
            The requested section, or an empty dictionary when the section is
            missing or malformed.
        """

        data = self.load()
        value = data.get(section)
        return value if isinstance(value, dict) else {}

    def update_section(self, section: str, value: dict[str, Any]):
        """Replace one top-level section while preserving the rest of the file.

        Parameters
        ----------
        section:
            Top-level section name to update.
        value:
            New section payload to persist.
        """

        data = self.load()
        data[section] = value
        self.save(data)


def default_settings_path() -> Path:
    """Resolve the default settings file path for the current platform.

    Returns
    -------
    pathlib.Path
        Platform-aware path for ``settings.yaml``. The fallback is a standard
        ``~/.config`` location when no better OS-specific directory is known.
    """

    if user_config_dir := _user_config_dir():
        return user_config_dir / APP_DIR_NAME / SETTINGS_FILENAME

    return Path.home() / ".config" / APP_DIR_NAME / SETTINGS_FILENAME


def _user_config_dir() -> Path | None:
    """Return the base user configuration directory for the current OS."""

    import os
    import platform

    system_name = platform.system().lower()
    if system_name == "windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) if appdata else None
    if system_name == "darwin":
        return Path.home() / "Library" / "Application Support"

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home)
    return None
