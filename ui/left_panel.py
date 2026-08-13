"""Panel izquierdo: zona de arrastre y cola de archivos."""
from __future__ import annotations
import os
from typing import Dict, List

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QColor, QPainter, QBrush, QPen, QDragEnterEvent, QDropEvent,
)
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget, QFrame,
)

from core.models import (
    FileItem, FileKind, FileStatus, classify_file, expand_paths, file_dialog_filter,
)
from ui import theme as T
from ui.widgets import Panel, SectionLabel, make_btn


class LeftPanel(QWidget):
    files_added   = pyqtSignal(list)   # list[str]
    file_selected = pyqtSignal(int)
    file_removed  = pyqtSignal(int)
    file_retried  = pyqtSignal(int)
    clear_all     = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(236)
        self.setMaximumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        # ── Entrada ──────────────────────────────────────────────────
        input_panel = Panel(padded=True)
        input_panel.layout().addWidget(SectionLabel("Entrada"))
        input_panel.layout().addSpacing(6)

        self.dropzone = Dropzone()
        self.dropzone.files_dropped.connect(self.files_added)
        input_panel.layout().addWidget(self.dropzone)
        root.addWidget(input_panel)

        # ── Cola ─────────────────────────────────────────────────────
        self.queue_panel = Panel(padded=True)
        self.queue_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        clear_btn = make_btn("Vaciar", kind="subtle")
        clear_btn.setFixedHeight(22)
        clear_btn.clicked.connect(self.clear_all)
        self._section = SectionLabel("Cola · 0", clear_btn)
        self.queue_panel.layout().addWidget(self._section)
        self._section_label = self._section.findChild(QLabel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._rows_lay = QVBoxLayout(inner)
        self._rows_lay.setContentsMargins(0, 4, 4, 0)
        self._rows_lay.setSpacing(5)

        self._empty_lbl = QLabel("Aún no hay archivos.\nArrástralos arriba para empezar.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(
            f"background: transparent; font-size: 11.5px; color: {T.DIM}; padding: 24px 8px;"
        )
        self._rows_lay.addWidget(self._empty_lbl)
        self._rows_lay.addStretch()

        scroll.setWidget(inner)
        self.queue_panel.layout().addWidget(scroll, stretch=1)
        root.addWidget(self.queue_panel, stretch=1)

        self._rows: Dict[int, FileRow] = {}
        self._selected: int | None = None

    # ── API pública ──────────────────────────────────────────────────────────
    def add_file(self, item: FileItem) -> None:
        row = FileRow(item)
        row.clicked.connect(self._on_row_clicked)
        row.removed.connect(self.file_removed)
        row.retried.connect(self.file_retried)
        self._rows[item.id] = row
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)
        self._refresh_header()

    def update_file(self, item: FileItem) -> None:
        row = self._rows.get(item.id)
        if row is not None:
            row.update_item(item)

    def remove_file(self, file_id: int) -> None:
        row = self._rows.pop(file_id, None)
        if row is not None:
            self._rows_lay.removeWidget(row)
            # Sin setParent(None) la fila sigue visible hasta que corre
            # deleteLater(), y se ve un hueco fantasma en la cola.
            row.setParent(None)
            row.deleteLater()
        if self._selected == file_id:
            self._selected = None
        self._refresh_header()

    def clear_files(self) -> None:
        for row in self._rows.values():
            self._rows_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self._selected = None
        self._refresh_header()

    def select_file(self, file_id: int) -> None:
        self._selected = file_id
        for fid, row in self._rows.items():
            row.set_selected(fid == file_id)

    def _on_row_clicked(self, file_id: int) -> None:
        self.select_file(file_id)
        self.file_selected.emit(file_id)

    def _refresh_header(self) -> None:
        count = len(self._rows)
        if self._section_label is not None:
            self._section_label.setText(f"COLA · {count}")
        self._empty_lbl.setVisible(count == 0)


# ─────────────────────────────────────────────────────────────────────────────
class Dropzone(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._hovering = False
        self.setMinimumHeight(134)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 16, 14, 16)
        lay.setSpacing(9)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon = QLabel("↑")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setFixedSize(38, 38)
        self._icon.setStyleSheet(f"""
            background: {T.ELEV};
            border: 1px solid {T.LINE};
            border-radius: 10px;
            color: {T.FG2};
            font-size: 18px;
            font-weight: 300;
        """)
        lay.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Arrastra archivos aquí")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"background: transparent; font-size: 13px; font-weight: 500; color: {T.FG};"
        )
        lay.addWidget(title)

        hint = QLabel("Audio · Video · Imágenes · PDF\nTambién carpetas completas")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"background: transparent; font-size: 10.5px; color: {T.MUTED}; line-height: 1.5;"
        )
        lay.addWidget(hint)

        self._btn = make_btn("Elegir archivos", kind="ghost_sm")
        self._btn.setFixedHeight(28)
        self._btn.clicked.connect(self._open_dialog)
        lay.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._update_style()

    def _update_style(self) -> None:
        border = T.ACCENT if self._hovering else T.LINE
        bg = T.ACCENT_SOFT if self._hovering else T.PANEL2
        self.setStyleSheet(f"""
            Dropzone {{
                background: {bg};
                border: 1.5px dashed {border};
                border-radius: {T.R_LG}px;
            }}
        """)

    def _open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Elegir archivos", "", file_dialog_filter()
        )
        if paths:
            self.files_dropped.emit(paths)

    # ── Arrastrar y soltar ───────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._hovering = True
            self._update_style()
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, _) -> None:
        self._hovering = False
        self._update_style()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hovering = False
        self._update_style()
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        # Soltar una carpeta agrega todo lo soportado que tenga dentro.
        paths = expand_paths(paths)
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()


