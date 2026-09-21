"""Worker de procesamiento en segundo plano (QThread).

Es el unico puente entre los motores (que no conocen Qt) y la interfaz.
Cada archivo emite progreso fraccional, de modo que la barra global del footer
puede avanzar de forma continua en vez de saltar de archivo en archivo.
"""
from __future__ import annotations
import time
import traceback
from datetime import datetime
from typing import List

from PyQt6.QtCore import QThread, pyqtSignal

from core.models import AppConfig, FileItem, FileKind, FileStatus, LogEntry, Segment
from core import formatter as F


class ProcessingWorker(QThread):
    file_started  = pyqtSignal(int)                 # file_id
    file_stage    = pyqtSignal(int, str)            # file_id, etiqueta visible
    file_progress = pyqtSignal(int, float)          # file_id, 0.0-1.0
    file_done     = pyqtSignal(int, object, str, float)  # id, segments, texto, duracion
    file_error    = pyqtSignal(int, str)            # file_id, mensaje
    log_entry     = pyqtSignal(object)              # LogEntry
    all_done      = pyqtSignal(bool)                # abortado?

    def __init__(self, files: List[FileItem], config: AppConfig, parent=None):
        super().__init__(parent)
        self.files = files
        self.config = config
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def _aborted(self) -> bool:
        return self._abort

    # ------------------------------------------------------------------
    def run(self) -> None:
        for item in self.files:
            if self._abort:
                break

            self.file_started.emit(item.id)
            self._log("info", f"Iniciando {item.name}")
            started_at = time.monotonic()

            try:
                if item.kind.is_speech:
                    segments, duration = self._process_speech(item)
                else:
                    segments, duration = self._process_visual(item)

                if self._abort:
                    break

                text = F.to_document(
                    segments,
                    include_timestamps=self.config.include_timestamps,
                    include_speakers=self.config.include_speakers,
                    is_visual=item.kind.is_visual,
                )
                elapsed = time.monotonic() - started_at
                self.file_done.emit(item.id, segments, text, duration)

                words = F.word_count(text)
                if words:
                    self._log("ok", f"{item.name} · {words:,} palabras en {elapsed:.0f}s"
                                    .replace(",", "."))
                else:
                    self._log("warn", f"{item.name}: no se detectó texto")

            except Exception as exc:
                if self._abort:
                    break
                message = str(exc) or exc.__class__.__name__
                self.file_error.emit(item.id, message)
                self._log("err", f"{item.name}: {message.splitlines()[0]}")
                traceback.print_exc()

        self.all_done.emit(self._abort)

    # ── Audio y video ────────────────────────────────────────────────────────
    def _process_speech(self, item: FileItem) -> tuple[List[Segment], float]:
        from core.engines import media, asr
        from core import cache

        if not self.config.transcribe_audio:
            self._log("warn", f"{item.name} omitido: la transcripción está desactivada")
            return [], 0.0

        # La cache se consulta antes de decodificar: si acierta, nos ahorramos
        # tambien leer el archivo entero, que en un video son varios segundos.
        cache_key = cache.key_for(item.path, self.config)
        cached = cache.load(cache_key)
        if cached is not None:
            self._stage(item, "Recuperando…", 0.5)
            self._log("info", f"{item.name}: recuperado de la caché, sin reprocesar")
            self._progress(item, 1.0)
            return cached, media.probe_duration(item.path)

        self._stage(item, "Leyendo audio…", 0.02)
        audio = media.load_audio(item.path)
        duration = len(audio) / media.SAMPLE_RATE

        diarize_on = self.config.include_speakers
        # Con diarizacion, la transcripcion ocupa el primer 70% de la barra.
        asr_span = 0.68 if diarize_on else 0.96

        self._stage(item, "Transcribiendo…", 0.04)
        segments = asr.transcribe(
            audio,
            language=self.config.language,
            model_name=self.config.whisper_model,
            progress_callback=lambda p: self._progress(item, 0.04 + p * asr_span),
            should_abort=self._aborted,
            on_notice=lambda level, msg: self._log(level, f"{item.name}: {msg}"),
            vocabulary=self.config.vocabulary,
        )

        if diarize_on and segments and not self._abort:
            segments = self._diarize(item, audio, segments)

        # Solo se guarda lo completo: una transcripcion cortada a medias por el
        # boton de parar volveria mañana como si fuera el resultado bueno.
        if not self._abort:
            cache.store(cache_key, segments)

        self._progress(item, 1.0)
        return segments, duration

    def _diarize(self, item: FileItem, audio, segments: List[Segment]) -> List[Segment]:
        from core.engines import diarize as D

        self._stage(item, "Identificando hablantes…", 0.72)
        try:
            turns = D.diarize(
                audio,
                progress_callback=lambda p: self._progress(item, 0.72 + p * 0.26),
            )
        except Exception as exc:
            # Un fallo aqui no debe perder la transcripcion, que es lo valioso.
            self._log("warn", f"{item.name}: diarización no disponible ({exc})")
            return segments

        segments = D.assign_speakers(segments, turns)
        speakers = len({s.speaker for s in segments if s.speaker})
        if speakers:
            self._log("info", f"{item.name}: {speakers} hablante(s) identificado(s)")
        return segments

    # ── Imagenes y PDF ───────────────────────────────────────────────────────
    def _process_visual(self, item: FileItem) -> tuple[List[Segment], float]:
        from core.engines import ocr, pdf

        if not self.config.ocr_images:
            self._log("warn", f"{item.name} omitido: el OCR está desactivado")
            return [], 0.0

        if item.kind == FileKind.PDF:
            self._stage(item, "Leyendo PDF…", 0.02)
            segments = pdf.extract_from_pdf(
                item.path,
                language=self.config.language,
                progress_callback=lambda p: self._progress(item, p),
                should_abort=self._aborted,
            )
            pages = len({s.page for s in segments if s.page})
            if pages:
                self._log("info", f"{item.name}: {pages} página(s) con texto")
            return segments, 0.0

        self._stage(item, "Extrayendo texto…", 0.05)
        segments = ocr.extract_from_image(
            item.path,
            language=self.config.language,
            progress_callback=lambda p: self._progress(item, p),
        )
        return segments, 0.0

    # ── Utilidades ───────────────────────────────────────────────────────────
    def _stage(self, item: FileItem, label: str, progress: float) -> None:
        self.file_stage.emit(item.id, label)
        self._progress(item, progress)

    def _progress(self, item: FileItem, value: float) -> None:
        self.file_progress.emit(item.id, max(0.0, min(1.0, value)))

    def _log(self, level: str, message: str) -> None:
        self.log_entry.emit(LogEntry(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message,
        ))
