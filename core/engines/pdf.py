"""Extraccion de texto de PDFs, pagina por pagina.

Muchos PDFs tienen la letra como imagen (escaneos, fotos de documentos), donde
la extraccion de texto normal devuelve vacio. Esta implementacion decide por
pagina: si el texto embebido es pobre, rasteriza la pagina y le aplica OCR.
"""
from __future__ import annotations
from typing import Callable, List, Optional

import numpy as np

from core.models import Segment
from core.engines.ocr import extract_from_array

# Por debajo de este numero de caracteres se asume que la pagina es una imagen.
_MIN_CHARS_FOR_TEXT_LAYER = 25

# 300 dpi: el punto donde el OCR deja de mejorar y solo gasta memoria.
_OCR_DPI = 300


def page_count(path: str) -> int:
    import pymupdf
    with pymupdf.open(path) as doc:
        return doc.page_count


def extract_from_pdf(
    path: str,
    language: str = "es",
    prefer_tesseract: bool = False,
    progress_callback: Optional[Callable[[float], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
) -> List[Segment]:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "Falta la librería de PDF (PyMuPDF).\n\n"
            "Reinstala las dependencias con:  pip install PyMuPDF"
        ) from exc

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo abrir el PDF. Puede estar dañado o protegido con contraseña.\n\n"
            f"Detalle: {exc}"
        ) from exc

    segments: List[Segment] = []
    try:
        if doc.needs_pass:
            raise RuntimeError(
                "El PDF está protegido con contraseña y no se puede leer."
            )

        total = max(doc.page_count, 1)
        for index in range(doc.page_count):
            if should_abort is not None and should_abort():
                break

            page = doc[index]
            page_no = index + 1

            text = (page.get_text("text") or "").strip()
            if len(text) >= _MIN_CHARS_FOR_TEXT_LAYER:
                segments.extend(
                    Segment(text=line.strip(), page=page_no)
                    for line in text.splitlines() if line.strip()
                )
            else:
                segments.extend(
                    _ocr_page(page, page_no, language, prefer_tesseract)
                )

            if progress_callback:
                progress_callback((index + 1) / total)
    finally:
        doc.close()

    if progress_callback:
        progress_callback(1.0)
    return segments


def _ocr_page(page, page_no: int, language: str, prefer_tesseract: bool) -> List[Segment]:
    """Rasteriza una pagina sin capa de texto y le pasa OCR."""
    import pymupdf

    zoom = _OCR_DPI / 72.0
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    if pixmap.n == 4:      # RGBA -> RGB
        image = image[:, :, :3]
    elif pixmap.n == 1:    # escala de grises -> RGB
        image = np.repeat(image, 3, axis=2)

    return extract_from_array(
        image, page=page_no, prefer_tesseract=prefer_tesseract, language=language
    )
