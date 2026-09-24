"""Reconocimiento de voz con faster-whisper (CTranslate2).

Mismos pesos que openai-whisper pero 4-8x mas rapido y sin PyTorch, lo que
permite congelar la aplicacion en un ejecutable de tamano razonable.
"""
from __future__ import annotations
from typing import Callable, List, Optional

import numpy as np

from core.models import Segment
from core.paths import models_dir

SAMPLE_RATE = 16000

# El modelo tarda varios segundos en cargar, asi que se cachea entre archivos.
# Clave: (nombre_modelo, device, compute_type).
_MODEL_CACHE: dict[tuple, object] = {}

# Fraccion minima del audio que el VAD debe conservar para considerarlo fiable.
# Una conversacion normal deja pasar el 70-95%; una clase con pausas largas,
# rara vez menos de la mitad. Por debajo de eso el filtro esta fallando, no
# recortando silencio.
_MIN_VAD_COVERAGE = 0.5

# La cobertura sola no basta. En una nota de voz de WhatsApp el VAD conservaba
# el 62 % —por encima del umbral— pero entre lo que tiraba habia un hueco de
# ocho segundos con el 83 % de la energia de la voz: no era silencio, era
# habla. Mirar cuanto se descarta no dice nada; hay que mirar QUE se descarta.
#
# Solo se miran los huecos largos. Los cortos son pausas entre palabras donde
# el VAD recorta bordes de la propia voz, y eso ensucia la medida sin aportar:
# ahi no se pierde contenido. Medido con ese filtro: 0.77 en el archivo roto
# frente a 0.26 en uno con silencio de verdad. El corte va entre los dos.
_LONG_GAP_SECS = 1.5
_MAX_DISCARDED_ENERGY = 0.45


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


_VAD_PARAMETERS = {"min_silence_duration_ms": 500}


