"""Panel de recorte: reproductor, forma de onda y lista de tramos.

Vive dentro de la ventana principal, ocupando el sitio de la vista
previa mientras se elige el tramo. Una ventana aparte obligaba a
moverla para ver la cola y rompia la sensacion de una sola pantalla.

El reproductor usa QMediaPlayer, que se apoya en los codecs de Windows. Puede
no abrir un mkv o un webm que Lexa si transcribe, asi que cuando falla se cae a
mostrar fotogramas sacados con PyAV —que abre todo lo que la aplicacion
acepta— en vez de dejar un recuadro negro sin explicacion.
"""
from __future__ import annotations
import os
from typing import List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import Qt, QRectF, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.models import FileItem
from ui import theme as T
from ui.waveform import Waveform, _reloj

_SPEEDS = [0.5, 0.75, 1.0, 1.5, 2.0]


class _AudioLoader(QThread):
    """Decodifica el audio fuera del hilo de la interfaz.

    Un archivo de veinte minutos tarda unos segundos en decodificarse; hacerlo
    en el hilo de la ventana la dejaria congelada justo al abrirla.
    """
    ready = pyqtSignal(object, float)
    failed = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            from core.engines import media
            audio = media.load_audio(self._path)
            self.ready.emit(audio, len(audio) / media.SAMPLE_RATE)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


