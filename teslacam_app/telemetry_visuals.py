"""Custom telemetry widgets for the TeslaCam viewer.

These widgets turn raw telemetry values into quick-glance visuals that are
easier to understand while a clip is playing.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class SpeedDisplayTelemetryWidget(QWidget):
    """Show speed as a slim digital dash readout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speed_mps: float | None = None
        self.setMinimumHeight(52)
        self.setMaximumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_speed(self, speed_mps: float | None):
        """Update the speed value and repaint the display."""

        self._speed_mps = speed_mps
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        """Paint a low-profile dashboard speed strip."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer_rect = QRectF(0, 0, self.width(), self.height()).adjusted(1, 1, -1, -1)
        tile_width = min(162.0, outer_rect.width())
        card_rect = QRectF(
            outer_rect.left() + (outer_rect.width() - tile_width) / 2,
            outer_rect.top(),
            tile_width,
            outer_rect.height(),
        )
        gradient = QLinearGradient(card_rect.topLeft(), card_rect.bottomLeft())
        gradient.setColorAt(0.0, QColor("#121a22"))
        gradient.setColorAt(1.0, QColor("#070a0d"))

        painter.setPen(QPen(QColor("#293640"), 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(card_rect, 12, 12)

        available = self._speed_mps is not None
        mph = 0.0 if self._speed_mps is None else self._speed_mps * 2.2369362921
        mph_text = "---" if not available else f"{mph:03.0f}"
        unit_text = "no signal" if not available else f"MPH  |  {self._speed_mps * 3.6:.0f} km/h"

        value_font = QFont("Bahnschrift")
        value_font.setBold(True)
        value_font.setStyleHint(QFont.StyleHint.Monospace)
        value_font.setPointSize(max(21, min(29, int(card_rect.width() / 6))))
        painter.setFont(value_font)
        painter.setPen(QColor("#f4fbff") if available else QColor("#6d7882"))
        painter.drawText(
            QRectF(card_rect.left() + 16, card_rect.top() + 5, card_rect.width() - 32, 30),
            Qt.AlignmentFlag.AlignCenter,
            mph_text,
        )

        subtitle_font = QFont(painter.font())
        subtitle_font.setBold(False)
        subtitle_font.setPointSize(8)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#a8b6c2") if available else QColor("#6d7882"))
        painter.drawText(
            QRectF(card_rect.left() + 16, card_rect.top() + 35, card_rect.width() - 32, 12),
            Qt.AlignmentFlag.AlignCenter,
            unit_text,
        )


class TelemetryVisualBase(QWidget):
    """Base class that provides consistent sizing and panel styling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(76)
        self.setMaximumHeight(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw_title(self, painter: QPainter, title: str):
        """Draw the shared mini-panel title."""

        painter.setPen(QColor("#515761"))
        title_font = QFont(painter.font())
        title_font.setBold(True)
        title_font.setPointSize(max(9, title_font.pointSize()))
        painter.setFont(title_font)
        painter.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignCenter, title)


class SteeringWheelTelemetryWidget(TelemetryVisualBase):
    """Show steering angle with a simple wheel icon that rotates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle_deg: float | None = None

    def set_angle(self, angle_deg: float | None):
        """Update the steering angle and repaint."""

        self._angle_deg = angle_deg
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        """Paint the rotated steering wheel."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfbfc"))
        self.draw_title(painter, "Steering")

        panel_rect = QRectF(4, 22, self.width() - 8, self.height() - 26)
        center = panel_rect.center()
        radius = min(panel_rect.width(), panel_rect.height()) * 0.34

        painter.setPen(QPen(QColor("#d5d9de"), 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(panel_rect, 8, 8)

        painter.save()
        painter.translate(center)
        painter.rotate(self._angle_deg or 0.0)

        ring_pen = QPen(QColor("#1d1f22"), 4)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), radius, radius)

        spoke_pen = QPen(QColor("#1d1f22"), 3)
        spoke_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(spoke_pen)
        painter.drawLine(QPointF(0, 0), QPointF(0, -radius + 10))
        painter.drawLine(QPointF(0, 0), QPointF(-radius * 0.75, radius * 0.35))
        painter.drawLine(QPointF(0, 0), QPointF(radius * 0.75, radius * 0.35))
        painter.restore()


