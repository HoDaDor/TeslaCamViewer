"""Dialog for collecting evidence export options from the user."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


@dataclass(frozen=True, slots=True)
class ExportOptions:
    """Normalized export choices returned by ``EvidenceExportDialog``."""

    output_root: Path
    package_name: str
    scope: str
    anchor_mode: str
    current_position_ms: int
    event_position_ms: int | None
    include_originals: bool
    include_stills: bool
    include_clips: bool
    include_overlay: bool
    image_format: str
    clip_before_seconds: int
    clip_after_seconds: int


class EvidenceExportDialog(QDialog):
    """Small modal dialog for still/clip evidence package settings."""

    def __init__(
        self,
        *,
        default_output_root: Path,
        default_package_name: str,
        has_event_bookmark: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Export Evidence Package")
        self.setModal(True)
        self.resize(560, 420)

        self._has_event_bookmark = has_event_bookmark

        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(12)

        intro_label = QLabel(
            "Export an evidence-oriented package with untouched originals, annotated "
            "derivatives, and a manifest containing hashes and event metadata."
        )
        intro_label.setWordWrap(True)
        root_layout.addWidget(intro_label)

        location_group = QGroupBox("Package")
        location_layout = QGridLayout(location_group)
        location_layout.setHorizontalSpacing(10)
        location_layout.setVerticalSpacing(8)

        self.output_root_edit = QLineEdit(str(default_output_root))
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.choose_output_root)

        self.package_name_edit = QLineEdit(default_package_name)

        location_layout.addWidget(QLabel("Destination"), 0, 0)
        location_layout.addWidget(self.output_root_edit, 0, 1)
        location_layout.addWidget(browse_button, 0, 2)
        location_layout.addWidget(QLabel("Package Name"), 1, 0)
        location_layout.addWidget(self.package_name_edit, 1, 1, 1, 2)
        root_layout.addWidget(location_group)

        export_group = QGroupBox("Export Options")
        export_layout = QFormLayout(export_group)
        export_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Main angle only", "main")
        self.scope_combo.addItem("All detected angles", "all")

        self.anchor_combo = QComboBox()
        if has_event_bookmark:
            self.anchor_combo.addItem("Event bookmark (Recommended)", "event")
        self.anchor_combo.addItem("Current timeline position", "current")

        self.include_originals_check = QCheckBox("Copy untouched source clips and event.json")
        self.include_originals_check.setChecked(True)

        self.include_stills_check = QCheckBox("Export annotated still frames")
        self.include_stills_check.setChecked(True)

        self.include_clips_check = QCheckBox("Export annotated clip excerpts")
        self.include_clips_check.setChecked(False)

        self.include_overlay_check = QCheckBox("Burn metadata into exported stills/clips")
        self.include_overlay_check.setChecked(True)

        self.image_format_combo = QComboBox()
        self.image_format_combo.addItem("PNG", "png")
        self.image_format_combo.addItem("JPG", "jpg")

        clip_window_row = QHBoxLayout()
        clip_window_row.setSpacing(8)
        self.clip_before_spin = QSpinBox()
        self.clip_before_spin.setRange(0, 300)
        self.clip_before_spin.setValue(10)
        self.clip_after_spin = QSpinBox()
        self.clip_after_spin.setRange(0, 300)
        self.clip_after_spin.setValue(10)
        clip_window_row.addWidget(QLabel("Before"))
        clip_window_row.addWidget(self.clip_before_spin)
        clip_window_row.addWidget(QLabel("After"))
        clip_window_row.addWidget(self.clip_after_spin)
        clip_window_row.addStretch(1)
        clip_window_host = QHBoxLayout()
        clip_window_host.addLayout(clip_window_row)

        export_layout.addRow("Scope", self.scope_combo)
        export_layout.addRow("Anchor", self.anchor_combo)
        export_layout.addRow("Still Format", self.image_format_combo)
        export_layout.addRow("Clip Window (sec)", clip_window_row)
        export_layout.addRow(self.include_originals_check)
        export_layout.addRow(self.include_stills_check)
        export_layout.addRow(self.include_clips_check)
        export_layout.addRow(self.include_overlay_check)
        root_layout.addWidget(export_group)

        note_label = QLabel(
            "Best practice: keep the original Tesla clips untouched and treat the annotated "
            "exports as sharing copies or demonstratives."
        )
        note_label.setWordWrap(True)
        note_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root_layout.addWidget(note_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root_layout.addWidget(self.button_box)

        self.include_clips_check.toggled.connect(self.update_enabled_states)
        self.include_stills_check.toggled.connect(self.update_enabled_states)
        self.update_enabled_states()

    def choose_output_root(self):
        """Let the user choose where the export package should be written."""

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Export Destination",
            self.output_root_edit.text(),
        )
        if selected_dir:
            self.output_root_edit.setText(selected_dir)

    def update_enabled_states(self):
        """Enable fields only when their matching export option is selected."""

        clips_enabled = self.include_clips_check.isChecked()
        stills_enabled = self.include_stills_check.isChecked()
        self.clip_before_spin.setEnabled(clips_enabled)
        self.clip_after_spin.setEnabled(clips_enabled)
        self.image_format_combo.setEnabled(stills_enabled)

    def export_options(self, *, current_position_ms: int, event_position_ms: int | None) -> ExportOptions:
        """Return the dialog values as an ``ExportOptions`` object."""

        package_name = self.package_name_edit.text().strip()
        if not package_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            package_name = f"teslacam_evidence_{timestamp}"

        return ExportOptions(
            output_root=Path(self.output_root_edit.text()).expanduser().resolve(),
            package_name=package_name,
            scope=self.scope_combo.currentData(),
            anchor_mode=self.anchor_combo.currentData(),
            current_position_ms=max(0, int(current_position_ms)),
            event_position_ms=event_position_ms,
            include_originals=self.include_originals_check.isChecked(),
            include_stills=self.include_stills_check.isChecked(),
            include_clips=self.include_clips_check.isChecked(),
            include_overlay=self.include_overlay_check.isChecked(),
            image_format=self.image_format_combo.currentData(),
            clip_before_seconds=self.clip_before_spin.value(),
            clip_after_seconds=self.clip_after_spin.value(),
        )