# ─────────────────────────────────────────────────────────────────────────────
_KIND_ICONS = {
    FileKind.AUDIO: ("♪", T.ACCENT, T.ACCENT_SOFT),
    FileKind.VIDEO: ("▶", T.WARN,   T.WARN_SOFT),
    FileKind.IMAGE: ("▤", T.INFO,   T.INFO_SOFT),
    FileKind.PDF:   ("▦", T.DANGER, T.DANGER_SOFT),
}

_STATUS_COLORS = {
    FileStatus.PENDING:    T.DIM,
    FileStatus.PROCESSING: T.WARN,
    FileStatus.DONE:       T.ACCENT,
    FileStatus.ERROR:      T.DANGER,
}


class FileRow(QFrame):
    clicked = pyqtSignal(int)
    removed = pyqtSignal(int)
    retried = pyqtSignal(int)

    def __init__(self, item: FileItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)

        root = QVBoxLayout(self)
        root.setContentsMargins(9, 7, 8, 6)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        glyph, color, background = _KIND_ICONS[item.kind]
        self._icon = QLabel(glyph)
        self._icon.setFixedSize(21, 21)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet(f"""
            background: {background}; color: {color};
            border-radius: 6px; font-size: 11px;
        """)
        top.addWidget(self._icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)

        self._name = QLabel(item.name)
        self._name.setStyleSheet(
            f"background: transparent; font-size: 11.5px; color: {T.FG};"
        )
        # Nombres largos se recortan en vez de estirar la fila.
        self._name.setMinimumWidth(1)
        self._name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        text_col.addWidget(self._name)

        self._meta = QLabel("")
        self._meta.setStyleSheet(
            f"background: transparent; font-size: 10px; color: {T.MUTED};"
        )
        text_col.addWidget(self._meta)
        top.addLayout(text_col, stretch=1)

        self._retry_btn = _icon_btn("↻", T.WARN, "Reintentar este archivo")
        self._retry_btn.clicked.connect(lambda: self.retried.emit(self._item.id))
        self._retry_btn.setVisible(False)
        top.addWidget(self._retry_btn)

        self._close_btn = _icon_btn("✕", T.DANGER, "Quitar de la cola")
        self._close_btn.clicked.connect(lambda: self.removed.emit(self._item.id))
        top.addWidget(self._close_btn)

        root.addLayout(top)

        self._bar = RowProgress()
        root.addWidget(self._bar)

        self.update_item(item)

    def update_item(self, item: FileItem) -> None:
        self._item = item
        self._name.setText(_elide(item.name, 30))
        self._name.setToolTip(item.path)

        color = _STATUS_COLORS[item.status]
        if item.status == FileStatus.ERROR:
            detail = (item.error or "Error").splitlines()[0]
            self._meta.setText(_elide(detail, 34))
            self._meta.setToolTip(item.error or "")
        elif item.status == FileStatus.PROCESSING:
            label = item.stage or "Procesando…"
            self._meta.setText(f"{label}  {int(item.progress * 100)}%")
            self._meta.setToolTip("")
        elif item.status == FileStatus.DONE:
            words = len((item.result or "").split())
            self._meta.setText(f"Listo · {words:,} palabras".replace(",", "."))
            self._meta.setToolTip("")
        else:
            self._meta.setText(f"{item.kind.value.capitalize()} · {item.size_str}")
            self._meta.setToolTip("")

        self._meta.setStyleSheet(
            f"background: transparent; font-size: 10px; color: {color};"
        )

        self._bar.set_state(item.progress, item.status)
        self._retry_btn.setVisible(item.status == FileStatus.ERROR)
        self._apply_style()

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._apply_style()

    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(f"""
                FileRow {{
                    background: {T.ACCENT_SOFT};
                    border: 1px solid {T.ACCENT_LINE};
                    border-radius: 9px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                FileRow {{
                    background: {T.PANEL2};
                    border: 1px solid {T.LINE};
                    border-radius: 9px;
                }}
                FileRow:hover {{ background: {T.ELEV}; }}
            """)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._item.id)


class RowProgress(QWidget):
    """Barra de progreso individual de un archivo de la cola."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._progress = 0.0
        self._status = FileStatus.PENDING

    def set_state(self, progress: float, status: FileStatus) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self._status = status
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(T.BG)))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        if self._status == FileStatus.ERROR:
            p.setBrush(QBrush(QColor(T.DANGER)))
            p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
            p.end()
            return

        if self._progress <= 0:
            p.end()
            return

        color = T.ACCENT if self._status == FileStatus.DONE else T.WARN
        p.setBrush(QBrush(QColor(color)))
        p.drawRoundedRect(QRectF(0, 0, w * self._progress, h), h / 2, h / 2)
        p.end()


def _icon_btn(glyph: str, hover_color: str, tooltip: str):
    """Botón compacto de icono para las filas de la cola."""
    from PyQt6.QtWidgets import QPushButton
    btn = QPushButton(glyph)
    btn.setFixedSize(21, 21)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {T.MUTED};
            border: none;
            border-radius: 5px;
            font-size: 13px;
            font-weight: 600;
            padding: 0;
        }}
        QPushButton:hover {{ background: {T.ELEV}; color: {hover_color}; }}
        QPushButton:pressed {{ background: {T.LINE}; }}
    """)
    return btn


def _elide(text: str, limit: int) -> str:
    """Recorta por el medio, que conserva la extensión visible."""
    if len(text) <= limit:
        return text
    keep = (limit - 1) // 2
    return f"{text[:keep]}…{text[-keep:]}"
