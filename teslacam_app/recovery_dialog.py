"""Qt widgets and worker wiring for the TeslaCam recovery workspace."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTime, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .recovery import (
    DriveInfo,
    RecoveryCandidateResult,
    RecoveryOptions,
    RecoverySharedState,
    RecoveryTuning,
    build_raw_path_from_mount,
    carve_clip,
    detect_hardware_profile,
    drive_size_hint,
    ffprobe_program,
    format_bytes,
    format_target_dates,
    image_size_hint,
    is_plausible_mp4_header,
    is_windows_admin,
    list_windows_drives,
    parse_target_dates,
    probe_candidate_and_carve,
    recommended_salvage_size_mb,
    recommended_tuning,
    tuning_for_preset,
    RECOVERY_SOURCE_DRIVE,
    RECOVERY_SOURCE_IMAGE,
    TUNING_PRESET_AGGRESSIVE,
    TUNING_PRESET_CONSERVATIVE,
    TUNING_PRESET_RECOMMENDED,
)
from .settings_store import AppSettingsStore


DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "TeslaCamRecovered"
RECOVERY_REPORT_FILENAME = "recovery_report.json"


class CandidateProbeTask(QRunnable):
    """Thread-pool task that probes and optionally carves one MP4 candidate."""

    def __init__(
        self,
        *,
        options: RecoveryOptions,
        offset: int,
        shared_state: RecoverySharedState,
        worker: "RecoveryScanWorker",
    ):
        super().__init__()
        self.options = options
        self.offset = offset
        self.shared_state = shared_state
        self.worker = worker
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        """Run the candidate probe and report the result back to the worker."""

        result = probe_candidate_and_carve(
            options=self.options,
            offset=self.offset,
            is_cancelled=self.worker.is_cancelled,
        )
        self.shared_state.note_candidate_finished(result)
        self.worker.log_message.emit(format_candidate_result(result))
        self.worker.candidate_result.emit(result)


class RecoveryScanWorker(QObject):
    """Long-running recovery scanner that reports progress through Qt signals."""

    progress_changed = Signal(dict)
    log_message = Signal(str)
    candidate_result = Signal(object)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, options: RecoveryOptions):
        super().__init__()
        self.options = options
        self._cancel_requested = False

    @Slot()
    def run(self):
        """Scan the configured source for plausible MP4 headers."""

        thread_pool = QThreadPool()
        thread_pool.setMaxThreadCount(self.options.tuning.max_workers)
        shared_state = RecoverySharedState()
        carved_offsets: set[int] = set()
        scanned_bytes = 0
        total_size = max(0, int(self.options.total_size_hint or 0))
        last_report_time = datetime.now()
        last_report_percent = -1
        prev_tail = b""
        global_offset = 0
        start_time = datetime.now()
        self.log_message.emit(f"[START] Source: {self.options.source_label}")
        self.log_message.emit(
            "[SETTINGS] "
            f"chunk={format_bytes(self.options.tuning.chunk_size)}, "
            f"preview={format_bytes(self.options.tuning.preview_bytes)}, "
            f"carve_limit={format_bytes(self.options.tuning.max_carve_bytes)}, "
            f"workers={self.options.tuning.max_workers}, "
            f"pending_limit={self.options.tuning.max_pending_jobs}"
        )

        try:
            source_handle = open(self.options.source_path, "rb", buffering=0)
        except PermissionError:
            self.failed.emit(
                "Permission denied opening the selected source. Run the app as Administrator for raw USB scans."
            )
            return
        except OSError as exc:
            self.failed.emit(f"Unable to open the selected source: {exc}")
            return

        try:
            while not self._cancel_requested:
                chunk = source_handle.read(self.options.tuning.chunk_size)
                if not chunk:
                    break

                scanned_bytes += len(chunk)
                buffer = prev_tail + chunk
                buffer_start_offset = max(0, global_offset - len(prev_tail))

                pos = 0
                while not self._cancel_requested:
                    idx = buffer.find(b"ftyp", pos)
                    if idx == -1:
                        break

                    abs_ftyp_offset = buffer_start_offset + idx
                    abs_header_offset = abs_ftyp_offset - 4
                    pos = idx + 4
                    if abs_header_offset in carved_offsets:
                        continue
                    if not is_plausible_mp4_header(buffer, idx):
                        continue

                    carved_offsets.add(abs_header_offset)
                    shared_state.note_candidate_seen()
                    self._drain_backpressure(shared_state, scanned_bytes, total_size, start_time)
                    thread_pool.start(
                        CandidateProbeTask(
                            options=self.options,
                            offset=abs_header_offset,
                            shared_state=shared_state,
                            worker=self,
                        )
                    )

                prev_tail = buffer[-self.options.tuning.overlap :] if len(buffer) > self.options.tuning.overlap else buffer
                global_offset += len(chunk)
                now = datetime.now()
                percent = int(scanned_bytes * 100 / total_size) if total_size > 0 else 0
                if percent != last_report_percent or (now - last_report_time).total_seconds() >= 2:
                    last_report_percent = percent
                    last_report_time = now
                    self._emit_progress(shared_state, scanned_bytes, total_size, start_time)

            if self._cancel_requested:
                self.log_message.emit("[CANCEL] Scan cancelled. Waiting for active tasks to finish...")

            while shared_state.snapshot()["pending_jobs"] > 0:
                self._emit_progress(shared_state, scanned_bytes, total_size, start_time)
                QThread.msleep(75)

            thread_pool.waitForDone()
            snapshot = shared_state.snapshot()
            elapsed_seconds = int((datetime.now() - start_time).total_seconds())
            snapshot.update(
                {
                    "scanned_bytes": scanned_bytes,
                    "total_size": total_size,
                    "elapsed_seconds": elapsed_seconds,
                    "cancelled": self._cancel_requested,
                }
            )
            self.finished.emit(snapshot)
        finally:
            source_handle.close()

    def cancel(self):
        """Request a graceful stop for the scan loop."""

        self._cancel_requested = True

    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        return self._cancel_requested

    def _drain_backpressure(
        self,
        shared_state: RecoverySharedState,
        scanned_bytes: int,
        total_size: int,
        start_time: datetime,
    ):
        while not self._cancel_requested:
            pending_jobs = shared_state.snapshot()["pending_jobs"]
            if pending_jobs < self.options.tuning.max_pending_jobs:
                return
            self._emit_progress(shared_state, scanned_bytes, total_size, start_time)
            QThread.msleep(25)

    def _emit_progress(
        self,
        shared_state: RecoverySharedState,
        scanned_bytes: int,
        total_size: int,
        start_time: datetime,
    ):
        snapshot = shared_state.snapshot()
        elapsed = max(0.001, (datetime.now() - start_time).total_seconds())
        percent = int(scanned_bytes * 100 / total_size) if total_size > 0 else 0
        eta_seconds = None
        if percent > 0:
            estimated_total = elapsed * 100.0 / percent
            eta_seconds = max(0, int(estimated_total - elapsed))

        payload = {
            **snapshot,
            "scanned_bytes": scanned_bytes,
            "total_size": total_size,
            "percent": percent,
            "elapsed_seconds": int(elapsed),
            "eta_seconds": eta_seconds,
        }
        self.progress_changed.emit(payload)


class ManualSalvageWorker(QObject):
    """Background worker for larger one-off carves from a known offset."""

    log_message = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        source_path: str,
        output_path: Path,
        offset: int,
        max_bytes: int,
        chunk_size: int,
        total_size_hint: int,
    ):
        super().__init__()
        self.source_path = source_path
        self.output_path = output_path
        self.offset = offset
        self.max_bytes = max_bytes
        self.chunk_size = chunk_size
        self.total_size_hint = total_size_hint
        self._cancel_requested = False

    @Slot()
    def run(self):
        """Carve a larger bounded block without blocking the Qt UI thread."""

        try:
            self.log_message.emit(
                "[SALVAGE] "
                f"Recovering up to {format_bytes(self.max_bytes)} from offset {self.offset}"
            )
            bytes_written = carve_clip(
                source_path=self.source_path,
                output_path=self.output_path,
                offset=self.offset,
                max_bytes=self.max_bytes,
                chunk_size=self.chunk_size,
                is_cancelled=self.is_cancelled,
                total_size_hint=self.total_size_hint,
            )
        except PermissionError:
            self.failed.emit(
                "Permission denied opening the selected source. Run the app as Administrator for raw USB recovery."
            )
            return
        except OSError as exc:
            self.failed.emit(f"Unable to carve the selected offset: {exc}")
            return

        if self._cancel_requested and bytes_written <= 0:
            self.failed.emit("Extra salvage was cancelled before any data was written.")
            return
        if bytes_written <= 0:
            self.failed.emit("No data was written from the selected offset.")
            return

        self.finished.emit(
            RecoveryCandidateResult(
                offset=self.offset,
                timestamp_text="Manual salvage",
                matched=True,
                bytes_written=bytes_written,
                output_path=str(self.output_path),
                status="manual_salvage",
            )
        )

    def cancel(self):
        """Request a graceful stop for the manual carve."""

        self._cancel_requested = True

    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        return self._cancel_requested


class RecoverySetupDialog(QDialog):
    """Small guided dialog for non-technical recovery setup."""

    def __init__(self, *, suggested_event_date: date | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Guided Recovery Setup")
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Answer a few simple questions and the recovery tab will be filled in for you."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("Image / raw file (safer)", RECOVERY_SOURCE_IMAGE)
        self.source_combo.addItem("Live TeslaCam USB drive", RECOVERY_SOURCE_DRIVE)

        self.goal_combo = QComboBox()
        self.goal_combo.addItem("Balanced Scan (Recommended)", TUNING_PRESET_RECOMMENDED)
        self.goal_combo.addItem("Quick Scan", TUNING_PRESET_CONSERVATIVE)
        self.goal_combo.addItem("Deep Scan", TUNING_PRESET_AGGRESSIVE)

        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("YYYY-MM-DD")
        if suggested_event_date is not None:
            self.date_edit.setText(suggested_event_date.isoformat())

        self.use_time_window_check = QCheckBox("Limit to a time window")
        self.time_row = QWidget()
        time_row_layout = QHBoxLayout(self.time_row)
        time_row_layout.setContentsMargins(0, 0, 0, 0)
        time_row_layout.setSpacing(8)
        self.time_start_edit = QTimeEdit()
        self.time_start_edit.setDisplayFormat("HH:mm:ss")
        self.time_start_edit.setTime(QTime.fromString("00:00:00", "HH:mm:ss"))
        self.time_end_edit = QTimeEdit()
        self.time_end_edit.setDisplayFormat("HH:mm:ss")
        self.time_end_edit.setTime(QTime.fromString("23:59:59", "HH:mm:ss"))
        time_row_layout.addWidget(QLabel("Start"))
        time_row_layout.addWidget(self.time_start_edit)
        time_row_layout.addWidget(QLabel("End"))
        time_row_layout.addWidget(self.time_end_edit)
        time_row_layout.addStretch(1)

        self.scan_only_check = QCheckBox("Start with Scan Only")
        self.scan_only_check.setChecked(True)

        form.addRow("Source", self.source_combo)
        form.addRow("Recovery Preset", self.goal_combo)
        form.addRow("Target Date", self.date_edit)
        form.addRow("", self.use_time_window_check)
        form.addRow("Time Window", self.time_row)
        form.addRow("", self.scan_only_check)
        layout.addLayout(form)

        self.helper_label = QLabel(
            "Tip: if the clip matters, use an image copy instead of the live USB whenever possible."
        )
        self.helper_label.setWordWrap(True)
        layout.addWidget(self.helper_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.use_time_window_check.toggled.connect(self.time_row.setEnabled)
        self.time_row.setEnabled(False)

    def setup_values(self) -> dict[str, object]:
        """Return the guided selections in a simple settings-shaped dict."""

        return {
            "source_kind": str(self.source_combo.currentData()),
            "goal_preset": str(self.goal_combo.currentData()),
            "target_date": self.date_edit.text().strip(),
            "filter_by_time": self.use_time_window_check.isChecked(),
            "time_start": self.time_start_edit.time().toString("HH:mm:ss"),
            "time_end": self.time_end_edit.time().toString("HH:mm:ss"),
            "scan_only": self.scan_only_check.isChecked(),
        }


class RecoveryPanel(QWidget):
    """Recovery tab UI for source selection, tuning, progress, and results."""

    request_switch_to_viewer = Signal()

    def __init__(
        self,
        *,
        settings_store: AppSettingsStore,
        suggested_event_date: date | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.settings_store = settings_store
        self.suggested_event_date = suggested_event_date
        self.hardware_profile = detect_hardware_profile()
        self.recommended = recommended_tuning(self.hardware_profile)
        self.ffprobe_path = ffprobe_program()

        self.worker_thread: QThread | None = None
        self.worker: RecoveryScanWorker | None = None
        self.salvage_thread: QThread | None = None
        self.salvage_worker: ManualSalvageWorker | None = None
        self._busy = False

        self.drives = list_windows_drives()
        self._build_ui()
        self._load_saved_settings()
        self._refresh_drive_list()
        self._update_status_banner()

    def _build_ui(self):
        """Build the recovery tab controls and explanatory text."""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(10)

        intro = QLabel(
            "Recovery mode scans either a live TeslaCam USB drive or a disk image for plausible "
            "MP4 headers, probes candidate fragments by embedded creation timestamps, and can "
            "carve matching clips into a separate output folder. It is separate from normal event "
            "viewing."
        )
        intro.setWordWrap(True)
        root_layout.addWidget(intro)

        explanation = QPlainTextEdit()
        explanation.setReadOnly(True)
        explanation.setMaximumHeight(110)
        explanation.setPlainText(
            "What this mode does:\n"
            "- Reads a live USB volume directly or scans an image/raw file that you choose.\n"
            "- Looks for TeslaCam MP4 fragments that may no longer appear in the normal folder view.\n"
            "- Filters candidates by the dates and optional time window you specify.\n"
            "- Writes recovered matches to a new folder without modifying the source USB.\n\n"
            "Best practice: stop using the USB before scanning so new writes do not overwrite more data."
        )
        root_layout.addWidget(explanation)

        guide_group = QGroupBox("Recovery Guide")
        guide_layout = QVBoxLayout(guide_group)
        self.guide_summary_label = QLabel(
            "Use this mode when a clip no longer appears in TeslaCam normally and you want to search the raw USB media for video fragments that may still be recoverable."
        )
        self.guide_summary_label.setWordWrap(True)
        self.guide_steps_label = QLabel(
            "1. Choose the safest source you have. An image copy is better than the live USB.\n"
            "2. Enter the date you care about. Add a time window only if you need to narrow results.\n"
            "3. Pick a recovery preset. Most users should stay on Balanced.\n"
            "4. Start with Scan Only if you want to preview likely matches before writing recovered files."
        )
        self.guide_steps_label.setWordWrap(True)
        self.image_first_label = QLabel(
            "If the footage matters, unplug the Tesla USB from the car and avoid writing anything new to it before scanning."
        )
        self.image_first_label.setWordWrap(True)
        guide_action_row = QHBoxLayout()
        self.guided_setup_button = QPushButton("Guided Setup")
        self.guided_setup_button.clicked.connect(self._open_guided_setup)
        self.image_copy_guide_button = QPushButton("Image Copy Guide")
        self.image_copy_guide_button.clicked.connect(self._show_image_copy_guidance)
        guide_action_row.addWidget(self.guided_setup_button)
        guide_action_row.addWidget(self.image_copy_guide_button)
        guide_action_row.addStretch(1)
        guide_layout.addWidget(self.guide_summary_label)
        guide_layout.addWidget(self.guide_steps_label)
        guide_layout.addWidget(self.image_first_label)
        guide_layout.addLayout(guide_action_row)
        root_layout.addWidget(guide_group)

        system_group = QGroupBox("System")
        system_layout = QVBoxLayout(system_group)
        self.hardware_label = QLabel(self.hardware_profile.summary)
        self.hardware_label.setWordWrap(True)
        self.settings_path_label = QLabel(
            f"Settings YAML: {self.settings_store.path}"
        )
        self.settings_path_label.setWordWrap(True)
        system_layout.addWidget(self.hardware_label)
        system_layout.addWidget(self.settings_path_label)
        root_layout.addWidget(system_group)

        quick_help_group = QGroupBox("Quick Help")
        quick_help_layout = QVBoxLayout(quick_help_group)
        self.quick_help_label = QLabel(
            "Start with <b>Recommended</b> unless you already know your system can handle more. "
            "Use <b>Image / raw file</b> when possible to avoid working against the live USB. "
            "Narrow results with <b>Target Dates</b> first, then add a time window only if one day still has too many candidates. "
            "<b>Aggressive</b> uses more CPU and memory; <b>Conservative</b> is safer for smaller systems."
        )
        self.quick_help_label.setWordWrap(True)
        self.quick_help_label.setTextFormat(Qt.TextFormat.RichText)
        self.usb_speed_note_label = QLabel(
            "<b>Speed note:</b> recovery can only read as fast as the source drive and USB port allow. "
            "A USB 2.0 port can take much longer than USB 3.x or USB-C, and writing recovered files to a slow external drive can also become the bottleneck. "
            "If possible, scan an image copy stored on a fast internal SSD and write recovered clips to a separate fast drive."
        )
        self.usb_speed_note_label.setWordWrap(True)
        self.usb_speed_note_label.setTextFormat(Qt.TextFormat.RichText)
        self.usb_speed_note_label.setToolTip(
            "The app auto-tunes CPU worker settings, but USB bus speed and disk speed still control how quickly bytes can be read and written."
        )
        quick_help_layout.addWidget(self.quick_help_label)
        quick_help_layout.addWidget(self.usb_speed_note_label)
        root_layout.addWidget(quick_help_group)

        scan_group = QGroupBox("Scan Setup")
        scan_layout = QGridLayout(scan_group)
        scan_layout.setHorizontalSpacing(10)
        scan_layout.setVerticalSpacing(8)

        self.recovery_goal_combo = QComboBox()
        self.recovery_goal_combo.addItem("Balanced Scan (Recommended)", TUNING_PRESET_RECOMMENDED)
        self.recovery_goal_combo.addItem("Quick Scan", TUNING_PRESET_CONSERVATIVE)
        self.recovery_goal_combo.addItem("Deep Scan", TUNING_PRESET_AGGRESSIVE)
        self.recovery_goal_combo.currentIndexChanged.connect(self._apply_goal_preset)
        self.recovery_goal_label = self._help_label(
            "Recovery Preset",
            "Quick Scan is lighter and faster, Balanced is the default for most users, and Deep Scan searches more aggressively with higher system load.",
            self.recovery_goal_combo,
        )
        self.scenario_combo = QComboBox()
        self.scenario_combo.addItem("Common scenario: I only know the date", "date_only")
        self.scenario_combo.addItem("Common scenario: I know the date and rough time", "date_time")
        self.scenario_combo.addItem("Common scenario: I want to preview before writing files", "preview")
        self.scenario_combo.addItem("Common scenario: I want the safest workflow", "safe_image")
        self.scenario_combo.currentIndexChanged.connect(self._apply_scenario_hint)
        self.scenario_label = self._help_label(
            "Common Scenario",
            "Choose a common recovery scenario to get a matching tip and a few sensible defaults.",
            self.scenario_combo,
        )

        self.source_mode_combo = QComboBox()
        self.source_mode_combo.addItem("TeslaCam USB drive", RECOVERY_SOURCE_DRIVE)
        self.source_mode_combo.addItem("Image / raw file", RECOVERY_SOURCE_IMAGE)
        self.source_mode_combo.currentIndexChanged.connect(self._on_source_mode_changed)

        self.drive_combo = QComboBox()
        self.drive_combo.currentIndexChanged.connect(lambda *_: self._update_status_banner())
        self.refresh_drives_button = QPushButton("Refresh Drives")
        self.refresh_drives_button.clicked.connect(self._refresh_drive_list)
        self.refresh_drives_button.setToolTip(
            "Re-scan Windows for currently mounted drives in case the TeslaCam USB was inserted after the app opened."
        )

        self.image_path_edit = QLineEdit()
        self.image_path_edit.setPlaceholderText("Choose a raw image or recovered device file")
        self.image_path_edit.textChanged.connect(lambda *_: self._update_status_banner())
        self.choose_image_button = QPushButton("Browse")
        self.choose_image_button.clicked.connect(self._choose_image_path)
        self.choose_image_button.setToolTip(
            "Browse for an image file, raw device dump, or other source file copy to scan."
        )

        self.output_dir_edit = QLineEdit(str(DEFAULT_OUTPUT_DIR))
        self.output_dir_edit.textChanged.connect(lambda *_: self._update_result_actions())
        self.output_dir_edit.textChanged.connect(lambda *_: self._update_status_banner())
        self.choose_output_button = QPushButton("Browse")
        self.choose_output_button.clicked.connect(self._choose_output_dir)
        self.choose_output_button.setToolTip(
            "Choose where recovered clips should be written."
        )

        self.target_dates_edit = QLineEdit()
        self.target_dates_edit.setPlaceholderText("YYYY-MM-DD, YYYY-MM-DD")
        self.target_dates_edit.textChanged.connect(lambda *_: self._update_status_banner())
        self.use_suggested_date_button = QPushButton("Use Loaded Event Date")
        self.use_suggested_date_button.clicked.connect(self._use_suggested_event_date)
        self.use_suggested_date_button.setEnabled(self.suggested_event_date is not None)
        self.use_suggested_date_button.setToolTip(
            "Fill the target date field with the date from the event currently loaded in the viewer."
        )

        self.filter_by_time_check = QCheckBox("Match local time window")
        self.filter_by_time_check.toggled.connect(self._update_time_filter_state)
        self.filter_by_time_check.toggled.connect(lambda *_: self._update_status_banner())
        self.time_start_edit = QTimeEdit()
        self.time_start_edit.setDisplayFormat("HH:mm:ss")
        self.time_start_edit.setTime(QTime.fromString("00:00:00", "HH:mm:ss"))
        self.time_start_edit.setToolTip("Only recover candidates at or after this local time.")
        self.time_end_edit = QTimeEdit()
        self.time_end_edit.setDisplayFormat("HH:mm:ss")
        self.time_end_edit.setTime(QTime.fromString("23:59:59", "HH:mm:ss"))
        self.time_end_edit.setToolTip("Only recover candidates at or before this local time.")
        self.time_filter_widget = QWidget()
        self.time_filter_layout = QHBoxLayout(self.time_filter_widget)
        self.time_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.time_filter_layout.setSpacing(8)
        self.time_start_label = self._help_label(
            "Start",
            "Candidates earlier than this local time will be skipped when time filtering is enabled.",
            self.time_start_edit,
        )
        self.time_filter_layout.addWidget(self.time_start_label)
        self.time_filter_layout.addWidget(self.time_start_edit)
        self.time_end_label = self._help_label(
            "End",
            "Candidates later than this local time will be skipped when time filtering is enabled.",
            self.time_end_edit,
        )
        self.time_filter_layout.addWidget(self.time_end_label)
        self.time_filter_layout.addWidget(self.time_end_edit)
        self.time_filter_layout.addStretch(1)

        self.criteria_hint_label = QLabel(
            "Dates and times are matched against the clip's embedded creation timestamp using your local timezone."
        )
        self.criteria_hint_label.setWordWrap(True)
        self.criteria_hint_label.setToolTip(
            "Recovery uses each clip candidate's embedded creation timestamp, converted to your local timezone, to decide whether it matches your date and time filters."
        )
        self.filter_by_time_check.setToolTip(
            "Enable this to narrow recovery to a time-of-day window after the selected dates are matched."
        )
        self.time_start_edit.setToolTip(self.time_start_label.toolTip())
        self.time_end_edit.setToolTip(self.time_end_label.toolTip())

        self.scan_source_label = self._help_label(
            "Scan Source",
            "Choose whether recovery scans the live TeslaCam USB drive directly or a separate image/raw file copy.",
            self.source_mode_combo,
        )
        self.drive_source_label = self._help_label(
            "TeslaCam USB",
            "Select the mounted TeslaCam USB drive to scan. Live drive scans usually require Administrator access and should only be used on the intended source device.",
            self.drive_combo,
        )
        self.image_source_label = self._help_label(
            "Image / Raw File",
            "Choose a disk image, raw device dump, or other source file copy to scan instead of the live USB drive.",
            self.image_path_edit,
        )
        self.output_folder_label = self._help_label(
            "Output Folder",
            "Recovered clips are written here. Choose a separate destination so recovery output does not mix with the source media.",
            self.output_dir_edit,
        )
        self.target_dates_label = self._help_label(
            "Target Dates",
            "Enter one or more dates as comma-separated YYYY-MM-DD values. Only candidates whose embedded creation date matches one of these dates will be recovered.",
            self.target_dates_edit,
        )
        self.scan_only_check = QCheckBox("Scan Only (do not write recovered files yet)")
        self.scan_only_check.setToolTip(
            "Use this to preview likely matches first. Matching candidates will appear in the results list, but no recovered MP4 files will be written."
        )
        self.scan_only_check.toggled.connect(lambda *_: self._update_status_banner())

        self.recovery_goal_combo.setToolTip(self.recovery_goal_label.toolTip())
        self.scenario_combo.setToolTip(self.scenario_label.toolTip())
        self.source_mode_combo.setToolTip(self.scan_source_label.toolTip())
        self.drive_combo.setToolTip(self.drive_source_label.toolTip())
        self.image_path_edit.setToolTip(self.image_source_label.toolTip())
        self.output_dir_edit.setToolTip(self.output_folder_label.toolTip())
        self.target_dates_edit.setToolTip(self.target_dates_label.toolTip())

        scan_layout.addWidget(self.recovery_goal_label, 0, 0)
        scan_layout.addWidget(self.recovery_goal_combo, 0, 1, 1, 2)
        scan_layout.addWidget(self.scenario_label, 1, 0)
        scan_layout.addWidget(self.scenario_combo, 1, 1, 1, 2)
        scan_layout.addWidget(self.scan_source_label, 2, 0)
        scan_layout.addWidget(self.source_mode_combo, 2, 1, 1, 2)
        scan_layout.addWidget(self.drive_source_label, 3, 0)
        scan_layout.addWidget(self.drive_combo, 3, 1)
        scan_layout.addWidget(self.refresh_drives_button, 3, 2)
        scan_layout.addWidget(self.image_source_label, 4, 0)
        scan_layout.addWidget(self.image_path_edit, 4, 1)
        scan_layout.addWidget(self.choose_image_button, 4, 2)
        scan_layout.addWidget(self.output_folder_label, 5, 0)
        scan_layout.addWidget(self.output_dir_edit, 5, 1)
        scan_layout.addWidget(self.choose_output_button, 5, 2)
        scan_layout.addWidget(self.target_dates_label, 6, 0)
        scan_layout.addWidget(self.target_dates_edit, 6, 1)
        scan_layout.addWidget(self.use_suggested_date_button, 6, 2)
        scan_layout.addWidget(self.filter_by_time_check, 7, 0)
        scan_layout.addWidget(self.time_filter_widget, 7, 1, 1, 2)
        scan_layout.addWidget(self.scan_only_check, 8, 0, 1, 3)
        scan_layout.addWidget(self.criteria_hint_label, 9, 0, 1, 3)
        root_layout.addWidget(scan_group)

        tuning_group = QGroupBox("Advanced Settings")
        self.tuning_group = tuning_group
        tuning_layout = QFormLayout(tuning_group)
        self.tuning_preset_combo = QComboBox()
        self.tuning_preset_combo.addItem("Recommended", TUNING_PRESET_RECOMMENDED)
        self.tuning_preset_combo.addItem("Conservative", TUNING_PRESET_CONSERVATIVE)
        self.tuning_preset_combo.addItem("Aggressive", TUNING_PRESET_AGGRESSIVE)
        self.apply_preset_button = QPushButton("Apply Preset")
        self.apply_preset_button.clicked.connect(self._apply_selected_preset)
        self.apply_preset_button.setToolTip(
            "Apply the selected preset values to the advanced recovery settings."
        )
        preset_row = QWidget()
        preset_row_layout = QHBoxLayout(preset_row)
        preset_row_layout.setContentsMargins(0, 0, 0, 0)
        preset_row_layout.setSpacing(8)
        preset_row_layout.addWidget(self.tuning_preset_combo, 1)
        preset_row_layout.addWidget(self.apply_preset_button)
        self.chunk_size_spin = self._mb_spinbox(1, 256)
        self.preview_bytes_spin = self._mb_spinbox(1, 256)
        self.max_carve_spin = self._mb_spinbox(1, 1024)
        self.max_workers_spin = self._plain_spinbox(1, 64)
        self.max_pending_spin = self._plain_spinbox(1, 4096)
        self.overlap_spin = self._plain_spinbox(1, 4096)

        self.tuning_preset_label = self._help_label(
            "Tuning Preset",
            "Applies a bundled performance profile based on your hardware. Recommended aims for balance, Conservative reduces system load, and Aggressive pushes harder for speed.",
            self.tuning_preset_combo,
        )
        self.chunk_size_label = self._help_label(
            "Chunk Size (MB)",
            "How much data the scanner reads from the source at a time. Larger chunks can improve throughput but use more memory.",
            self.chunk_size_spin,
        )
        self.preview_size_label = self._help_label(
            "Preview Size (MB)",
            "How many bytes are sent to ffprobe for each candidate clip. Larger previews can improve timestamp detection but increase per-candidate work.",
            self.preview_bytes_spin,
        )
        self.max_carve_size_label = self._help_label(
            "Max Carve Size (MB)",
            "Maximum number of bytes written out for a matched clip. Increase this if clips are being truncated; keep it reasonable to avoid oversized partial recoveries.",
            self.max_carve_spin,
        )
        self.worker_threads_label = self._help_label(
            "Worker Threads",
            "Maximum number of Qt worker tasks probing and carving candidates in parallel. Higher values can speed recovery on strong CPUs but increase system load.",
            self.max_workers_spin,
        )
        self.pending_jobs_label = self._help_label(
            "Pending Jobs Limit",
            "Caps how many candidate probe jobs can queue up at once so the scan does not consume too much memory when lots of MP4-like fragments are found.",
            self.max_pending_spin,
        )
        self.overlap_label = self._help_label(
            "Buffer Overlap (bytes)",
            "Extra bytes carried from one scan chunk into the next so MP4 headers split across chunk boundaries are less likely to be missed.",
            self.overlap_spin,
        )

        self.tuning_preset_combo.setToolTip(self.tuning_preset_label.toolTip())
        self.chunk_size_spin.setToolTip(self.chunk_size_label.toolTip())
        self.preview_bytes_spin.setToolTip(self.preview_size_label.toolTip())
        self.max_carve_spin.setToolTip(self.max_carve_size_label.toolTip())
        self.max_workers_spin.setToolTip(self.worker_threads_label.toolTip())
        self.max_pending_spin.setToolTip(self.pending_jobs_label.toolTip())
        self.overlap_spin.setToolTip(self.overlap_label.toolTip())

        tuning_layout.addRow(
            self._help_row_widget(
                self.tuning_preset_label,
                "Tuning Preset Help",
                self.tuning_preset_label.toolTip(),
            ),
            preset_row,
        )
        tuning_layout.addRow(
            self._help_row_widget(
                self.chunk_size_label,
                "Chunk Size Help",
                self.chunk_size_label.toolTip(),
            ),
            self.chunk_size_spin,
        )
        tuning_layout.addRow(
            self._help_row_widget(
                self.preview_size_label,
                "Preview Size Help",
                self.preview_size_label.toolTip(),
            ),
            self.preview_bytes_spin,
        )
        tuning_layout.addRow(
            self._help_row_widget(
                self.max_carve_size_label,
                "Max Carve Size Help",
                self.max_carve_size_label.toolTip(),
            ),
            self.max_carve_spin,
        )
        tuning_layout.addRow(
            self._help_row_widget(
                self.worker_threads_label,
                "Worker Threads Help",
                self.worker_threads_label.toolTip(),
            ),
            self.max_workers_spin,
        )
        tuning_layout.addRow(
            self._help_row_widget(
                self.pending_jobs_label,
                "Pending Jobs Limit Help",
                self.pending_jobs_label.toolTip(),
            ),
            self.max_pending_spin,
        )
        tuning_layout.addRow(
            self._help_row_widget(
                self.overlap_label,
                "Buffer Overlap Help",
                self.overlap_label.toolTip(),
            ),
            self.overlap_spin,
        )
        root_layout.addWidget(tuning_group)

        self.show_advanced_check = QCheckBox("Show advanced tuning controls")
        self.show_advanced_check.toggled.connect(self._update_advanced_visibility)
        root_layout.addWidget(self.show_advanced_check)

        status_group = QGroupBox("Progress")
        status_layout = QVBoxLayout(status_group)
        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        self.preflight_label = QLabel()
        self.preflight_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_stats_label = QLabel("Idle")
        self.progress_stats_label.setWordWrap(True)
        self.next_steps_label = QLabel("Next steps will appear here after the scan starts.")
        self.next_steps_label.setWordWrap(True)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(220)
        status_layout.addWidget(self.status_banner)
        status_layout.addWidget(self.preflight_label)
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.progress_stats_label)
        status_layout.addWidget(self.next_steps_label)
        status_layout.addWidget(self.log_output, 1)
        root_layout.addWidget(status_group, 1)

        results_group = QGroupBox("Recovered Clips")
        results_layout = QVBoxLayout(results_group)
        self.results_hint_label = QLabel(
            "Successful recoveries appear here so you can open the output folder or inspect a specific file. Skipped candidates stay in the scan log."
        )
        self.results_hint_label.setWordWrap(True)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["Timestamp", "Offset", "Size", "Confidence", "Recovered File"]
        )
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.results_table.itemSelectionChanged.connect(self._on_result_selection_changed)

        results_button_row = QHBoxLayout()
        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self._open_output_folder)
        self.open_selected_button = QPushButton("Open Selected File")
        self.open_selected_button.clicked.connect(self._open_selected_result)
        self.copy_selected_path_button = QPushButton("Copy Selected Path")
        self.copy_selected_path_button.clicked.connect(self._copy_selected_result_path)
        self.export_report_button = QPushButton("Export Scan Report")
        self.export_report_button.clicked.connect(self._export_scan_report)
        self.clear_results_button = QPushButton("Clear Results")
        self.clear_results_button.clicked.connect(self._clear_results)
        results_button_row.addWidget(self.open_output_button)
        results_button_row.addWidget(self.open_selected_button)
        results_button_row.addWidget(self.copy_selected_path_button)
        results_button_row.addWidget(self.export_report_button)
        results_button_row.addStretch(1)
        results_button_row.addWidget(self.clear_results_button)

        results_layout.addWidget(self.results_hint_label)
        results_layout.addWidget(self.results_table, 1)
        results_layout.addLayout(results_button_row)
        root_layout.addWidget(results_group, 1)

        salvage_group = QGroupBox("Extra Salvage")
        salvage_layout = QGridLayout(salvage_group)
        salvage_layout.setHorizontalSpacing(10)
        salvage_layout.setVerticalSpacing(8)
        self.salvage_hint_label = QLabel(
            "If a likely result is clipped or scan-only found something important, select it and recover a larger block from the same offset. "
            "You normally do not need to type an offset yourself; selecting a result fills it in. "
            "Automatic sizing is conservative, while advanced users can override it."
        )
        self.salvage_hint_label.setWordWrap(True)
        self.manual_offset_edit = QLineEdit()
        self.manual_offset_edit.setPlaceholderText("Select a result or paste an offset")
        self.manual_offset_edit.textChanged.connect(lambda *_: self._update_result_actions())
        self.auto_salvage_size_check = QCheckBox("Choose salvage size automatically")
        self.auto_salvage_size_check.setChecked(True)
        self.auto_salvage_size_check.toggled.connect(self._update_salvage_size_state)
        self.salvage_size_spin = self._mb_spinbox(64, 4096)
        self.salvage_size_spin.setValue(recommended_salvage_size_mb(self.hardware_profile))
        self.salvage_offset_label = self._help_label(
            "Offset",
            "Byte offset to recover from. Selecting a scan result fills this in automatically; advanced users can paste a known offset.",
            self.manual_offset_edit,
        )
        self.salvage_size_label = self._help_label(
            "Salvage Size",
            "Maximum amount of data to copy from the selected offset. This affects the recovered output file size, not the original source.",
            self.salvage_size_spin,
        )
        self.manual_offset_edit.setToolTip(self.salvage_offset_label.toolTip())
        self.salvage_size_spin.setToolTip(self.salvage_size_label.toolTip())
        self.auto_salvage_size_check.setToolTip(
            "Let the app choose a larger carve size based on this computer. Turn this off to set an exact maximum size."
        )
        self.recover_more_button = QPushButton("Recover More Around Selected Result")
        self.recover_more_button.clicked.connect(self._recover_more_selected_result)
        self.recover_more_button.setToolTip(
            "Use the selected scan result's offset and write a larger recovery file into the output folder."
        )
        self.manual_salvage_button = QPushButton("Recover From Offset")
        self.manual_salvage_button.clicked.connect(self._recover_manual_offset)
        self.manual_salvage_button.setToolTip(
            "Recover a larger file starting from the offset typed in the box."
        )
        salvage_layout.addWidget(self.salvage_hint_label, 0, 0, 1, 4)
        salvage_layout.addWidget(self.salvage_offset_label, 1, 0)
        salvage_layout.addWidget(self.manual_offset_edit, 1, 1)
        salvage_layout.addWidget(self.recover_more_button, 1, 2)
        salvage_layout.addWidget(self.manual_salvage_button, 1, 3)
        salvage_layout.addWidget(self.salvage_size_label, 2, 0)
        salvage_layout.addWidget(self.salvage_size_spin, 2, 1)
        salvage_layout.addWidget(self.auto_salvage_size_check, 2, 2, 1, 2)
        root_layout.addWidget(salvage_group)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start Recovery")
        self.start_button.clicked.connect(self._start_recovery)
        self.cancel_button = QPushButton("Cancel Scan")
        self.cancel_button.clicked.connect(self._cancel_recovery)
        self.cancel_button.setEnabled(False)
        self.switch_to_viewer_button = QPushButton("Back To Viewer")
        self.switch_to_viewer_button.clicked.connect(self.request_switch_to_viewer.emit)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        button_row.addWidget(self.switch_to_viewer_button)
        root_layout.addLayout(button_row)
        self._apply_control_heights()
        self._update_advanced_visibility()
        self._update_salvage_size_state()
        self._update_source_mode_state()
        self._update_result_actions()

    def _apply_control_heights(self):
        for widget in (
            self.source_mode_combo,
            self.drive_combo,
            self.image_path_edit,
            self.output_dir_edit,
            self.target_dates_edit,
            self.time_start_edit,
            self.time_end_edit,
            self.recovery_goal_combo,
            self.tuning_preset_combo,
            self.chunk_size_spin,
            self.preview_bytes_spin,
            self.max_carve_spin,
            self.manual_offset_edit,
            self.salvage_size_spin,
            self.max_workers_spin,
            self.max_pending_spin,
            self.overlap_spin,
        ):
            widget.setMinimumHeight(30)

        for button in (
            self.refresh_drives_button,
            self.choose_image_button,
            self.choose_output_button,
            self.use_suggested_date_button,
            self.apply_preset_button,
            self.guided_setup_button,
            self.image_copy_guide_button,
            self.export_report_button,
            self.open_output_button,
            self.open_selected_button,
            self.copy_selected_path_button,
            self.recover_more_button,
            self.manual_salvage_button,
            self.clear_results_button,
            self.start_button,
            self.cancel_button,
            self.switch_to_viewer_button,
        ):
            button.setMinimumHeight(32)

    def _mb_spinbox(self, minimum: int, maximum: int) -> QSpinBox:
        spinbox = QSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setSuffix(" MB")
        return spinbox

    def _plain_spinbox(self, minimum: int, maximum: int) -> QSpinBox:
        spinbox = QSpinBox()
        spinbox.setRange(minimum, maximum)
        return spinbox

    def _help_label(self, text: str, tooltip: str, buddy: QWidget | None = None) -> QLabel:
        label = QLabel(text)
        label.setToolTip(tooltip)
        label.setStatusTip(tooltip)
        if buddy is not None:
            label.setBuddy(buddy)
        return label

    def _help_button(self, title: str, message: str) -> QToolButton:
        button = QToolButton()
        button.setText("?")
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(message)
        button.setFixedSize(20, 20)
        button.clicked.connect(lambda: QMessageBox.information(self, title, message))
        return button

    def _help_row_widget(self, label: QLabel, title: str, message: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(label)
        layout.addWidget(self._help_button(title, message))
        layout.addStretch(1)
        return container

    def _selected_source_kind(self) -> str:
        return str(self.source_mode_combo.currentData() or RECOVERY_SOURCE_DRIVE)

    def _selected_goal_preset(self) -> str:
        return str(self.recovery_goal_combo.currentData() or TUNING_PRESET_RECOMMENDED)

    def _selected_tuning_preset(self) -> str:
        return str(self.tuning_preset_combo.currentData() or TUNING_PRESET_RECOMMENDED)

    def _is_busy(self) -> bool:
        """Return whether a scan or larger salvage task is active."""

        return self._busy or self.worker_thread is not None or self.salvage_thread is not None

    def _refresh_drive_list(self):
        current_device = self.drive_combo.currentData() or self.drive_combo.property("saved_drive_device")
        self.drives = list_windows_drives()
        self.drive_combo.clear()
        for drive in self.drives:
            self.drive_combo.addItem(drive.display_name, drive.device)

        if current_device:
            index = self.drive_combo.findData(current_device)
            if index >= 0:
                self.drive_combo.setCurrentIndex(index)
        self._update_status_banner()

    def _open_guided_setup(self):
        dialog = RecoverySetupDialog(
            suggested_event_date=self.suggested_event_date,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        values = dialog.setup_values()
        source_index = self.source_mode_combo.findData(values["source_kind"])
        if source_index >= 0:
            self.source_mode_combo.setCurrentIndex(source_index)

        goal_index = self.recovery_goal_combo.findData(values["goal_preset"])
        if goal_index >= 0:
            self.recovery_goal_combo.setCurrentIndex(goal_index)

        if values["target_date"]:
            self.target_dates_edit.setText(str(values["target_date"]))
        self.filter_by_time_check.setChecked(bool(values["filter_by_time"]))
        self.time_start_edit.setTime(_parse_time_or_default(str(values["time_start"]), "00:00:00"))
        self.time_end_edit.setTime(_parse_time_or_default(str(values["time_end"]), "23:59:59"))
        self.scan_only_check.setChecked(bool(values["scan_only"]))
        self._set_next_steps_message(
            "The form was filled in for you. Check the source, output folder, and date, then start the scan when ready."
        )
        self._update_status_banner()

    def _show_image_copy_guidance(self):
        QMessageBox.information(
            self,
            "Image Copy Guide",
            "Safer workflow for important footage:\n\n"
            "1. Remove the TeslaCam USB from the car.\n"
            "2. Use another tool or workstation to make a full image copy of the USB.\n"
            "3. Return here and choose Image / raw file instead of the live USB.\n"
            "4. Start with Scan Only to preview likely matches before carving files.\n\n"
            "This app can scan image files directly, but it does not create full forensic images for you yet.",
        )

    def _apply_scenario_hint(self):
        scenario = str(self.scenario_combo.currentData() or "date_only")
        if scenario == "date_only":
            self.filter_by_time_check.setChecked(False)
            self.scan_only_check.setChecked(False)
            self._set_next_steps_message(
                "Start with the date only. Add a time window later only if that date still returns too many candidates."
            )
        elif scenario == "date_time":
            self.filter_by_time_check.setChecked(True)
            self.scan_only_check.setChecked(False)
            self._set_next_steps_message(
                "Use the date and a broad time window first. If you get no results, widen the time range or turn it off."
            )
        elif scenario == "preview":
            self.scan_only_check.setChecked(True)
            self._set_next_steps_message(
                "Scan Only is good when you want to see likely matches before writing any recovered files."
            )
        elif scenario == "safe_image":
            source_index = self.source_mode_combo.findData(RECOVERY_SOURCE_IMAGE)
            if source_index >= 0:
                self.source_mode_combo.setCurrentIndex(source_index)
            self.scan_only_check.setChecked(True)
            self._set_next_steps_message(
                "Use an image copy and start with Scan Only. That is the safest workflow when the footage matters."
            )
        self._update_status_banner()

    def _choose_output_dir(self):
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Recovery Output Folder",
            self.output_dir_edit.text(),
        )
        if selected_dir:
            self.output_dir_edit.setText(selected_dir)
            self._update_result_actions()

    def _choose_image_path(self):
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Recovery Image / Raw File",
            self.image_path_edit.text() or str(Path.home()),
            "All Files (*.*)",
        )
        if selected_path:
            self.image_path_edit.setText(selected_path)
            self._update_status_banner()

    def _use_suggested_event_date(self):
        if self.suggested_event_date is not None:
            self.target_dates_edit.setText(self.suggested_event_date.isoformat())

    def _apply_recommended_tuning(self):
        self.tuning_preset_combo.setCurrentIndex(
            self.tuning_preset_combo.findData(TUNING_PRESET_RECOMMENDED)
        )
        self._apply_tuning_values(self.recommended)

    def _apply_goal_preset(self):
        preset = self._selected_goal_preset()
        preset_index = self.tuning_preset_combo.findData(preset)
        if preset_index >= 0:
            self.tuning_preset_combo.setCurrentIndex(preset_index)
        self._apply_selected_preset()
        self._set_next_steps_message(
            "Balanced is the safest default. Quick Scan uses fewer resources, while Deep Scan searches more aggressively and may take longer."
        )

    def _apply_selected_preset(self):
        tuning = tuning_for_preset(self._selected_tuning_preset(), self.hardware_profile)
        self._apply_tuning_values(tuning)

    def _apply_tuning_values(self, tuning: RecoveryTuning):
        self.chunk_size_spin.setValue(tuning.chunk_size // (1024 * 1024))
        self.preview_bytes_spin.setValue(tuning.preview_bytes // (1024 * 1024))
        self.max_carve_spin.setValue(tuning.max_carve_bytes // (1024 * 1024))
        self.max_workers_spin.setValue(tuning.max_workers)
        self.max_pending_spin.setValue(tuning.max_pending_jobs)
        self.overlap_spin.setValue(tuning.overlap)

    def _on_source_mode_changed(self):
        self._update_source_mode_state()
        self._update_status_banner()

    def _update_advanced_visibility(self):
        self.tuning_group.setVisible(self.show_advanced_check.isChecked())

    def _update_source_mode_state(self):
        use_drive = self._selected_source_kind() == RECOVERY_SOURCE_DRIVE
        controls_locked = self._is_busy()
        self.drive_combo.setEnabled(use_drive and not controls_locked)
        self.refresh_drives_button.setEnabled(use_drive and not controls_locked)
        self.image_path_edit.setEnabled((not use_drive) and not controls_locked)
        self.choose_image_button.setEnabled((not use_drive) and not controls_locked)

    def _update_time_filter_state(self):
        enabled = self.filter_by_time_check.isChecked()
        self.time_start_edit.setEnabled(enabled)
        self.time_end_edit.setEnabled(enabled)

    def _update_result_actions(self):
        has_output_dir = bool(self.output_dir_edit.text().strip())
        has_selection = self._selected_result_path() is not None
        has_selected_offset = self._selected_result_offset() is not None
        has_manual_offset = self._manual_offset_value(silent=True) is not None
        has_rows = self.results_table.rowCount() > 0
        is_busy = self._is_busy()
        self.open_output_button.setEnabled(has_output_dir)
        self.open_selected_button.setEnabled(has_selection)
        self.copy_selected_path_button.setEnabled(has_selection)
        self.export_report_button.setEnabled(has_rows or bool(self.log_output.toPlainText().strip()))
        self.clear_results_button.setEnabled(has_rows)
        self.recover_more_button.setEnabled(has_output_dir and has_selected_offset and not is_busy)
        self.manual_salvage_button.setEnabled(has_output_dir and has_manual_offset and not is_busy)

    def _update_salvage_size_state(self):
        self.salvage_size_spin.setEnabled(
            not self._is_busy() and not self.auto_salvage_size_check.isChecked()
        )

    def _on_result_selection_changed(self):
        offset = self._selected_result_offset()
        if offset is not None and not self.manual_offset_edit.hasFocus():
            self.manual_offset_edit.setText(str(offset))
        self._update_result_actions()

    def _clear_results(self):
        self.results_table.setRowCount(0)
        self._update_result_actions()

    def _selected_result_path(self) -> Path | None:
        current_row = self.results_table.currentRow()
        if current_row < 0:
            return None
        file_item = self.results_table.item(current_row, 4)
        path_text = file_item.data(Qt.ItemDataRole.UserRole) if file_item is not None else None
        return Path(path_text) if path_text else None

    def _selected_result_offset(self) -> int | None:
        current_row = self.results_table.currentRow()
        if current_row < 0:
            return None
        offset_item = self.results_table.item(current_row, 1)
        if offset_item is None:
            return None
        try:
            return int(offset_item.text().replace(",", "").replace("_", ""))
        except ValueError:
            return None

    def _manual_offset_value(self, *, silent: bool) -> int | None:
        offset_text = self.manual_offset_edit.text().strip()
        if not offset_text:
            if not silent:
                QMessageBox.information(self, "Offset Required", "Select a result or enter an offset first.")
            return None

        try:
            offset = int(offset_text.replace(",", "").replace("_", ""), 0)
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Invalid Offset",
                    "Enter the offset as a whole number. Hex values like 0x1234 are also accepted.",
                )
            return None

        if offset < 0:
            if not silent:
                QMessageBox.warning(self, "Invalid Offset", "Offset must be zero or greater.")
            return None
        return offset

    def _export_scan_report(self):
        output_root = Path(self.output_dir_edit.text().strip() or DEFAULT_OUTPUT_DIR).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)
        report_path = output_root / RECOVERY_REPORT_FILENAME
        report = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_kind": self._selected_source_kind(),
            "source_label": self.status_banner.text(),
            "target_dates": [item.strip() for item in self.target_dates_edit.text().split(",") if item.strip()],
            "time_filter_enabled": self.filter_by_time_check.isChecked(),
            "time_start": self.time_start_edit.time().toString("HH:mm:ss"),
            "time_end": self.time_end_edit.time().toString("HH:mm:ss"),
            "scan_only": self.scan_only_check.isChecked(),
            "extra_salvage_auto_size": self.auto_salvage_size_check.isChecked(),
            "extra_salvage_size_mb": self.salvage_size_spin.value(),
            "recovery_preset": self.recovery_goal_combo.currentText(),
            "advanced_preset": self.tuning_preset_combo.currentText(),
            "results": self._results_snapshot(),
            "log": self.log_output.toPlainText().splitlines(),
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self._append_log(f"[INFO] Wrote scan report to {report_path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(report_path.resolve())))

    def _results_snapshot(self) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for row in range(self.results_table.rowCount()):
            results.append(
                {
                    "timestamp": self.results_table.item(row, 0).text(),
                    "offset": self.results_table.item(row, 1).text(),
                    "size": self.results_table.item(row, 2).text(),
                    "confidence": self.results_table.item(row, 3).text(),
                    "file": self.results_table.item(row, 4).text(),
                }
            )
        return results

    def _set_next_steps_message(self, message: str):
        self.next_steps_label.setText(f"Next steps: {message}")

    def _open_output_folder(self):
        output_dir_text = self.output_dir_edit.text().strip()
        if not output_dir_text:
            QMessageBox.information(self, "No Output Folder", "Choose an output folder first.")
            return

        output_dir = Path(output_dir_text).expanduser()
        if not output_dir.exists():
            QMessageBox.information(self, "Output Folder Missing", "The output folder does not exist yet.")
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir.resolve())))

    def _open_selected_result(self):
        selected_path = self._selected_result_path()
        if selected_path is None or not selected_path.exists():
            QMessageBox.information(self, "No File Selected", "Select a recovered file first.")
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(selected_path.resolve())))

    def _copy_selected_result_path(self):
        selected_path = self._selected_result_path()
        if selected_path is None:
            QMessageBox.information(self, "No File Selected", "Select a recovered file first.")
            return

        QApplication.clipboard().setText(str(selected_path))
        self._append_log(f"[INFO] Copied path: {selected_path}")

    def _recover_more_selected_result(self):
        offset = self._selected_result_offset()
        if offset is None:
            QMessageBox.information(
                self,
                "No Result Selected",
                "Select a likely match from the results list first.",
            )
            return
        self._start_manual_salvage(offset)

    def _recover_manual_offset(self):
        offset = self._manual_offset_value(silent=False)
        if offset is None:
            return
        self._start_manual_salvage(offset)

    def _salvage_size_mb(self, *, source_size_hint: int) -> int:
        if self.auto_salvage_size_check.isChecked():
            return recommended_salvage_size_mb(
                self.hardware_profile,
                source_size_hint=source_size_hint,
            )
        return self.salvage_size_spin.value()

    def _unique_salvage_path(self, output_dir: Path, offset: int, size_mb: int) -> Path:
        base_path = output_dir / f"extra_salvage_off{offset}_{size_mb}MB.mp4"
        if not base_path.exists():
            return base_path

        counter = 2
        while True:
            candidate = output_dir / f"extra_salvage_off{offset}_{size_mb}MB_{counter}.mp4"
            if not candidate.exists():
                return candidate
            counter += 1

    def _start_manual_salvage(self, offset: int):
        if self._is_busy():
            QMessageBox.information(self, "Already Running", "A recovery task is already running.")
            return

        output_dir_text = self.output_dir_edit.text().strip()
        if not output_dir_text:
            QMessageBox.warning(self, "Output Folder Required", "Choose an output folder first.")
            return
        output_dir = Path(output_dir_text).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        source_context = self._selected_source_context()
        if source_context is None:
            return
        source_path, source_label, source_kind, _drive, total_size_hint = source_context
        if total_size_hint > 0 and offset >= total_size_hint:
            QMessageBox.warning(
                self,
                "Offset Outside Source",
                "The offset is past the end of the selected source.",
            )
            return
        if (
            source_kind == RECOVERY_SOURCE_DRIVE
            and QMessageBox.question(
                self,
                "Live USB Extra Salvage",
                "You are about to read a larger block from the live TeslaCam USB directly.\n\n"
                "This does not write to the USB, but an image copy is still safer when the footage matters.\n\n"
                "Do you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        self._save_settings()
        salvage_mb = self._salvage_size_mb(source_size_hint=total_size_hint)
        max_bytes = salvage_mb * 1024 * 1024
        output_path = self._unique_salvage_path(output_dir.resolve(), offset, salvage_mb)
        self._append_log(
            "[SALVAGE] "
            f"Source: {source_label} | Offset: {offset} | Limit: {format_bytes(max_bytes)} | "
            f"Output: {output_path.name}"
        )
        self.progress_bar.setRange(0, 0)
        self.progress_stats_label.setText("Extra salvage is reading from the selected offset...")
        self._set_next_steps_message(
            "Wait for the larger salvage file to finish, then open it from the results list or output folder."
        )
        self._set_running_state(True)

        self.salvage_thread = QThread(self)
        self.salvage_worker = ManualSalvageWorker(
            source_path=source_path,
            output_path=output_path,
            offset=offset,
            max_bytes=max_bytes,
            chunk_size=self._current_tuning().chunk_size,
            total_size_hint=total_size_hint,
        )
        self.salvage_worker.moveToThread(self.salvage_thread)
        self.salvage_thread.started.connect(self.salvage_worker.run)
        self.salvage_worker.log_message.connect(self._append_log)
        self.salvage_worker.finished.connect(self._on_salvage_finished)
        self.salvage_worker.failed.connect(self._on_salvage_failed)
        self.salvage_thread.start()

    def _on_salvage_finished(self, result: RecoveryCandidateResult):
        self._append_log(format_candidate_result(result))
        self._record_candidate_result(result)
        self._teardown_salvage_worker()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_stats_label.setText(
            f"Extra salvage wrote {format_bytes(result.bytes_written)} to the output folder."
        )
        self._set_running_state(False)
        self._set_next_steps_message(
            "Open the extra salvage file and check whether it contains more of the missing clip."
        )

    def _on_salvage_failed(self, message: str):
        self._append_log(f"[ERROR] {message}")
        self._teardown_salvage_worker()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_stats_label.setText("Extra salvage did not write a usable file.")
        self._set_running_state(False)
        QMessageBox.warning(self, "Extra Salvage Stopped", message)

    def set_suggested_event_date(self, suggested_event_date: date | None):
        """Update the event date offered by the viewer tab."""

        self.suggested_event_date = suggested_event_date
        self.use_suggested_date_button.setEnabled(suggested_event_date is not None)

    def use_suggested_event_date(self):
        """Apply the viewer-provided event date to the date filter field."""

        self._use_suggested_event_date()

    def apply_recommended_tuning(self):
        """Apply hardware-aware recovery tuning values."""

        self._apply_recommended_tuning()

    def focus_primary_input(self):
        """Move keyboard focus to the main date-filter field."""

        self.target_dates_edit.setFocus(Qt.FocusReason.TabFocusReason)

    def start_recovery(self):
        """Start a recovery scan from the public panel API."""

        self._start_recovery()

    def cancel_recovery(self):
        """Cancel the active recovery scan from the public panel API."""

        self._cancel_recovery()

    def _load_saved_settings(self):
        section = self.settings_store.get_section("recovery")
        goal_key = str(section.get("goal_preset", TUNING_PRESET_RECOMMENDED))
        goal_index = self.recovery_goal_combo.findData(goal_key)
        if goal_index >= 0:
            self.recovery_goal_combo.setCurrentIndex(goal_index)
        source_kind = str(section.get("source_kind", RECOVERY_SOURCE_DRIVE))
        source_index = self.source_mode_combo.findData(source_kind)
        if source_index >= 0:
            self.source_mode_combo.setCurrentIndex(source_index)
        self.image_path_edit.setText(str(section.get("image_path", "")))
        self.output_dir_edit.setText(str(section.get("output_dir", DEFAULT_OUTPUT_DIR)))
        saved_dates = section.get("target_dates")
        if isinstance(saved_dates, list) and saved_dates:
            self.target_dates_edit.setText(", ".join(str(item) for item in saved_dates))
        elif self.suggested_event_date is not None:
            self.target_dates_edit.setText(self.suggested_event_date.isoformat())
        self.filter_by_time_check.setChecked(bool(section.get("filter_by_time", False)))
        self.scan_only_check.setChecked(bool(section.get("scan_only", False)))
        self.show_advanced_check.setChecked(bool(section.get("show_advanced", False)))
        self.auto_salvage_size_check.setChecked(bool(section.get("auto_salvage_size", True)))
        try:
            salvage_size_mb = int(
                section.get(
                    "salvage_size_mb",
                    recommended_salvage_size_mb(self.hardware_profile),
                )
            )
        except (TypeError, ValueError):
            salvage_size_mb = recommended_salvage_size_mb(self.hardware_profile)
        self.salvage_size_spin.setValue(salvage_size_mb)
        self.time_start_edit.setTime(
            _parse_time_or_default(str(section.get("time_start", "00:00:00")), "00:00:00")
        )
        self.time_end_edit.setTime(
            _parse_time_or_default(str(section.get("time_end", "23:59:59")), "23:59:59")
        )
        self._update_time_filter_state()
        self._update_salvage_size_state()
        self._update_source_mode_state()

        preset_key = str(section.get("tuning_preset", TUNING_PRESET_RECOMMENDED))
        preset_index = self.tuning_preset_combo.findData(preset_key)
        if preset_index >= 0:
            self.tuning_preset_combo.setCurrentIndex(preset_index)

        tuning = RecoveryTuning.from_settings_dict(section, fallback=self.recommended)
        self.chunk_size_spin.setValue(tuning.chunk_size // (1024 * 1024))
        self.preview_bytes_spin.setValue(tuning.preview_bytes // (1024 * 1024))
        self.max_carve_spin.setValue(tuning.max_carve_bytes // (1024 * 1024))
        self.max_workers_spin.setValue(tuning.max_workers)
        self.max_pending_spin.setValue(tuning.max_pending_jobs)
        self.overlap_spin.setValue(tuning.overlap)

        saved_drive = section.get("drive_device")
        self.drive_combo.setProperty("saved_drive_device", saved_drive)
        self._update_advanced_visibility()
        self._update_result_actions()

    def _save_settings(self):
        payload = {
            "goal_preset": self._selected_goal_preset(),
            "source_kind": self._selected_source_kind(),
            "drive_device": self.drive_combo.currentData(),
            "image_path": self.image_path_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
            "target_dates": [
                target_date.isoformat()
                for target_date in self._validated_target_dates(silent=True) or ()
            ],
            "filter_by_time": self.filter_by_time_check.isChecked(),
            "scan_only": self.scan_only_check.isChecked(),
            "show_advanced": self.show_advanced_check.isChecked(),
            "auto_salvage_size": self.auto_salvage_size_check.isChecked(),
            "salvage_size_mb": self.salvage_size_spin.value(),
            "time_start": self.time_start_edit.time().toString("HH:mm:ss"),
            "time_end": self.time_end_edit.time().toString("HH:mm:ss"),
            "tuning_preset": self._selected_tuning_preset(),
            **self._current_tuning().to_settings_dict(),
        }
        self.settings_store.update_section("recovery", payload)

    def _current_tuning(self) -> RecoveryTuning:
        return RecoveryTuning(
            chunk_size=self.chunk_size_spin.value() * 1024 * 1024,
            overlap=self.overlap_spin.value(),
            preview_bytes=self.preview_bytes_spin.value() * 1024 * 1024,
            max_carve_bytes=self.max_carve_spin.value() * 1024 * 1024,
            max_workers=self.max_workers_spin.value(),
            max_pending_jobs=self.max_pending_spin.value(),
        )

    def _validated_target_dates(self, *, silent: bool) -> tuple[date, ...] | None:
        try:
            dates = parse_target_dates(self.target_dates_edit.text().strip())
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Invalid Dates",
                    "Enter target dates as comma-separated YYYY-MM-DD values.",
                )
            return None

        if not dates:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Missing Dates",
                    "At least one target date is required.",
                )
            return None
        return dates

    def _selected_drive(self) -> DriveInfo | None:
        device = self.drive_combo.currentData()
        for drive in self.drives:
            if drive.device == device:
                return drive
        return None

    def _selected_source_context(self) -> tuple[str, str, str, DriveInfo | None, int] | None:
        """Validate and describe the source selected for scanning or salvage."""

        source_kind = self._selected_source_kind()
        if source_kind == RECOVERY_SOURCE_DRIVE:
            if not is_windows_admin():
                QMessageBox.warning(
                    self,
                    "Administrator Required",
                    "Open the app as Administrator before scanning a raw TeslaCam USB drive.",
                )
                return None

            drive = self._selected_drive()
            if drive is None:
                QMessageBox.warning(
                    self,
                    "No Drive Selected",
                    "Choose the TeslaCam USB drive first.",
                )
                return None

            return (
                build_raw_path_from_mount(drive.mountpoint),
                f"{drive.device} ({drive.mountpoint}, {drive.fstype})",
                source_kind,
                drive,
                drive_size_hint(drive),
            )

        image_path_text = self.image_path_edit.text().strip()
        if not image_path_text:
            QMessageBox.warning(
                self,
                "Image File Required",
                "Choose a raw image or source file to scan first.",
            )
            return None

        image_path = Path(image_path_text).expanduser()
        if not image_path.is_file():
            QMessageBox.warning(
                self,
                "Image File Missing",
                "The selected image or raw file does not exist.",
            )
            return None

        resolved_path = image_path.resolve()
        return (
            str(resolved_path),
            f"Image file: {resolved_path}",
            source_kind,
            None,
            image_size_hint(resolved_path),
        )

    def _build_options(self) -> RecoveryOptions | None:
        if not self.ffprobe_path:
            QMessageBox.warning(
                self,
                "ffprobe Missing",
                "ffprobe was not found on PATH. Install FFmpeg or add ffprobe to PATH first.",
            )
            return None

        target_dates = self._validated_target_dates(silent=False)
        if target_dates is None:
            return None

        output_dir_text = self.output_dir_edit.text().strip()
        if not output_dir_text:
            QMessageBox.warning(self, "Output Folder Required", "Choose an output folder first.")
            return None
        output_dir = Path(output_dir_text).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        source_context = self._selected_source_context()
        if source_context is None:
            return None
        source_path, source_label, source_kind, drive, total_size_hint = source_context

        return RecoveryOptions(
            source_path=source_path,
            source_label=source_label,
            output_dir=output_dir.resolve(),
            target_dates=target_dates,
            filter_by_time=self.filter_by_time_check.isChecked(),
            target_time_start=self.time_start_edit.time().toPython() if self.filter_by_time_check.isChecked() else None,
            target_time_end=self.time_end_edit.time().toPython() if self.filter_by_time_check.isChecked() else None,
            tuning=self._current_tuning(),
            ffprobe_program=self.ffprobe_path,
            scan_only=self.scan_only_check.isChecked(),
            source_kind=source_kind,
            drive=drive,
            total_size_hint=total_size_hint,
        )

    def _start_recovery(self):
        if self._is_busy():
            QMessageBox.information(self, "Already Running", "A recovery task is already running.")
            return

        options = self._build_options()
        if options is None:
            return
        if (
            options.source_kind == RECOVERY_SOURCE_DRIVE
            and QMessageBox.question(
                self,
                "Live USB Scan",
                "You are about to scan the live TeslaCam USB directly.\n\n"
                "Best practice is to stop using the USB and scan an image copy first when the footage matters.\n\n"
                "Do you want to continue with the live USB scan?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        self._save_settings()
        self.log_output.clear()
        self._clear_results()
        self.progress_bar.setValue(0)
        self.progress_stats_label.setText("Starting recovery...")
        if options.filter_by_time:
            time_filter_text = (
                f"{options.target_time_start.isoformat()} - "
                f"{options.target_time_end.isoformat()}"
            )
        else:
            time_filter_text = "disabled"
        self._append_log(
            "[FILTERS] "
            f"Dates: {format_target_dates(options.target_dates)} | "
            f"Time window: {time_filter_text} | "
            f"Scan only: {'yes' if options.scan_only else 'no'}"
        )
        self._set_next_steps_message(
            "Wait for the scan to finish, then review the results list. If nothing useful appears, widen the date range or remove the time filter."
        )
        self._set_running_state(True)

        self.worker_thread = QThread(self)
        self.worker = RecoveryScanWorker(options)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress_changed.connect(self._on_progress_changed)
        self.worker.log_message.connect(self._append_log)
        self.worker.candidate_result.connect(self._record_candidate_result)
        self.worker.finished.connect(self._on_recovery_finished)
        self.worker.failed.connect(self._on_recovery_failed)
        self.worker_thread.start()

    def _cancel_recovery(self):
        if self.worker is not None:
            self.worker.cancel()
            self._append_log("[CANCEL] Cancellation requested.")
            self.cancel_button.setEnabled(False)
        if self.salvage_worker is not None:
            self.salvage_worker.cancel()
            self._append_log("[CANCEL] Extra salvage cancellation requested.")
            self.cancel_button.setEnabled(False)

    def _on_progress_changed(self, payload: dict):
        percent = int(payload.get("percent", 0))
        scanned_bytes = int(payload.get("scanned_bytes", 0))
        total_size = int(payload.get("total_size", 0))
        elapsed_seconds = int(payload.get("elapsed_seconds", 0))
        eta_seconds = payload.get("eta_seconds")
        carved_count = int(payload.get("carved_count", 0))
        total_candidates = int(payload.get("total_candidates", 0))
        pending_jobs = int(payload.get("pending_jobs", 0))
        output_bytes = int(payload.get("total_output_bytes", 0))

        self.progress_bar.setValue(percent)
        eta_text = f"{eta_seconds}s" if eta_seconds is not None else "calculating..."
        match_count = int(payload.get("match_count", 0))
        action_word = "Matches" if self.scan_only_check.isChecked() else "Recovered"
        self.progress_stats_label.setText(
            f"Scanned: {format_bytes(scanned_bytes)} / {format_bytes(total_size)} | "
            f"Candidates: {total_candidates} | {action_word}: {match_count if self.scan_only_check.isChecked() else carved_count} | "
            f"Output: {format_bytes(output_bytes)} | Pending: {pending_jobs} | "
            f"Elapsed: {elapsed_seconds}s | ETA: {eta_text}"
        )

    def _append_log(self, message: str):
        self.log_output.appendPlainText(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def _record_candidate_result(self, result: RecoveryCandidateResult):
        if result.status not in {"matched", "scan_only_match", "manual_salvage"}:
            return

        output_path = Path(result.output_path) if result.output_path else None
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        timestamp_item = QTableWidgetItem(result.timestamp_text or "Unknown")
        offset_item = QTableWidgetItem(str(result.offset))
        size_item = QTableWidgetItem(
            format_bytes(result.bytes_written) if result.bytes_written > 0 else "Not carved"
        )
        confidence_item = QTableWidgetItem(result.confidence_label)
        if output_path is not None:
            file_text = output_path.name
        elif result.status == "scan_only_match":
            file_text = "Scan-only match"
        else:
            file_text = "No file"
        file_item = QTableWidgetItem(file_text)
        if output_path is not None:
            file_item.setToolTip(str(output_path))
            file_item.setData(Qt.ItemDataRole.UserRole, str(output_path))
        else:
            file_item.setToolTip("No file written because Scan Only mode was enabled.")

        self.results_table.setItem(row, 0, timestamp_item)
        self.results_table.setItem(row, 1, offset_item)
        self.results_table.setItem(row, 2, size_item)
        self.results_table.setItem(row, 3, confidence_item)
        self.results_table.setItem(row, 4, file_item)
        self.results_table.resizeRowToContents(row)
        self.results_table.selectRow(row)
        self._update_result_actions()

    def _on_recovery_finished(self, payload: dict):
        cancelled = bool(payload.get("cancelled"))
        carved_count = int(payload.get("carved_count", 0))
        match_count = int(payload.get("match_count", 0))
        total_candidates = int(payload.get("total_candidates", 0))
        output_bytes = int(payload.get("total_output_bytes", 0))
        elapsed_seconds = int(payload.get("elapsed_seconds", 0))

        self._append_log(
            "[DONE] "
            f"{'Cancelled' if cancelled else 'Completed'} | "
            f"Candidates: {total_candidates} | "
            f"Matches: {match_count} | "
            f"Recovered: {carved_count} | "
            f"Output: {format_bytes(output_bytes)} | "
            f"Elapsed: {elapsed_seconds}s"
        )
        self._teardown_worker()
        self._set_running_state(False)
        if self.scan_only_check.isChecked():
            self.progress_stats_label.setText(
                f"{'Cancelled' if cancelled else 'Completed'} scan-only run. "
                f"Found {match_count} likely match(es)."
            )
        else:
            self.progress_stats_label.setText(
                f"{'Cancelled' if cancelled else 'Completed'} recovery. "
                f"Recovered {carved_count} clip(s) into {self.output_dir_edit.text().strip()}."
            )
        self._set_next_steps_message(self._next_step_guidance(cancelled, match_count, carved_count))

    def _on_recovery_failed(self, message: str):
        self._append_log(f"[ERROR] {message}")
        self._teardown_worker()
        self._set_running_state(False)
        QMessageBox.critical(self, "Recovery Failed", message)

    def _set_running_state(self, running: bool):
        self._busy = running
        for widget in (
            self.recovery_goal_combo,
            self.scenario_combo,
            self.source_mode_combo,
            self.drive_combo,
            self.refresh_drives_button,
            self.image_path_edit,
            self.choose_image_button,
            self.output_dir_edit,
            self.choose_output_button,
            self.target_dates_edit,
            self.use_suggested_date_button,
            self.filter_by_time_check,
            self.scan_only_check,
            self.show_advanced_check,
            self.manual_offset_edit,
            self.auto_salvage_size_check,
            self.tuning_preset_combo,
            self.apply_preset_button,
            self.chunk_size_spin,
            self.preview_bytes_spin,
            self.max_carve_spin,
            self.salvage_size_spin,
            self.max_workers_spin,
            self.max_pending_spin,
            self.overlap_spin,
            self.recover_more_button,
            self.manual_salvage_button,
            self.start_button,
            self.switch_to_viewer_button,
            self.guided_setup_button,
            self.image_copy_guide_button,
        ):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.cancel_button.setText("Cancel Task" if running else "Cancel Scan")
        self.time_start_edit.setEnabled(not running and self.filter_by_time_check.isChecked())
        self.time_end_edit.setEnabled(not running and self.filter_by_time_check.isChecked())
        self._update_salvage_size_state()
        self._update_source_mode_state()
        self._update_result_actions()

    def _teardown_worker(self):
        if self.worker_thread is not None:
            self.worker_thread.quit()
            self.worker_thread.wait(2000)
            self.worker_thread.deleteLater()
            self.worker_thread = None
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def _teardown_salvage_worker(self):
        if self.salvage_thread is not None:
            self.salvage_thread.quit()
            self.salvage_thread.wait(2000)
            self.salvage_thread.deleteLater()
            self.salvage_thread = None
        if self.salvage_worker is not None:
            self.salvage_worker.deleteLater()
            self.salvage_worker = None

    def _update_status_banner(self):
        details = []
        if self._selected_source_kind() == RECOVERY_SOURCE_DRIVE:
            details.append("Drive mode reads the live TeslaCam USB device.")
            if not is_windows_admin():
                details.append("Run as Administrator to access the raw USB device.")
            if not self.drives:
                details.append("No mounted drives were detected.")
        else:
            details.append("Image mode scans a user-selected file and does not touch the live USB device.")
            if not self.image_path_edit.text().strip():
                details.append("Choose an image or raw file to scan.")
        if not self.ffprobe_path:
            details.append("ffprobe is not currently available on PATH.")
        if len(details) == 1 and self.ffprobe_path:
            details.append("Ready to scan. Settings will be saved to YAML after you start.")
        self.status_banner.setText(" ".join(details))
        self.preflight_label.setText(self._build_preflight_summary())

    def _build_preflight_summary(self) -> str:
        checks: list[str] = []
        checks.append(f"ffprobe: {'OK' if self.ffprobe_path else 'Missing'}")
        if self._selected_source_kind() == RECOVERY_SOURCE_DRIVE:
            checks.append(f"Admin: {'OK' if is_windows_admin() else 'Required'}")
            checks.append(
                f"Source: {'Drive selected' if self._selected_drive() is not None else 'Choose a TeslaCam USB drive'}"
            )
        else:
            image_path = self.image_path_edit.text().strip()
            checks.append(
                "Source: Image file selected"
                if image_path and Path(image_path).expanduser().is_file()
                else "Source: Choose an image or raw file"
            )
        checks.append(
            "Dates: Ready" if self._validated_target_dates(silent=True) else "Dates: Enter at least one YYYY-MM-DD"
        )
        checks.append(
            "Output: Ready"
            if self.output_dir_edit.text().strip()
            else "Output: Choose an output folder"
        )
        checks.append(
            "Mode: Scan only" if self.scan_only_check.isChecked() else "Mode: Recover files"
        )
        return "Preflight: " + " | ".join(checks)

    def _next_step_guidance(self, cancelled: bool, match_count: int, carved_count: int) -> str:
        """Return a plain-language suggestion after a recovery run finishes."""

        if cancelled:
            return "You can resume with the same settings, or switch to Scan Only first if you want to narrow results before carving files."
        if self.scan_only_check.isChecked():
            if match_count > 0:
                return "Review the likely matches. Use Extra Salvage on a promising result, or run again with Scan Only turned off to write normal recovered MP4 files."
            return "No likely matches were found. Try widening the date range, removing the time filter, or using Deep Scan."
        if carved_count > 0:
            return "Open the recovered files. If a clip seems cut short, select it and use Extra Salvage to copy a larger block from the same offset."
        return "No clips were recovered. Try Scan Only first, remove the time filter, or switch to an image copy if you have one."

def format_candidate_result(result: RecoveryCandidateResult) -> str:
    """Format one candidate probe result for the recovery log."""

    if result.status == "matched":
        output_name = Path(result.output_path).name if result.output_path else "unknown"
        return (
            f"[MATCH] Offset {result.offset}: ts={result.timestamp_text} -> "
            f"{output_name} ({format_bytes(result.bytes_written)})"
        )
    if result.status == "scan_only_match":
        return f"[MATCH] Offset {result.offset}: ts={result.timestamp_text} (scan only)"
    if result.status == "manual_salvage":
        output_name = Path(result.output_path).name if result.output_path else "unknown"
        return (
            f"[SALVAGE] Offset {result.offset}: wrote {output_name} "
            f"({format_bytes(result.bytes_written)})"
        )
    if result.status == "date_mismatch":
        return f"[SKIP] Offset {result.offset}: ts={result.timestamp_text} not in selected dates"
    if result.status == "time_mismatch":
        return f"[SKIP] Offset {result.offset}: ts={result.timestamp_text} not in selected time window"
    if result.status == "no_timestamp":
        return f"[SKIP] Offset {result.offset}: no timestamp found"
    if result.status == "cancelled":
        return f"[SKIP] Offset {result.offset}: cancelled"
    if result.timestamp_text:
        return f"[SKIP] Offset {result.offset}: {result.timestamp_text}"
    return f"[SKIP] Offset {result.offset}: {result.status}"


def _parse_time_or_default(value: str, fallback: str):
    """Parse a saved ``HH:mm:ss`` value, falling back when it is invalid."""

    parsed = QTime.fromString(value, "HH:mm:ss")
    if parsed.isValid():
        return parsed
    return QTime.fromString(fallback, "HH:mm:ss")


class RecoveryDialog(QDialog):
    """Standalone dialog wrapper for the reusable recovery panel."""

    def __init__(
        self,
        *,
        settings_store: AppSettingsStore,
        suggested_event_date: date | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Recovery Mode")
        self.resize(920, 800)
        layout = QVBoxLayout(self)
        self.panel = RecoveryPanel(
            settings_store=settings_store,
            suggested_event_date=suggested_event_date,
            parent=self,
        )
        self.panel.request_switch_to_viewer.connect(self.accept)
        layout.addWidget(self.panel)
