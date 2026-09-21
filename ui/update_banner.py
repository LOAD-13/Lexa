"""Aviso de actualizacion y su descarga, sin bloquear la interfaz.

La comprobacion y la descarga van en hilos aparte: son operaciones de red y
congelarian la ventana. El hilo solo emite resultados; quien toca los widgets
es siempre el hilo de la interfaz.
"""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from ui import theme as T


class UpdateCheckThread(QThread):
    """Pregunta a GitHub si hay version nueva. Silencioso si no la hay."""

    found = pyqtSignal(object)      # core.updater.Update

    def run(self) -> None:
        try:
            from core.updater import check
            update = check()
        except Exception:
            return
        if update is not None:
            self.found.emit(update)


class UpdateDownloadThread(QThread):
    """Descarga y deja preparada la actualizacion."""

    progress = pyqtSignal(float)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, update, parent=None):
        super().__init__(parent)
        self._update = update
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            from core.updater import download, stage
            archivo = download(self._update,
                               progress=self.progress.emit,
                               should_abort=lambda: self._abort)
            stage(self._update, archivo)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished_ok.emit()


class UpdateBanner(QWidget):
    """Barra discreta sobre el contenido. Oculta mientras no haya novedades."""

    restart_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setObjectName("UpdateBanner")
        self.setStyleSheet(f"""
            QWidget#UpdateBanner {{
                background: {T.ACCENT_SOFT};
                border: 1px solid {T.ACCENT_LINE};
                border-radius: {T.R_MD}px;
            }}
        """)

        self._update = None
        self._thread: Optional[UpdateDownloadThread] = None

        fila = QHBoxLayout(self)
        fila.setContentsMargins(12, 7, 8, 7)
        fila.setSpacing(10)

        self._texto = QLabel()
        self._texto.setStyleSheet(
            f"background: transparent; font-size: 12px; color: {T.FG};")
        fila.addWidget(self._texto)

        self._barra = QProgressBar()
        self._barra.setVisible(False)
        self._barra.setFixedWidth(140)
        self._barra.setFixedHeight(6)
        self._barra.setTextVisible(False)
        self._barra.setStyleSheet(f"""
            QProgressBar {{
                background: {T.LINE}; border: none; border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {T.ACCENT}; border-radius: 3px;
            }}
        """)
        fila.addWidget(self._barra)
        fila.addStretch()

        self._accion = QPushButton("Actualizar")
        self._accion.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accion.setStyleSheet(f"""
            QPushButton {{
                background: {T.ACCENT}; color: {T.ACCENT_TEXT};
                border: none; border-radius: {T.R_SM}px;
                padding: 5px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:disabled {{ background: {T.ELEV}; color: {T.MUTED}; }}
        """)
        self._accion.clicked.connect(self._on_action)
        fila.addWidget(self._accion)

        self._cerrar = QPushButton("✕")
        self._cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cerrar.setFixedSize(24, 24)
        self._cerrar.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T.MUTED};
                border: none; font-size: 13px;
            }}
            QPushButton:hover {{ color: {T.FG}; }}
        """)
        self._cerrar.clicked.connect(self._on_dismiss)
        fila.addWidget(self._cerrar)

    # -- API ------------------------------------------------------------------
    def show_update(self, update) -> None:
        self._update = update
        self._texto.setText(
            f"Lexa {update.version} disponible · {update.size_str}")
        self._accion.setText("Actualizar")
        self._accion.setEnabled(True)
        self._barra.setVisible(False)
        self.setVisible(True)

    def show_applied(self, version: str) -> None:
        """Mensaje tras un arranque que acaba de aplicar una actualizacion."""
        self._update = None
        self._texto.setText(f"Actualizado a Lexa {version}")
        self._accion.setVisible(False)
        self._barra.setVisible(False)
        self.setVisible(True)

    # -- Interno --------------------------------------------------------------
    def _on_action(self) -> None:
        if self._update is None:
            self.restart_requested.emit()
            return

        self._accion.setEnabled(False)
        self._accion.setText("Descargando…")
        self._barra.setValue(0)
        self._barra.setVisible(True)

        self._thread = UpdateDownloadThread(self._update, self)
        self._thread.progress.connect(
            lambda p: self._barra.setValue(int(p * 100)))
        self._thread.finished_ok.connect(self._on_ready)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_ready(self) -> None:
        self._update = None            # ya descargada: el boton pasa a reiniciar
        self._barra.setVisible(False)
        self._texto.setText("Actualización lista. Reinicia Lexa para aplicarla.")
        self._accion.setText("Reiniciar")
        self._accion.setEnabled(True)

    def _on_failed(self, mensaje: str) -> None:
        self._barra.setVisible(False)
        # Solo la primera linea: el detalle completo va al registro.
        self._texto.setText(mensaje.splitlines()[0])
        self._accion.setText("Reintentar")
        self._accion.setEnabled(True)

    def _on_dismiss(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.abort()
        self.setVisible(False)
