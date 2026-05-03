"""Small custom Qt widgets used by the viewer."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygon
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class EventBookmarkSlider(QSlider):
    """Slider that draws a visible marker for the Tesla event timestamp."""

    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self._event_position = -1

    def set_event_position(self, position: int | None):
        """Set the event marker position in the slider's value range."""

        self._event_position = -1 if position is None else max(0, int(position))
        self.update()

    def clear_event_position(self):
        """Hide the event marker until a new event position is available."""

        self._event_position = -1
        self.update()

    def mousePressEvent(self, event):
        """Jump the slider thumb directly to the clicked position."""

        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self.pixel_pos_to_range_value(event.position().toPoint()))
            self.sliderMoved.emit(self.value())
            self.sliderPressed.emit()
            self.sliderReleased.emit()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Keep dragging responsive after a click-to-seek jump."""

        if event.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self.pixel_pos_to_range_value(event.position().toPoint()))
            self.sliderMoved.emit(self.value())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def pixel_pos_to_range_value(self, position: QPoint) -> int:
        """Convert a click position inside the slider into a value."""

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )

        if self.orientation() == Qt.Orientation.Horizontal:
            slider_min = groove_rect.x()
            slider_max = groove_rect.right() - handle_rect.width() + 1
            slider_pos = position.x() - (handle_rect.width() // 2)
        else:
            slider_min = groove_rect.y()
            slider_max = groove_rect.bottom() - handle_rect.height() + 1
            slider_pos = position.y() - (handle_rect.height() // 2)

        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            slider_pos - slider_min,
            max(1, slider_max - slider_min),
            option.upsideDown,
        )

    def paintEvent(self, event: QPaintEvent):
        """Draw the normal slider, then overlay the event marker."""

        super().paintEvent(event)
        if self._event_position < 0 or self.maximum() <= self.minimum():
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if not groove_rect.isValid():
            return

        span = max(1, self.maximum() - self.minimum())
        ratio = (self._event_position - self.minimum()) / span
        ratio = max(0.0, min(1.0, ratio))

        if self.orientation() == Qt.Orientation.Horizontal:
            x_pos = groove_rect.left() + int(groove_rect.width() * ratio)
            marker_rect = QRect(x_pos - 1, groove_rect.top() - 8, 3, groove_rect.height() + 16)
            triangle = QPolygon(
                [
                    QPoint(x_pos, marker_rect.top()),
                    QPoint(x_pos - 6, marker_rect.top() + 8),
                    QPoint(x_pos + 6, marker_rect.top() + 8),
                ]
            )
        else:
            y_pos = groove_rect.bottom() - int(groove_rect.height() * ratio)
            marker_rect = QRect(groove_rect.left() - 8, y_pos - 1, groove_rect.width() + 16, 3)
            triangle = QPolygon(
                [
                    QPoint(marker_rect.right(), y_pos),
                    QPoint(marker_rect.right() - 8, y_pos - 6),
                    QPoint(marker_rect.right() - 8, y_pos + 6),
                ]
            )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        accent = QColor("#ff6b35")
        painter.fillRect(marker_rect, accent)
        painter.setPen(QPen(QColor("#fff3ed"), 1))
        painter.setBrush(accent)
        painter.drawPolygon(triangle)
