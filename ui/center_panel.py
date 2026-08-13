"""Panel central: vista previa de los resultados.

Las tres pestañas producen salidas realmente distintas: «Formateado» agrupa en
párrafos, «Texto plano» entrega el texto corrido para copiar y pegar, y «JSON»
expone los segmentos con sus tiempos.
"""
from __future__ import annotations
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget, QFrame,
)

from core.models import AppConfig, FileItem, FileKind, FileStatus
from core import formatter as F
from ui import theme as T
from ui.widgets import Panel, SegmentedTabs, make_btn, vdivider

_KIND_TAGS = {
    FileKind.AUDIO: "AUDIO",
    FileKind.VIDEO: "VIDEO",
    FileKind.IMAGE: "IMAGEN",
    FileKind.PDF:   "PDF",
}

# Un QLabel con ajuste de línea recalcula todo el texto en cada redimensionado.
# Con la transcripción de una reunión de dos horas (~120 000 caracteres) eso hace
# que arrastrar el borde de la ventana se sienta pesado, así que la vista previa
# se corta. El texto completo sigue íntegro al copiar y al exportar.
_PREVIEW_LIMIT = 20_000


class CenterPanel(QWidget):
    copied = pyqtSignal(str)   # mensaje para el registro

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._items: List[FileItem] = []
        self._focus_id: Optional[int] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = Panel(padded=False)
        root.addWidget(card)

        # ── Cabecera ─────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet(f"border-bottom: 1px solid {T.LINE};")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(14, 0, 14, 0)
        header_row.setSpacing(9)

        self._view_tabs = SegmentedTabs(
            [("formatted", "Formateado"), ("plain", "Texto plano"), ("json", "JSON")],
            initial="formatted",
        )
        self._view_tabs.changed.connect(lambda _: self.refresh())
        header_row.addWidget(self._view_tabs)

        self._divider = vdivider()
        header_row.addWidget(self._divider)

        self._filter_tabs = SegmentedTabs(
            [("all", "Todo"), ("speech", "Voz"), ("visual", "OCR")],
            initial="all",
        )
        self._filter_tabs.changed.connect(lambda _: self.refresh())
        header_row.addWidget(self._filter_tabs)

        header_row.addStretch()

        self._stats = QLabel("0 palabras · 0 fuentes")
        self._stats.setStyleSheet(
            f"background: transparent; font-size: 11px; color: {T.MUTED}; "
            f"font-family: Consolas, monospace;"
        )
        header_row.addWidget(self._stats)

        self._copy_all_btn = make_btn("Copiar todo", kind="subtle")
        self._copy_all_btn.clicked.connect(self._copy_all)
        header_row.addWidget(self._copy_all_btn)

        card.layout().addWidget(header)

        # ── Contenido ────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {T.PANEL}; }}")

        content = QWidget()
        content.setStyleSheet(f"background: {T.PANEL};")
        self._content_lay = QVBoxLayout(content)
        self._content_lay.setContentsMargins(26, 20, 26, 20)
        self._content_lay.setSpacing(0)

        self._preview_header = QWidget()
        head_row = QHBoxLayout(self._preview_header)
        head_row.setContentsMargins(0, 0, 0, 20)
        head_row.setSpacing(11)
        title = QLabel("Vista previa")
        title.setStyleSheet(
            f"background: transparent; font-size: 21px; font-weight: 700; "
            f"color: {T.FG}; letter-spacing: -0.3px;"
        )
        head_row.addWidget(title)
        self._head_sub = QLabel("Se actualiza al completar cada archivo")
        self._head_sub.setStyleSheet(
            f"background: transparent; font-size: 12px; color: {T.MUTED};"
        )
        head_row.addWidget(self._head_sub)
        head_row.addStretch()
        self._content_lay.addWidget(self._preview_header)

        self._blocks = QWidget()
        self._blocks.setStyleSheet(f"background: {T.PANEL};")
        self._blocks_lay = QVBoxLayout(self._blocks)
        self._blocks_lay.setContentsMargins(0, 0, 0, 0)
        self._blocks_lay.setSpacing(12)
        self._content_lay.addWidget(self._blocks)

        self._empty = EmptyState()
        self._content_lay.addWidget(self._empty)
        self._content_lay.addStretch()

        self._scroll.setWidget(content)
        card.layout().addWidget(self._scroll, stretch=1)

    def resizeEvent(self, event) -> None:
        """Oculta lo secundario antes que dejar que la cabecera se desborde."""
        super().resizeEvent(event)
        width = self.width()
        self._stats.setVisible(width >= 700)
        self._copy_all_btn.setVisible(width >= 560)
        show_filter = width >= 480
        self._filter_tabs.setVisible(show_filter)
        self._divider.setVisible(show_filter)
        self._head_sub.setVisible(width >= 620)

    # ── API pública ──────────────────────────────────────────────────────────
    def update_items(self, items: List[FileItem]) -> None:
        self._items = items
        self.refresh()

    def focus_file(self, file_id: int) -> None:
        """Resalta un archivo concreto y desplaza la vista hasta él."""
        self._focus_id = file_id
        self.refresh()

    def refresh(self) -> None:
        self._rebuild()
        self._update_stats()

    # ── Interno ──────────────────────────────────────────────────────────────
    def _visible_items(self) -> List[FileItem]:
        done = [f for f in self._items if f.segments]
        filt = self._filter_tabs.value
        if filt == "speech":
            done = [f for f in done if f.kind.is_speech]
        elif filt == "visual":
            done = [f for f in done if f.kind.is_visual]
        return done

    def _render(self, item: FileItem) -> str:
        view = self._view_tabs.value
        if view == "plain":
            return F.to_plain(item.segments)
        if view == "json":
            return F.to_json(item)
        return F.to_document(
            item.segments,
            include_timestamps=self._config.include_timestamps,
            include_speakers=self._config.include_speakers,
            is_visual=item.kind.is_visual,
        )

    def _rebuild(self) -> None:
        while self._blocks_lay.count():
            child = self._blocks_lay.takeAt(0)
            widget = child.widget()
            if widget is not None:
                # setParent(None) lo saca de la pantalla en el acto. Con solo
                # deleteLater() el widget sigue dibujándose hasta el siguiente
                # ciclo del bucle de eventos y se superpone al contenido nuevo.
                widget.setParent(None)
                widget.deleteLater()

        done = self._visible_items()
        pending = [f for f in self._items
                   if f.status in (FileStatus.PENDING, FileStatus.PROCESSING)]
        errors = [f for f in self._items if f.status == FileStatus.ERROR]

        has_content = bool(done or pending or errors)
        self._empty.setVisible(not has_content)
        self._preview_header.setVisible(has_content)

        monospace = self._view_tabs.value == "json"
        target: Optional[QWidget] = None

        for item in done:
            block = ResultBlock(item, self._render(item), monospace=monospace)
            block.copied.connect(self.copied)
            self._blocks_lay.addWidget(block)
            if item.id == self._focus_id:
                target = block

        for item in errors:
            self._blocks_lay.addWidget(ErrorBlock(item))

        if pending:
            self._blocks_lay.addWidget(PendingBlock([f.name for f in pending]))

        if target is not None:
            self._scroll.ensureWidgetVisible(target, 0, 40)
            self._focus_id = None

    def _update_stats(self) -> None:
        done = self._visible_items()
        words = sum(len(F.to_plain(f.segments).split()) for f in done)
        label = f"{words:,} palabras · {len(done)} fuente(s)".replace(",", ".")
        self._stats.setText(label)

    def _copy_all(self) -> None:
        from PyQt6.QtWidgets import QApplication
        items = self._visible_items()
        if not items:
            return
        parts = [f"═══ {item.name} ═══\n\n{self._render(item)}" for item in items]
        QApplication.clipboard().setText("\n\n\n".join(parts))
        self.copied.emit(f"Copiado el texto de {len(items)} archivo(s)")


