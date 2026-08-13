"""Barra de identidad de la app: logo, lote actual, estado y ayuda.

Los controles de ventana (cerrar, minimizar, maximizar) los pone el marco nativo
de Windows que va encima de esta barra.
"""
from __future__ import annotations
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush, QLinearGradient, QFont, QPixmap, QPainterPath
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ui import theme as T
from ui.widgets import make_btn
from core.paths import resource


class TitleBar(QWidget):
    help_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setObjectName("TitleBar")
        self.setStyleSheet(f"""
            QWidget#TitleBar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1d22, stop:1 #14161a
                );
                border-bottom: 1px solid {T.LINE};
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 12, 0)
        row.setSpacing(0)

        self.logo = _LogoBadge()
        row.addWidget(self.logo)
        row.addSpacing(9)

        name_lbl = QLabel("Lexa")
        name_lbl.setStyleSheet(
            f"background: transparent; color: {T.FG}; font-size: 13px; font-weight: 600;"
        )
        row.addWidget(name_lbl)

        dot = QLabel(" · ")
        dot.setStyleSheet(f"background: transparent; color: {T.DIM}; font-size: 12px;")
        row.addWidget(dot)

        self._batch_lbl = QLabel("Sin archivos")
        self._batch_lbl.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 12px;"
        )
        row.addWidget(self._batch_lbl)

        row.addStretch()

        self._status_badge = QLabel("Listo")
        self._apply_badge(T.MUTED)
        row.addWidget(self._status_badge)

        row.addSpacing(8)

        self.help_btn = make_btn("?", kind="ghost_sm")
        self.help_btn.setFixedSize(26, 26)
        self.help_btn.setToolTip("Ver el tour guiado de la aplicación")
        self.help_btn.clicked.connect(self.help_requested)
        row.addWidget(self.help_btn)

    def set_batch_name(self, name: str) -> None:
        self._batch_lbl.setText(name)

    def set_status(self, text: str, color: str = T.MUTED) -> None:
        self._status_badge.setText(text)
        self._apply_badge(color)

    def _apply_badge(self, color: str) -> None:
        self._status_badge.setStyleSheet(f"""
            background: {T.BG};
            color: {color};
            font-size: 11px;
            border: 1px solid {T.LINE};
            border-radius: 6px;
            padding: 3px 10px;
        """)


class _LogoBadge(QWidget):
    """Muestra icon.png si existe; si no, dibuja una insignia con la inicial."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self._pixmap: QPixmap | None = None
        path = resource("icon.png")
        if os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self._pixmap = pix.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self._pixmap is not None:
            path = QPainterPath()
            path.addRoundedRect(0, 0, 24, 24, 6, 6)
            p.setClipPath(path)
            p.drawPixmap(0, 0, 24, 24, self._pixmap)
            p.end()
            return

        grad = QLinearGradient(0, 0, 24, 24)
        grad.setColorAt(0, QColor(T.ACCENT))
        grad.setColorAt(1, QColor("#3b9fd4"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        path = QPainterPath()
        path.addRoundedRect(0, 0, 24, 24, 6, 6)
        p.drawPath(path)

        p.setPen(QColor(T.ACCENT_TEXT))
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(0, 0, 24, 24, Qt.AlignmentFlag.AlignCenter, "L")
        p.end()