def vad_speech(audio: np.ndarray) -> Optional[list]:
    """Tramos de voz segun el VAD (en samples), o None si no se puede medir."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:
        return None

    if len(audio) == 0:
        return None

    try:
        return get_speech_timestamps(audio, VadOptions(**_VAD_PARAMETERS))
    except Exception:
        return None


def vad_coverage(audio: np.ndarray) -> Optional[float]:
    """Fraccion del audio que el VAD marcaria como voz, o None si no se puede medir.

    Es la unica etapa de la cadena que puede descartar voz sin dejar rastro:
    lo que recorta no llega al modelo y no aparece en el resultado. Por eso se
    mide antes, en vez de confiar en que acerto.
    """
    speech = vad_speech(audio)
    if speech is None or len(audio) == 0:
        return None
    return sum(t["end"] - t["start"] for t in speech) / len(audio)


# Sin VAD, el modelo decodifica tambien el silencio y rellena cada ventana de
# 30 s con una frase inventada («gracias por ver el video»). Se filtran con dos
# reglas medidas sobre audio real, no adivinadas:
#
#   - Densidad: en la grabacion de prueba el habla mas lenta daba 4.67 car/s y
#     las alucinaciones 0.33-0.83. Un segmento largo casi vacio no es habla.
#   - Cola: todas caian pasado el ultimo tramo que el VAD reconocio. El VAD
#     peca de no detectar voz floja, nunca de inventarla, asi que su ultima
#     deteccion mas un margen de una ventana es un final seguro.
#
# Solo se aplican cuando el VAD va desactivado; con VAD el silencio ni llega
# al modelo y estas reglas no tendrian nada que hacer.
_LONG_SEGMENT_SECS = 20.0
_MIN_CHARS_PER_SEC = 2.0
_TAIL_MARGIN_SECS = 30.0


def discarded_energy(audio: np.ndarray, speech: Optional[list]) -> float:
    """Energia de lo que el VAD descarta, en proporcion a la que conserva.

    Cerca de 0 significa que lo recortado es silencio de verdad. Cerca de 1,
    que suena igual que la voz y por tanto probablemente lo sea.

    Devuelve 0.0 cuando no hay nada que comparar (sin VAD, o el VAD no recorta
    nada), para no desactivar el filtro por falta de datos.
    """
    if not speech or len(audio) == 0:
        return 0.0

    mascara = np.zeros(len(audio), dtype=bool)
    for tramo in speech:
        mascara[tramo["start"]:tramo["end"]] = True

    voz = audio[mascara]
    if len(voz) == 0:
        return 0.0
    rms_voz = float(np.sqrt(np.mean(np.square(voz))))
    if rms_voz <= 0:
        return 0.0

    # Solo los huecos largos: en los cortos el VAD recorta bordes de la propia
    # voz, lo que sube la medida sin que se pierda nada aprovechable.
    minimo = int(_LONG_GAP_SECS * SAMPLE_RATE)
    huecos = []
    anterior = 0
    for tramo in list(speech) + [{"start": len(audio), "end": len(audio)}]:
        if tramo["start"] - anterior >= minimo:
            huecos.append(audio[anterior:tramo["start"]])
        anterior = tramo["end"]

    if not huecos:
        return 0.0
    resto = np.concatenate(huecos)
    return float(np.sqrt(np.mean(np.square(resto)))) / rms_voz


def _describe_audio(audio: np.ndarray, seconds: float,
                    coverage: Optional[float]) -> str:
    """Resumen legible del material: duracion, volumen y cuanta voz se detecta."""
    minutes, secs = divmod(int(seconds), 60)
    parts = [f"{minutes}:{secs:02d} de audio"]

    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    if rms > 0:
        # dBFS: 0 es el maximo, los valores utiles son negativos. Por debajo de
        # -35 la grabacion es floja aunque se entienda bien al oido.
        dbfs = 20.0 * np.log10(rms)
        nivel = "bajo" if dbfs < -35 else "normal"
        parts.append(f"nivel {nivel} ({dbfs:.0f} dBFS)")

    if coverage is not None:
        parts.append(f"{coverage:.0%} de voz detectada")
    return " · ".join(parts)


def _is_implausible(start: float, end: float, text: str) -> bool:
    """True si el segmento es demasiado largo para lo poco que dice."""
    duration = end - start
    if duration < _LONG_SEGMENT_SECS:
        return False
    return len(text) / duration < _MIN_CHARS_PER_SEC


def transcribe(
    audio: np.ndarray,
    language: str = "es",
    model_name: str = "large-v3-turbo",
    progress_callback: Optional[Callable[[float], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
    on_notice: Optional[Callable[[str, str], None]] = None,
    vocabulary: str = "",
) -> List[Segment]:
    """Transcribe PCM float32 mono a 16 kHz y devuelve los segmentos crudos.

    El formateo (parrafos, timestamps, hablantes) NO ocurre aqui: es
    responsabilidad de core.formatter, para que ASR y OCR produzcan lo mismo.
    """
    model = load_model(model_name)

    total_secs = max(len(audio) / float(SAMPLE_RATE), 0.001)

    # El VAD de Silero da por silencio la voz lejana y reverberada de una sala,
    # y con un microfono a varios metros puede tragarse casi la grabacion
    # entera. Sondearlo cuesta ~2 s por cada 20 min de audio; perder el 90% de
    # una clase, todo. Si descarta demasiado, se transcribe el audio completo:
    # mas lento, pero nunca devuelve media transcripcion en silencio.
    speech = vad_speech(audio)
    coverage = (sum(t["end"] - t["start"] for t in speech) / len(audio)
                if speech is not None and len(audio) else None)
    ruido = discarded_energy(audio, speech)
    use_vad = (coverage is not None
               and coverage >= _MIN_VAD_COVERAGE
               and ruido <= _MAX_DISCARDED_ENERGY)

    # Frontera tras la cual ya no queda voz que transcribir. Solo tiene sentido
    # si el VAD detecto algo: sin detecciones no hay nada en que basarse.
    tail_cutoff = float("inf")
    if not use_vad and speech:
        tail_cutoff = speech[-1]["end"] / SAMPLE_RATE + _TAIL_MARGIN_SECS

    if on_notice:
        # Analisis previo: sale antes de empezar el trabajo pesado, para que se
        # vea con que material se esta trabajando en vez de descubrirlo al final.
        on_notice("info", _describe_audio(audio, total_secs, coverage))
        if not use_vad:
            # Se dice cual de las dos senales salto: no es lo mismo una
            # grabacion de sala que una nota de voz comprimida, y saberlo
            # ayuda a entender por que ese archivo concreto tarda mas.
            motivo = ("el filtro descartaría habla"
                      if ruido > _MAX_DISCARDED_ENERGY
                      else "se detecta poca voz")
            on_notice(
                "warn",
                f"{motivo}: se transcribe el audio completo, tardará más",
            )

    segments_iter, info = model.transcribe(
        audio,
        language=None if language == "auto" else language,
        task="transcribe",
        beam_size=5,
        vad_filter=use_vad,       # recorta silencios: mas rapido y menos alucinaciones
        vad_parameters=_VAD_PARAMETERS,
        condition_on_previous_text=False,   # evita bucles de texto repetido
        # «hotwords» y no «initial_prompt»: con condition_on_previous_text=False
        # el prompt inicial se descarta tras la primera ventana de 30 s, asi que
        # solo corregiria el principio del archivo. Los hotwords se reinyectan
        # en cada ventana (faster_whisper/transcribe.py, get_prompt).
        hotwords=vocabulary.strip() or None,
    )

    # La duracion que reporta el modelo es mas fiable que la del contenedor.
    if getattr(info, "duration", 0):
        total_secs = max(float(info.duration), 0.001)

    out: List[Segment] = []
    dropped = 0
    for seg in segments_iter:
        if should_abort is not None and should_abort():
            break
        # Un segmento que empieza despues del ultimo sample no existe.
        if float(seg.start) >= total_secs:
            continue
        text = (seg.text or "").strip()
        if text and not use_vad and (
            float(seg.start) >= tail_cutoff
            or _is_implausible(float(seg.start), float(seg.end), text)
        ):
            dropped += 1
            continue
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
    if dropped and on_notice:
        on_notice("warn",
                  f"{dropped} fragmento(s) inventados sobre el silencio, descartados")
    return out


def _load_error(model_name: str, exc: Exception) -> str:
    return (
        f"No se pudo cargar el modelo «{model_name}».\n\n"
        f"Detalle: {exc}\n\n"
        "Si el problema persiste, borra la carpeta de modelos para forzar una "
        f"descarga limpia:\n{models_dir()}"
    )
