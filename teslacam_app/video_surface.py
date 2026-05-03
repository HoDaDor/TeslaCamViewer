"""Paint-based video surface used by the multi-camera viewer panes."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtMultimedia import QVideoSink
from PySide6.QtWidgets import QSizePolicy, QWidget


class VideoFrameWidget(QWidget):
    """Display frames from a ``QVideoSink`` with viewer-friendly sizing.

    The widget keeps Qt Multimedia in charge of decoding while the app controls
    the final paint step. That makes it possible to fill the camera panels,
    keep a small inset border, and support click-to-promote behavior for
    auxiliary angles.
    """

    clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        aspect_ratio_mode: Qt.AspectRatioMode = Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        frame_padding: int = 6,
    ):
        super().__init__(parent)
        self._video_sink = QVideoSink(self)
        self._video_sink.videoFrameChanged.connect(self._on_frame_changed)
        self._current_frame = QImage()
        self._aspect_ratio_mode = aspect_ratio_mode
        self._frame_padding = max(0, frame_padding)

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )

    def videoSink(self) -> QVideoSink:
        """Return the sink assigned to ``QMediaPlayer.setVideoSink``."""

        return self._video_sink

    def setAspectRatioMode(self, mode: Qt.AspectRatioMode):
        """Choose how frames scale into the padded paint area."""

        self._aspect_ratio_mode = mode
        self.update()

    def setFramePadding(self, padding: int):
        """Set the inset, in pixels, around the painted video image."""

        self._frame_padding = max(0, padding)
        self.update()

    def clear(self):
        """Clear the displayed frame without removing the video sink."""

        self._current_frame = QImage()
        self.update()

    def _on_frame_changed(self, frame):
        """Store a new decoded frame and schedule a repaint."""

        if not frame.isValid():
            return

        image = frame.toImage()
        if image.isNull():
            return

        self._current_frame = image
        self.update()

    def mousePressEvent(self, event):
        """Emit ``clicked`` so auxiliary camera panes can be promoted."""

        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        """Paint the latest frame into the widget with a small safe border."""

        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#05070a"))

        if self._current_frame.isNull():
            return

        content_rect = self.rect().adjusted(
            self._frame_padding,
            self._frame_padding,
            -self._frame_padding,
            -self._frame_padding,
        )
        if not content_rect.isValid():
            return

        painter.fillRect(content_rect, QColor("#080a0d"))
        target_size = self._current_frame.size().scaled(
            content_rect.size(),
            self._aspect_ratio_mode,
        )
        target_rect = QRect(
            content_rect.x() + (content_rect.width() - target_size.width()) // 2,
            content_rect.y() + (content_rect.height() - target_size.height()) // 2,
            target_size.width(),
            target_size.height(),
        )
        painter.setClipRect(content_rect)
        painter.drawImage(target_rect, self._current_frame)
