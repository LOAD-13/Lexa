"""OCR de imagenes.

Prioridad:
1. RapidOCR (onnxruntime) — funciona sin instalar nada en el sistema.
2. pytesseract — solo si el usuario ya tiene el binario de Tesseract.

Las imagenes se cargan siempre con Pillow y se pasan como ndarray: OpenCV no
sabe abrir rutas con acentos o eñes en Windows, y este es un proyecto en español.
"""
from __future__ import annotations
import os
import shutil
from typing import Callable, List, Optional

import numpy as np

from core.models import Segment
from core.paths import models_dir

_ENGINE_CACHE: dict = {}

# Descartar detecciones con confianza muy baja: suelen ser ruido o bordes.
_MIN_CONFIDENCE = 0.35


def latin_model_paths() -> tuple[str, str]:
    """Rutas del modelo de reconocimiento latino: (modelo onnx, diccionario)."""
    base = os.path.join(models_dir(), "ocr")
    return (
        os.path.join(base, "latin_rec.onnx"),
        os.path.join(base, "latin_keys.txt"),
    )


def latin_available() -> bool:
    return all(os.path.isfile(p) for p in latin_model_paths())


def load_image_array(path: str) -> np.ndarray:
    """Carga una imagen a un ndarray RGB, tolerando rutas no ASCII."""
    from PIL import Image, ImageOps
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)     # respeta la rotación de la cámara
        return np.array(img.convert("RGB"))


def _rapid_engine():
    """Motor de RapidOCR con el modelo de reconocimiento latino si esta disponible.

    El modelo que trae RapidOCR por defecto esta entrenado en chino e ingles: su
    diccionario no contiene á é í ó ú ñ ü, asi que devuelve «traduccion» en vez
    de «traducción». El modelo latino corrige eso.
    """
    if "rapid" in _ENGINE_CACHE:
        return _ENGINE_CACHE["rapid"]

    from rapidocr_onnxruntime import RapidOCR

    onnx_path, keys_path = latin_model_paths()
    if latin_available():
        engine = RapidOCR(rec_model_path=onnx_path, rec_keys_path=keys_path)
    else:
        engine = RapidOCR()

    _ENGINE_CACHE["rapid"] = engine
    return engine


def tesseract_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        return True
    except ImportError:
        return False


def extract_from_array(
    image: np.ndarray,
    page: Optional[int] = None,
    prefer_tesseract: bool = False,
    language: str = "es",
) -> List[Segment]:
    """Extrae texto de una imagen ya cargada en memoria."""
    if prefer_tesseract and tesseract_available():
        try:
            text = _tesseract(image, language)
            if text.strip():
                return [Segment(text=line, page=page)
                        for line in text.splitlines() if line.strip()]
        except Exception:
            pass   # cae a RapidOCR

    engine = _rapid_engine()
    result, _ = engine(image)
    if not result:
        return []

    return [Segment(text=line, page=page) for line in _to_lines(result)]


def extract_from_image(
    path: str,
    language: str = "es",
    prefer_tesseract: bool = False,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> List[Segment]:
    """Extrae texto de un archivo de imagen."""
    if progress_callback:
        progress_callback(0.15)
    try:
        image = load_image_array(path)
    except Exception as exc:
        raise RuntimeError(f"No se pudo abrir la imagen.\n\nDetalle: {exc}") from exc

    if progress_callback:
        progress_callback(0.35)

    segments = extract_from_array(
        image, prefer_tesseract=prefer_tesseract, language=language
    )

    if progress_callback:
        progress_callback(1.0)
    return segments


def _to_lines(result: list) -> List[str]:
    """Convierte las cajas detectadas en lineas de texto en orden de lectura.

    RapidOCR devuelve una caja por fragmento. Los fragmentos cuyos centros
    verticales estan cerca pertenecen visualmente a la misma linea, asi que se
    agrupan y se ordenan de izquierda a derecha.
    """
    boxes = []
    for entry in result:
        if len(entry) < 2:
            continue
        box, text = entry[0], entry[1]
        score = entry[2] if len(entry) > 2 else 1.0
        text = str(text).strip()
        if not text or score < _MIN_CONFIDENCE:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append({
            "text": text,
            "cy": sum(ys) / len(ys),
            "x": min(xs),
            "h": max(ys) - min(ys),
        })

    if not boxes:
        return []

    boxes.sort(key=lambda b: b["cy"])
    median_h = sorted(b["h"] for b in boxes)[len(boxes) // 2] or 10
    tolerance = median_h * 0.6

    lines: List[List[dict]] = [[boxes[0]]]
    for b in boxes[1:]:
        if abs(b["cy"] - lines[-1][-1]["cy"]) <= tolerance:
            lines[-1].append(b)
        else:
            lines.append([b])

    out: List[str] = []
    for line in lines:
        line.sort(key=lambda b: b["x"])
        out.append(" ".join(b["text"] for b in line))
    return out


def _tesseract(image: np.ndarray, language: str) -> str:
    import pytesseract
    from PIL import Image

    lang_map = {
        "es": "spa", "en": "eng", "pt": "por",
        "fr": "fra", "it": "ita", "de": "deu",
    }
    lang = lang_map.get(language)
    kwargs = {"lang": lang} if lang else {}
    return pytesseract.image_to_string(Image.fromarray(image), **kwargs)


def unload() -> None:
    _ENGINE_CACHE.clear()
