"""Diarizacion de hablantes con sherpa-onnx.

Usa pyannote-segmentation-3.0 exportado a ONNX mas embeddings CAM++ del proyecto
3D-Speaker. Es la misma arquitectura que pyannote.audio pero corriendo sobre
onnxruntime, por lo que no arrastra PyTorch ni requiere token de HuggingFace.
"""
from __future__ import annotations
import os
from typing import Callable, List, Optional

import numpy as np

from core.models import Segment
from core.paths import models_dir

SAMPLE_RATE = 16000

_SEG_DIR = os.path.join("diarization", "sherpa-onnx-pyannote-segmentation-3-0")
_EMB_FILE = os.path.join("diarization", "campplus_sv_zh_en_16k.onnx")

_CACHE: dict = {}


def _seg_model_path() -> str:
    return os.path.join(models_dir(), _SEG_DIR, "model.onnx")


def _emb_model_path() -> str:
    return os.path.join(models_dir(), _EMB_FILE)


def is_available() -> bool:
    """True si ambos modelos estan descargados."""
    return os.path.isfile(_seg_model_path()) and os.path.isfile(_emb_model_path())


def _build():
    """Construye (y cachea) el diarizador. Cargarlo cuesta ~1s."""
    if "diarizer" in _CACHE:
        return _CACHE["diarizer"]

    import sherpa_onnx

    if not is_available():
        raise RuntimeError(
            "Los modelos de diarización no están descargados.\n\n"
            "Desactiva «Identificar hablantes» o reinicia la aplicación para "
            "que se descarguen."
        )

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=_seg_model_path()
            ),
            num_threads=max(1, (os.cpu_count() or 2) // 2),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=_emb_model_path(),
            num_threads=max(1, (os.cpu_count() or 2) // 2),
        ),
        # -1 = deduce automaticamente cuantos hablantes hay usando el umbral.
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError(
            "La configuración de diarización no es válida. "
            "Borra la carpeta de modelos para forzar una descarga limpia."
        )

    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    _CACHE["diarizer"] = diarizer
    return diarizer


def diarize(
    audio: np.ndarray,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> List[tuple[float, float, int]]:
    """Devuelve los turnos de habla como (inicio, fin, id_hablante)."""
    diarizer = _build()

    def _cb(processed: int, total: int, _arg=None) -> int:
        if progress_callback and total > 0:
            progress_callback(min(1.0, processed / total))
        return 0

    result = diarizer.process(audio, callback=_cb)
    return [(float(s.start), float(s.end), int(s.speaker))
            for s in result.sort_by_start_time()]


def assign_speakers(
    segments: List[Segment],
    turns: List[tuple[float, float, int]],
) -> List[Segment]:
    """Etiqueta cada segmento de texto con el hablante que mas lo solapa.

    Los ids se renumeran por orden de aparicion, para que el primero en hablar
    sea siempre «Hablante 1» sin importar como los agrupo el clustering.
    """
    if not turns:
        return segments

    renumber: dict[int, str] = {}

    for seg in segments:
        best_overlap = 0.0
        best_speaker: Optional[int] = None
        for start, end, speaker in turns:
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker

        if best_speaker is None:
            # Sin solapamiento: usar el turno cuyo centro este mas cerca.
            mid = (seg.start + seg.end) / 2
            best_speaker = min(
                turns, key=lambda t: abs((t[0] + t[1]) / 2 - mid)
            )[2]

        if best_speaker not in renumber:
            renumber[best_speaker] = str(len(renumber) + 1)
        seg.speaker = renumber[best_speaker]

    return segments


def unload() -> None:
    _CACHE.clear()
