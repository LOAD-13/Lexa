"""Pie: progreso global del lote, contadores, ETA y registro de actividad.

El progreso global suma el avance fraccional del archivo en curso, no solo los
archivos terminados. Antes saltaba de 0 % a 50 % a 100 % con dos archivos.
"""
from __future__ import annotations
import time
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QBrush, QLinearGradient
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from core.models import FileItem, FileStatus, LogEntry
from ui import theme as T

_MAX_LOG_ROWS = 400


class Footer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(112)
        self.setMaximumHeight(320)
        self.setStyleSheet(f"""
            Footer {{
                background: {T.PANEL};
                border-top: 1px solid {T.LINE};
            }}
        """)

        self._started_at: Optional[float] = None
        self._last_progress = 0.0

        grid = QHBoxLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # ── Izquierda: progreso ──────────────────────────────────────
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left.setFixedWidth(330)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(16, 12, 16, 12)
        left_lay.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(9)

        self._dot = _PulseDot()
        status_row.addWidget(self._dot)

        self._status = QLabel("Listo")
        self._status.setStyleSheet(
            f"background: transparent; font-size: 12px; font-weight: 500; color: {T.FG};"
        )
        status_row.addWidget(self._status)
        status_row.addStretch()

        self._eta = QLabel("")
        self._eta.setStyleSheet(
            f"background: transparent; font-size: 10.5px; color: {T.MUTED}; "
            f"font-family: Consolas, monospace;"
        )
        status_row.addWidget(self._eta)

        self._pct = QLabel("0%")
        self._pct.setStyleSheet(
            f"background: transparent; font-family: Consolas, monospace; "
            f"font-size: 11px; color: {T.FG2};"
        )
        status_row.addWidget(self._pct)
        left_lay.addLayout(status_row)

        self._bar = ProgressBar()
        left_lay.addWidget(self._bar)

        counters = QHBoxLayout()
        counters.setSpacing(13)
        self._done_counter  = _counter("0", T.ACCENT, "completados")
        self._proc_counter  = _counter("0", T.WARN,   "procesando")
        self._queue_counter = _counter("0", T.FG2,    "en cola")
        self._err_counter   = _counter("0", T.DANGER, "con error")
        for widget, _ in (self._done_counter, self._proc_counter,
                          self._queue_counter, self._err_counter):
            counters.addWidget(widget)
        counters.addStretch()
        left_lay.addLayout(counters)
        left_lay.addStretch()

        grid.addWidget(left)

        separator = QWidget()
        separator.setFixedWidth(1)
        separator.setStyleSheet(f"background: {T.LINE};")
        grid.addWidget(separator)

        self._log = LogViewer()
        grid.addWidget(self._log, stretch=1)

    # ── API pública ──────────────────────────────────────────────────────────
    def mark_started(self) -> None:
        self._started_at = time.monotonic()
        self._last_progress = 0.0

    def mark_stopped(self) -> None:
        self._started_at = None
        self._eta.setText("")

    def update_files(self, items: List[FileItem]) -> None:
        if not items:
            self._reset()
            return

        total = len(items)
        done = sum(1 for f in items if f.status == FileStatus.DONE)
        processing = [f for f in items if f.status == FileStatus.PROCESSING]
        errors = sum(1 for f in items if f.status == FileStatus.ERROR)
        queued = total - done - len(processing) - errors

        # El avance del archivo en curso cuenta como fracción, no como medio archivo.
        partial = sum(f.progress for f in processing)
        overall = (done + errors + partial) / total

        self._bar.set_progress(overall)
        self._pct.setText(f"{int(overall * 100)}%")
        self._last_progress = overall

        self._done_counter[1].setText(str(done))
        self._proc_counter[1].setText(str(len(processing)))
        self._queue_counter[1].setText(str(max(0, queued)))
        self._err_counter[1].setText(str(errors))
        self._err_counter[0].setVisible(errors > 0)

        if processing:
            current = processing[0]
            self._status.setText(f"Procesando {done + errors + 1} de {total}")
            self._status.setToolTip(current.name)
            self._dot.set_active(True)
            self._update_eta(overall)
        elif done + errors >= total:
            self._status.setText("Completado" if not errors else f"Completado · {errors} error(es)")
            self._dot.set_active(False)
            self._eta.setText("")
        else:
            self._status.setText("Listo")
            self._dot.set_active(False)
            self._eta.setText("")

    def add_log(self, entry: LogEntry) -> None:
        self._log.add_entry(entry)

    def clear_logs(self) -> None:
        self._log.clear()

    # ── Interno ──────────────────────────────────────────────────────────────
    def _update_eta(self, progress: float) -> None:
        """Estima el tiempo restante extrapolando el ritmo observado."""
        if self._started_at is None or progress <= 0.02:
            self._eta.setText("")
            return
        elapsed = time.monotonic() - self._started_at
        remaining = elapsed / progress - elapsed
        if remaining < 1 or remaining > 86400:
            self._eta.setText("")
            return
        self._eta.setText(f"~{_duration(remaining)} restante")

    def _reset(self) -> None:
        self._bar.set_progress(0)
        self._pct.setText("0%")
        self._status.setText("Listo")
        self._status.setToolTip("")
        self._eta.setText("")
        for _, value in (self._done_counter, self._proc_counter,
                         self._queue_counter, self._err_counter):
            value.setText("0")
        self._err_counter[0].setVisible(False)
        self._dot.set_active(False)


