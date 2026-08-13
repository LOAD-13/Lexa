"""Reconocimiento de voz con faster-whisper (CTranslate2).

Mismos pesos que openai-whisper pero 4-8x mas rapido y sin PyTorch, lo que
permite congelar la aplicacion en un ejecutable de tamano razonable.
"""
from __future__ import annotations
from typing import Callable, List, Optional

import numpy as np

from core.models import Segment
from core.paths import models_dir

# El modelo tarda varios segundos en cargar, asi que se cachea entre archivos.
# Clave: (nombre_modelo, device, compute_type).
_MODEL_CACHE: dict[tuple, object] = {}


def detect_device() -> tuple[str, str]:
    """Elige el mejor backend disponible: (device, compute_type).

    CUDA con float16 si hay una GPU NVIDIA utilizable; si no, CPU con int8,
    que es la cuantizacion mas rapida de CTranslate2 sin perdida notable.
    """
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def describe_device() -> str:
    device, compute = detect_device()
    return "GPU NVIDIA (float16)" if device == "cuda" else f"CPU ({compute})"


def is_model_downloaded(model_name: str) -> bool:
    """True si el modelo ya esta en la cache local y no hay que descargarlo."""
    try:
        from faster_whisper.utils import download_model
        download_model(model_name, output_dir=None,
                       cache_dir=models_dir(), local_files_only=True)
        return True
    except Exception:
        return False


def ensure_model(model_name: str) -> str:
    """Descarga el modelo si falta y devuelve su ruta local."""
    from faster_whisper.utils import download_model
    return download_model(model_name, output_dir=None, cache_dir=models_dir())


def load_model(model_name: str):
    """Carga (y cachea) el modelo. Descarga automaticamente si falta."""
    device, compute_type = detect_device()
    key = (model_name, device, compute_type)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=models_dir(),
            cpu_threads=0,      # 0 = usa todos los nucleos disponibles
        )
    except Exception as exc:
        if device == "cuda":
            # La GPU existe pero cuDNN/cuBLAS puede faltar: caer a CPU en vez de fallar.
            model = WhisperModel(
                model_name, device="cpu", compute_type="int8",
                download_root=models_dir(), cpu_threads=0,
            )
            _MODEL_CACHE[(model_name, "cpu", "int8")] = model
            return model
        raise RuntimeError(_load_error(model_name, exc)) from exc

    _MODEL_CACHE[key] = model
    return model


def unload_models() -> None:
    """Libera la memoria de los modelos cacheados."""
    _MODEL_CACHE.clear()


def transcribe(
    audio: np.ndarray,
    language: str = "es",
    model_name: str = "large-v3-turbo",
    progress_callback: Optional[Callable[[float], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
) -> List[Segment]:
    """Transcribe PCM float32 mono a 16 kHz y devuelve los segmentos crudos.

    El formateo (parrafos, timestamps, hablantes) NO ocurre aqui: es
    responsabilidad de core.formatter, para que ASR y OCR produzcan lo mismo.
    """
    model = load_model(model_name)

    total_secs = max(len(audio) / 16000.0, 0.001)

    segments_iter, info = model.transcribe(
        audio,
        language=None if language == "auto" else language,
        task="transcribe",
        beam_size=5,
        vad_filter=True,          # recorta silencios: mas rapido y menos alucinaciones
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,   # evita bucles de texto repetido
    )

    # La duracion que reporta el modelo es mas fiable que la del contenedor.
    if getattr(info, "duration", 0):
        total_secs = max(float(info.duration), 0.001)

    out: List[Segment] = []
    for seg in segments_iter:
        if should_abort is not None and should_abort():
            break
        text = (seg.text or "").strip()
        if text:
            out.append(Segment(
                start=float(seg.start),
                end=float(seg.end),
                text=text,
            ))
        if progress_callback:
            progress_callback(min(0.99, float(seg.end) / total_secs))

    if progress_callback:
        progress_callback(1.0)
    return out


def _load_error(model_name: str, exc: Exception) -> str:
    return (
        f"No se pudo cargar el modelo «{model_name}».\n\n"
        f"Detalle: {exc}\n\n"
        "Si el problema persiste, borra la carpeta de modelos para forzar una "
        f"descarga limpia:\n{models_dir()}"
    )