class PedalTelemetryWidget(TelemetryVisualBase):
    """Show brake and throttle values as simple motorsport-style bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._throttle_percent: float | None = None
        self._brake_percent: float | None = None

    def set_pedals(self, throttle_percent: float | None, brake_percent: float | None):
        """Update pedal values and repaint."""

        self._throttle_percent = throttle_percent
        self._brake_percent = brake_percent
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        """Paint brake-left and throttle-right meters."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfbfc"))
        self.draw_title(painter, "Pedals")

        panel_rect = QRectF(4, 22, self.width() - 8, self.height() - 26)

        painter.setPen(QPen(QColor("#d5d9de"), 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(panel_rect, 8, 8)

        bar_width = max(16, panel_rect.width() * 0.22)
        bar_height = max(24, panel_rect.height() - 26)
        left_rect = QRectF(panel_rect.left() + panel_rect.width() * 0.22, panel_rect.top() + 12, bar_width, bar_height)
        right_rect = QRectF(panel_rect.right() - panel_rect.width() * 0.22 - bar_width, panel_rect.top() + 12, bar_width, bar_height)

        self.draw_bar(painter, left_rect, self._brake_percent, QColor("#ea4a4a"), "B")
        self.draw_bar(painter, right_rect, self._throttle_percent, QColor("#2bb673"), "T")

    def draw_bar(
        self,
        painter: QPainter,
        rect: QRectF,
        value_percent: float | None,
        fill_color: QColor,
        caption: str,
    ):
        """Draw one pedal meter."""

        painter.setPen(QPen(QColor("#ced3d8"), 2))
        painter.setBrush(QColor("#eef1f4"))
        painter.drawRoundedRect(rect, 8, 8)

        value = 0.0 if value_percent is None else max(0.0, min(value_percent, 100.0))
        fill_height = rect.height() * (value / 100.0)
        fill_rect = QRectF(rect.left(), rect.bottom() - fill_height, rect.width(), fill_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill_color)
        painter.drawRoundedRect(fill_rect, 8, 8)

        painter.setPen(QColor("#2f343a"))
        painter.drawText(
            QRectF(rect.left() - 12, rect.bottom() + 1, rect.width() + 24, 14),
            Qt.AlignmentFlag.AlignCenter,
            caption,
        )


class GForceTelemetryWidget(TelemetryVisualBase):
    """Show lateral and longitudinal acceleration as a compact g-meter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ax: float | None = None
        self._ay: float | None = None

    def set_acceleration(self, ax: float | None, ay: float | None):
        """Update horizontal-plane acceleration values and repaint."""

        self._ax = ax
        self._ay = ay
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        """Paint the acceleration dot against a simple crosshair."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfbfc"))
        self.draw_title(painter, "G Meter")

        panel_rect = QRectF(4, 22, self.width() - 8, self.height() - 26)

        painter.setPen(QPen(QColor("#d5d9de"), 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(panel_rect, 8, 8)

        center = panel_rect.center()
        radius = min(panel_rect.width(), panel_rect.height()) * 0.34

        painter.setPen(QPen(QColor("#d0d5da"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))

        if self._ax is not None and self._ay is not None:
            # Keep the dot readable rather than physically exact; most normal
            # driving values fit nicely within about +/- 5 m/s².
            scale = radius / 5.0
            dot = QPointF(
                center.x() + max(-radius, min(radius, self._ax * scale)),
                center.y() - max(-radius, min(radius, self._ay * scale)),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e82127"))
            painter.drawEllipse(dot, 7, 7)
