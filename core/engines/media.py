"""Decodificacion de audio y video con PyAV.

PyAV trae ffmpeg compilado dentro de su wheel, asi que no hace falta ningun
binario instalado en el sistema. Esto cubre tanto los archivos de audio como la
extraccion de la pista de audio de un video.
"""
from __future__ import annotations
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000


class NoAudioTrackError(RuntimeError):
    """El archivo no contiene ninguna pista de audio utilizable."""


def probe_duration(path: str) -> float:
    """Duracion en segundos, o 0.0 si no se puede determinar."""
    try:
        import av
    except ImportError as exc:
        raise RuntimeError(_missing_av()) from exc

    try:
        with av.open(path) as container:
            if container.duration is not None:
                return float(container.duration) / av.time_base
            for stream in container.streams:
                if stream.duration is not None and stream.time_base is not None:
                    return float(stream.duration * stream.time_base)
    except Exception:
        pass
    return 0.0


def has_audio_track(path: str) -> bool:
    try:
        import av
        with av.open(path) as container:
            return len(container.streams.audio) > 0
    except Exception:
        return False


def load_audio(path: str) -> np.ndarray:
    """Decodifica cualquier audio o video a PCM float32 mono a 16 kHz.

    Es el formato que esperan tanto faster-whisper como sherpa-onnx, de modo que
    el archivo se decodifica una sola vez y se reutiliza para ambos.
    """
    try:
        from faster_whisper.audio import decode_audio
    except ImportError as exc:
        raise RuntimeError(_missing_av()) from exc

    try:
        audio = decode_audio(path, sampling_rate=SAMPLE_RATE)
    except Exception as exc:
        raise _decode_error(path, exc) from exc

    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        raise NoAudioTrackError(
            "El archivo no contiene audio audible: la pista está vacía."
        )
    return audio


def _decode_error(path: str, exc: Exception) -> Exception:
    """Distingue los tres motivos por los que falla la decodificación."""
    import os

    try:
        if os.path.getsize(path) == 0:
            return NoAudioTrackError("El archivo está vacío (0 bytes).")
    except OSError:
        pass

    # Si el contenedor ni siquiera se puede abrir, el archivo está dañado;
    # si se abre pero no tiene pistas de audio, es un video mudo.
    try:
        import av
        with av.open(path) as container:
            if not container.streams.audio:
                return NoAudioTrackError(
                    "El archivo no contiene una pista de audio.\n\n"
                    "Si es un video, comprueba que no sea un clip mudo."
                )
    except Exception:
        return RuntimeError(
            "El archivo está dañado o su formato no se reconoce.\n\n"
            f"Detalle: {exc}"
        )

    return RuntimeError(
        f"No se pudo decodificar el audio del archivo.\n\nDetalle: {exc}"
    )


def _missing_av() -> str:
    return (
        "Falta la librería de decodificación de audio (PyAV).\n\n"
        "Reinstala las dependencias con:  pip install av faster-whisper"
    )
