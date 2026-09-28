"""Forma de onda con seleccion de tramos por gestos.

No hay boton de modo. El gesto decide: un clic mueve el cursor, un arrastre
selecciona. Cambiar de modo con un boton obliga a recordar en cual estas y a ir
y volver constantemente mientras afinas un corte.

El umbral de arrastre es lo que hace que esto se sienta bien: sin el, cada clic
con el pulso algo tembloroso crea un tramo de dos pixeles y la herramienta pasa
a estorbar en vez de ayudar.
"""
from __future__ import annotations
from typing import List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QLinearGradient, QFont
from PyQt6.QtWidgets import QWidget

from ui import theme as T

# Columnas de la onda. Mas resolucion no se aprecia y solo cuesta memoria.
_PEAKS = 2000

# Pixeles que hay que arrastrar antes de considerar que no fue un clic.
_DRAG_THRESHOLD = 4

# Margen para agarrar el borde de un tramo en vez de crear otro encima.
_EDGE_GRAB = 6

# Distancia maxima a la que un corte se pega a un punto de silencio.
_SNAP_SECS = 0.25

# Cuantos cambios se pueden deshacer.
_UNDO_DEPTH = 20


class Waveform(QWidget):
    """Dibuja la onda y gestiona la seleccion de tramos."""

    ranges_changed = pyqtSignal()
    seeked = pyqtSignal(float)          # el usuario movio el cursor, en segundos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._peaks: np.ndarray = np.zeros(0, dtype=np.float32)
        self._duration = 0.0
        self._position = 0.0            # cursor de reproduccion, en segundos
        self._ranges: List[Tuple[float, float]] = []
        self._selected = -1             # indice del tramo seleccionado

        # Estado del gesto en curso.
        self._press_x: Optional[int] = None
        self._press_time = 0.0
        self._dragging = False
        self._mode = ""                 # "crear" | "borde" | "mover"
        self._edge = 0                  # -1 izquierdo, +1 derecho
        self._grab_offset = 0.0
        self._hover_edge = False
        self._undo: List[list] = []

    # -- Datos ----------------------------------------------------------------
    def set_audio(self, audio: np.ndarray, duration: float) -> None:
        """Calcula la envolvente a partir del PCM ya decodificado."""
        self._duration = max(duration, 0.001)
        if len(audio) == 0:
            self._peaks = np.zeros(0, dtype=np.float32)
        else:
            columnas = min(_PEAKS, len(audio))
            # Se recorta al multiplo exacto para poder plegar sin relleno.
            por_columna = len(audio) // columnas
            util = audio[:columnas * por_columna].reshape(columnas, por_columna)
            self._peaks = np.abs(util).max(axis=1)
            techo = float(self._peaks.max()) or 1.0
            self._peaks = self._peaks / techo
        self.update()

    def ranges(self) -> List[Tuple[float, float]]:
        return list(self._ranges)

    def set_ranges(self, ranges) -> None:
        self._ranges = [(float(a), float(b)) for a, b in (ranges or [])]
        self._selected = -1
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position = max(0.0, min(seconds, self._duration))
        self.update()

    def selected_index(self) -> int:
        return self._selected

    # -- Edicion --------------------------------------------------------------
    def delete_selected(self) -> None:
        if 0 <= self._selected < len(self._ranges):
            self._push_undo()
            self._ranges.pop(self._selected)
            self._selected = -1
            self._commit()

    def undo(self) -> None:
        if self._undo:
            self._ranges = self._undo.pop()
            self._selected = -1
            self._commit(record=False)

    def clear_ranges(self) -> None:
        if self._ranges:
            self._push_undo()
            self._ranges = []
            self._selected = -1
            self._commit()

    # -- Conversiones ---------------------------------------------------------
    def _x_to_time(self, x: float) -> float:
        if self.width() <= 0:
            return 0.0
        return max(0.0, min(self._duration, x / self.width() * self._duration))

    def _time_to_x(self, t: float) -> float:
        if self._duration <= 0:
            return 0.0
        return t / self._duration * self.width()

    def _edge_at(self, x: int):
        """(indice, lado) del borde bajo el cursor, o None."""
        for i, (a, b) in enumerate(self._ranges):
            if abs(x - self._time_to_x(a)) <= _EDGE_GRAB:
                return i, -1
            if abs(x - self._time_to_x(b)) <= _EDGE_GRAB:
                return i, +1
        return None

    def _range_at(self, x: int) -> int:
        t = self._x_to_time(x)
        for i, (a, b) in enumerate(self._ranges):
            if a <= t <= b:
                return i
        return -1

    def _snap(self, t: float) -> float:
        """Pega el corte al punto mas silencioso que haya cerca.

        Cortar a ojo casi siempre parte una palabra. Se busca el minimo de la
        envolvente dentro de la ventana, que es robusto y no depende del VAD
        —ese ya demostro que en audio comprimido marca voz como silencio.
        """
        if len(self._peaks) == 0 or self._duration <= 0:
            return t
        por_columna = self._duration / len(self._peaks)
        radio = int(_SNAP_SECS / por_columna)
        if radio < 1:
            return t
        centro = int(t / por_columna)
        ini = max(0, centro - radio)
        fin = min(len(self._peaks), centro + radio + 1)
        if fin <= ini:
            return t
        return float((ini + int(np.argmin(self._peaks[ini:fin]))) * por_columna)

    # -- Raton ----------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = int(event.position().x())
        self._press_x = x
        self._press_time = self._x_to_time(x)
        self._dragging = False

        borde = self._edge_at(x)
        if borde is not None:
            self._mode, (self._selected, self._edge) = "borde", borde
        else:
            dentro = self._range_at(x)
            if dentro >= 0:
                self._mode = "mover"
                self._selected = dentro
                self._grab_offset = self._press_time - self._ranges[dentro][0]
            else:
                self._mode = "crear"
                self._selected = -1
        self.update()

    def mouseMoveEvent(self, event) -> None:
        x = int(event.position().x())

        if self._press_x is None:
            # Solo pasear el raton: avisar de que hay un borde agarrable.
            hover = self._edge_at(x) is not None
            if hover != self._hover_edge:
                self._hover_edge = hover
                self.setCursor(Qt.CursorShape.SizeHorCursor if hover
                               else Qt.CursorShape.ArrowCursor)
            return

        if not self._dragging:
            if abs(x - self._press_x) < _DRAG_THRESHOLD:
                return          # todavia puede ser un clic
            self._dragging = True
            self._push_undo()
            if self._mode == "crear":
                self._ranges.append((self._press_time, self._press_time))
                self._selected = len(self._ranges) - 1

        t = self._x_to_time(x)
        if self._mode == "crear":
            a, b = self._press_time, t
            self._ranges[self._selected] = (min(a, b), max(a, b))
        elif self._mode == "borde":
            a, b = self._ranges[self._selected]
            nuevo = (t, b) if self._edge < 0 else (a, t)
            self._ranges[self._selected] = (min(nuevo), max(nuevo))
        elif self._mode == "mover":
            a, b = self._ranges[self._selected]
            largo = b - a
            inicio = max(0.0, min(t - self._grab_offset, self._duration - largo))
            self._ranges[self._selected] = (inicio, inicio + largo)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._press_x is None:
            return

        if not self._dragging:
            # Fue un clic: mover el cursor de reproduccion.
            self.seeked.emit(self._press_time)
            self._position = self._press_time
        else:
            # Alt salta el ajuste, para quien quiere el corte donde lo puso.
            if not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
                if self._mode in ("crear", "borde") and 0 <= self._selected:
                    a, b = self._ranges[self._selected]
                    self._ranges[self._selected] = (self._snap(a), self._snap(b))
            self._normalize()
            self.ranges_changed.emit()

        self._press_x = None
        self._dragging = False
        self._mode = ""
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
        elif (event.key() == Qt.Key.Key_Z
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.undo()
        else:
            super().keyPressEvent(event)

    # -- Interno --------------------------------------------------------------
    def _push_undo(self) -> None:
        self._undo.append(list(self._ranges))
        del self._undo[:-_UNDO_DEPTH]

    def _commit(self, record: bool = True) -> None:
        self._normalize()
        self.ranges_changed.emit()
        self.update()

    def _normalize(self) -> None:
        from core.engines.media import normalize_ranges
        antes = self._ranges[self._selected] if 0 <= self._selected < len(self._ranges) else None
        self._ranges = normalize_ranges(self._ranges, self._duration)
        # Tras fundir o descartar, el indice anterior puede ya no existir.
        self._selected = -1
        if antes is not None:
            for i, (a, b) in enumerate(self._ranges):
                if a <= antes[0] <= b:
                    self._selected = i
                    break

    # -- Pintado --------------------------------------------------------------
    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        medio = h / 2

        p.fillRect(self.rect(), QColor(T.PANEL2))

        if len(self._peaks) == 0:
            p.setPen(QColor(T.DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Cargando audio…")
            p.end()
            return

        # Onda: una linea vertical por columna.
        p.setPen(QPen(QColor(T.FG2), 1))
        columnas = len(self._peaks)
        for x in range(w):
            i = int(x / w * columnas)
            alto = float(self._peaks[min(i, columnas - 1)]) * (medio - 4)
            p.drawLine(x, int(medio - alto), x, int(medio + alto))

        # Tramos seleccionados por encima.
        for i, (a, b) in enumerate(self._ranges):
            x0, x1 = self._time_to_x(a), self._time_to_x(b)
            rect = QRectF(x0, 0, max(1.0, x1 - x0), h)
            relleno = QLinearGradient(0, 0, 0, h)
            relleno.setColorAt(0.0, QColor(*T.rgba(T.ACCENT_SOFT)))
            relleno.setColorAt(1.0, QColor(*T.rgba(T.ACCENT_SOFT)))
            p.fillRect(rect, QBrush(relleno))
            grosor = 2 if i == self._selected else 1
            p.setPen(QPen(QColor(T.ACCENT), grosor))
            p.drawLine(int(x0), 0, int(x0), h)
            p.drawLine(int(x1), 0, int(x1), h)

        # Cursor de reproduccion.
        xp = self._time_to_x(self._position)
        p.setPen(QPen(QColor(T.WARN), 2))
        p.drawLine(int(xp), 0, int(xp), h)

        # Rotulo mientras se arrastra: evita tener que soltar para ver cuanto va.
        if self._dragging and 0 <= self._selected < len(self._ranges):
            a, b = self._ranges[self._selected]
            texto = f"{_reloj(a)} → {_reloj(b)}  ({_reloj(b - a)})"
            fuente = QFont("Consolas")
            fuente.setPointSize(8)
            p.setFont(fuente)
            ancho = p.fontMetrics().horizontalAdvance(texto) + 12
            x = min(max(0, self._time_to_x(b) + 6), w - ancho)
            caja = QRectF(x, 4, ancho, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(T.ELEV)))
            p.drawRoundedRect(caja, 4, 4)
            p.setPen(QColor(T.FG))
            p.drawText(caja, Qt.AlignmentFlag.AlignCenter, texto)
        p.end()


def _reloj(t: float) -> str:
    minutos, segundos = divmod(int(max(0.0, t)), 60)
    horas, minutos = divmod(minutos, 60)
    return (f"{horas}:{minutos:02d}:{segundos:02d}" if horas
            else f"{minutos:02d}:{segundos:02d}")
