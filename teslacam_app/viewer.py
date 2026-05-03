"""Primary Qt window for TeslaCamViewer.

This module owns top-level UI orchestration: loading TeslaCam folders,
coordinating synchronized playback, exposing evidence export actions, and
hosting the separate recovery workspace. The specialized business logic lives
in sibling modules so this file can stay focused on wiring user intent to UI
behavior.
"""

from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QMainWindow,
    QMessageBox,
)

from .cameras import COMPOSITE_CLIP_KEY, camera_label, choose_primary_camera, sort_camera_keys
from .data import EventMetadata, load_event_metadata
from .export_dialog import EvidenceExportDialog
from .exporter import EvidencePackageExporter
from .map_renderer import LeafletMapRenderer
from .recovery_dialog import RecoveryPanel
from .settings_store import AppSettingsStore
from .telemetry import (
    TelemetrySample,
    TelemetrySeries,
    acceleration_label,
    angle_label,
    autopilot_label,
    gear_label,
    load_telemetry_series,
    pedal_label,
    position_label,
    signals_label,
    speed_label,
)
from .ui import Ui_tesla_cam_viewer_main_window


class MapRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Attach headers that help public tile servers accept embedded requests."""

    def interceptRequest(self, info):
        """Rewrite map tile requests with a stable referrer and user agent."""

        host = info.requestUrl().host().lower()
        if "openstreetmap.org" not in host:
            return

        info.setHttpHeader(b"Referer", b"https://teslacam-viewer.local/")
        info.setHttpHeader(b"Origin", b"https://teslacam-viewer.local")
        info.setHttpHeader(b"User-Agent", b"TeslaCamViewer/1.0 (PySide6 QtWebEngine)")


class TeslaCamViewer(QMainWindow, Ui_tesla_cam_viewer_main_window):
    """Main application window for playback, export, and recovery tasks."""

    def __init__(self, *args, **kwargs):
        """Construct the window, child panels, and periodic sync timer."""

        super().__init__(*args, **kwargs)
        self.setupUi(self)

        self.project_dir = Path(__file__).resolve().parent.parent
        self.map_renderer = LeafletMapRenderer(self.project_dir)
        self.map_request_interceptor = MapRequestInterceptor(self)
        self.settings_store = AppSettingsStore.default()
        self.recovery_panel = RecoveryPanel(
            settings_store=self.settings_store,
            suggested_event_date=None,
            parent=self.recovery_panel_host,
        )
        self.recovery_panel_host_layout.addWidget(self.recovery_panel)

        self.folder: Path | None = None
        self.metadata: EventMetadata | None = None
        self.event_timestamp_ms = 0
        self.playback_speed = 1.0

        self.players: dict[str, QMediaPlayer] = {}
        self.audio_outputs: dict[str, QAudioOutput] = {}
        self.loaded_video_files: dict[str, Path] = {}
        self.camera_outputs: dict[str, object] = {}
        self.camera_panels: dict[str, object] = {}
        self.current_main_key: str | None = None
        self.telemetry_cache: dict[Path, TelemetrySeries | None] = {}
        self.current_telemetry: TelemetrySeries | None = None

        self.configure_layout()
        self.init_controls()
        self.map_view.page().profile().setUrlRequestInterceptor(self.map_request_interceptor)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_playback)
        self.timer.start(50)

    def configure_layout(self):
        """Set initial splitter proportions and hide optional sections."""

        self.main_content_splitter.setStretchFactor(0, 3)
        self.main_content_splitter.setStretchFactor(1, 4)
        self.top_content_splitter.setStretchFactor(0, 5)
        self.top_content_splitter.setStretchFactor(1, 2)
        self.top_content_splitter.setStretchFactor(2, 2)
        self.update_layout_visibility(has_details_panel=False, has_auxiliary_angles=False)

    def init_controls(self):
        """Wire signals, button styling, and initial disabled states."""

        buttons = [
            self.load_folder_button,
            self.recover_clips_button,
            self.rename_button,
            self.delete_button,
            self.event_back_frame_button,
            self.play_button_event,
            self.event_forward_frame_button,
            self.goto_event_button,
            self.synced_back_frame_button,
            self.play_button_synced,
            self.synced_forward_frame_button,
            self.capture_frame_button,
            self.export_evidence_button,
        ]

        for button in buttons:
            button.setMinimumHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setGraphicsEffect(self.default_shadow())

        self.apply_tesla_style()
        self.rename_input.setMinimumWidth(260)
        self.timestamp_label.setMinimumWidth(170)
        self.event_type_label.setMinimumWidth(220)
        self.seek_slider.setRange(0, 0)
        self.event_seek_slider.setRange(0, 0)
        self.seek_slider.setSingleStep(int(1000 / 30))
        self.event_seek_slider.setSingleStep(int(1000 / 30))
        self.speed_dropdown.setCurrentText("1x")

        self.load_folder_button.clicked.connect(self.load_folder)
        self.recover_clips_button.clicked.connect(self.switch_to_recovery_tab)
        self.actionLoad_Files.triggered.connect(self.load_folder)
        self.actionViewer_Mode.triggered.connect(self.switch_to_viewer_tab)
        self.actionRecovery_Mode.triggered.connect(self.switch_to_recovery_tab)
        self.actionStart_Recovery.triggered.connect(self.recovery_panel.start_recovery)
        self.actionCancel_Recovery.triggered.connect(self.recovery_panel.cancel_recovery)
        self.actionUse_Recommended_Recovery_Settings.triggered.connect(
            self.recovery_panel.apply_recommended_tuning
        )
        self.actionUse_Loaded_Event_Date.triggered.connect(
            self.recovery_panel.use_suggested_event_date
        )
        self.rename_button.clicked.connect(self.rename_folder)
        self.rename_input.returnPressed.connect(self.rename_folder)
        self.delete_button.clicked.connect(self.delete_folder)
        self.map_view.loadStarted.connect(self.on_map_load_started)
        self.map_view.loadFinished.connect(self.on_map_load_finished)
        self.play_button_event.clicked.connect(self.toggle_play_pause_event)
        self.play_button_synced.clicked.connect(self.toggle_play_pause_synced)
        self.event_back_frame_button.clicked.connect(lambda: self.step_main_frame(-1))
        self.event_forward_frame_button.clicked.connect(lambda: self.step_main_frame(1))
        self.synced_back_frame_button.clicked.connect(lambda: self.step_all_frames(-1))
        self.synced_forward_frame_button.clicked.connect(lambda: self.step_all_frames(1))
        self.goto_event_button.clicked.connect(self.seek_to_event)
        self.capture_frame_button.clicked.connect(self.capture_frame)
        self.export_evidence_button.clicked.connect(self.export_evidence_package)
        self.event_seek_slider.sliderMoved.connect(self.seek_event_video)
        self.seek_slider.sliderMoved.connect(self.seek_video)
        self.speed_dropdown.currentIndexChanged.connect(self.change_speed_from_dropdown)
        self.event_filter_dropdown.currentIndexChanged.connect(self.filter_events)
        self.mode_tabs.currentChanged.connect(self.update_mode_actions)
        self.recovery_panel.request_switch_to_viewer.connect(self.switch_to_viewer_tab)

        self.goto_event_button.setEnabled(False)
        self.play_button_event.setEnabled(False)
        self.play_button_synced.setEnabled(False)
        self.capture_frame_button.setEnabled(False)
        self.export_evidence_button.setEnabled(False)
        self.set_main_status("No folder loaded")
        self.set_map_status("Waiting for GPS data")
        self.set_event_details("Event details: Waiting for event data")
        self.clear_telemetry_display(
            "Load a supported clip to view embedded speed, steering, and driver input data."
        )
        self.update_mode_actions()

    def apply_tesla_style(self):
        """Apply a light Tesla-inspired stylesheet to the desktop viewer."""

        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f5f6f7;
                color: #1e2023;
                font-size: 10pt;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d7dadd;
                border-radius: 14px;
                margin-top: 12px;
                font-weight: 600;
                padding-top: 12px;
            }
            QGroupBox::title {
                left: 14px;
                padding: 0 4px;
            }
            QFrame#main_window_frame, QFrame#recovery_panel_host {
                background: transparent;
                border: none;
            }
            QLabel#viewer_help_label, QLabel#recovery_tab_header {
                background: #ffffff;
                border: 1px solid #d7dadd;
                border-radius: 12px;
                padding: 10px 12px;
            }
            QLabel#telemetry_status_label, QLabel#event_metadata_label, QLabel#map_status_label,
            QLabel#main_video_status_label {
                color: #50545a;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #d0d4d8;
                border-radius: 10px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background: #f0f2f4;
            }
            QPushButton:pressed {
                background: #e7eaee;
            }
            QPushButton:disabled {
                color: #8c9298;
                background: #f3f4f5;
            }
            QLineEdit, QComboBox {
                background: #ffffff;
                border: 1px solid #d0d4d8;
                border-radius: 10px;
                padding: 6px 10px;
            }
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background: #ebedef;
                border: 1px solid #d0d4d8;
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                min-width: 110px;
                padding: 8px 16px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
            }
            QMenuBar {
                background: #ffffff;
                border-bottom: 1px solid #dde1e4;
            }
            QSplitter::handle {
                background: #eaedf0;
            }
            """
        )

    def default_shadow(self):
        """Create the shared shadow used for the main action buttons."""

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setXOffset(2)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 150))
        return shadow

    def load_folder(self):
        """Prompt for a TeslaCam folder and load it into the viewer."""

        folder = QFileDialog.getExistingDirectory(self, "Open TeslaCam Event Folder")
        if not folder:
            return

        self.folder = Path(folder).resolve()
        metadata = load_event_metadata(self.folder)
        self.metadata = metadata
        self.event_timestamp_ms = metadata.event_offset_ms
        suggested_date = metadata.event_time.date() if metadata.event_time else None
        self.recovery_panel.set_suggested_event_date(suggested_date)

        self.configure_media_for(metadata)
        self.apply_event_metadata(metadata)
        self.viewer_help_label.setText(
            "Tip: click another angle below to promote it into the main view, or use Recovery Tools if the clip you need does not appear in the folder."
        )

    def configure_media_for(self, metadata: EventMetadata):
        """Rebuild player state for a newly loaded event folder."""

        self.clear_players()
        self.clear_camera_grid()
        self.event_seek_slider.clear_event_position()
        self.seek_slider.clear_event_position()
        self.current_telemetry = None

        # Respect the normalized ordering from ``data.py`` so the same folder
        # always produces the same layout and main-angle default.
        self.loaded_video_files = {
            key: metadata.camera_files[key] for key in metadata.ordered_camera_keys
        }

        self.current_main_key = choose_primary_camera(self.loaded_video_files)
        # Some Tesla exports provide only a pre-rendered event clip. Falling
        # back to that single file is better than presenting an empty viewer.
        if not self.loaded_video_files and metadata.composite_clip:
            self.loaded_video_files = {COMPOSITE_CLIP_KEY: metadata.composite_clip}
            self.current_main_key = COMPOSITE_CLIP_KEY

        self.camera_outputs = {}
        self.camera_panels = {}

        if self.current_main_key is None:
            self.set_main_status("No playable camera angles were detected in this folder")
            self.viewer_help_label.setText(
                "No playable camera angles were found in this folder. If you expected footage here, try Recovery Tools to search raw media for older clips."
            )
            self.update_section_titles()
            self.update_layout_visibility(
                has_details_panel=self.metadata is not None,
                has_auxiliary_angles=False,
            )
            self.update_control_availability()
            self.clear_telemetry_display(
                "This folder did not include a playable primary angle, so no vehicle data could be checked."
            )
            return

        self.camera_outputs[self.current_main_key] = self.event_video_widget
        auxiliary_keys = [key for key in self.loaded_video_files if key != self.current_main_key]
        self.set_main_status(f"Preparing {camera_label(self.current_main_key)}")
        self.build_auxiliary_grid(auxiliary_keys)
        self.create_players()
        self.play_all()

        self.update_section_titles()
        self.update_layout_visibility(
            has_details_panel=self.metadata is not None,
            has_auxiliary_angles=bool(auxiliary_keys),
        )
        self.update_control_availability()
        self.load_current_telemetry()

    def build_auxiliary_grid(self, auxiliary_keys: list[str]):
        """Create auxiliary camera panels for every non-primary angle."""

        if not auxiliary_keys:
            return

        columns = len(auxiliary_keys) if len(auxiliary_keys) <= 4 else self.column_count_for(auxiliary_keys)
        rows = (len(auxiliary_keys) + columns - 1) // columns
        if rows <= 1:
            self.camera_grid_host.setMinimumHeight(170)
            self.camera_grid_host.setMaximumHeight(250)
        else:
            self.camera_grid_host.setMinimumHeight(170 * rows)
            self.camera_grid_host.setMaximumHeight(16777215)
        for index, camera_key in enumerate(auxiliary_keys):
            row, column = divmod(index, columns)
            panel, video_widget = self.build_camera_panel(
                self.camera_grid_host,
                camera_label(camera_key),
                f"{camera_key}_video_widget",
            )
            panel.setCursor(Qt.CursorShape.PointingHandCursor)
            video_widget.setCursor(Qt.CursorShape.PointingHandCursor)
            video_widget.clicked.connect(self.handle_auxiliary_widget_clicked)

            self.camera_grid_layout.addWidget(panel, row, column)
            self.camera_grid_layout.setRowStretch(row, 1)
            self.camera_panels[camera_key] = panel
            self.camera_outputs[camera_key] = video_widget

        for column in range(columns):
            self.camera_grid_layout.setColumnStretch(column, 1)

    def handle_auxiliary_widget_clicked(self):
        """Promote the clicked auxiliary angle into the main view."""

        widget = self.sender()
        if widget is None:
            return

        selected_key = self.camera_key_for_widget(widget)
        if selected_key is None or selected_key == self.current_main_key:
            return

        self.swap_to_main_view(selected_key)

    @staticmethod
    def column_count_for(auxiliary_keys: list[str]) -> int:
        """Choose an efficient auxiliary grid width for the loaded angle count."""

        angle_count = len(auxiliary_keys)
        if angle_count <= 0:
            return 1
        if angle_count <= 3:
            return angle_count
        if angle_count == 4:
            return 2
        return 3

    def create_players(self):
        """Instantiate media players and connect UI-relevant signals."""

        for camera_key, video_path in self.loaded_video_files.items():
            output_widget = self.camera_outputs[camera_key]
            player, audio_output = self.create_player(output_widget, camera_key == self.current_main_key)
            player.setSource(QUrl.fromLocalFile(str(video_path)))
            player.playbackStateChanged.connect(self.update_playback_buttons)
            player.mediaStatusChanged.connect(partial(self.on_player_media_status_changed, camera_key))
            player.durationChanged.connect(partial(self.on_player_duration_changed, camera_key))
            player.positionChanged.connect(partial(self.on_player_position_changed, camera_key))
            self.players[camera_key] = player
            self.audio_outputs[camera_key] = audio_output

        self.update_audio_focus()
        self.refresh_main_video_status()

    def create_player(self, output_widget, is_audible: bool) -> tuple[QMediaPlayer, QAudioOutput]:
        """Create one player/audio pair bound to a specific video widget."""

        player = QMediaPlayer(self)
        audio_output = QAudioOutput(self)
        audio_output.setVolume(1.0 if is_audible else 0.0)
        player.setAudioOutput(audio_output)
        player.setVideoSink(output_widget.videoSink())
        return player, audio_output

    def clear_players(self):
        """Dispose of existing players before loading another folder."""

        for player in self.players.values():
            player.stop()
            player.deleteLater()

        for audio_output in self.audio_outputs.values():
            audio_output.deleteLater()

        self.players.clear()
        self.audio_outputs.clear()
        self.event_video_widget.clear()
        for widget in self.camera_outputs.values():
            if hasattr(widget, "clear"):
                widget.clear()

    def clear_camera_grid(self):
        """Remove and delete all auxiliary angle panels."""

        while self.camera_grid_layout.count():
            item = self.camera_grid_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

        self.camera_panels.clear()

    def apply_event_metadata(self, metadata: EventMetadata):
        """Refresh labels, map state, and slider bookmarks from event metadata."""

        event_type_text = self.humanize_event_reason(metadata.event_type)
        self.event_type_label.setText(f"Event Type: {event_type_text}")
        self.goto_event_button.setEnabled(self.has_event_bookmark(metadata))
        self.goto_event_button.setText(
            "Jump To Event" if metadata.event_offset_ms > 0 else "Event At Start"
        )
        event_marker = metadata.event_offset_ms if self.has_event_bookmark(metadata) else None
        self.event_seek_slider.set_event_position(event_marker)
        self.seek_slider.set_event_position(event_marker)
        self.set_event_details(self.format_event_details(metadata))
        location_suffix = f": {metadata.city}" if metadata.city else ""
        self.map_view_container.setTitle(f"Map / Event Location{location_suffix}")

        if metadata.gps_coords:
            self.show_map(metadata.gps_coords)
        else:
            self.map_view.setUrl(QUrl("about:blank"))
            self.set_map_status("No GPS coordinates found for this event")

    def show_map(self, gps_coords: dict[str, float]):
        """Render the Leaflet event map in the embedded web view."""

        self.set_map_status("Loading event map")
        try:
            location_label = self.metadata.city if self.metadata and self.metadata.city else "Tesla Event"
            popup_label = location_label
            if self.metadata and self.metadata.event_type:
                popup_label = f"{location_label}: {self.humanize_event_reason(self.metadata.event_type)}"
            map_html = self.map_renderer.render_html(
                gps_coords,
                location_label=location_label,
                popup_label=popup_label,
            )
        except Exception as exc:  # noqa: BLE001 - surface as UI state, not a hard crash
            self.map_view.setUrl(QUrl("about:blank"))
            self.map_view_container.setToolTip(f"Map unavailable: {exc}")
            self.set_map_status(f"Map unavailable: {exc}")
            return

        self.map_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.map_view.setHtml(map_html, QUrl("https://teslacam-viewer.local/"))
        self.map_view_container.setToolTip("")

    def update_layout_visibility(self, *, has_details_panel: bool, has_auxiliary_angles: bool):
        """Show or hide optional UI sections based on available content."""

        self.telemetry_sidebar.setVisible(has_details_panel)
        self.map_view_container.setVisible(has_details_panel)
        self.synced_videos_section.setVisible(has_auxiliary_angles)

        if has_details_panel:
            self.top_content_splitter.setSizes([930, 330, 390])
        else:
            self.top_content_splitter.setSizes([1200, 0, 0])
        self.main_content_splitter.setSizes([460, 500 if has_auxiliary_angles else 0])

    def update_section_titles(self):
        """Refresh the group-box titles after loading or swapping angles."""

        main_title = camera_label(self.current_main_key) if self.current_main_key else "Main View"
        self.event_video_section.setTitle(f"Main View: {main_title}")

        auxiliary_count = max(0, len(self.loaded_video_files) - (1 if self.current_main_key else 0))
        suffix = f" ({auxiliary_count})" if auxiliary_count else ""
        self.synced_videos_section.setTitle(f"Other Angles{suffix}")
        self.refresh_auxiliary_panel_titles()

    def update_control_availability(self):
        """Enable only the playback controls that make sense right now."""

        has_primary = self.primary_player() is not None
        has_any = bool(self.players)
        has_auxiliary = len(self.players) > 1

        self.play_button_event.setEnabled(has_primary)
        self.event_back_frame_button.setEnabled(has_primary)
        self.event_forward_frame_button.setEnabled(has_primary)
        self.event_seek_slider.setEnabled(has_primary)

        self.play_button_synced.setEnabled(has_any)
        self.synced_back_frame_button.setEnabled(has_any)
        self.synced_forward_frame_button.setEnabled(has_any)
        self.seek_slider.setEnabled(has_any)
        self.capture_frame_button.setEnabled(has_any)
        self.export_evidence_button.setEnabled(has_any)

        if not has_auxiliary:
            self.play_button_synced.setText("▶ Play All Angles")

        self.update_playback_buttons()

    def set_main_status(self, message: str):
        """Show a short status message under the main camera view."""

        self.main_video_status_label.setText(f"Main angle status: {message}")

    def set_map_status(self, message: str):
        """Show the current map loading or availability state."""

        self.map_status_label.setText(f"Map status: {message}")

    def set_event_details(self, message: str):
        """Replace the text in the event-details card."""

        self.event_metadata_label.setText(message)

    def clear_telemetry_display(self, status_message: str):
        """Reset the vehicle-data card to its neutral empty state."""

        self.telemetry_status_label.setText(f"Telemetry status: {status_message}")
        self.speed_display.set_speed(None)
        self.steering_visual.set_angle(None)
        self.pedals_visual.set_pedals(None, None)
        self.gforce_visual.set_acceleration(None, None)
        empty_value = "Not available"
        for label in (
            self.telemetry_speed_value,
            self.telemetry_steering_value,
            self.telemetry_pedals_value,
            self.telemetry_gear_value,
            self.telemetry_signals_value,
            self.telemetry_drive_assist_value,
            self.telemetry_heading_value,
            self.telemetry_position_value,
            self.telemetry_acceleration_value,
        ):
            label.setText(empty_value)

    def load_current_telemetry(self):
        """Decode or reuse telemetry for the current main angle."""

        if self.current_main_key is None:
            self.current_telemetry = None
            self.clear_telemetry_display("No primary angle is selected.")
            return

        video_path = self.loaded_video_files.get(self.current_main_key)
        if video_path is None:
            self.current_telemetry = None
            self.clear_telemetry_display("The active angle has no playable source file.")
            return

        cached = self.telemetry_cache.get(video_path)
        if cached is None and video_path not in self.telemetry_cache:
            cached = load_telemetry_series(video_path)
            self.telemetry_cache[video_path] = cached

        self.current_telemetry = cached
        if cached is None:
            self.clear_telemetry_display(
                "No embedded Tesla vehicle data was found in this clip."
            )
            return

        self.telemetry_status_label.setText(
            "Telemetry status: Embedded vehicle data loaded for the current main angle."
        )
        self.update_telemetry_for_position(self.primary_player().position() if self.primary_player() else 0)

    def update_telemetry_for_position(self, position_ms: int):
        """Refresh the telemetry card for the current playback position."""

        if self.current_telemetry is None:
            return

        main_player = self.primary_player()
        duration_ms = main_player.duration() if self.player_has_source(main_player) else 0
        sample = self.current_telemetry.sample_for_position(position_ms, duration_ms)
        if sample is None:
            self.clear_telemetry_display("Telemetry exists, but no sample matched this position.")
            return

        self.apply_telemetry_sample(sample)

    def apply_telemetry_sample(self, sample: TelemetrySample):
        """Populate the telemetry labels from one decoded sample."""

        throttle_percent = self.normalize_throttle_percent(sample.accelerator_pedal_position)
        brake_percent = 100.0 if sample.brake_applied else 0.0 if sample.brake_applied is not None else None
        self.speed_display.set_speed(sample.vehicle_speed_mps)
        self.steering_visual.set_angle(sample.steering_wheel_angle)
        self.pedals_visual.set_pedals(throttle_percent, brake_percent)
        self.gforce_visual.set_acceleration(
            sample.linear_acceleration_mps2_x,
            sample.linear_acceleration_mps2_y,
        )
        self.telemetry_speed_value.setText(speed_label(sample.vehicle_speed_mps))
        self.telemetry_steering_value.setText(angle_label(sample.steering_wheel_angle))
        self.telemetry_pedals_value.setText(pedal_label(sample))
        self.telemetry_gear_value.setText(gear_label(sample.gear_state))
        self.telemetry_signals_value.setText(signals_label(sample))
        self.telemetry_drive_assist_value.setText(autopilot_label(sample.autopilot_state))
        self.telemetry_heading_value.setText(angle_label(sample.heading_deg))
        self.telemetry_position_value.setText(position_label(sample))
        self.telemetry_acceleration_value.setText(acceleration_label(sample))

        frame_suffix = (
            f" Frame {sample.frame_seq_no}" if sample.frame_seq_no is not None else ""
        )
        self.telemetry_status_label.setText(
            "Telemetry status: Frame-synced vehicle data." + frame_suffix
        )

    @staticmethod
    def normalize_throttle_percent(raw_value: float | None) -> float | None:
        """Normalize Tesla throttle values into a 0-100 display range."""

        if raw_value is None:
            return None
        if raw_value <= 1.0:
            return max(0.0, min(raw_value * 100.0, 100.0))
        return max(0.0, min(raw_value, 100.0))

    def refresh_main_video_status(self):
        """Recompute the main status label from the active player's state."""

        if self.current_main_key is None:
            self.set_main_status("No primary angle selected")
            return

        player = self.primary_player()
        if not self.player_has_source(player):
            self.set_main_status(f"{camera_label(self.current_main_key)} has no media source")
            return

        self.on_player_media_status_changed(self.current_main_key, player.mediaStatus())

    def primary_player(self) -> QMediaPlayer | None:
        """Return the media player currently attached to the main pane."""

        if self.current_main_key is None:
            return None
        return self.players.get(self.current_main_key)

    def camera_key_for_widget(self, widget) -> str | None:
        """Find the logical camera key attached to a video widget."""

        for camera_key, output_widget in self.camera_outputs.items():
            if output_widget is widget:
                return camera_key
        return None

    def refresh_auxiliary_panel_titles(self):
        """Keep auxiliary group-box titles accurate after an angle swap."""

        for camera_key, output_widget in self.camera_outputs.items():
            if output_widget is self.event_video_widget:
                continue

            panel = output_widget.parentWidget()
            if panel is not None:
                panel.setTitle(camera_label(camera_key))

    def auxiliary_players(self) -> dict[str, QMediaPlayer]:
        """Return all players that are not currently shown as the main angle."""

        return {
            camera_key: player
            for camera_key, player in self.players.items()
            if camera_key != self.current_main_key
        }

    @staticmethod
    def player_has_source(player: QMediaPlayer | None) -> bool:
        """Check whether a player object exists and has a media source."""

        return player is not None and not player.source().isEmpty()

    def any_player_playing(self) -> bool:
        """Return whether any loaded angle is actively playing."""

        return any(
            self.player_has_source(player)
            and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            for player in self.players.values()
        )

    def update_audio_focus(self):
        """Mute auxiliary angles so only the main view can produce audio."""

        for camera_key, audio_output in self.audio_outputs.items():
            audio_output.setVolume(1.0 if camera_key == self.current_main_key else 0.0)

    def update_playback_buttons(self, *_):
        """Refresh play/pause button labels from current playback state."""

        main_player = self.primary_player()
        main_is_playing = (
            self.player_has_source(main_player)
            and main_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.play_button_event.setText("⏸ Pause Main" if main_is_playing else "▶ Play Main")

        all_is_playing = self.any_player_playing()
        self.play_button_synced.setText(
            "⏸ Pause All Angles" if all_is_playing else "▶ Play All Angles"
        )

    def on_player_media_status_changed(self, camera_key: str, status: QMediaPlayer.MediaStatus):
        """Reflect Qt media status changes in the main status label."""

        if camera_key != self.current_main_key:
            return

        source_path = self.loaded_video_files.get(camera_key)
        source_name = source_path.name if source_path else "unknown source"
        angle_name = camera_label(camera_key)
        status_text = {
            QMediaPlayer.MediaStatus.NoMedia: f"{angle_name} has no media source",
            QMediaPlayer.MediaStatus.LoadingMedia: f"Loading {angle_name} from {source_name}",
            QMediaPlayer.MediaStatus.LoadedMedia: f"{angle_name} loaded from {source_name}",
            QMediaPlayer.MediaStatus.BufferingMedia: f"Buffering {angle_name}",
            QMediaPlayer.MediaStatus.BufferedMedia: f"{angle_name} ready: {source_name}",
            QMediaPlayer.MediaStatus.StalledMedia: f"{angle_name} playback stalled",
            QMediaPlayer.MediaStatus.EndOfMedia: f"{angle_name} reached the end of the clip",
            QMediaPlayer.MediaStatus.InvalidMedia: f"{angle_name} could not be read: {source_name}",
        }.get(status, f"{angle_name} status: {status.name}")
        self.set_main_status(status_text)

    def on_map_load_started(self):
        """Show a loading message while the embedded map view refreshes."""

        self.set_map_status("Loading event map")

    def on_map_load_finished(self, ok: bool):
        """Show map success/failure details after WebEngine finishes loading."""

        if not ok:
            self.set_map_status("The embedded map page failed to render")
            return

        if not self.metadata or not self.metadata.gps_coords:
            self.set_map_status("Map ready")
            return

        latitude = self.metadata.gps_coords.get("lat")
        longitude = self.metadata.gps_coords.get("lon")
        if latitude is None or longitude is None:
            self.set_map_status("Map ready")
            return

        self.set_map_status(f"Event map ready at {latitude:.6f}, {longitude:.6f}")

    def on_player_duration_changed(self, camera_key: str, duration: int):
        """Update slider ranges when the active main clip reports duration."""

        if camera_key != self.current_main_key or duration <= 0:
            return

        self.event_seek_slider.setRange(0, duration)
        self.seek_slider.setRange(0, duration)
        event_position = None
        if self.metadata and self.metadata.event_time and self.metadata.selected_clip_start:
            event_position = min(duration, self.event_timestamp_ms)
        self.event_seek_slider.set_event_position(event_position)
        self.seek_slider.set_event_position(event_position)

    def on_player_position_changed(self, camera_key: str, position: int):
        """Mirror main-player position into labels, sliders, and telemetry."""

        if camera_key != self.current_main_key:
            return

        if not self.event_seek_slider.isSliderDown():
            self.event_seek_slider.setValue(position)
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self.timestamp_label.setText(f"Timestamp: {self.format_time(position)}")
        self.update_telemetry_for_position(position)

    def play_all(self):
        """Start playback for every loaded camera angle."""

        for player in self.players.values():
            if self.player_has_source(player):
                player.setPlaybackRate(self.playback_speed)
                player.play()
        self.update_playback_buttons()

    def pause_all(self):
        """Pause every loaded camera angle."""

        for player in self.players.values():
            player.pause()
        self.update_playback_buttons()

    def toggle_play_pause_event(self):
        """Toggle playback for only the current main angle."""

        main_player = self.primary_player()
        if not self.player_has_source(main_player):
            return

        if main_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            main_player.pause()
        else:
            for player in self.auxiliary_players().values():
                player.pause()
            main_player.setPlaybackRate(self.playback_speed)
            main_player.play()
        self.update_playback_buttons()

    def toggle_play_pause_synced(self):
        """Toggle synchronized playback for all loaded angles."""

        if not any(self.player_has_source(player) for player in self.players.values()):
            return

        if self.any_player_playing():
            self.pause_all()
        else:
            self.play_all()

    def swap_to_main_view(self, new_main_key: str):
        """Swap an auxiliary angle into the main pane without rebuilding players."""

        if new_main_key == self.current_main_key or new_main_key not in self.players:
            return

        # Swapping sinks preserves playback position and buffering state, which
        # feels much better than tearing players down and rebuilding them.
        old_main_key = self.current_main_key
        if old_main_key is None:
            return

        old_main_widget = self.camera_outputs[old_main_key]
        new_main_widget = self.camera_outputs[new_main_key]
        old_main_frame = old_main_widget.videoSink().videoFrame()
        new_main_frame = new_main_widget.videoSink().videoFrame()

        self.players[old_main_key].setVideoSink(new_main_widget.videoSink())
        self.players[new_main_key].setVideoSink(old_main_widget.videoSink())
        self.camera_outputs[old_main_key], self.camera_outputs[new_main_key] = (
            new_main_widget,
            old_main_widget,
        )
        if old_main_frame.isValid():
            new_main_widget.videoSink().setVideoFrame(old_main_frame)
        elif hasattr(new_main_widget, "clear"):
            new_main_widget.clear()

        if new_main_frame.isValid():
            old_main_widget.videoSink().setVideoFrame(new_main_frame)
        elif hasattr(old_main_widget, "clear"):
            old_main_widget.clear()

        self.current_main_key = new_main_key
        self.update_audio_focus()
        self.update_section_titles()
        self.update_control_availability()
        self.load_current_telemetry()
        self.on_player_duration_changed(new_main_key, self.players[new_main_key].duration())
        self.on_player_position_changed(new_main_key, self.players[new_main_key].position())
        self.refresh_main_video_status()

    def seek_to_event(self):
        """Pause and jump all loaded angles to the event bookmark."""

        if not self.metadata or not self.has_event_bookmark(self.metadata):
            return

        self.pause_all()
        for player in self.players.values():
            if self.player_has_source(player):
                player.setPosition(self.event_timestamp_ms)

    def seek_event_video(self, position: int):
        """Seek only the main angle from the main timeline slider."""

        main_player = self.primary_player()
        if self.player_has_source(main_player):
            main_player.setPosition(position)

    def seek_video(self, position: int):
        """Seek all loaded angles from the synchronized timeline slider."""

        for player in self.players.values():
            if self.player_has_source(player):
                player.setPosition(position)

    def change_speed_from_dropdown(self):
        """Apply the selected playback speed preset."""

        speed_map = {"0.25x": 0.25, "0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}
        self.set_playback_speed(speed_map[self.speed_dropdown.currentText()])

    def set_playback_speed(self, speed: float):
        """Set playback speed for all existing players."""

        self.playback_speed = speed
        for player in self.players.values():
            player.setPlaybackRate(speed)

    def step_main_frame(self, step: int):
        """Move the main angle by one approximate frame."""

        main_player = self.primary_player()
        if not self.player_has_source(main_player):
            return

        main_player.pause()
        frame_duration = int(1000 / 30)
        main_player.setPosition(max(0, main_player.position() + (frame_duration * step)))
        self.update_playback_buttons()

    def step_all_frames(self, step: int):
        """Move every loaded angle by one approximate frame."""

        self.pause_all()
        frame_duration = int(1000 / 30)
        for player in self.players.values():
            if self.player_has_source(player):
                player.setPosition(max(0, player.position() + (frame_duration * step)))

    def capture_frame(self):
        """Export one still frame per loaded angle at the current position."""

        if self.folder is None or not self.players:
            return

        save_path = QFileDialog.getExistingDirectory(self, "Select Save Location")
        if not save_path:
            return

        save_dir = Path(save_path)
        for camera_key, player in self.players.items():
            if not self.player_has_source(player):
                continue

            source_path = self.loaded_video_files.get(camera_key)
            if source_path is None:
                continue

            frame = self.get_video_frame(source_path, player.position())
            if frame is not None:
                cv2.imwrite(str(save_dir / f"frame_{camera_key}.jpg"), frame)

        QMessageBox.information(self, "Success", "Frames captured successfully!")

    def export_evidence_package(self):
        """Launch the evidence-export dialog and build a package on success."""

        if self.metadata is None or not self.loaded_video_files:
            QMessageBox.information(self, "No Media", "Load an event before exporting evidence.")
            return

        default_output_root = self.metadata.folder.parent / "_teslacam_exports"
        default_package_name = f"{self.metadata.folder.name}_evidence"
        dialog = EvidenceExportDialog(
            default_output_root=default_output_root,
            default_package_name=default_package_name,
            has_event_bookmark=self.has_event_bookmark(self.metadata),
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        main_player = self.primary_player()
        current_position_ms = main_player.position() if self.player_has_source(main_player) else 0
        event_position_ms = (
            self.metadata.event_offset_ms if self.has_event_bookmark(self.metadata) else None
        )
        options = dialog.export_options(
            current_position_ms=current_position_ms,
            event_position_ms=event_position_ms,
        )

        exporter = EvidencePackageExporter(
            metadata=self.metadata,
            loaded_video_files=self.loaded_video_files,
            current_main_key=self.current_main_key,
        )

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = exporter.export(options)
        except Exception as exc:  # noqa: BLE001 - show as UI error, do not crash
            QMessageBox.critical(self, "Export Failed", f"Unable to export evidence package:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self,
            "Export Complete",
            "Evidence package exported successfully.\n\n"
            f"Folder: {result.package_dir}\n"
            f"Manifest: {result.manifest_path.name}",
        )

    def switch_to_viewer_tab(self):
        """Switch the central tab widget back to normal playback mode."""

        self.mode_tabs.setCurrentWidget(self.viewer_tab)
        self.update_mode_actions()
        if self.folder is None:
            self.viewer_help_label.setText(
                "Start by opening a TeslaCam event folder. The viewer loads only the camera angles found in that folder, and Recovery Tools can help when footage no longer appears normally."
            )

    def switch_to_recovery_tab(self):
        """Switch the central tab widget to the recovery workspace."""

        self.mode_tabs.setCurrentWidget(self.recovery_tab)
        self.update_mode_actions()
        self.recovery_panel.focus_primary_input()

    def update_mode_actions(self):
        """Enable only the mode menu actions that make sense right now."""

        in_recovery_mode = self.mode_tabs.currentWidget() is self.recovery_tab
        self.actionViewer_Mode.setEnabled(in_recovery_mode)
        self.actionRecovery_Mode.setEnabled(not in_recovery_mode)
        self.menuRecovery.menuAction().setVisible(True)

    @staticmethod
    def get_video_frame(video_path: Path, position_ms: int):
        """Read a frame near ``position_ms`` using OpenCV."""

        capture = cv2.VideoCapture(str(video_path))
        frame_number = int(position_ms / (1000 / 30))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        capture.release()
        return frame if ok else None

    def filter_events(self):
        """Store the selected event filter as a tooltip placeholder."""

        self.event_filter_dropdown.setToolTip(
            f"Current filter: {self.event_filter_dropdown.currentText()}"
        )

    def sync_playback(self):
        """Keep auxiliary players aligned to the main player position."""

        main_player = self.primary_player()
        if not self.player_has_source(main_player):
            return

        if main_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.timestamp_label.setText(f"Timestamp: {self.format_time(main_player.position())}")
            return

        main_position = main_player.position()
        for camera_key, player in self.auxiliary_players().items():
            if not self.player_has_source(player):
                continue
            if abs(player.position() - main_position) > 100:
                player.setPosition(main_position)

        self.timestamp_label.setText(f"Timestamp: {self.format_time(main_position)}")

    @staticmethod
    def format_time(milliseconds: int) -> str:
        """Format milliseconds as ``HH:MM:SS`` for labels and overlays."""

        seconds = int(milliseconds / 1000) % 60
        minutes = int(milliseconds / (1000 * 60)) % 60
        hours = int(milliseconds / (1000 * 60 * 60)) % 24
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    @staticmethod
    def humanize_event_reason(reason: str | None) -> str:
        """Convert Tesla reason identifiers into readable display text."""

        if not reason:
            return "Unknown"
        return reason.replace("_", " ").title()

    @staticmethod
    def has_event_bookmark(metadata: EventMetadata) -> bool:
        """Return whether the event timestamp can be mapped into a clip."""

        return metadata.event_time is not None and metadata.selected_clip_start is not None

    def format_event_details(self, metadata: EventMetadata) -> str:
        """Build the event-details summary shown under the map."""

        details: list[str] = []
        if metadata.city:
            details.append(f"City: {metadata.city}")
        if metadata.event_time:
            details.append(f"Event Time: {metadata.event_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if metadata.camera_id:
            details.append(f"Camera ID: {metadata.camera_id}")
        if metadata.event_type:
            details.append(f"Reason: {self.humanize_event_reason(metadata.event_type)}")
        if metadata.gps_coords:
            details.append(
                "Coordinates: "
                f"{metadata.gps_coords['lat']:.6f}, {metadata.gps_coords['lon']:.6f}"
            )
        if metadata.selected_clip_start:
            details.append(
                f"Clip Start: {metadata.selected_clip_start.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        if metadata.event_offset_ms > 0:
            details.append(f"Event Offset: {self.format_time(metadata.event_offset_ms)}")
        if metadata.camera_files:
            loaded_angles = ", ".join(
                camera_label(camera_key) for camera_key in metadata.ordered_camera_keys
            )
            details.append(f"Angles: {loaded_angles}")

        return "Event details: " + " | ".join(details) if details else "Event details: None"

    def rename_folder(self):
        """Rename the currently loaded event folder on disk."""

        if self.folder is None:
            return

        new_name = self.rename_input.text().strip()
        if not new_name:
            return

        new_path = self.folder.parent / new_name
        try:
            self.folder.rename(new_path)
            self.folder = new_path
            QMessageBox.information(self, "Success", "Folder renamed successfully!")
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"Failed to rename folder: {exc}")

    def delete_folder(self):
        """Delete the currently loaded event folder after confirmation."""

        if self.folder is None:
            return

        reply = QMessageBox.question(
            self,
            "Delete Folder",
            "Are you sure you want to delete this folder?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            shutil.rmtree(self.folder)
            self.folder = None
            QMessageBox.information(self, "Success", "Folder deleted successfully!")
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"Failed to delete folder: {exc}")
