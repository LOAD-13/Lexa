"""Asistente Lexa: tour guiado con foco sobre los elementos de la interfaz.

Es una capa que cubre toda la ventana, oscurece el fondo y recorta un hueco
alrededor del widget que se esta explicando. Se lanza solo la primera vez y
queda disponible en el boton «?» de la barra superior.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QBrush, QPen, QPixmap, QFont,
)
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame

from ui import theme as T
from ui.widgets import make_btn
from core.paths import resource


@dataclass
class TourStep:
    title: str
    body: str
    # Se resuelve en el momento de mostrar el paso: el widget puede no existir
    # todavia o haber cambiado de posicion.
    target: Optional[Callable[[], Optional[QWidget]]] = None
    padding: int = 8


class TourOverlay(QWidget):
    """Capa a pantalla completa sobre la ventana principal."""

    finished = pyqtSignal()

    def __init__(self, steps: List[TourStep], parent: QWidget):
        super().__init__(parent)
        self._steps = steps
        self._index = 0
        self._hole = QRect()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._bubble = _Bubble(self)
        self._bubble.next_clicked.connect(self.next_step)
        self._bubble.back_clicked.connect(self.previous_step)
        self._bubble.skip_clicked.connect(self.finish)

        self.setGeometry(parent.rect())
        self.raise_()

    # ── Navegacion ───────────────────────────────────────────────────────────
    def start(self) -> None:
        self._index = 0
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        # Un tick de retraso: los widgets deben estar ya posicionados para que
        # mapTo() devuelva coordenadas correctas.
        QTimer.singleShot(0, self._apply_step)

    def next_step(self) -> None:
        if self._index >= len(self._steps) - 1:
            self.finish()
            return
        self._index += 1
        self._apply_step()

    def previous_step(self) -> None:
        if self._index == 0:
            return
        self._index -= 1
        self._apply_step()

    def finish(self) -> None:
        self.hide()
        self.finished.emit()

    # ── Pintado ──────────────────────────────────────────────────────────────
    def _apply_step(self) -> None:
        step = self._steps[self._index]
        self._hole = self._resolve_rect(step)
        self._bubble.set_step(
            step, self._index + 1, len(self._steps),
            is_first=self._index == 0,
            is_last=self._index == len(self._steps) - 1,
        )
        self._place_bubble()
        self.update()

    def _resolve_rect(self, step: TourStep) -> QRect:
        if step.target is None:
            return QRect()
        try:
            widget = step.target()
        except Exception:
            widget = None
        if widget is None or not widget.isVisible():
            return QRect()
        top_left = widget.mapTo(self.parentWidget(), QPoint(0, 0))
        rect = QRect(top_left, widget.size())
        return rect.adjusted(-step.padding, -step.padding, step.padding, step.padding)

    def _place_bubble(self) -> None:
        """Coloca la burbuja junto al hueco sin salirse de la ventana."""
        self._bubble.adjustSize()
        bw, bh = self._bubble.width(), self._bubble.height()
        margin = 14
        area = self.rect()

        if self._hole.isNull():
            x = (area.width() - bw) // 2
            y = (area.height() - bh) // 2
        else:
            # Preferir el lado con mas espacio libre.
            space_right = area.right() - self._hole.right()
            space_left = self._hole.left() - area.left()
            space_below = area.bottom() - self._hole.bottom()

            if space_right >= bw + margin:
                x = self._hole.right() + margin
                y = self._hole.center().y() - bh // 2
            elif space_left >= bw + margin:
                x = self._hole.left() - bw - margin
                y = self._hole.center().y() - bh // 2
            elif space_below >= bh + margin:
                x = self._hole.center().x() - bw // 2
                y = self._hole.bottom() + margin
            else:
                x = self._hole.center().x() - bw // 2
                y = self._hole.top() - bh - margin

        x = max(margin, min(x, area.width() - bw - margin))
        y = max(margin, min(y, area.height() - bh - margin))
        self._bubble.move(x, y)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        veil = QPainterPath()
        veil.addRect(QRectF(self.rect()))

        if not self._hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._hole), 12, 12)
            veil = veil.subtracted(hole)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(6, 7, 9, 215)))
        p.drawPath(veil)

        if not self._hole.isNull():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T.ACCENT), 2))
            p.drawRoundedRect(QRectF(self._hole), 12, 12)
        p.end()

    # ── Eventos ──────────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        # Un clic en cualquier parte oscurecida avanza; sobre el hueco no hace nada
        # para que el usuario pueda mirar el elemento resaltado.
        if not self._hole.contains(event.pos()):
            self.next_step()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Escape,):
            self.finish()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.next_step()
        elif key == Qt.Key.Key_Left:
            self.previous_step()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._apply_step()


# ─────────────────────────────────────────────────────────────────────────────
class _Bubble(QFrame):
    next_clicked = pyqtSignal()
    back_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(330)
        self.setStyleSheet(f"""
            _Bubble {{
                background: {T.PANEL};
                border: 1px solid {T.ACCENT_LINE};
                border-radius: 14px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(9)

        head.addWidget(_Avatar())

        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        name = QLabel("Lexa")
        name.setStyleSheet(
            f"background: transparent; font-size: 13px; font-weight: 600; color: {T.ACCENT};"
        )
        name_col.addWidget(name)
        self._counter = QLabel("")
        self._counter.setStyleSheet(
            f"background: transparent; font-size: 10px; color: {T.DIM};"
        )
        name_col.addWidget(self._counter)
        head.addLayout(name_col)
        head.addStretch()
        root.addLayout(head)
        root.addSpacing(13)

        self._title = QLabel("")
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            f"background: transparent; font-size: 15px; font-weight: 600; color: {T.FG};"
        )
        root.addWidget(self._title)
        root.addSpacing(6)

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            f"background: transparent; font-size: 12.5px; color: {T.FG2}; line-height: 1.55;"
        )
        root.addWidget(self._body)
        root.addSpacing(16)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        # Los estilos compartidos usan padding vertical de 9 px; con una altura
        # fija de 28 px el texto queda recortado. Aquí se define el padding a
        # medida en vez de forzar la altura.
        self._skip = _tour_btn("Saltar", "subtle")
        self._skip.clicked.connect(self.skip_clicked)
        actions.addWidget(self._skip)
        actions.addStretch()

        self._back = _tour_btn("Atrás", "ghost")
        self._back.clicked.connect(self.back_clicked)
        actions.addWidget(self._back)

        self._next = _tour_btn("Siguiente", "primary")
        self._next.clicked.connect(self.next_clicked)
        actions.addWidget(self._next)

        root.addLayout(actions)

    def set_step(self, step: TourStep, number: int, total: int,
                 is_first: bool, is_last: bool) -> None:
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._counter.setText(f"Paso {number} de {total}")
        self._back.setVisible(not is_first)
        self._next.setText("Empezar a usar Lexa" if is_last else "Siguiente")
        self._skip.setVisible(not is_last)

        # Las etiquetas con ajuste de línea solo saben su alto una vez fijado el
        # ancho. Sin calcularlo a mano, adjustSize() mide con el ancho natural
        # del texto y la burbuja sale más baja de lo necesario.
        inner = self.width() - 36   # márgenes izquierdo y derecho
        for label in (self._title, self._body):
            label.setFixedHeight(label.heightForWidth(inner))

        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()