class _PlayButton(QPushButton):
    """Play y pausa dibujados en vez de con glifos.

    «▶» y «⏸» dependen de la fuente instalada: cambian de tamano entre si,
    se desalinean y en algunos equipos salen como un cuadrado vacio. Dos
    triangulos y dos barras pintados a mano siempre se ven igual.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 30)
        self.setStyleSheet(
            f"QPushButton {{ background: {T.PANEL2}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_SM}px; }}"
            f"QPushButton:hover {{ border-color: {T.MUTED}; }}")

    def set_playing(self, value: bool) -> None:
        self._playing = value
        self.update()

    def is_playing(self) -> bool:
        return self._playing

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.ACCENT))
        cx, cy = self.width() / 2, self.height() / 2

        if self._playing:
            ancho, alto, hueco = 3.0, 12.0, 3.5
            p.drawRect(QRectF(cx - hueco / 2 - ancho, cy - alto / 2, ancho, alto))
            p.drawRect(QRectF(cx + hueco / 2, cy - alto / 2, ancho, alto))
        else:
            lado = 12.0
            camino = QPainterPath()
            camino.moveTo(cx - lado / 3, cy - lado / 2)
            camino.lineTo(cx + lado * 2 / 3, cy)
            camino.lineTo(cx - lado / 3, cy + lado / 2)
            camino.closeSubpath()
            p.drawPath(camino)
        p.end()


class TrimPanel(QWidget):
    """Editor de tramos embebido. Lista vacia = archivo entero."""

    applied = pyqtSignal(int, object)    # file_id, tramos
    cancelled = pyqtSignal()

    def __init__(self, item: FileItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._duration = item.duration or 0.0
        self._player = None
        self._audio_out = None
        self._video = None
        self._frames = None            # respaldo con PyAV
        self._only_selection = False
        self._sel_index = 0
        self._sel_landed = False
        self._sel_waits = 0
        self._loader: Optional[_AudioLoader] = None
        self._watch: Optional[QTimer] = None
        self._fullscreen = False

        self.setStyleSheet(f"background: {T.PANEL};")

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 14)
        raiz.setSpacing(10)

        raiz.addWidget(self._build_header())
        raiz.addWidget(self._build_preview(), stretch=1)

        self._wave = Waveform()
        self._wave.ranges_changed.connect(self._refresh)
        self._wave.seeked.connect(self._seek)
        raiz.addWidget(self._wave)

        raiz.addWidget(self._build_controls())
        raiz.addWidget(self._build_list(), stretch=1)
        raiz.addWidget(self._build_footer())

        self._wave.set_ranges(item.ranges)
        self._start_player()
        self._load_audio()
        self._refresh()

    # -- Construccion ---------------------------------------------------------
    def _build_header(self) -> QWidget:
        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)

        nombre = QLabel(self._item.name)
        nombre.setStyleSheet(
            f"background: transparent; color: {T.FG}; font-size: 13px; font-weight: 600;")
        lay.addWidget(nombre)
        lay.addStretch()

        self._clock = QLabel("00:00 / 00:00")
        self._clock.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 11.5px; "
            f"font-family: Consolas, monospace;")
        lay.addWidget(self._clock)
        lay.addSpacing(10)

        self._full_btn = self._boton("Pantalla completa", self._toggle_fullscreen,
                                     ancho=140)
        lay.addWidget(self._full_btn)
        return fila

    def _build_preview(self) -> QWidget:
        caja = QWidget()
        caja.setMinimumHeight(220)
        caja.setStyleSheet(
            f"background: #000000; border: 1px solid {T.LINE}; "
            f"border-radius: {T.R_MD}px;")
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)
        self._preview_lay = lay

        try:
            from PyQt6.QtMultimediaWidgets import QVideoWidget
            self._video = QVideoWidget()
            lay.addWidget(self._video)
        except Exception:
            self._video = None

        # Etiqueta de respaldo: aqui se pintan los fotogramas de PyAV cuando el
        # reproductor no puede con el formato, y el aviso de solo audio.
        self._fallback = QLabel("")
        self._fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 12px;")
        self._fallback.setVisible(False)
        lay.addWidget(self._fallback)
        return caja

    def _build_controls(self) -> QWidget:
        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._play_btn = _PlayButton()
        self._play_btn.clicked.connect(self._toggle_play)
        lay.addWidget(self._play_btn)

        lay.addSpacing(10)
        self._speed_btns = {}
        for v in _SPEEDS:
            etiqueta = f"{v:g}×"
            b = self._boton(etiqueta, lambda _=False, s=v: self._set_speed(s), ancho=46)
            self._speed_btns[v] = b
            lay.addWidget(b)
        self._set_speed(1.0)

        lay.addStretch()
        self._sel_btn = self._boton("Reproducir la selección", self._play_selection,
                                    ancho=170)
        lay.addWidget(self._sel_btn)
        return fila

    def _build_list(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._list_host = QWidget()
        self._list_host.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(4)
        self._list_lay.addStretch()
        scroll.setWidget(self._list_host)
        return scroll

    def _build_footer(self) -> QWidget:
        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)

        self._summary = QLabel("")
        self._summary.setStyleSheet(
            f"background: transparent; color: {T.FG2}; font-size: 12px;")
        lay.addWidget(self._summary)
        lay.addStretch()

        lay.addWidget(self._boton("Quitar recorte", self._wave.clear_ranges, ancho=120))
        lay.addWidget(self._boton("Cancelar", self._on_cancel, ancho=90))
        aplicar = self._boton("Aplicar", self._on_apply, ancho=100, principal=True)
        lay.addWidget(aplicar)
        return fila

    def _boton(self, texto: str, accion, ancho: int = 80,
               principal: bool = False) -> QPushButton:
        b = QPushButton(texto)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedHeight(30)
        b.setFixedWidth(ancho)
        b.clicked.connect(accion)
        b.setStyleSheet(self._estilo_boton(principal))
        return b

    @staticmethod
    def _estilo_boton(principal: bool, activo: bool = False) -> str:
        if principal:
            return (f"QPushButton {{ background: {T.ACCENT}; color: {T.ACCENT_TEXT};"
                    f" border: none; border-radius: {T.R_SM}px; font-size: 12px;"
                    f" font-weight: 600; }}"
                    f"QPushButton:hover {{ background: #7fd6a8; }}")
        fondo = T.ACCENT_SOFT if activo else T.PANEL2
        color = T.ACCENT if activo else T.FG2
        return (f"QPushButton {{ background: {fondo}; color: {color};"
                f" border: 1px solid {T.LINE}; border-radius: {T.R_SM}px;"
                f" font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {T.MUTED}; }}")

    def _toggle_fullscreen(self) -> None:
        """Agranda el video a toda la pantalla y vuelve.

        Se saca el widget de video a una ventana propia sin marco en lugar de
        maximizar el panel: asi ocupa la pantalla entera de verdad, y al salir
        vuelve a su hueco sin tocar el resto de la interfaz.
        """
        if self._video is None:
            return
        if not self._fullscreen:
            self._video.setParent(None)
            self._video.setWindowFlags(Qt.WindowType.Window
                                       | Qt.WindowType.FramelessWindowHint)
            self._video.showFullScreen()
            self._video.installEventFilter(self)
            self._fullscreen = True
            self._full_btn.setText("Salir")
        else:
            self._exit_fullscreen()

    def _exit_fullscreen(self) -> None:
        if not self._fullscreen or self._video is None:
            return
        self._video.removeEventFilter(self)
        self._video.setWindowFlags(Qt.WindowType.Widget)
        self._preview_lay.addWidget(self._video)
        self._video.showNormal()
        self._video.setVisible(True)
        self._fullscreen = False
        self._full_btn.setText("Pantalla completa")

    def eventFilter(self, obj, event):
        # Escape y doble clic salen de pantalla completa: es lo que la gente
        # intenta sin pensar.
        from PyQt6.QtCore import QEvent
        if obj is self._video and self._fullscreen:
            if event.type() == QEvent.Type.KeyPress and                     event.key() == Qt.Key.Key_Escape:
                self._exit_fullscreen()
                return True
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._exit_fullscreen()
                return True
        return super().eventFilter(obj, event)

    # -- Reproductor ----------------------------------------------------------
    def _start_player(self) -> None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        except Exception:
            self._show_fallback("Reproducción no disponible en este equipo.")
            return

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        if self._video is not None:
            self._player.setVideoOutput(self._video)
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(self._item.path)))
        self._player.positionChanged.connect(self._on_position)
        self._player.errorOccurred.connect(lambda *_: self._on_media_error())
        self._player.durationChanged.connect(self._on_duration)

        # Vigilante del modo «solo lo seleccionado»: salta al siguiente tramo
        # en cuanto la reproduccion sale del actual.
        self._watch = QTimer(self)
        self._watch.setInterval(80)
        self._watch.timeout.connect(self._watch_selection)

    def _on_media_error(self) -> None:
        """El formato no lo abre Windows: se pasa a fotogramas con PyAV."""
        if self._video is not None:
            self._video.setVisible(False)
        self._show_fallback(
            "Este formato no se puede reproducir en Windows.\n"
            "Se muestran fotogramas del vídeo; el recorte funciona igual.")
        self._load_frames()

    def _show_fallback(self, texto: str) -> None:
        self._fallback.setText(texto)
        self._fallback.setVisible(True)

    def _load_frames(self) -> None:
        try:
            import av
            self._frames = av.open(os.path.abspath(self._item.path))
        except Exception:
            self._frames = None

    def _frame_at(self, seconds: float) -> None:
        """Pinta el fotograma de ese instante en la etiqueta de respaldo."""
        if self._frames is None:
            return
        try:
            stream = self._frames.streams.video[0]
            self._frames.seek(int(seconds / stream.time_base), stream=stream)
            for cuadro in self._frames.decode(stream):
                img = cuadro.to_ndarray(format="rgb24")
                alto, ancho, _ = img.shape
                qimg = QImage(img.data, ancho, alto, 3 * ancho,
                              QImage.Format.Format_RGB888)
                self._fallback.setPixmap(QPixmap.fromImage(qimg).scaled(
                    self._fallback.width(), self._fallback.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                return
        except Exception:
            pass

    def _toggle_play(self) -> None:
        if self._player is None:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_btn.set_playing(False)
        else:
            self._player.play()
            self._play_btn.set_playing(True)

    def _set_speed(self, value: float) -> None:
        if self._player is not None:
            self._player.setPlaybackRate(value)
        for v, b in self._speed_btns.items():
            b.setStyleSheet(self._estilo_boton(False, activo=(v == value)))

    def _seek(self, seconds: float) -> None:
        self._only_selection = False
        if self._player is not None:
            self._player.setPosition(int(seconds * 1000))
        else:
            self._frame_at(seconds)
        self._wave.set_position(seconds)
        self._update_clock(seconds)

    def _play_selection(self) -> None:
        tramos = self._wave.ranges()
        if not tramos or self._player is None:
            return
        self._only_selection = True
        self._goto_range(0)
        self._player.play()
        self._play_btn.set_playing(True)
        self._watch.start()

    def _goto_range(self, index: int) -> None:
        tramos = self._wave.ranges()
        if not (0 <= index < len(tramos)):
            return
        self._sel_index = index
        self._sel_landed = False
        self._sel_waits = 0
        self._player.setPosition(int(tramos[index][0] * 1000))

    def _watch_selection(self) -> None:
        """Encadena los tramos, respetando que el salto tarda en aplicarse.

        setPosition es asincrono: hasta que el salto no llega, el reproductor
        sigue devolviendo la posicion anterior. Actuar sobre ese valor era el
        fallo: si se venia escuchando despues del ultimo tramo, el primer
        vistazo lo veia fuera de todo y pausaba al instante, de modo que el
        boton parecia no hacer nada.
        """
        if not self._only_selection or self._player is None:
            self._watch.stop()
            return

        tramos = self._wave.ranges()
        if not tramos or self._sel_index >= len(tramos):
            self._stop_selection()
            return

        a, b = tramos[self._sel_index]
        t = self._player.position() / 1000.0

        if not self._sel_landed:
            if a - 0.5 <= t <= b + 0.5:
                self._sel_landed = True
                return
            self._sel_waits += 1
            # Si el salto no llega nunca (formato que no admite busqueda) se
            # deja de esperar en vez de quedarse mirando para siempre.
            if self._sel_waits > 40:
                self._stop_selection()
            return

        if t <= b:
            return
        if self._sel_index + 1 < len(tramos):
            self._goto_range(self._sel_index + 1)
        else:
            self._stop_selection()

    def _stop_selection(self) -> None:
        if self._player is not None:
            self._player.pause()
        self._play_btn.set_playing(False)
        self._only_selection = False
        self._watch.stop()

    def _on_position(self, ms: int) -> None:
        segundos = ms / 1000.0
        self._wave.set_position(segundos)
        self._update_clock(segundos)

    def _on_duration(self, ms: int) -> None:
        if ms > 0 and self._duration <= 0:
            self._duration = ms / 1000.0

    def _update_clock(self, seconds: float) -> None:
        self._clock.setText(f"{_reloj(seconds)} / {_reloj(self._duration)}")

    # -- Audio y onda ---------------------------------------------------------
    def _load_audio(self) -> None:
        self._loader = _AudioLoader(self._item.path, self)
        self._loader.ready.connect(self._on_audio)
        self._loader.failed.connect(
            lambda msg: self._show_fallback(f"No se pudo leer el audio.\n{msg}"))
        self._loader.start()

    def _on_audio(self, audio, duration: float) -> None:
        if self._duration <= 0:
            self._duration = duration
        self._wave.set_audio(audio, duration)
        self._update_clock(0.0)
        self._refresh()

    # -- Lista y resumen ------------------------------------------------------
    def _refresh(self) -> None:
        while self._list_lay.count() > 1:
            fila = self._list_lay.takeAt(0)
            if fila.widget():
                fila.widget().deleteLater()

        tramos = self._wave.ranges()
        for i, (a, b) in enumerate(tramos):
            self._list_lay.insertWidget(i, self._build_row(i, a, b))

        total = sum(b - a for a, b in tramos)
        if tramos:
            self._summary.setText(
                f"Se transcribirán {_reloj(total)} de {_reloj(self._duration)}")
        else:
            self._summary.setText(
                f"Sin recorte: se transcribirá todo ({_reloj(self._duration)})")

    def _build_row(self, index: int, a: float, b: float) -> QWidget:
        fila = QWidget()
        fila.setStyleSheet(
            f"background: {T.PANEL2}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_SM}px;")
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(10, 5, 6, 5)

        texto = QLabel(f"Tramo {index + 1}    {_reloj(a)} → {_reloj(b)}    "
                       f"({_reloj(b - a)})")
        texto.setStyleSheet(
            f"background: transparent; border: none; color: {T.FG2};"
            f" font-size: 12px; font-family: Consolas, monospace;")
        lay.addWidget(texto)
        lay.addStretch()

        quitar = QPushButton("✕")
        quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        quitar.setFixedSize(22, 22)
        quitar.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {T.MUTED}; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {T.DANGER}; }}")
        quitar.clicked.connect(lambda _=False, i=index: self._remove(i))
        lay.addWidget(quitar)
        return fila

    def _remove(self, index: int) -> None:
        tramos = self._wave.ranges()
        if 0 <= index < len(tramos):
            del tramos[index]
            self._wave.set_ranges(tramos)
            self._refresh()

    # -- Resultado ------------------------------------------------------------
    def ranges(self) -> List[Tuple[float, float]]:
        return self._wave.ranges()

    def _on_apply(self) -> None:
        self.release()
        self.applied.emit(self._item.id, self._wave.ranges())

    def _on_cancel(self) -> None:
        self.release()
        self.cancelled.emit()

    def release(self) -> None:
        """Suelta reproductor y archivos. Se llama al cerrar el panel."""
        self._exit_fullscreen()
        if self._watch is not None:
            self._watch.stop()
        if self._player is not None:
            # Tolerante a proposito: si el reproductor ya se solto o nunca
            # llego a crearse del todo, soltarlo no debe tumbar la ventana.
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                pass
        if self._frames is not None:
            try:
                self._frames.close()
            except Exception:
                pass
            self._frames = None

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._toggle_play()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
            return
        super().keyPressEvent(event)
