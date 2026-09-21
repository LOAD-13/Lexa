"""Modal bloqueante de descarga de modelos.

Aparece solo cuando falta algun modelo. Una vez descargados quedan en
%LOCALAPPDATA%\\Lexa\\models y el modal no vuelve a mostrarse. La ventana
principal queda inaccesible mientras dura la descarga, que es justo lo que se
quiere: la app no sirve de nada sin los modelos.
"""
from __future__ import annotations
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush, QLinearGradient
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QMessageBox,
)

from core import downloader as D
from core.downloader import ModelSpec
from ui import theme as T
from ui.widgets import make_btn


def required_specs(config) -> List[ModelSpec]:
    """Modelos que faltan para la configuracion actual."""
    from core.models import WHISPER_MODELS

    specs: List[ModelSpec] = []

    label, size = next(
        ((lbl, sz) for val, lbl, sz in WHISPER_MODELS if val == config.whisper_model),
        (config.whisper_model, "?"),
    )
    specs.append(D.whisper_spec(config.whisper_model, label, size))
    specs.append(D.ocr_spec())
    if config.include_speakers:
        specs.extend(D.diarization_specs())

    return [s for s in specs if not D.is_present(s)]


class _DownloadThread(QThread):
    step_started = pyqtSignal(int, str)        # indice, etiqueta
    step_progress = pyqtSignal(int, int)       # bytes hechos, bytes totales
    failed = pyqtSignal(str)
    finished_ok = pyqtSignal()

    def __init__(self, specs: List[ModelSpec], parent=None):
        super().__init__(parent)
        self.specs = specs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            for index, spec in enumerate(self.specs):
                if self._cancel:
                    return
                self.step_started.emit(index, spec.label)
                D.fetch(
                    spec,
                    progress=lambda done, total: self.step_progress.emit(done, total),
                    should_cancel=lambda: self._cancel,
                )
        except D.DownloadCancelled:
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class SetupDialog(QDialog):
    """Descarga los modelos que falten. exec() devuelve Accepted si todo fue bien."""

    def __init__(self, specs: List[ModelSpec], parent=None):
        super().__init__(parent)
        self._specs = specs
        self._thread: Optional[_DownloadThread] = None
        self._current = 0
        self._failed = False

        self.setWindowTitle("Preparando Lexa")
        self.setModal(True)
        # Sin boton de cerrar: la descarga tiene que completarse o cancelarse
        # explicitamente, nunca quedar a medias por un clic accidental.
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setFixedSize(480, 260)
        self.setStyleSheet(f"QDialog {{ background: {T.PANEL}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22)
        root.setSpacing(0)

        title = QLabel("Preparando Lexa")
        title.setStyleSheet(
            f"background: transparent; font-size: 19px; font-weight: 700; color: {T.FG};"
        )
        root.addWidget(title)
        root.addSpacing(6)

        total_size = _humanize_total(specs)
        subtitle = QLabel(
            f"Se descargarán los modelos de inteligencia artificial "
            f"({total_size}).\nEsto ocurre una sola vez; los próximos arranques "
            f"serán inmediatos."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"background: transparent; font-size: 12px; color: {T.MUTED}; line-height: 1.5;"
        )
        root.addWidget(subtitle)
        root.addSpacing(22)

        self._step_lbl = QLabel("Conectando…")
        self._step_lbl.setStyleSheet(
            f"background: transparent; font-size: 13px; font-weight: 500; color: {T.FG};"
        )
        root.addWidget(self._step_lbl)
        root.addSpacing(8)

        self._bar = _Bar()
        root.addWidget(self._bar)
        root.addSpacing(8)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        self._bytes_lbl = QLabel("")
        self._bytes_lbl.setStyleSheet(
            f"background: transparent; font-size: 11px; color: {T.MUTED}; "
            f"font-family: Consolas, monospace;"
        )
        meta_row.addWidget(self._bytes_lbl)
        meta_row.addStretch()
        self._count_lbl = QLabel(f"0 / {len(specs)}")
        self._count_lbl.setStyleSheet(
            f"background: transparent; font-size: 11px; color: {T.DIM}; "
            f"font-family: Consolas, monospace;"
        )
        meta_row.addWidget(self._count_lbl)
        root.addLayout(meta_row)

        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()
        self._cancel_btn = make_btn("Cancelar", kind="ghost")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)
        self._retry_btn = make_btn("Reintentar", kind="primary")
        self._retry_btn.clicked.connect(self._on_retry)
        self._retry_btn.hide()
        btn_row.addWidget(self._retry_btn)
        root.addLayout(btn_row)

    # ── Ciclo de vida ────────────────────────────────────────────────────────
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._thread is None:
            self._start_thread()

    def _start_thread(self) -> None:
        previous = self._thread
        if previous is not None:
            previous.wait(2000)
            previous.deleteLater()
        self._thread = _DownloadThread(self._specs, self)
        self._thread.step_started.connect(self._on_step)
        self._thread.step_progress.connect(self._on_progress)
        self._thread.failed.connect(self._on_failed)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.start()

    def _on_step(self, index: int, label: str) -> None:
        self._current = index
        self._step_lbl.setText(f"Descargando {label}…")
        self._count_lbl.setText(f"{index + 1} / {len(self._specs)}")
        self._bar.set_progress(0.0)
        self._bytes_lbl.setText("")

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._bar.set_progress(done / total)
            self._bytes_lbl.setText(f"{_mb(done)} / {_mb(total)}")
        else:
            self._bar.set_indeterminate()
            self._bytes_lbl.setText(_mb(done))

    def _on_failed(self, message: str) -> None:
        # El modal se queda abierto: lo ya descargado sigue en disco y un reintento
        # retoma donde se quedó, en vez de obligar a repetir la sesión entera.
        self._failed = True
        self._bar.set_error()
        self._step_lbl.setText("La descarga falló")
        self._bytes_lbl.setText("")
        self._cancel_btn.setText("Cerrar")
        self._cancel_btn.setEnabled(True)
        self._retry_btn.show()
        QMessageBox.critical(self, "No se pudo descargar", message)

    def _on_retry(self) -> None:
        self._failed = False
        self._retry_btn.hide()
        self._cancel_btn.setText("Cancelar")
        self._cancel_btn.setEnabled(True)
        self._bar.set_progress(0.0)
        self._step_lbl.setText("Reintentando…")
        self._bytes_lbl.setText("")
        # Los modelos que ya bajaron se saltan solos: fetch() no hace nada si el
        # artefacto está presente.
        self._start_thread()

    def _on_finished(self) -> None:
        self._bar.set_progress(1.0)
        self._step_lbl.setText("Todo listo")
        self._count_lbl.setText(f"{len(self._specs)} / {len(self._specs)}")
        self.accept()

    def _on_cancel(self) -> None:
        if self._failed:
            # Aquí el botón dice «Cerrar»: el hilo ya terminó, no hay nada que cancelar.
            self.reject()
            return
        if self._thread and self._thread.isRunning():
            self._step_lbl.setText("Cancelando…")
            self._cancel_btn.setEnabled(False)
            self._thread.cancel()
            self._thread.wait(5000)
        self.reject()

    def reject(self) -> None:
        # Bloquea Escape mientras la descarga sigue viva.
        if self._thread and self._thread.isRunning() and not self._failed:
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(5000)
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
class _Bar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._progress = 0.0
        self._error = False
        self._indeterminate = False
        self._offset = 0.0
        self._timer = None

    def set_progress(self, value: float) -> None:
        self._stop_pulse()
        self._indeterminate = False
        self._error = False
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def set_error(self) -> None:
        self._stop_pulse()
        self._error = True
        self.update()

    def set_indeterminate(self) -> None:
        """Barra en movimiento cuando el servidor no informa el tamaño total."""
        if self._indeterminate:
            return
        self._indeterminate = True
        from PyQt6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(30)

    def _stop_pulse(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _pulse(self) -> None:
        self._offset = (self._offset + 0.012) % 1.0
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(T.BG)))
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        if self._error:
            p.setBrush(QBrush(QColor(T.DANGER)))
            p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
            p.end()
            return

        if self._indeterminate:
            band = w * 0.28
            x = (w + band) * self._offset - band
            p.setBrush(QBrush(QColor(T.ACCENT)))
            p.drawRoundedRect(int(max(0, x)), 0,
                              int(min(band, w - max(0, x))), h, h / 2, h / 2)
            p.end()
            return

        fill = int(w * self._progress)
        if fill > 0:
            grad = QLinearGradient(0, 0, max(fill, 1), 0)
            grad.setColorAt(0, QColor(T.ACCENT))
            grad.setColorAt(1, QColor("#8fd9b4"))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, fill, h, h / 2, h / 2)
        p.end()


def _mb(value: int) -> str:
    if value >= 1024 ** 3:
        return f"{value / 1024 ** 3:.2f} GB"
    return f"{value / 1024 ** 2:.1f} MB"


def _humanize_total(specs: List[ModelSpec]) -> str:
    return " + ".join(s.approx_size for s in specs) if specs else "0 MB"