def _tour_btn(label: str, kind: str):
    """Botón del tour con padding horizontal amplio y vertical ajustado."""
    from PyQt6.QtWidgets import QPushButton
    btn = QPushButton(label)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind == "primary":
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.ACCENT}; color: {T.ACCENT_TEXT};
                border: 1px solid transparent; border-radius: 7px;
                font-size: 12px; font-weight: 600; padding: 7px 14px;
            }}
            QPushButton:hover {{ background: #7fd9a9; }}
        """)
    elif kind == "ghost":
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.PANEL2}; color: {T.FG};
                border: 1px solid {T.LINE}; border-radius: 7px;
                font-size: 12px; font-weight: 500; padding: 7px 12px;
            }}
            QPushButton:hover {{ background: {T.ELEV}; }}
        """)
    else:
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T.MUTED};
                border: none; border-radius: 7px;
                font-size: 12px; font-weight: 500; padding: 7px 10px;
            }}
            QPushButton:hover {{ color: {T.FG}; background: {T.PANEL2}; }}
        """)
    return btn


_AVATAR_SIZE = 30
_AVATAR_INSET = 5     # aire entre el borde del circulo y el icono
_AVATAR_SCALE = 4     # se guarda a 4x para que no pixele en pantallas escaladas


class _Avatar(QWidget):
    """Icono de la app centrado sobre un circulo blanco, o una «L» si falta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
        self._pixmap: QPixmap | None = None
        path = resource("icon.png")
        if os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                side = (_AVATAR_SIZE - 2 * _AVATAR_INSET) * _AVATAR_SCALE
                self._pixmap = pix.scaled(
                    side, side,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Circulo blanco: el icono tiene trazos oscuros y sobre el panel casi
        # negro apenas se distinguian.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(0, 0, _AVATAR_SIZE, _AVATAR_SIZE)

        if self._pixmap is not None:
            # Encajado dentro del circulo y centrado, respetando la proporcion.
            # Antes se estiraba a 30x30 de borde a borde y el recorte circular
            # le cortaba la parte de arriba y la de abajo.
            w = self._pixmap.width() / _AVATAR_SCALE
            h = self._pixmap.height() / _AVATAR_SCALE
            p.drawPixmap(
                QRectF((_AVATAR_SIZE - w) / 2, (_AVATAR_SIZE - h) / 2, w, h),
                self._pixmap,
                QRectF(self._pixmap.rect()),
            )
            p.end()
            return

        p.setPen(QColor(T.BG))
        font = QFont()
        font.setPointSize(12)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(0, 0, _AVATAR_SIZE, _AVATAR_SIZE,
                   Qt.AlignmentFlag.AlignCenter, "L")
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
def build_steps(window) -> List[TourStep]:
    """Guion del tour. Los objetivos se resuelven al mostrar cada paso."""
    return [
        TourStep(
            title="Hola, soy Lexa",
            body=(
                "Convierto audio, video, imágenes y PDFs en texto que puedes "
                "editar, copiar y exportar. Todo ocurre en tu computadora: nada "
                "se sube a internet.\n\nTe muestro cómo funciona en 30 segundos."
            ),
        ),
        TourStep(
            title="1. Trae tus archivos",
            body=(
                "Arrastra aquí un audio, un video, una imagen o un PDF. También "
                "puedes soltar una carpeta entera y tomaré todo lo que haya "
                "dentro, o usar el botón para elegirlos a mano."
            ),
            target=lambda: window._left.dropzone,
            padding=6,
        ),
        TourStep(
            title="2. Revisa la cola",
            body=(
                "Cada archivo aparece aquí con su estado y su propia barra de "
                "progreso. Puedes quitar uno con la × o reintentarlo si algo "
                "falló."
            ),
            target=lambda: window._left.queue_panel,
            padding=6,
        ),
        TourStep(
            title="3. Elige idioma y calidad",
            body=(
                "El modelo Turbo es el equilibrio recomendado entre velocidad y "
                "precisión. Si activas «Identificar hablantes» separaré la "
                "conversación por persona, aunque tardaré un poco más.\n\n"
                "En «Palabras del audio» escribe los nombres y términos que "
                "suelo escribir mal: apellidos, marcas, jerga de tu carrera. "
                "Con eso delante los acierto."
            ),
            target=lambda: window._right.processing_panel,
            padding=6,
        ),
        TourStep(
            title="4. Decide cómo guardar",
            body=(
                "Elige el formato de salida y dónde dejarlo. TXT y Word para "
                "documentos, PDF para imprimir, SRT o VTT si necesitas "
                "subtítulos para un video."
            ),
            target=lambda: window._right.export_panel,
            padding=6,
        ),
        TourStep(
            title="5. Dale al botón verde",
            body=(
                "Eso es todo. Procesaré los archivos uno por uno y guardaré el "
                "resultado automáticamente en la carpeta que elegiste."
            ),
            target=lambda: window._right.start_btn,
            padding=8,
        ),
        TourStep(
            title="6. Vigila el avance aquí abajo",
            body=(
                "El ritmo muestra cuánto audio proceso por segundo: 2.4x quiere "
                "decir que en un segundo avanzo 2,4 de grabación. Sube y baja "
                "según lo denso que venga el audio.\n\n"
                "En el registro aviso de lo que encuentro: si la grabación trae "
                "poca voz, si el filtro de silencios se estaba comiendo habla, "
                "y si descarto frases que me inventé sobre el silencio."
            ),
            target=lambda: window._footer,
            padding=4,
        ),
        TourStep(
            title="7. Lee y copia el resultado",
            body=(
                "El texto aparece aquí a medida que termino cada archivo. Puedes "
                "verlo formateado en párrafos, como texto plano o en JSON, y "
                "copiarlo con un clic.\n\nSi vuelves a soltar un archivo que ya "
                "procesé con los mismos ajustes, te devuelvo el resultado al "
                "instante en vez de repetir el trabajo.\n\nSi necesitas verme "
                "otra vez, usa el botón «?» de arriba a la derecha."
            ),
            target=lambda: window._center,
            padding=4,
        ),
    ]
