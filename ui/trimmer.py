"""Ventana de recorte: reproductor, forma de onda y lista de tramos.

El reproductor usa QMediaPlayer, que se apoya en los codecs de Windows. Puede
no abrir un mkv o un webm que Lexa si transcribe, asi que cuando falla se cae a
mostrar fotogramas sacados con PyAV —que abre todo lo que la aplicacion
acepta— en vez de dejar un recuadro negro sin explicacion.
"""
from __future__ import annotations
import os
from typing import List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
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


class TrimDialog(QDialog):
    """Devuelve los tramos elegidos. Lista vacia = archivo entero."""

    def __init__(self, item: FileItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._duration = item.duration or 0.0
        self._player = None
        self._audio_out = None
        self._video = None
        self._frames = None            # respaldo con PyAV
        self._only_selection = False
        self._loader: Optional[_AudioLoader] = None

        self.setWindowTitle(f"Recortar · {item.name}")
        self.setMinimumSize(880, 620)
        self.setStyleSheet(f"QDialog {{ background: {T.PANEL}; }}")

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
        return fila

    def _build_preview(self) -> QWidget:
        caja = QWidget()
        caja.setMinimumHeight(220)
        caja.setStyleSheet(
            f"background: #000000; border: 1px solid {T.LINE}; "
            f"border-radius: {T.R_MD}px;")
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)

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

        self._play_btn = self._boton("▶", self._toggle_play, ancho=44)
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
        self._sel_btn = self._boton("▶ Solo lo seleccionado", self._play_selection,
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
        lay.addWidget(self._boton("Cancelar", self.reject, ancho=90))
        aplicar = self._boton("Aplicar", self.accept, ancho=100, principal=True)
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
            self._play_btn.setText("▶")
        else:
            self._player.play()
            self._play_btn.setText("⏸")

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
        self._player.setPosition(int(tramos[0][0] * 1000))
        self._player.play()
        self._play_btn.setText("⏸")
        self._watch.start()

    def _watch_selection(self) -> None:
        if not self._only_selection or self._player is None:
            self._watch.stop()
            return
        t = self._player.position() / 1000.0
        tramos = self._wave.ranges()
        for a, b in tramos:
            if a <= t <= b:
                return
        # Fuera de todo tramo: saltar al siguiente que empiece despues.
        siguientes = [a for a, _ in tramos if a > t]
        if siguientes:
            self._player.setPosition(int(min(siguientes) * 1000))
        else:
            self._player.pause()
            self._play_btn.setText("▶")
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

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._toggle_play()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._player is not None:
            self._player.stop()
        if self._frames is not None:
            try:
                self._frames.close()
            except Exception:
                pass
        super().closeEvent(event)
