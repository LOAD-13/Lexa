"""Decodificacion de audio y video con PyAV.

PyAV trae ffmpeg compilado dentro de su wheel, asi que no hace falta ningun
binario instalado en el sistema. Esto cubre tanto los archivos de audio como la
extraccion de la pista de audio de un video.
"""
from __future__ import annotations
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000

# Tramos mas cortos que esto se descartan: salen de un clic con pulso
# tembloroso, no de una seleccion deliberada.
MIN_RANGE_SECS = 0.3


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


def normalize_ranges(ranges, duration: float = 0.0) -> list:
    """Deja los tramos ordenados, sin solapes y dentro del archivo.

    Acepta lo que venga de la interfaz —invertidos, solapados, fuera de
    rango— y devuelve algo con lo que se pueda decodificar sin sorpresas.
    Una lista vacia significa «el archivo entero», que es el comportamiento
    de siempre.
    """
    if not ranges:
        return []

    limpios = []
    for inicio, fin in ranges:
        a, b = float(min(inicio, fin)), float(max(inicio, fin))
        a = max(0.0, a)
        if duration > 0:
            b = min(b, duration)
        if b - a >= MIN_RANGE_SECS:
            limpios.append((a, b))

    if not limpios:
        return []

    # Fundir los que se tocan: dos tramos solapados producirian el mismo audio
    # dos veces en la transcripcion.
    limpios.sort()
    fundidos = [limpios[0]]
    for a, b in limpios[1:]:
        ultimo_a, ultimo_b = fundidos[-1]
        if a <= ultimo_b:
            fundidos[-1] = (ultimo_a, max(ultimo_b, b))
        else:
            fundidos.append((a, b))
    return fundidos


def map_time(t: float, ranges) -> float:
    """Convierte un instante del audio recortado al del archivo original.

    Sin tramos devuelve el mismo valor. Con ellos, el segundo 0 del audio
    concatenado es el inicio del primer tramo, y asi sucesivamente: es lo que
    permite que un SRT sacado de un recorte siga cuadrando con el video
    completo.
    """
    if not ranges:
        return t

    restante = max(0.0, t)
    for inicio, fin in ranges:
        largo = fin - inicio
        if restante <= largo:
            return inicio + restante
        restante -= largo
    # Mas alla del final: se ancla al fin del ultimo tramo.
    return ranges[-1][1]


def format_ranges(ranges) -> str:
    """«03:12-08:40, 40:05-45:19», para el registro de la aplicacion."""
    def reloj(t: float) -> str:
        minutos, segundos = divmod(int(t), 60)
        horas, minutos = divmod(minutos, 60)
        return (f"{horas}:{minutos:02d}:{segundos:02d}" if horas
                else f"{minutos:02d}:{segundos:02d}")
    return ", ".join(f"{reloj(a)}-{reloj(b)}" for a, b in ranges)


def load_audio(path: str, ranges=None) -> np.ndarray:
    """Decodifica cualquier audio o video a PCM float32 mono a 16 kHz.

    Es el formato que esperan tanto faster-whisper como sherpa-onnx, de modo que
    el archivo se decodifica una sola vez y se reutiliza para ambos.

    Con `ranges` decodifica solo esos tramos y los concatena, de modo que
    transcribir cinco minutos de una clase de una hora cuesta cinco minutos de
    proceso y no una hora.
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

    tramos = normalize_ranges(ranges, len(audio) / SAMPLE_RATE)
    if not tramos:
        return audio

    trozos = [audio[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)] for a, b in tramos]
    trozos = [t for t in trozos if len(t)]
    if not trozos:
        raise NoAudioTrackError(
            "Los tramos seleccionados no contienen audio."
        )
    return np.concatenate(trozos)


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
