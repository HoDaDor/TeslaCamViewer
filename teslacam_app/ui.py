"""Main window widget layout for TeslaCamViewer.

The behavioral code lives in ``viewer.py``. This module keeps the widget tree
and layout details together so playback, map, export, and recovery logic do
not have to be mixed with hundreds of Qt construction calls.
"""

from PySide6 import QtCore, QtGui, QtWidgets, QtWebEngineWidgets

from .telemetry_visuals import (
    GForceTelemetryWidget,
    PedalTelemetryWidget,
    SpeedDisplayTelemetryWidget,
    SteeringWheelTelemetryWidget,
)
from .video_surface import VideoFrameWidget
from .widgets import EventBookmarkSlider


class Ui_tesla_cam_viewer_main_window(object):
    """Build the Qt widgets used by ``TeslaCamViewer``."""

    def build_camera_panel(self, parent, title, object_name):
        """Create one titled camera panel for an auxiliary angle."""

        panel = QtWidgets.QGroupBox(parent=parent)
        panel.setObjectName(f"{object_name}_panel")
        panel.setTitle(title)

        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        video_widget = VideoFrameWidget(parent=panel)
        video_widget.setObjectName(object_name)
        video_widget.setMinimumSize(QtCore.QSize(220, 124))
        video_widget.setSizePolicy(
            QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
        )
        layout.addWidget(video_widget)
        return panel, video_widget

    def setupUi(self, tesla_cam_viewer_main_window):
        """Create the main window layout and all persistent child widgets."""

        tesla_cam_viewer_main_window.setObjectName("tesla_cam_viewer_main_window")
        tesla_cam_viewer_main_window.resize(1680, 980)
        tesla_cam_viewer_main_window.setMinimumSize(QtCore.QSize(1440, 1000))
        tesla_cam_viewer_main_window.setAcceptDrops(True)
        tesla_cam_viewer_main_window.setDocumentMode(False)

        self.central_widget = QtWidgets.QWidget(parent=tesla_cam_viewer_main_window)
        self.central_widget.setObjectName("central_widget")
        self.central_widget_vertical_layout = QtWidgets.QVBoxLayout(self.central_widget)
        self.central_widget_vertical_layout.setContentsMargins(8, 8, 8, 8)
        self.central_widget_vertical_layout.setSpacing(8)

        self.mode_tabs = QtWidgets.QTabWidget(parent=self.central_widget)
        self.mode_tabs.setObjectName("mode_tabs")
        self.mode_tabs.setDocumentMode(True)

        self.viewer_tab = QtWidgets.QWidget()
        self.viewer_tab.setObjectName("viewer_tab")
        self.viewer_tab_layout = QtWidgets.QVBoxLayout(self.viewer_tab)
        self.viewer_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_tab_layout.setSpacing(0)

        self.recovery_tab = QtWidgets.QWidget()
        self.recovery_tab.setObjectName("recovery_tab")
        self.recovery_tab_layout = QtWidgets.QVBoxLayout(self.recovery_tab)
        self.recovery_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.recovery_tab_layout.setSpacing(8)

        self.recovery_tab_header = QtWidgets.QLabel(parent=self.recovery_tab)
        self.recovery_tab_header.setObjectName("recovery_tab_header")
        self.recovery_tab_header.setWordWrap(True)
        self.recovery_tab_layout.addWidget(self.recovery_tab_header)

        self.recovery_scroll_area = QtWidgets.QScrollArea(parent=self.recovery_tab)
        self.recovery_scroll_area.setObjectName("recovery_scroll_area")
        self.recovery_scroll_area.setWidgetResizable(True)
        self.recovery_scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self.recovery_panel_host = QtWidgets.QFrame()
        self.recovery_panel_host.setObjectName("recovery_panel_host")
        self.recovery_panel_host_layout = QtWidgets.QVBoxLayout(self.recovery_panel_host)
        self.recovery_panel_host_layout.setContentsMargins(0, 0, 0, 8)
        self.recovery_panel_host_layout.setSpacing(0)
        self.recovery_scroll_area.setWidget(self.recovery_panel_host)
        self.recovery_tab_layout.addWidget(self.recovery_scroll_area, 1)

        self.mode_tabs.addTab(self.viewer_tab, "")
        self.mode_tabs.addTab(self.recovery_tab, "")

        self.main_window_frame = QtWidgets.QFrame(parent=self.viewer_tab)
        self.main_window_frame.setObjectName("main_window_frame")
        self.main_window_frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.main_window_frame.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.main_window_frame.setLineWidth(2)
        self.main_window_frame.setMidLineWidth(1)

        self.main_window_vertical_layout = QtWidgets.QVBoxLayout(self.main_window_frame)
        self.main_window_vertical_layout.setContentsMargins(8, 8, 8, 8)
        self.main_window_vertical_layout.setSpacing(8)

        self.viewer_help_label = QtWidgets.QLabel(parent=self.main_window_frame)
        self.viewer_help_label.setObjectName("viewer_help_label")
        self.viewer_help_label.setWordWrap(True)
        self.viewer_help_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.main_window_vertical_layout.addWidget(self.viewer_help_label)

        self.main_content_splitter = QtWidgets.QSplitter(parent=self.main_window_frame)
        self.main_content_splitter.setObjectName("main_content_splitter")
        self.main_content_splitter.setOrientation(QtCore.Qt.Orientation.Vertical)
        self.main_content_splitter.setChildrenCollapsible(False)
        self.main_content_splitter.setHandleWidth(8)

        self.top_content_splitter = QtWidgets.QSplitter(parent=self.main_content_splitter)
        self.top_content_splitter.setObjectName("top_content_splitter")
        self.top_content_splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.top_content_splitter.setChildrenCollapsible(False)
        self.top_content_splitter.setHandleWidth(8)

        self.event_video_section = QtWidgets.QGroupBox(parent=self.top_content_splitter)
        self.event_video_section.setObjectName("event_video_section")
        self.event_video_section.setMinimumWidth(640)

        self.event_video_section__vertical_layout = QtWidgets.QVBoxLayout(self.event_video_section)
        self.event_video_section__vertical_layout.setContentsMargins(8, 8, 8, 8)
        self.event_video_section__vertical_layout.setSpacing(8)

        self.event_video_widget = VideoFrameWidget(parent=self.event_video_section)
        self.event_video_widget.setObjectName("event_video_widget")
        self.event_video_widget.setMinimumSize(QtCore.QSize(640, 260))
        self.event_video_widget.setSizePolicy(
            QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
        )
        self.event_video_section__vertical_layout.addWidget(self.event_video_widget)

        self.event_controls_layout = QtWidgets.QHBoxLayout()
        self.event_controls_layout.setObjectName("event_controls_layout")
        self.event_controls_layout.setSpacing(8)

        self.event_back_frame_button = QtWidgets.QPushButton(parent=self.event_video_section)
        self.event_back_frame_button.setObjectName("event_back_frame_button")
        self.event_controls_layout.addWidget(self.event_back_frame_button)

        self.play_button_event = QtWidgets.QPushButton(parent=self.event_video_section)
        self.play_button_event.setObjectName("play_button_event")
        self.event_controls_layout.addWidget(self.play_button_event)

        self.event_forward_frame_button = QtWidgets.QPushButton(parent=self.event_video_section)
        self.event_forward_frame_button.setObjectName("event_forward_frame_button")
        self.event_controls_layout.addWidget(self.event_forward_frame_button)

        self.goto_event_button = QtWidgets.QPushButton(parent=self.event_video_section)
        self.goto_event_button.setObjectName("goto_event_button")
        self.event_controls_layout.addWidget(self.goto_event_button)

        self.event_seek_slider = EventBookmarkSlider(
            QtCore.Qt.Orientation.Horizontal,
            parent=self.event_video_section,
        )
        self.event_seek_slider.setObjectName("event_seek_slider")
        self.event_controls_layout.addWidget(self.event_seek_slider, 1)

        self.event_video_section__vertical_layout.addLayout(self.event_controls_layout)

        self.main_video_status_label = QtWidgets.QLabel(parent=self.event_video_section)
        self.main_video_status_label.setObjectName("main_video_status_label")
        self.main_video_status_label.setWordWrap(True)
        self.event_video_section__vertical_layout.addWidget(self.main_video_status_label)

        self.telemetry_sidebar = QtWidgets.QGroupBox(parent=self.top_content_splitter)
        self.telemetry_sidebar.setObjectName("telemetry_sidebar")
        self.telemetry_sidebar.setMinimumWidth(320)

        self.telemetry_sidebar_layout = QtWidgets.QVBoxLayout(self.telemetry_sidebar)
        self.telemetry_sidebar_layout.setContentsMargins(8, 8, 8, 8)
        self.telemetry_sidebar_layout.setSpacing(8)

        self.telemetry_section = QtWidgets.QGroupBox(parent=self.telemetry_sidebar)
        self.telemetry_section.setObjectName("telemetry_section")
        self.telemetry_section_layout = QtWidgets.QVBoxLayout(self.telemetry_section)
        self.telemetry_section_layout.setContentsMargins(8, 8, 8, 8)
        self.telemetry_section_layout.setSpacing(8)

        self.speed_display = SpeedDisplayTelemetryWidget(parent=self.telemetry_section)
        self.speed_display.setObjectName("speed_display")
        self.telemetry_section_layout.addWidget(self.speed_display)

        self.telemetry_status_label = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_status_label.setObjectName("telemetry_status_label")
        self.telemetry_status_label.setWordWrap(True)
        self.telemetry_section_layout.addWidget(self.telemetry_status_label)

        self.telemetry_visuals_layout = QtWidgets.QHBoxLayout()
        self.telemetry_visuals_layout.setSpacing(8)

        self.steering_visual = SteeringWheelTelemetryWidget(parent=self.telemetry_section)
        self.steering_visual.setObjectName("steering_visual")
        self.telemetry_visuals_layout.addWidget(self.steering_visual, 1)

        self.pedals_visual = PedalTelemetryWidget(parent=self.telemetry_section)
        self.pedals_visual.setObjectName("pedals_visual")
        self.telemetry_visuals_layout.addWidget(self.pedals_visual, 1)

        self.gforce_visual = GForceTelemetryWidget(parent=self.telemetry_section)
        self.gforce_visual.setObjectName("gforce_visual")
        self.telemetry_visuals_layout.addWidget(self.gforce_visual, 1)

        self.telemetry_section_layout.addLayout(self.telemetry_visuals_layout)

        self.telemetry_grid = QtWidgets.QGridLayout()
        self.telemetry_grid.setHorizontalSpacing(10)
        self.telemetry_grid.setVerticalSpacing(2)

        self.telemetry_speed_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_speed_caption.setObjectName("telemetry_speed_caption")
        self.telemetry_grid.addWidget(self.telemetry_speed_caption, 0, 0)
        self.telemetry_speed_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_speed_value.setObjectName("telemetry_speed_value")
        self.telemetry_speed_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_speed_value, 0, 1)

        self.telemetry_steering_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_steering_caption.setObjectName("telemetry_steering_caption")
        self.telemetry_grid.addWidget(self.telemetry_steering_caption, 1, 0)
        self.telemetry_steering_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_steering_value.setObjectName("telemetry_steering_value")
        self.telemetry_steering_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_steering_value, 1, 1)

        self.telemetry_pedals_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_pedals_caption.setObjectName("telemetry_pedals_caption")
        self.telemetry_grid.addWidget(self.telemetry_pedals_caption, 2, 0)
        self.telemetry_pedals_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_pedals_value.setObjectName("telemetry_pedals_value")
        self.telemetry_pedals_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_pedals_value, 2, 1)

        self.telemetry_gear_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_gear_caption.setObjectName("telemetry_gear_caption")
        self.telemetry_grid.addWidget(self.telemetry_gear_caption, 3, 0)
        self.telemetry_gear_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_gear_value.setObjectName("telemetry_gear_value")
        self.telemetry_gear_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_gear_value, 3, 1)

        self.telemetry_signals_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_signals_caption.setObjectName("telemetry_signals_caption")
        self.telemetry_grid.addWidget(self.telemetry_signals_caption, 4, 0)
        self.telemetry_signals_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_signals_value.setObjectName("telemetry_signals_value")
        self.telemetry_signals_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_signals_value, 4, 1)

        self.telemetry_drive_assist_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_drive_assist_caption.setObjectName("telemetry_drive_assist_caption")
        self.telemetry_grid.addWidget(self.telemetry_drive_assist_caption, 5, 0)
        self.telemetry_drive_assist_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_drive_assist_value.setObjectName("telemetry_drive_assist_value")
        self.telemetry_drive_assist_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_drive_assist_value, 5, 1)

        self.telemetry_heading_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_heading_caption.setObjectName("telemetry_heading_caption")
        self.telemetry_grid.addWidget(self.telemetry_heading_caption, 6, 0)
        self.telemetry_heading_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_heading_value.setObjectName("telemetry_heading_value")
        self.telemetry_heading_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_heading_value, 6, 1)

        self.telemetry_position_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_position_caption.setObjectName("telemetry_position_caption")
        self.telemetry_grid.addWidget(self.telemetry_position_caption, 7, 0)
        self.telemetry_position_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_position_value.setObjectName("telemetry_position_value")
        self.telemetry_position_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_position_value, 7, 1)

        self.telemetry_acceleration_caption = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_acceleration_caption.setObjectName("telemetry_acceleration_caption")
        self.telemetry_grid.addWidget(self.telemetry_acceleration_caption, 8, 0)
        self.telemetry_acceleration_value = QtWidgets.QLabel(parent=self.telemetry_section)
        self.telemetry_acceleration_value.setObjectName("telemetry_acceleration_value")
        self.telemetry_acceleration_value.setWordWrap(True)
        self.telemetry_grid.addWidget(self.telemetry_acceleration_value, 8, 1)

        self.telemetry_grid.setColumnStretch(1, 1)
        self.telemetry_section_layout.addLayout(self.telemetry_grid)
        self.telemetry_sidebar_layout.addWidget(self.telemetry_section, 1)

        self.map_view_container = QtWidgets.QGroupBox(parent=self.top_content_splitter)
        self.map_view_container.setObjectName("map_view_container")
        self.map_view_container.setMinimumWidth(360)

        self.map_view_container_layout = QtWidgets.QVBoxLayout(self.map_view_container)
        self.map_view_container_layout.setContentsMargins(8, 8, 8, 8)
        self.map_view_container_layout.setSpacing(8)

        self.map_view = QtWebEngineWidgets.QWebEngineView(parent=self.map_view_container)
        self.map_view.setObjectName("map_view")
        self.map_view.setMinimumSize(QtCore.QSize(320, 180))
        self.map_view.setUrl(QtCore.QUrl("about:blank"))
        self.map_view_container_layout.addWidget(self.map_view)

        self.map_status_label = QtWidgets.QLabel(parent=self.map_view_container)
        self.map_status_label.setObjectName("map_status_label")
        self.map_status_label.setWordWrap(True)
        self.map_status_label.setMaximumHeight(42)
        self.map_view_container_layout.addWidget(self.map_status_label)

        self.event_details_section = QtWidgets.QGroupBox(parent=self.map_view_container)
        self.event_details_section.setObjectName("event_details_section")
        self.event_details_section_layout = QtWidgets.QVBoxLayout(self.event_details_section)
        self.event_details_section_layout.setContentsMargins(8, 8, 8, 8)
        self.event_details_section_layout.setSpacing(6)

        self.event_metadata_label = QtWidgets.QLabel(parent=self.event_details_section)
        self.event_metadata_label.setObjectName("event_metadata_label")
        self.event_metadata_label.setWordWrap(True)
        self.event_metadata_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.event_details_section_layout.addWidget(self.event_metadata_label)
        self.map_view_container_layout.addWidget(self.event_details_section)

        self.synced_videos_section = QtWidgets.QGroupBox(parent=self.main_content_splitter)
        self.synced_videos_section.setObjectName("synced_videos_section")
        self.synced_videos_section.setMinimumHeight(420)

        self.synced_videos_section_vertical_layout = QtWidgets.QVBoxLayout(self.synced_videos_section)
        self.synced_videos_section_vertical_layout.setContentsMargins(6, 6, 6, 6)
        self.synced_videos_section_vertical_layout.setSpacing(6)

        self.camera_grid_host = QtWidgets.QWidget()
        self.camera_grid_host.setObjectName("camera_grid_host")
        self.camera_grid_host.setMinimumHeight(170)
        self.camera_grid_host.setSizePolicy(
            QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
        )
        self.camera_grid_layout = QtWidgets.QGridLayout(self.camera_grid_host)
        self.camera_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_grid_layout.setSpacing(8)
        self.synced_videos_section_vertical_layout.addWidget(self.camera_grid_host, 1)

        self.synced_controls_vertical_layout = QtWidgets.QVBoxLayout()
        self.synced_controls_vertical_layout.setSpacing(8)

        self.synced_controls_horizontal_layout = QtWidgets.QHBoxLayout()
        self.synced_controls_horizontal_layout.setSpacing(8)

        self.synced_back_frame_button = QtWidgets.QPushButton(parent=self.synced_videos_section)
        self.synced_back_frame_button.setObjectName("synced_back_frame_button")
        self.synced_controls_horizontal_layout.addWidget(self.synced_back_frame_button)

        self.play_button_synced = QtWidgets.QPushButton(parent=self.synced_videos_section)
        self.play_button_synced.setObjectName("play_button_synced")
        self.synced_controls_horizontal_layout.addWidget(self.play_button_synced)

        self.synced_forward_frame_button = QtWidgets.QPushButton(parent=self.synced_videos_section)
        self.synced_forward_frame_button.setObjectName("synced_forward_frame_button")
        self.synced_controls_horizontal_layout.addWidget(self.synced_forward_frame_button)

        self.capture_frame_button = QtWidgets.QPushButton(parent=self.synced_videos_section)
        self.capture_frame_button.setObjectName("capture_frame_button")
        self.synced_controls_horizontal_layout.addWidget(self.capture_frame_button)

        self.export_evidence_button = QtWidgets.QPushButton(parent=self.synced_videos_section)
        self.export_evidence_button.setObjectName("export_evidence_button")
        self.synced_controls_horizontal_layout.addWidget(self.export_evidence_button)

        self.synced_seek_label = QtWidgets.QLabel(parent=self.synced_videos_section)
        self.synced_seek_label.setObjectName("synced_seek_label")
        self.synced_controls_horizontal_layout.addWidget(self.synced_seek_label)

        self.seek_slider = EventBookmarkSlider(
            QtCore.Qt.Orientation.Horizontal,
            parent=self.synced_videos_section,
        )
        self.seek_slider.setObjectName("seek_slider")
        self.seek_slider.setMinimumWidth(220)
        self.synced_controls_horizontal_layout.addWidget(self.seek_slider, 1)

        self.speed_label = QtWidgets.QLabel(parent=self.synced_videos_section)
        self.speed_label.setObjectName("speed_label")
        self.synced_controls_horizontal_layout.addWidget(self.speed_label)

        self.speed_dropdown = QtWidgets.QComboBox(parent=self.synced_videos_section)
        self.speed_dropdown.setObjectName("speed_dropdown")
        self.speed_dropdown.addItems(["0.25x", "0.5x", "1x", "2x", "4x"])
        self.synced_controls_horizontal_layout.addWidget(self.speed_dropdown)

        self.synced_controls_vertical_layout.addLayout(self.synced_controls_horizontal_layout)
        self.synced_videos_section_vertical_layout.addLayout(self.synced_controls_vertical_layout)

        self.main_window_vertical_layout.addWidget(self.main_content_splitter, 1)

        self.bottom_controls_frame = QtWidgets.QFrame(parent=self.main_window_frame)
        self.bottom_controls_frame.setObjectName("bottom_controls_frame")
        self.bottom_controls_frame.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        self.bottom_controls_layout = QtWidgets.QVBoxLayout(self.bottom_controls_frame)
        self.bottom_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_controls_layout.setSpacing(8)

        self.folder_controls_row = QtWidgets.QHBoxLayout()
        self.folder_controls_row.setSpacing(8)

        self.load_folder_button = QtWidgets.QPushButton(parent=self.bottom_controls_frame)
        self.load_folder_button.setObjectName("load_folder_button")
        self.folder_controls_row.addWidget(self.load_folder_button)

        self.recover_clips_button = QtWidgets.QPushButton(parent=self.bottom_controls_frame)
        self.recover_clips_button.setObjectName("recover_clips_button")
        self.folder_controls_row.addWidget(self.recover_clips_button)

        self.rename_input = QtWidgets.QLineEdit(parent=self.bottom_controls_frame)
        self.rename_input.setObjectName("rename_input")
        self.folder_controls_row.addWidget(self.rename_input, 1)

        self.rename_button = QtWidgets.QPushButton(parent=self.bottom_controls_frame)
        self.rename_button.setObjectName("rename_button")
        self.folder_controls_row.addWidget(self.rename_button)

        self.delete_button = QtWidgets.QPushButton(parent=self.bottom_controls_frame)
        self.delete_button.setObjectName("delete_button")
        self.folder_controls_row.addWidget(self.delete_button)

        self.bottom_controls_layout.addLayout(self.folder_controls_row)

        self.status_controls_row = QtWidgets.QHBoxLayout()
        self.status_controls_row.setSpacing(8)

        self.event_filter_label = QtWidgets.QLabel(parent=self.bottom_controls_frame)
        self.event_filter_label.setObjectName("event_filter_label")
        self.status_controls_row.addWidget(self.event_filter_label)

        self.event_filter_dropdown = QtWidgets.QComboBox(parent=self.bottom_controls_frame)
        self.event_filter_dropdown.setObjectName("event_filter_dropdown")
        self.event_filter_dropdown.addItems(
            ["All Events", "Sentry Mode", "Collision", "Door Open", "Normal Drive"]
        )
        self.status_controls_row.addWidget(self.event_filter_dropdown)

        self.status_controls_row.addStretch(1)

        self.timestamp_label = QtWidgets.QLabel(parent=self.bottom_controls_frame)
        self.timestamp_label.setObjectName("timestamp_label")
        self.status_controls_row.addWidget(self.timestamp_label)

        self.event_type_label = QtWidgets.QLabel(parent=self.bottom_controls_frame)
        self.event_type_label.setObjectName("event_type_label")
        self.status_controls_row.addWidget(self.event_type_label)

        self.bottom_controls_layout.addLayout(self.status_controls_row)
        self.main_window_vertical_layout.addWidget(self.bottom_controls_frame)

        self.viewer_tab_layout.addWidget(self.main_window_frame)
        self.central_widget_vertical_layout.addWidget(self.mode_tabs)
        tesla_cam_viewer_main_window.setCentralWidget(self.central_widget)

        self.menuBar = QtWidgets.QMenuBar(parent=tesla_cam_viewer_main_window)
        self.menuBar.setObjectName("menuBar")
        self.menuFile = QtWidgets.QMenu(parent=self.menuBar)
        self.menuFile.setObjectName("menuFile")
        self.menuMode = QtWidgets.QMenu(parent=self.menuBar)
        self.menuMode.setObjectName("menuMode")
        self.menuRecovery = QtWidgets.QMenu(parent=self.menuBar)
        self.menuRecovery.setObjectName("menuRecovery")
        tesla_cam_viewer_main_window.setMenuBar(self.menuBar)

        self.actionLoad_Files = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionLoad_Files.setObjectName("actionLoad_Files")
        self.actionViewer_Mode = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionViewer_Mode.setObjectName("actionViewer_Mode")
        self.actionRecovery_Mode = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionRecovery_Mode.setObjectName("actionRecovery_Mode")
        self.actionStart_Recovery = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionStart_Recovery.setObjectName("actionStart_Recovery")
        self.actionCancel_Recovery = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionCancel_Recovery.setObjectName("actionCancel_Recovery")
        self.actionUse_Recommended_Recovery_Settings = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionUse_Recommended_Recovery_Settings.setObjectName("actionUse_Recommended_Recovery_Settings")
        self.actionUse_Loaded_Event_Date = QtGui.QAction(parent=tesla_cam_viewer_main_window)
        self.actionUse_Loaded_Event_Date.setObjectName("actionUse_Loaded_Event_Date")
        self.menuFile.addAction(self.actionLoad_Files)
        self.menuMode.addAction(self.actionViewer_Mode)
        self.menuMode.addAction(self.actionRecovery_Mode)
        self.menuRecovery.addAction(self.actionStart_Recovery)
        self.menuRecovery.addAction(self.actionCancel_Recovery)
        self.menuRecovery.addSeparator()
        self.menuRecovery.addAction(self.actionUse_Recommended_Recovery_Settings)
        self.menuRecovery.addAction(self.actionUse_Loaded_Event_Date)
        self.menuBar.addAction(self.menuFile.menuAction())
        self.menuBar.addAction(self.menuMode.menuAction())
        self.menuBar.addAction(self.menuRecovery.menuAction())

        self.top_content_splitter.setStretchFactor(0, 5)
        self.top_content_splitter.setStretchFactor(1, 2)
        self.top_content_splitter.setStretchFactor(2, 2)
        self.main_content_splitter.setStretchFactor(0, 3)
        self.main_content_splitter.setStretchFactor(1, 4)

        self.retranslateUi(tesla_cam_viewer_main_window)
        QtCore.QMetaObject.connectSlotsByName(tesla_cam_viewer_main_window)

    def retranslateUi(self, tesla_cam_viewer_main_window):
        """Apply user-visible text to the already-created widgets."""

        _translate = QtCore.QCoreApplication.translate
        tesla_cam_viewer_main_window.setWindowTitle(
            _translate("tesla_cam_viewer_main_window", "TeslaCam Viewer")
        )
        self.mode_tabs.setTabText(self.mode_tabs.indexOf(self.viewer_tab), _translate("tesla_cam_viewer_main_window", "Viewer"))
        self.mode_tabs.setTabText(self.mode_tabs.indexOf(self.recovery_tab), _translate("tesla_cam_viewer_main_window", "Recovery"))
        self.recovery_tab_header.setText(
            _translate(
                "tesla_cam_viewer_main_window",
                "Recovery mode is separate from normal clip playback. Use it to scan either a live TeslaCam USB device or an image/raw file for likely overwritten footage and recover matches into a separate output folder.",
            )
        )
        self.event_video_section.setTitle(
            _translate("tesla_cam_viewer_main_window", "Main View")
        )
        self.telemetry_sidebar.setTitle(
            _translate("tesla_cam_viewer_main_window", "Vehicle Data")
        )
        self.telemetry_section.setTitle(
            _translate("tesla_cam_viewer_main_window", "Live Telemetry")
        )
        self.map_view_container.setTitle(
            _translate("tesla_cam_viewer_main_window", "Map / Event Location")
        )
        self.event_details_section.setTitle(
            _translate("tesla_cam_viewer_main_window", "Event Details")
        )
        self.synced_videos_section.setTitle(
            _translate("tesla_cam_viewer_main_window", "Other Angles")
        )
        self.event_back_frame_button.setText(
            _translate("tesla_cam_viewer_main_window", "◀ Frame")
        )
        self.play_button_event.setText(
            _translate("tesla_cam_viewer_main_window", "▶ Play Main")
        )
        self.event_forward_frame_button.setText(
            _translate("tesla_cam_viewer_main_window", "Frame ▶")
        )
        self.goto_event_button.setText(
            _translate("tesla_cam_viewer_main_window", "Jump to Event")
        )
        self.main_video_status_label.setText(
            _translate("tesla_cam_viewer_main_window", "Main angle status: Waiting for media")
        )
        self.synced_back_frame_button.setText(
            _translate("tesla_cam_viewer_main_window", "◀ Frame")
        )
        self.play_button_synced.setText(
            _translate("tesla_cam_viewer_main_window", "▶ Play All Angles")
        )
        self.synced_forward_frame_button.setText(
            _translate("tesla_cam_viewer_main_window", "Frame ▶")
        )
        self.capture_frame_button.setText(
            _translate("tesla_cam_viewer_main_window", "Capture Frame")
        )
        self.export_evidence_button.setText(
            _translate("tesla_cam_viewer_main_window", "Export Evidence")
        )
        self.speed_label.setText(_translate("tesla_cam_viewer_main_window", "Speed"))
        self.synced_seek_label.setText(_translate("tesla_cam_viewer_main_window", "Timeline"))
        self.load_folder_button.setText(
            _translate("tesla_cam_viewer_main_window", "Open TeslaCam Folder")
        )
        self.recover_clips_button.setText(
            _translate("tesla_cam_viewer_main_window", "Open Recovery Tools")
        )
        self.rename_input.setPlaceholderText(
            _translate("tesla_cam_viewer_main_window", "Rename current folder")
        )
        self.rename_button.setText(_translate("tesla_cam_viewer_main_window", "Rename"))
        self.delete_button.setText(
            _translate("tesla_cam_viewer_main_window", "Delete Folder")
        )
        self.event_filter_label.setText(
            _translate("tesla_cam_viewer_main_window", "Filter")
        )
        self.timestamp_label.setText(
            _translate("tesla_cam_viewer_main_window", "Timestamp: 00:00:00")
        )
        self.event_type_label.setText(
            _translate("tesla_cam_viewer_main_window", "Event Type: N/A")
        )
        self.viewer_help_label.setText(
            _translate(
                "tesla_cam_viewer_main_window",
                "Start by opening a TeslaCam event folder. The viewer loads only the camera angles found in that folder, and Recovery Tools can help when footage no longer appears normally.",
            )
        )
        self.map_status_label.setText(
            _translate("tesla_cam_viewer_main_window", "Map status: Waiting for GPS data")
        )
        self.event_metadata_label.setText(
            _translate("tesla_cam_viewer_main_window", "Event details: Waiting for event data")
        )
        self.telemetry_status_label.setText(
            _translate(
                "tesla_cam_viewer_main_window",
                "Telemetry status: Load a supported clip to view embedded driving data.",
            )
        )
        self.telemetry_speed_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Speed")
        )
        self.telemetry_speed_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_steering_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Steering")
        )
        self.telemetry_steering_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_pedals_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Pedals")
        )
        self.telemetry_pedals_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_gear_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Gear")
        )
        self.telemetry_gear_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_signals_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Signals")
        )
        self.telemetry_signals_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_drive_assist_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Drive Assist")
        )
        self.telemetry_drive_assist_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_heading_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Heading")
        )
        self.telemetry_heading_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_position_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Position")
        )
        self.telemetry_position_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.telemetry_acceleration_caption.setText(
            _translate("tesla_cam_viewer_main_window", "Acceleration")
        )
        self.telemetry_acceleration_value.setText(
            _translate("tesla_cam_viewer_main_window", "Not available")
        )
        self.menuFile.setTitle(_translate("tesla_cam_viewer_main_window", "File"))
        self.menuMode.setTitle(_translate("tesla_cam_viewer_main_window", "Mode"))
        self.menuRecovery.setTitle(_translate("tesla_cam_viewer_main_window", "Recovery"))
        self.actionLoad_Files.setText(
            _translate("tesla_cam_viewer_main_window", "Load Files")
        )
        self.actionViewer_Mode.setText(
            _translate("tesla_cam_viewer_main_window", "Viewer Mode")
        )
        self.actionRecovery_Mode.setText(
            _translate("tesla_cam_viewer_main_window", "Recovery Mode")
        )
        self.actionStart_Recovery.setText(
            _translate("tesla_cam_viewer_main_window", "Start Recovery")
        )
        self.actionCancel_Recovery.setText(
            _translate("tesla_cam_viewer_main_window", "Cancel Recovery")
        )
        self.actionUse_Recommended_Recovery_Settings.setText(
            _translate("tesla_cam_viewer_main_window", "Use Recommended Settings")
        )
        self.actionUse_Loaded_Event_Date.setText(
            _translate("tesla_cam_viewer_main_window", "Use Loaded Event Date")
        )
