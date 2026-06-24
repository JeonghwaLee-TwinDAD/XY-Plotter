"""widgets.py
----------
Qt ports of the design system's core components:
design-system/components/core/{LED,StatusChip,TestTag,Panel,Readout}.jsx
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


class LED(QWidget):
    """A small status lamp, optionally with a mono-caps label."""

    def __init__(self, color: str = "idle", label: str | None = None, size: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._size = size
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._lamp = _Lamp(size)
        layout.addWidget(self._lamp)
        if label:
            lbl = QLabel(label.upper())
            lbl.setStyleSheet(
                f"font-family: '{theme.FONT_MONO}'; font-size: 12px; "
                f"color: {theme.INK_2}; letter-spacing: 1px;"
            )
            layout.addWidget(lbl)
        layout.addStretch(0)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self._color = color
        c = theme.VERDICT_STYLE.get(color, (color, None, None))[0]
        self._lamp.set_color(c)


class _Lamp(QWidget):
    def __init__(self, size: int) -> None:
        super().__init__()
        self._size = size
        self._color = QColor(theme.LINE_STRONG)
        self.setFixedSize(size, size)

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(self.rect())


class StatusChip(QLabel):
    """PASS / FAIL / RUNNING / WARN / IDLE verdict pill."""

    def __init__(self, status: str = "idle", size: str = "md", parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self.set_status(status)

    def set_status(self, status: str) -> None:
        color, soft, label = theme.VERDICT_STYLE.get(status, theme.VERDICT_STYLE["idle"])
        solid = status in ("pass", "fail")
        heights = {"sm": 18, "md": 22, "lg": 26}
        fonts = {"sm": 10, "md": 11, "lg": 12}
        h = heights.get(self._size, 22)
        fz = fonts.get(self._size, 11)
        self.setText(label)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(h)
        self.setStyleSheet(
            f"background: {color if solid else soft}; "
            f"color: {'#fff' if solid else color}; "
            f"border: 1px solid {color if solid else 'transparent'}; "
            f"border-radius: {theme.R_1}px; "
            f"font-family: '{theme.FONT_MONO}'; font-weight: 700; font-size: {fz}px; "
            f"letter-spacing: 1px; padding: 0 9px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)


class TestTag(QLabel):
    """Labels a test mode with its calibrated color (TestTag.jsx)."""

    def __init__(self, mode: str = "PG", parent=None) -> None:
        super().__init__(parent)
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        label, color, soft = theme.MODE_STYLE.get(mode, (mode, theme.INK_2, theme.PANEL_2))
        self.setText("  " + label)
        self.setStyleSheet(
            f"background: {soft}; color: {color}; "
            f"border: 1px solid {color}55; border-radius: {theme.R_2}px; "
            f"font-family: '{theme.FONT_SANS}'; font-weight: 600; font-size: 12px; "
            f"padding: 0 10px;"
        )
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)


class Panel(QFrame):
    """Bordered card with optional eyebrow/title header (Panel.jsx)."""

    def __init__(self, title: str | None = None, eyebrow: str | None = None,
                 tone: str = "light", actions: QWidget | None = None, parent=None) -> None:
        super().__init__(parent)
        self._console = tone == "console"
        self.setObjectName("fgPanelConsole" if self._console else "fgPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if title or eyebrow or actions:
            header = QFrame()
            header.setObjectName("fgPanelHeaderConsole" if self._console else "fgPanelHeader")
            hl = QHBoxLayout(header)
            hl.setContentsMargins(16, 10, 16, 10)
            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            if eyebrow:
                lbl = QLabel(eyebrow.upper())
                lbl.setObjectName("fgEyebrowConsole" if self._console else "fgEyebrow")
                text_col.addWidget(lbl)
            if title:
                lbl = QLabel(title)
                lbl.setObjectName("fgTitleConsole" if self._console else "fgTitle")
                text_col.addWidget(lbl)
            hl.addLayout(text_col)
            hl.addStretch(1)
            if actions:
                hl.addWidget(actions)
            outer.addWidget(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(16, 16, 16, 16)
        outer.addWidget(self.body)

    def set_body_margins(self, *margins: int) -> None:
        self.body_layout.setContentsMargins(*margins)


class Readout(QWidget):
    """A label + monospace value + unit, colored by calibrated signal (Readout.jsx)."""

    SIGNAL_COLOR = {
        "up": theme.UP, "down": theme.DOWN, "gain": theme.GAIN,
        "leak": theme.LEAK, "warn": theme.AMBER, None: theme.CONSOLE_INK,
    }

    def __init__(self, label: str, value: str = "", unit: str = "", signal: str | None = None,
                 size: str = "md", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(2)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"font-family: '{theme.FONT_SANS}'; font-size: 11px; color: {theme.CONSOLE_INK_2}; "
            "text-transform: uppercase; letter-spacing: 1px;"
        )
        layout.addWidget(self._label)

        row = QHBoxLayout()
        row.setSpacing(6)
        fz = 26 if size == "md" else 16
        color = self.SIGNAL_COLOR.get(signal, theme.CONSOLE_INK)
        self._value = QLabel(str(value))
        self._value.setStyleSheet(
            f"font-family: '{theme.FONT_MONO}'; font-weight: 500; font-size: {fz}px; color: {color};"
        )
        row.addWidget(self._value)
        if unit:
            self._unit = QLabel(unit)
            self._unit.setStyleSheet(
                f"font-family: '{theme.FONT_MONO}'; font-size: 12px; color: {theme.CONSOLE_INK_2};"
            )
            row.addWidget(self._unit)
        row.addStretch(1)
        layout.addLayout(row)

    def set_value(self, value: str, unit: str | None = None) -> None:
        self._value.setText(str(value))
        if unit is not None and hasattr(self, "_unit"):
            self._unit.setText(unit)
