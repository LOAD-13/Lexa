"""Cuadro para pegar un enlace de YouTube.

Es una capa sobre la ventana, como la de actualizar, y no un diálogo del
sistema: un cuadro gris de Windows en medio de una aplicación oscura se ve
como un error.
"""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from core import youtube
from ui import theme as T
from ui.widgets import make_btn


class YoutubeDialog(QWidget):
    """Capa modal con un campo para el enlace."""

    accepted = pyqtSignal(str)     # enlace ya normalizado
    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setVisible(False)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addStretch()
        fila = QHBoxLayout()
        fila.addStretch()
        fila.addWidget(self._build_card())
        fila.addStretch()
        raiz.addLayout(fila)
        raiz.addStretch()

    def _build_card(self) -> QFrame:
        tarjeta = QFrame()
        tarjeta.setObjectName("YtCard")
        tarjeta.setFixedWidth(460)
        tarjeta.setStyleSheet(f"""
            QFrame#YtCard {{
                background: {T.PANEL};
                border: 1px solid {T.ACCENT_LINE};
                border-radius: 16px;
            }}
        """)
        col = QVBoxLayout(tarjeta)
        col.setContentsMargins(26, 24, 26, 20)
        col.setSpacing(12)

        titulo = QLabel("Enlace de YouTube")
        titulo.setStyleSheet(
            f"background: transparent; font-size: 19px; font-weight: 700;"
            f" color: {T.FG}; letter-spacing: -0.3px;")
        col.addWidget(titulo)

        self._sub = QLabel("Se descargará a una carpeta de Lexa y entrará en la cola.")
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(
            f"background: transparent; font-size: 12px; color: {T.MUTED};")
        col.addWidget(self._sub)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self._edit.textChanged.connect(self._revisar)
        self._edit.returnPressed.connect(self._aceptar)
        col.addWidget(self._edit)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(
            f"background: transparent; font-size: 11.5px; color: {T.DANGER};")
        self._error.setVisible(False)
        col.addWidget(self._error)

        botones = QHBoxLayout()
        botones.addStretch()
        cancelar = make_btn("Cancelar", kind="ghost")
        cancelar.clicked.connect(self._cancelar)
        botones.addWidget(cancelar)
        self._ok = make_btn("Descargar", kind="primary")
        self._ok.clicked.connect(self._aceptar)
        botones.addWidget(self._ok)
        col.addLayout(botones)
        return tarjeta

    # -- Uso ------------------------------------------------------------------
    def open(self, texto: str = "") -> None:
        """Muestra el cuadro. Si no se da texto, se mira el portapapeles."""
        if not texto:
            try:
                portapapeles = QGuiApplication.clipboard().text()
            except Exception:
                portapapeles = ""
            # Solo se rellena si de verdad es un enlace: meter cualquier cosa
            # que hubiera copiada es mas molesto que dejarlo vacio.
            if youtube.is_link(portapapeles):
                texto = portapapeles.strip()
        self._edit.setText(texto)
        self._revisar()
        if self.parent():
            self.setGeometry(self.parent().rect())
        self.setVisible(True)
        self.raise_()
        self._edit.setFocus()
        self._edit.selectAll()

    def _revisar(self) -> None:
        texto = self._edit.text().strip()
        valido = bool(texto) and youtube.is_link(texto)
        self._ok.setEnabled(valido)
        if texto and not valido:
            self._error.setText("Eso no parece un enlace de un vídeo de YouTube.")
            self._error.setVisible(True)
        else:
            self._error.setVisible(False)

    def _aceptar(self) -> None:
        enlace = youtube.normalize_link(self._edit.text())
        if not enlace:
            self._revisar()
            return
        self.setVisible(False)
        self.accepted.emit(enlace)

    def _cancelar(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()

    # -- Presentacion ---------------------------------------------------------
    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 170))
        p.end()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self._cancelar()
            return
        super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.parent():
            self.setGeometry(self.parent().rect())
