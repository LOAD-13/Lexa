"""Shared UI primitives matching the Lexa design system."""
from __future__ import annotations
from typing import List, Tuple

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)
from ui import theme as T


# ─────────────────────────────────────────────────────────────────────────────
# Panel — card with border, rounded corners, dark background
# ─────────────────────────────────────────────────────────────────────────────
class Panel(QFrame):
    def __init__(self, parent=None, padded: bool = True):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setStyleSheet(f"""
            QFrame#Panel {{
                background: {T.PANEL};
                border: 1px solid {T.LINE};
                border-radius: {T.R_XL}px;
            }}
        """)
        self._layout = QVBoxLayout(self)
        if padded:
            self._layout.setContentsMargins(14, 14, 14, 14)
        else:
            self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def layout(self) -> QVBoxLayout:  # type: ignore[override]
        return self._layout


# ─────────────────────────────────────────────────────────────────────────────
# SectionLabel — uppercase small label
# ─────────────────────────────────────────────────────────────────────────────
class SectionLabel(QWidget):
    def __init__(self, text: str, action_widget: QWidget | None = None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        lbl = QLabel(text.upper())
        lbl.setStyleSheet(f"""
            background: transparent;
            color: {T.MUTED};
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 0.8px;
        """)
        row.addWidget(lbl)
        row.addStretch()
        if action_widget:
            row.addWidget(action_widget)

        self.setFixedHeight(24)
        self.setContentsMargins(0, 0, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# ToggleSwitch — animated pill toggle
# ─────────────────────────────────────────────────────────────────────────────
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._thumb_x = 13 if checked else 1
        self.setFixedSize(30, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def checked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool) -> None:
        if self._checked != val:
            self._checked = val
            self._thumb_x = 13 if val else 1
            self.update()

    def mousePressEvent(self, _) -> None:
        self._checked = not self._checked
        self._thumb_x = 13 if self._checked else 1
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_color = QColor(T.ACCENT) if self._checked else QColor(T.ELEV)
        p.setPen(QPen(QColor(T.LINE), 1))
        p.setBrush(QBrush(track_color))
        p.drawRoundedRect(QRectF(0.5, 0.5, 29, 17), 8.5, 8.5)
        thumb_color = QColor(T.ACCENT_TEXT) if self._checked else QColor(T.FG2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(thumb_color))
        p.drawEllipse(QRectF(self._thumb_x, 2, 14, 14))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# SegmentedTabs
# ─────────────────────────────────────────────────────────────────────────────
class SegmentedTabs(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, items: List[Tuple[str, str]], initial: str = "", parent=None):
        super().__init__(parent)
        self._items = items
        self._current = initial or (items[0][0] if items else "")

        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)

        self.setStyleSheet(f"""
            SegmentedTabs {{
                background: {T.BG};
                border: 1px solid {T.LINE};
                border-radius: {T.R_MD}px;
            }}
        """)

        self._buttons: dict[str, QPushButton] = {}
        for value, label in items:
            btn = QPushButton(label)
            btn.setCheckable(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("seg_value", value)
            btn.clicked.connect(self._on_click)
            # Sin tamaño fijo, un layout apretado comprime los botones hasta
            # dejar las etiquetas ilegibles en vez de recortar otra cosa.
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(label) + 22)
            self._buttons[value] = btn
            row.addWidget(btn)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._refresh()

    def _on_click(self) -> None:
        val = self.sender().property("seg_value")
        if val != self._current:
            self._current = val
            self._refresh()
            self.changed.emit(val)

    def _refresh(self) -> None:
        for val, btn in self._buttons.items():
            if val == self._current:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {T.ELEV};
                        color: {T.FG};
                        border: none;
                        border-radius: 6px;
                        font-size: 12px;
                        font-weight: 500;
                        padding: 5px 10px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {T.MUTED};
                        border: none;
                        border-radius: 6px;
                        font-size: 12px;
                        font-weight: 500;
                        padding: 5px 10px;
                    }}
                    QPushButton:hover {{
                        color: {T.FG2};
                        background: rgba(255,255,255,6);
                    }}
                """)

    def set_value(self, val: str) -> None:
        if val in self._buttons and val != self._current:
            self._current = val
            self._refresh()

    @property
    def value(self) -> str:
        return self._current


# ─────────────────────────────────────────────────────────────────────────────
# Btn helpers
# ─────────────────────────────────────────────────────────────────────────────
_BTN_STYLES = {
    "primary": f"""
        QPushButton {{
            background: {T.ACCENT};
            color: {T.ACCENT_TEXT};
            border: 1px solid transparent;
            border-radius: 9px;
            font-size: 13px;
            font-weight: 600;
            padding: 9px 16px;
        }}
        QPushButton:hover {{ background: #7fd9a9; }}
        QPushButton:pressed {{ background: #5ab884; }}
        QPushButton:disabled {{ background: {T.LINE}; color: {T.DIM}; }}
    """,
    "ghost": f"""
        QPushButton {{
            background: {T.PANEL2};
            color: {T.FG};
            border: 1px solid {T.LINE};
            border-radius: {T.R_MD}px;
            font-size: 13px;
            font-weight: 500;
            padding: 7px 12px;
        }}
        QPushButton:hover {{ background: {T.ELEV}; }}
        QPushButton:pressed {{ background: {T.LINE}; }}
        QPushButton:disabled {{ color: {T.DIM}; }}
    """,
    "ghost_sm": f"""
        QPushButton {{
            background: {T.PANEL2};
            color: {T.FG};
            border: 1px solid {T.LINE};
            border-radius: {T.R_SM}px;
            font-size: 12px;
            font-weight: 500;
            padding: 5px 10px;
        }}
        QPushButton:hover {{ background: {T.ELEV}; }}
        QPushButton:pressed {{ background: {T.LINE}; }}
    """,
    "subtle": f"""
        QPushButton {{
            background: transparent;
            color: {T.FG2};
            border: 1px solid transparent;
            border-radius: {T.R_MD}px;
            font-size: 12px;
            font-weight: 500;
            padding: 5px 8px;
        }}
        QPushButton:hover {{ background: {T.PANEL2}; color: {T.FG}; }}
        QPushButton:pressed {{ background: {T.ELEV}; }}
    """,
    "danger": f"""
        QPushButton {{
            background: transparent;
            color: {T.FG2};
            border: 1px solid {T.LINE};
            border-radius: {T.R_MD}px;
            font-size: 13px;
            font-weight: 500;
            padding: 7px 12px;
        }}
        QPushButton:hover {{ color: {T.DANGER}; border-color: {T.DANGER}; }}
        QPushButton:pressed {{ background: {T.DANGER_SOFT}; }}
    """,
}


def make_btn(label: str = "", kind: str = "ghost") -> QPushButton:
    btn = QPushButton(label)
    btn.setStyleSheet(_BTN_STYLES.get(kind, _BTN_STYLES["ghost"]))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


# ─────────────────────────────────────────────────────────────────────────────
# FormatChip — selectable card using QFrame (NOT QPushButton)
# QPushButton + child QLabels causes opaque label backgrounds in Qt.
# Using QFrame + mousePressEvent avoids that issue entirely.
# ─────────────────────────────────────────────────────────────────────────────
class FormatChip(QFrame):
    clicked = pyqtSignal()

    def __init__(self, value: str, label: str, sub: str, parent=None):
        super().__init__(parent)
        self.value = value
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)
        self.setToolTip(sub)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 7, 8, 7)
        lay.setSpacing(1)

        self._lbl = QLabel(label)
        self._sub = QLabel(sub)
        self._sub.setStyleSheet(f"background: transparent; font-size: 9px; color: {T.MUTED};")
        # El subtítulo se recorta con puntos suspensivos en vez de ensanchar la
        # tarjeta, que es lo que rompía la fila de formatos en ventanas estrechas.
        self._sub.setMinimumWidth(1)

        lay.addWidget(self._lbl)
        lay.addWidget(self._sub)

        self.setActive(False)

    def setActive(self, active: bool) -> None:
        self._active = active
        if active:
            self._lbl.setStyleSheet(f"background: transparent; font-size: 12px; font-weight: 600; color: {T.ACCENT};")
            self.setStyleSheet(f"""
                FormatChip {{
                    background: {T.ACCENT_SOFT};
                    border: 1px solid {T.ACCENT_LINE};
                    border-radius: 9px;
                }}
            """)
        else:
            self._lbl.setStyleSheet(f"background: transparent; font-size: 12px; font-weight: 600; color: {T.FG};")
            self.setStyleSheet(f"""
                FormatChip {{
                    background: {T.PANEL2};
                    border: 1px solid {T.LINE};
                    border-radius: 9px;
                }}
                FormatChip:hover {{
                    background: {T.ELEV};
                }}
            """)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ─────────────────────────────────────────────────────────────────────────────
# RadioOption — full-row radio card using QFrame
# ─────────────────────────────────────────────────────────────────────────────
class RadioOption(QFrame):
    clicked = pyqtSignal()

    def __init__(self, value: str, label: str, sub: str, parent=None):
        super().__init__(parent)
        self.value = value
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(50)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self._radio = _RadioDot()
        lay.addWidget(self._radio)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(f"background: transparent; font-size: 12.5px; font-weight: 500; color: {T.FG};")
        self._sub = QLabel(sub)
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(f"background: transparent; font-size: 10.5px; color: {T.MUTED};")
        text_col.addWidget(self._lbl)
        text_col.addWidget(self._sub)
        lay.addLayout(text_col, stretch=1)

        self.setActive(False)

    def setActive(self, active: bool) -> None:
        self._radio.set_active(active)
        if active:
            self.setStyleSheet(f"""
                RadioOption {{
                    background: {T.ACCENT_SOFT};
                    border: 1px solid {T.ACCENT_LINE};
                    border-radius: 9px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                RadioOption {{
                    background: {T.PANEL2};
                    border: 1px solid {T.LINE};
                    border-radius: 9px;
                }}
                RadioOption:hover {{
                    background: {T.ELEV};
                }}
            """)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _RadioDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self.setFixedSize(14, 14)

    def set_active(self, val: bool) -> None:
        self._active = val
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        border_col = QColor(T.ACCENT) if self._active else QColor(T.DIM)
        p.setPen(QPen(border_col, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(0.75, 0.75, 12.5, 12.5))
        if self._active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(T.ACCENT)))
            p.drawEllipse(QRectF(4, 4, 6, 6))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# SettingRow — label + sub | control
# ─────────────────────────────────────────────────────────────────────────────
class SettingRow(QWidget):
    """Etiqueta + descripción a la izquierda, control a la derecha."""

    def __init__(self, label: str, sub: str = "", control: QWidget | None = None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 9, 0, 9)
        row.setSpacing(10)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._label = QLabel(label)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"background: transparent; font-size: 12.5px; font-weight: 500; color: {T.FG};"
        )
        col.addWidget(self._label)

        # Siempre se crea, aunque venga vacío, para poder actualizarlo después
        # (por ejemplo la ruta de guardado cuando el usuario la cambia).
        self._sub = QLabel(sub)
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(f"background: transparent; font-size: 10.5px; color: {T.MUTED};")
        self._sub.setVisible(bool(sub))
        col.addWidget(self._sub)

        row.addLayout(col, stretch=1)
        if control:
            control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(control, alignment=Qt.AlignmentFlag.AlignVCenter)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"border: none; border-top: 1px solid {T.LINE_S};")
        sep.setFixedHeight(1)
        self._sep = sep

    def set_sub(self, text: str) -> None:
        self._sub.setText(text)
        self._sub.setVisible(bool(text))

    def separator(self) -> QFrame:
        return self._sep


# ─────────────────────────────────────────────────────────────────────────────
# Dividers
# ─────────────────────────────────────────────────────────────────────────────
def hdivider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"border: none; border-top: 1px solid {T.LINE_S}; margin: 0;")
    f.setFixedHeight(1)
    return f


def vdivider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet(f"border: none; border-left: 1px solid {T.LINE}; margin: 0;")
    f.setFixedWidth(1)
    return f