# ─────────────────────────────────────────────────────────────────────────────
class ProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0.0
        self.setFixedHeight(6)

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(T.BG)))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        fill = int(w * self._progress)
        if fill > 0:
            grad = QLinearGradient(0, 0, max(fill, 1), 0)
            grad.setColorAt(0, QColor(T.ACCENT))
            grad.setColorAt(1, QColor("#8fd9b4"))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, fill, h, 3, 3)
        p.end()


class LogViewer(QWidget):
    _COLORS = {"info": T.INFO, "ok": T.ACCENT, "warn": T.WARN, "err": T.DANGER}
    _LABELS = {"info": "INFO", "ok": "OK", "warn": "WARN", "err": "ERR"}

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)

        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title = QLabel("REGISTRO")
        title.setStyleSheet(
            f"background: transparent; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 0.8px; color: {T.MUTED};"
        )
        header_row.addWidget(title)
        header_row.addStretch()
        self._count = QLabel("0 entradas")
        self._count.setStyleSheet(
            f"background: transparent; font-size: 10.5px; color: {T.DIM}; "
            f"font-family: Consolas, monospace;"
        )
        header_row.addWidget(self._count)
        lay.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {T.BG};
                border: 1px solid {T.LINE};
                border-radius: {T.R_SM}px;
            }}
        """)

        inner = QWidget()
        inner.setStyleSheet(f"background: {T.BG};")
        self._rows = QVBoxLayout(inner)
        self._rows.setContentsMargins(10, 6, 10, 6)
        self._rows.setSpacing(1)
        self._rows.addStretch()
        self._scroll.setWidget(inner)
        lay.addWidget(self._scroll, stretch=1)

        self._entries = 0

    def add_entry(self, entry: LogEntry) -> None:
        self._entries += 1
        self._count.setText(f"{self._entries} entradas")

        # Sin tope, un lote largo acumula miles de widgets y la app se arrastra.
        while self._rows.count() - 1 > _MAX_LOG_ROWS:
            item = self._rows.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 1, 0, 1)
        row_lay.setSpacing(9)

        timestamp = QLabel(entry.timestamp)
        timestamp.setFixedWidth(56)
        timestamp.setStyleSheet(
            f"background: transparent; font-family: Consolas, monospace; "
            f"font-size: 10.5px; color: {T.DIM};"
        )
        row_lay.addWidget(timestamp)

        color = self._COLORS.get(entry.level, T.MUTED)
        level = QLabel(self._LABELS.get(entry.level, entry.level.upper()))
        level.setFixedWidth(34)
        level.setStyleSheet(
            f"background: transparent; font-family: Consolas, monospace; "
            f"font-size: 9.5px; font-weight: 600; color: {color};"
        )
        row_lay.addWidget(level)

        text_color = color if entry.level in ("warn", "err") else T.FG2
        message = QLabel(entry.message)
        message.setWordWrap(True)
        message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message.setStyleSheet(
            f"background: transparent; font-family: Consolas, monospace; "
            f"font-size: 10.5px; color: {text_color};"
        )
        row_lay.addWidget(message, stretch=1)

        self._rows.insertWidget(self._rows.count() - 1, row)
        # El scroll se hace tras el ciclo de layout; si no, maximum() aún es el viejo.
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        self._entries = 0
        self._count.setText("0 entradas")
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


def _counter(initial: str, color: str, label: str):
    widget = QWidget()
    widget.setStyleSheet("background: transparent;")
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    value = QLabel(initial)
    value.setStyleSheet(
        f"background: transparent; font-size: 11px; font-weight: 600; color: {color};"
    )
    text = QLabel(label)
    text.setStyleSheet(f"background: transparent; font-size: 10.5px; color: {T.MUTED};")
    row.addWidget(value)
    row.addWidget(text)
    return widget, value


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


class _PulseDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self._active = False
        self._opacity = 1.0
        self._direction = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_active(self, value: bool) -> None:
        if value == self._active:
            return
        self._active = value
        if value:
            self._timer.start(45)
        else:
            self._timer.stop()
            self._opacity = 1.0
        self.update()

    def _tick(self) -> None:
        self._opacity += self._direction * 0.05
        if self._opacity <= 0.3:
            self._direction = 1
        elif self._opacity >= 1.0:
            self._direction = -1
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(T.WARN if self._active else T.DIM)
        color.setAlphaF(self._opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(0, 0, 8, 8)
        p.end()