# ─────────────────────────────────────────────────────────────────────────────
class ResultBlock(QWidget):
    copied = pyqtSignal(str)

    def __init__(self, item: FileItem, text: str, monospace: bool = False, parent=None):
        super().__init__(parent)
        self._text = text
        self._item = item

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 24)
        lay.setSpacing(0)

        header = QWidget()
        header.setStyleSheet(f"border-bottom: 1px solid {T.LINE_S};")
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 9)
        row.setSpacing(8)

        name = QLabel(item.name)
        name.setStyleSheet(
            f"background: transparent; font-family: Consolas, monospace; "
            f"font-size: 12px; color: {T.FG};"
        )
        row.addWidget(name)

        tag = QLabel(_KIND_TAGS[item.kind])
        tag.setStyleSheet(f"""
            font-size: 9px; font-weight: 600; padding: 2px 6px;
            background: {T.PANEL2}; color: {T.MUTED};
            border: 1px solid {T.LINE}; border-radius: 4px;
        """)
        row.addWidget(tag)

        if item.duration:
            dur = QLabel(F.format_timestamp(item.duration))
            dur.setStyleSheet(
                f"background: transparent; font-size: 10px; color: {T.DIM}; "
                f"font-family: Consolas, monospace;"
            )
            row.addWidget(dur)

        row.addStretch()

        copy_btn = make_btn("Copiar", kind="subtle")
        copy_btn.setFixedHeight(23)
        copy_btn.clicked.connect(self._copy)
        row.addWidget(copy_btn)

        lay.addWidget(header)
        lay.addSpacing(12)

        shown = text
        truncated = len(text) > _PREVIEW_LIMIT
        if truncated:
            cut = text.rfind(" ", 0, _PREVIEW_LIMIT)
            shown = text[:cut if cut > 0 else _PREVIEW_LIMIT]

        body = QLabel(shown or "(sin texto)")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        if monospace:
            body.setStyleSheet(
                f"background: transparent; font-family: Consolas, monospace; "
                f"font-size: 11.5px; color: {T.FG2};"
            )
        else:
            body.setStyleSheet(
                f"background: transparent; font-size: 13.5px; color: {T.FG}; line-height: 1.7;"
            )
        lay.addWidget(body)

        if truncated:
            note = QLabel(
                f"Vista previa recortada a {_PREVIEW_LIMIT:,} de {len(text):,} caracteres. "
                f"«Copiar» y el archivo exportado incluyen el texto completo."
                .replace(",", ".")
            )
            note.setWordWrap(True)
            note.setStyleSheet(f"""
                background: {T.PANEL2}; color: {T.MUTED};
                border: 1px solid {T.LINE}; border-radius: 7px;
                font-size: 11px; padding: 8px 10px;
            """)
            lay.addSpacing(10)
            lay.addWidget(note)

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._text)
        self.copied.emit(f"Copiado el texto de {self._item.name}")


