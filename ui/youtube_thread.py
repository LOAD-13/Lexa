"""Hilo que baja los enlaces de YouTube, de uno en uno.

De uno en uno a propósito: tres descargas a la vez se reparten la misma
conexión y ninguna acaba antes, pero el registro se vuelve ilegible. Pegar
varios enlaces los encola, y cada archivo entra en la cola de transcripción en
cuanto termina de bajar, sin esperar a los demás.
"""
from __future__ import annotations
from typing import List

from PyQt6.QtCore import QMutex, QThread, pyqtSignal

from core import youtube


class YoutubeDownloadThread(QThread):
    """Descarga una lista de enlaces y avisa por cada uno."""

    progress = pyqtSignal(str, float, str)   # enlace, 0..1, texto
    finished_one = pyqtSignal(str, str)      # enlace, ruta del archivo
    failed_one = pyqtSignal(str, str)        # enlace, motivo
    notice = pyqtSignal(str, str)            # nivel, mensaje
    all_done = pyqtSignal()

    def __init__(self, enlaces: List[str], with_video: bool, parent=None):
        super().__init__(parent)
        self._pendientes = list(enlaces)
        self._with_video = with_video
        self._abort = False
        self._cerrado = False
        self._candado = QMutex()

    def add(self, enlace: str) -> bool:
        """Mete un enlace en la cola del hilo que ya corre.

        Devuelve False si el hilo ya decidió que no le quedaba trabajo: en ese
        caso el enlace se perdería, y quien llama tiene que arrancar otro hilo.
        Sin el candado esa carrera ocurre de verdad —basta pegar un enlace en
        el instante en que termina el anterior— y el vídeo no se descarga nunca.
        """
        self._candado.lock()
        try:
            if self._cerrado or self._abort:
                return False
            self._pendientes.append(enlace)
            return True
        finally:
            self._candado.unlock()

    def abort(self) -> None:
        self._abort = True

    def _siguiente(self):
        self._candado.lock()
        try:
            if self._abort or not self._pendientes:
                self._cerrado = True
                return None
            return self._pendientes.pop(0)
        finally:
            self._candado.unlock()

    def run(self) -> None:
        while True:
            enlace = self._siguiente()
            if enlace is None:
                break
            try:
                ruta = youtube.download(
                    enlace,
                    with_video=self._with_video,
                    progress_callback=lambda f, t, u=enlace: self.progress.emit(u, f, t),
                    should_abort=lambda: self._abort,
                    on_notice=lambda n, m: self.notice.emit(n, m),
                )
                self.finished_one.emit(enlace, ruta)
            except Exception as e:
                self.failed_one.emit(enlace, str(e))
        self.all_done.emit()
