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
from PyQt6.QtGui import (
    QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.models import FileItem
from ui import theme as T
from ui.waveform import Waveform, _reloj
from ui.widgets import Panel, hdivider

_SPEEDS = [0.5, 0.75, 1.0, 1.5, 2.0]

# Alto minimo de la vista previa. Es el minimo de verdad, no el comodo: al
# declarar 220 el editor entero pedia 534 px y en un portatil de pantalla baja
# no cabia, asi que se salia por abajo y la lista de tramos quedaba cortada con
# barra de desplazamiento. Con el minimo real, encoge y cabe; cuando hay sitio,
# el factor de estiramiento le devuelve todo el espacio y se ve mas grande que
# antes.
_PREVIEW_ALTO_MIN = 104

# Por debajo de este alto se aprietan margenes y separaciones. No corta nada:
# solo gana unos pixeles para que la lista de tramos se vea sin desplazar.
_ALTO_COMODO = 560


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
        # Apagado se pinta en gris: si no, un boton que no hace nada sigue
        # llamando con el verde de siempre.
        p.setBrush(QColor(T.ACCENT if self.isEnabled() else T.DIM))
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
    notice = pyqtSignal(str, str)        # nivel, mensaje para el registro

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

        self.setStyleSheet("background: transparent;")

        # El editor vive dentro de la misma tarjeta redondeada que la vista
        # previa a la que sustituye: si va a pelo, corta a ras de los bordes y
        # se ve como un parche pegado encima.
        fuera = QVBoxLayout(self)
        fuera.setContentsMargins(0, 0, 0, 0)
        fuera.setSpacing(0)

        tarjeta = Panel(padded=False)
        fuera.addWidget(tarjeta)
        self._tarjeta = tarjeta
        self._compacto = False

        raiz = tarjeta.layout()
        raiz.setContentsMargins(16, 14, 16, 12)
        raiz.setSpacing(10)

        raiz.addWidget(self._build_header())
        self._preview = self._build_preview()
        raiz.addWidget(self._preview, stretch=3)
        raiz.addWidget(self._build_aviso())

        self._wave = Waveform()
        self._wave.setStyleSheet(f"border: 1px solid {T.LINE};"
                                 f" border-radius: {T.R_SM}px;")
        self._wave.ranges_changed.connect(self._refresh)
        self._wave.seeked.connect(self._seek)
        raiz.addWidget(self._wave)

        raiz.addWidget(self._build_controls())
        raiz.addWidget(self._build_list(), stretch=2)
        raiz.addWidget(self._build_footer())

        self._fit_chip()
        self._wave.set_ranges(item.ranges)
        self._start_player()
        self._load_audio()
        self._refresh()

    # -- Construccion ---------------------------------------------------------
    def _build_header(self) -> QWidget:
        """Titulo al mismo peso que el de la vista previa a la que sustituye.

        El nombre del archivo solo, flotando arriba a la izquierda, no decia
        que era esa pantalla. Ahora manda el titulo y el archivo va en una
        chapa, junto al tipo y la duracion; el reloj vive en su propia pildora.
        """
        caja = QWidget()
        col = QVBoxLayout(caja)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        titulo = QLabel("Recortar")
        titulo.setStyleSheet(
            f"background: transparent; font-size: 21px; font-weight: 700;"
            f" color: {T.FG}; letter-spacing: -0.3px;")
        lay.addWidget(titulo)

        self._chip = QLabel()
        self._chip.setStyleSheet(
            f"background: {T.PANEL2}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_SM}px; color: {T.FG2}; font-size: 11.5px;"
            f" padding: 3px 9px;")
        self._chip.setToolTip(self._item.name)
        lay.addWidget(self._chip)

        detalle = QLabel(self._detalle())
        detalle.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 12px;")
        lay.addWidget(detalle)
        lay.addStretch()

        self._clock = QLabel("00:00 / 00:00")
        self._clock.setStyleSheet(
            f"background: {T.PANEL2}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_SM}px; color: {T.FG2}; font-size: 11.5px;"
            f" padding: 3px 9px; font-family: Consolas, monospace;")
        lay.addWidget(self._clock)

        col.addWidget(fila)
        col.addWidget(hdivider())
        return caja

    def _detalle(self) -> str:
        """Tipo y duracion, lo unico del archivo que importa aqui."""
        partes = []
        ext = os.path.splitext(self._item.name)[1].lstrip(".").upper()
        if ext:
            partes.append(ext)
        if self._duration > 0:
            partes.append(_reloj(self._duration))
        return " · ".join(partes)

    def resizeEvent(self, e):
        """El nombre se recorta al ancho que sobra, no empuja al reloj fuera."""
        super().resizeEvent(e)
        self._fit_chip()
        self._ajustar_alto()

    def _ajustar_alto(self) -> None:
        """En pantallas bajas se aprietan margenes y separaciones.

        El reparto del alto lo hace el propio layout: la vista previa declara
        su minimo de verdad y se estira cuando hay sitio. Esto solo recupera
        los pixeles de los margenes, que en una pantalla corta son justo los
        que hacen que la lista de tramos se vea sin tener que desplazarla.
        """
        if getattr(self, "_preview", None) is None:
            return
        self._compactar(self.height() < _ALTO_COMODO)

    def _compactar(self, si: bool) -> None:
        if self._compacto == si:
            return
        self._compacto = si
        raiz = self._tarjeta.layout()
        raiz.setSpacing(6 if si else 10)
        if si:
            raiz.setContentsMargins(12, 10, 12, 8)
        else:
            raiz.setContentsMargins(16, 14, 16, 12)
        if hasattr(self, "_hint"):
            self._hint.setMinimumHeight(48 if si else 74)

    def _fit_chip(self) -> None:
        chip = getattr(self, "_chip", None)
        if chip is None:
            return
        tope = max(120, int(self.width() * 0.34))
        fm = QFontMetrics(chip.font())
        chip.setText(fm.elidedText(self._item.name, Qt.TextElideMode.ElideMiddle, tope))

    def _build_preview(self) -> QWidget:
        caja = QWidget()
        caja.setMinimumHeight(_PREVIEW_ALTO_MIN)
        caja.setStyleSheet(
            f"background: #000000; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_MD}px;")
        lay = QVBoxLayout(caja)
        # Un pixel de margen para que el video no tape las esquinas redondeadas
        # del recuadro que lo contiene.
        lay.setContentsMargins(1, 1, 1, 1)
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

    def _build_aviso(self) -> QWidget:
        """Franja para explicar por que no hay sonido o no hay imagen.

        Va fuera del recuadro negro a proposito: un QLabel no puede tener a la
        vez texto y fotograma, asi que si el aviso viviera dentro, en cuanto se
        pintara el primer fotograma desapareceria y la persona se quedaria sin
        saber que pasa.
        """
        self._aviso = QLabel("")
        self._aviso.setWordWrap(True)
        self._aviso.setStyleSheet(
            f"background: {T.WARN_SOFT}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_SM}px; color: {T.WARN};"
            f" font-size: 11.5px; padding: 6px 10px;")
        self._aviso.setVisible(False)
        return self._aviso

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
        self._list_lay.setSpacing(5)

        cabecera = QLabel("TRAMOS")
        cabecera.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 10px;"
            f" font-weight: 600; letter-spacing: 1px;")
        self._list_lay.addWidget(cabecera)

        # Un panel vacio no dice que hacer. Esta pista desaparece en cuanto
        # existe el primer tramo.
        self._hint = QLabel(
            "Arrastra sobre la onda para elegir qué parte transcribir.\n"
            "Arrastra los bordes para ajustarla, o por dentro para moverla.")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setMinimumHeight(74)   # se baja a 48 en pantallas cortas
        self._hint.setStyleSheet(
            f"background: {T.PANEL2}; border: 1px dashed {T.LINE};"
            f" border-radius: {T.R_MD}px; color: {T.DIM}; font-size: 12px;"
            f" line-height: 150%;")
        self._list_lay.addWidget(self._hint)

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

    # -- Reproductor ----------------------------------------------------------
    def _start_player(self) -> None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        except Exception as e:
            # Pasa en las ediciones N y KN de Windows sin el Media Feature
            # Pack: Qt6Multimedia.dll depende de AVRT.dll, que ahi no existe,
            # y entonces ni siquiera se puede importar.
            self.notice.emit(
                "warn", f"Este equipo no tiene el componente multimedia de "
                        f"Windows ({e}). El recorte funciona igual, sin sonido.")
            self._sin_reproductor()
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

    def _sin_reproductor(self) -> None:
        """Sin sonido, pero con imagen: se sacan los fotogramas con PyAV.

        Antes solo se ponia el aviso y se dejaba el recuadro en negro; como el
        cargador de fotogramas no llegaba a abrirse, moverse por el video
        tampoco ensenaba nada.
        """
        if self._video is not None:
            self._video.setVisible(False)
        self._show_fallback(
            "Este equipo no puede reproducir el sonido: le falta el componente "
            "multimedia de Windows.\n"
            "Se ve la imagen del vídeo y el recorte funciona igual.")
        self._load_frames()
        self._frame_at(0.0)
        # Los botones que dependen del reproductor no pueden hacer nada.
        for boton in (self._play_btn, self._sel_btn):
            boton.setEnabled(False)
            boton.setToolTip("Necesita el componente multimedia de Windows")

    def _on_media_error(self) -> None:
        """El formato no lo abre Windows: se pasa a fotogramas con PyAV."""
        if self._video is not None:
            self._video.setVisible(False)
        self._show_fallback(
            "Este formato no se puede reproducir en Windows.\n"
            "Se muestran fotogramas del vídeo; el recorte funciona igual.")
        self._load_frames()

    def _show_fallback(self, texto: str) -> None:
        # Pueden coincidir dos problemas —ni reproductor ni pista de audio— y
        # antes el segundo aviso borraba al primero, dejando media explicacion.
        corto = " ".join(texto.split())
        if not hasattr(self, "_avisos"):
            self._avisos = []
        if corto not in self._avisos:
            self._avisos.append(corto)
        self._aviso.setText("  ·  ".join(self._avisos))
        self._aviso.setVisible(True)
        # Tambien dentro del recuadro, para que no se quede negro mientras no
        # haya ningun fotograma que pintar.
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
        # Se quitan solo las filas: la cabecera, la pista y el hueco elastico
        # son fijos y viven en los extremos.
        for i in reversed(range(self._list_lay.count())):
            w = self._list_lay.itemAt(i).widget()
            if w is not None and getattr(w, "_es_fila_tramo", False):
                self._list_lay.takeAt(i)
                w.deleteLater()

        tramos = self._wave.ranges()
        self._hint.setVisible(not tramos)
        for i, (a, b) in enumerate(tramos):
            self._list_lay.insertWidget(i + 1, self._build_row(i, a, b))

        total = sum(b - a for a, b in tramos)
        if tramos:
            self._summary.setText(
                f"Se transcribirán {_reloj(total)} de {_reloj(self._duration)}")
        else:
            self._summary.setText(
                f"Sin recorte: se transcribirá todo ({_reloj(self._duration)})")

    def _build_row(self, index: int, a: float, b: float) -> QWidget:
        fila = QWidget()
        fila._es_fila_tramo = True
        fila.setStyleSheet(
            f"background: {T.PANEL2}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_SM}px;")
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.setSpacing(10)

        # Punto de color: ata visualmente la fila con su tramo en la onda.
        punto = QLabel("●")
        punto.setFixedWidth(12)
        punto.setStyleSheet(
            f"background: transparent; border: none; color: {T.ACCENT};"
            f" font-size: 11px;")
        lay.addWidget(punto)

        numero = QLabel(f"Tramo {index + 1}")
        numero.setFixedWidth(64)
        numero.setStyleSheet(
            f"background: transparent; border: none; color: {T.FG};"
            f" font-size: 12px; font-weight: 600;")
        lay.addWidget(numero)

        texto = QLabel(f"{_reloj(a)} → {_reloj(b)}")
        texto.setStyleSheet(
            f"background: transparent; border: none; color: {T.FG2};"
            f" font-size: 12px; font-family: Consolas, monospace;")
        lay.addWidget(texto)
        lay.addStretch()

        dura = QLabel(_reloj(b - a))
        dura.setStyleSheet(
            f"background: {T.ACCENT_SOFT}; border: none; border-radius: 4px;"
            f" padding: 1px 7px; color: {T.ACCENT}; font-size: 11px;"
            f" font-family: Consolas, monospace;")
        lay.addWidget(dura)

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
        # El hilo que decodifica la onda tiene el archivo abierto. Si se deja
        # corriendo, sigue leyendo un archivo que ya nadie mira y Windows no
        # deja borrarlo ni moverlo mientras Lexa siga viva.
        if self._loader is not None:
            try:
                if self._loader.isRunning():
                    self._loader.requestInterruption()
                    self._loader.wait(5000)
            except Exception:
                pass
            self._loader = None

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._toggle_play()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
            return
        super().keyPressEvent(event)