class ErrorBlock(QFrame):
    def __init__(self, item: FileItem, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            ErrorBlock {{
                background: {T.DANGER_SOFT};
                border: 1px solid {T.DANGER};
                border-radius: {T.R_LG}px;
            }}
        """)
        # El margen inferior va por fuera del marco para no cortar el borde.
        self.setContentsMargins(0, 0, 0, 0)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 13, 16, 14)
        lay.setSpacing(5)

        title = QLabel(f"No se pudo procesar {item.name}")
        title.setStyleSheet(
            f"background: transparent; font-size: 12.5px; font-weight: 600; color: {T.DANGER};"
        )
        lay.addWidget(title)

        detail = QLabel(item.error or "Error desconocido")
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail.setStyleSheet(
            f"background: transparent; font-size: 11.5px; color: {T.FG2}; line-height: 1.5;"
        )
        lay.addWidget(detail)


class PendingBlock(QFrame):
    def __init__(self, names: List[str], parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            PendingBlock {{
                background: {T.PANEL2};
                border: 1px dashed {T.LINE};
                border-radius: {T.R_LG}px;
            }}
        """)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(10)

        row.addWidget(_PulsingDot())

        shown = ", ".join(names[:3])
        if len(names) > 3:
            shown += f" y {len(names) - 3} más"
        label = QLabel(f"En cola: {shown}")
        label.setWordWrap(True)
        label.setStyleSheet(f"background: transparent; font-size: 12px; color: {T.FG2};")
        row.addWidget(label, stretch=1)


class _PulsingDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self._opacity = 1.0
        self._direction = -1
        from PyQt6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

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
        color = QColor(T.WARN)
        color.setAlphaF(self._opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(0, 0, 9, 9)
        p.end()


class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        lay.setContentsMargins(0, 60, 0, 60)

        icon = QLabel("◎")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"background: transparent; font-size: 34px; color: {T.DIM};")
        lay.addWidget(icon)

        message = QLabel(
            "Arrastra un archivo y pulsa «Iniciar procesamiento».\n"
            "El texto aparecerá aquí."
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet(
            f"background: transparent; font-size: 13px; color: {T.MUTED}; line-height: 1.7;"
        )
        lay.addWidget(message)
