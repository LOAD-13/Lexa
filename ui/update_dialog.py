"""Pantalla de actualizacion: capa a pantalla completa con la imagen de Lexa.

Se monta sobre la ventana entera, como el tour, en vez de abrir un dialogo del
sistema: un cuadro gris de Windows en medio de una aplicacion oscura se ve como
un error, no como una novedad.

El fondo no se limita a oscurecer: bloquea el raton, porque durante la descarga
no tiene sentido que se pueda seguir tocando la cola de archivos.
"""
from __future__ import annotations
import os
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPainterPath, QBrush, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from core.paths import resource
from ui import theme as T

_ICON_SIZE = 64


class UpdateDialog(QWidget):
    """Capa modal con el aviso, la descarga y el reinicio."""

    accepted = pyqtSignal()      # el usuario quiere actualizar
    restart = pyqtSignal()       # ya descargada: reiniciar
    dismissed = pyqtSignal()     # mas tarde

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setVisible(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._downloading = False

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addStretch()

        fila = QHBoxLayout()
        fila.addStretch()
        fila.addWidget(self._build_card())
        fila.addStretch()
        raiz.addLayout(fila)
        raiz.addStretch()

    # -- Construccion ---------------------------------------------------------
    def _build_card(self) -> QFrame:
        tarjeta = QFrame()
        tarjeta.setObjectName("UpdateCard")
        tarjeta.setFixedWidth(430)
        tarjeta.setStyleSheet(f"""
            QFrame#UpdateCard {{
                background: {T.PANEL};
                border: 1px solid {T.ACCENT_LINE};
                border-radius: 16px;
            }}
        """)

        col = QVBoxLayout(tarjeta)
        col.setContentsMargins(30, 28, 30, 24)
        col.setSpacing(0)

        icono = _AppIcon()
        fila_icono = QHBoxLayout()
        fila_icono.addStretch()
        fila_icono.addWidget(icono)
        fila_icono.addStretch()
        col.addLayout(fila_icono)
        col.addSpacing(16)

        self._titulo = QLabel("Hay una nueva versión de Lexa")
        self._titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._titulo.setWordWrap(True)
        self._titulo.setStyleSheet(
            f"background: transparent; color: {T.FG}; "
            f"font-size: 17px; font-weight: 600;"
        )
        col.addWidget(self._titulo)
        col.addSpacing(7)

        self._version = QLabel()
        self._version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version.setStyleSheet(
            f"background: transparent; color: {T.ACCENT}; font-size: 13px; "
            f"font-weight: 600; font-family: Consolas, monospace;"
        )
        col.addWidget(self._version)
        col.addSpacing(12)

        self._cuerpo = QLabel()
        self._cuerpo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cuerpo.setWordWrap(True)
        self._cuerpo.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 12.5px;")
        col.addWidget(self._cuerpo)
        col.addSpacing(20)

        self._barra = QProgressBar()
        self._barra.setVisible(False)
        self._barra.setFixedHeight(7)
        self._barra.setTextVisible(False)
        self._barra.setStyleSheet(f"""
            QProgressBar {{
                background: {T.ELEV}; border: none; border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {T.ACCENT}; border-radius: 4px;
            }}
        """)
        col.addWidget(self._barra)

        self._detalle = QLabel()
        self._detalle.setVisible(False)
        self._detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detalle.setStyleSheet(
            f"background: transparent; color: {T.DIM}; font-size: 11px; "
            f"font-family: Consolas, monospace;")
        col.addWidget(self._detalle)
        col.addSpacing(6)

        self._principal = QPushButton("Actualizar ahora")
        self._principal.setCursor(Qt.CursorShape.PointingHandCursor)
        self._principal.setFixedHeight(40)
        self._principal.setStyleSheet(f"""
            QPushButton {{
                background: {T.ACCENT}; color: {T.ACCENT_TEXT};
                border: none; border-radius: {T.R_MD}px;
                font-size: 13.5px; font-weight: 600;
            }}
            QPushButton:hover  {{ background: #7fd6a8; }}
            QPushButton:disabled {{ background: {T.ELEV}; color: {T.MUTED}; }}
        """)
        self._principal.clicked.connect(self._on_primary)
        col.addWidget(self._principal)
        col.addSpacing(4)

        self._secundario = QPushButton("Más tarde")
        self._secundario.setCursor(Qt.CursorShape.PointingHandCursor)
        self._secundario.setFixedHeight(30)
        self._secundario.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T.MUTED};
                border: none; font-size: 12px;
            }}
            QPushButton:hover {{ color: {T.FG}; }}
        """)
        self._secundario.clicked.connect(self._on_dismiss)
        col.addWidget(self._secundario)

        return tarjeta

    # -- API ------------------------------------------------------------------
    def show_update(self, update) -> None:
        self._downloading = False
        self._version.setText(f"Versión {update.version}")
        self._cuerpo.setText(
            f"Tienes la versión {_current()}. La actualización ocupa "
            f"{update.size_str} y se instala sola: Lexa se cerrará y volverá "
            f"a abrirse una vez."
        )
        self._titulo.setText("Hay una nueva versión de Lexa")
        self._principal.setText("Actualizar ahora")
        self._principal.setEnabled(True)
        self._secundario.setVisible(True)
        self._secundario.setText("Más tarde")
        self._barra.setVisible(False)
        self._detalle.setVisible(False)
        self._show()

    def set_progress(self, fraction: float) -> None:
        self._barra.setValue(int(fraction * 100))
        self._detalle.setText(f"{int(fraction * 100)} %")

    def show_downloading(self) -> None:
        self._downloading = True
        self._titulo.setText("Descargando la actualización")
        self._cuerpo.setText("No cierres Lexa mientras tanto.")
        self._principal.setEnabled(False)
        self._principal.setText("Descargando…")
        self._secundario.setVisible(False)
        self._barra.setValue(0)
        self._barra.setVisible(True)
        self._detalle.setVisible(True)

    def show_ready(self) -> None:
        self._downloading = False
        self._titulo.setText("Todo listo")
        self._cuerpo.setText(
            "Lexa se cerrará y volverá a abrirse para terminar de instalarla.")
        self._principal.setText("Reiniciar Lexa")
        self._principal.setEnabled(True)
        self._secundario.setVisible(True)
        self._secundario.setText("Reiniciar más tarde")
        self._barra.setVisible(False)
        self._detalle.setVisible(False)

    def show_error(self, mensaje: str) -> None:
        self._downloading = False
        self._titulo.setText("No se pudo actualizar")
        self._cuerpo.setText(mensaje.strip())
        self._principal.setText("Reintentar")
        self._principal.setEnabled(True)
        self._secundario.setVisible(True)
        self._secundario.setText("Cerrar")
        self._barra.setVisible(False)
        self._detalle.setVisible(False)

    # -- Interno --------------------------------------------------------------
    def _show(self) -> None:
        padre = self.parentWidget()
        if padre is not None:
            self.setGeometry(padre.rect())
        self.setVisible(True)
        self.raise_()

    def _on_primary(self) -> None:
        if self._principal.text().startswith("Reiniciar"):
            self.restart.emit()
        else:
            self.accepted.emit()

    def _on_dismiss(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()

    def paintEvent(self, _) -> None:
        # Velo oscuro: la ventana sigue viendose detras, pero queda claro que
        # lo que manda ahora es la tarjeta.
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 170))
        p.end()

    def mousePressEvent(self, event) -> None:
        # Se traga los clics para que no lleguen a la ventana de debajo.
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and not self._downloading:
            self._on_dismiss()
            return
        event.accept()


def _current() -> str:
    from core.version import VERSION
    return VERSION


class _AppIcon(QWidget):
    """Icono de Lexa dentro de un circulo claro, como en el tour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._pixmap: Optional[QPixmap] = None
        ruta = resource("icon.png")
        if os.path.isfile(ruta):
            pix = QPixmap(ruta)
            if not pix.isNull():
                lado = (_ICON_SIZE - 16) * 4
                self._pixmap = pix.scaled(
                    lado, lado,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(0, 0, _ICON_SIZE, _ICON_SIZE)

        if self._pixmap is not None:
            w = self._pixmap.width() / 4
            h = self._pixmap.height() / 4
            p.drawPixmap(
                QRectF((_ICON_SIZE - w) / 2, (_ICON_SIZE - h) / 2, w, h),
                self._pixmap, QRectF(self._pixmap.rect()),
            )
        else:
            p.setPen(QColor(T.BG))
            fuente = QFont()
            fuente.setPointSize(24)
            fuente.setWeight(QFont.Weight.Bold)
            p.setFont(fuente)
            p.drawText(0, 0, _ICON_SIZE, _ICON_SIZE,
                       Qt.AlignmentFlag.AlignCenter, "L")
        p.end()
