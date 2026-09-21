"""Exportacion de resultados a TXT, MD, PDF, DOCX, SRT y VTT."""
from __future__ import annotations
import os
import re
from typing import List

from core.models import AppConfig, FileItem, FileKind
from core.paths import resource
from core import formatter as F

# Formatos que solo tienen sentido para audio y video (necesitan tiempos).
SUBTITLE_FORMATS = {"srt", "vtt"}


class NothingToExportError(RuntimeError):
    """No hay ningun resultado exportable con la configuracion actual."""


def exportable(items: List[FileItem], config: AppConfig) -> List[FileItem]:
    """Items con contenido real. Un resultado vacio no genera archivo."""
    out = [f for f in items if f.segments and (f.result or "").strip()]
    if config.export_format in SUBTITLE_FORMATS:
        out = [f for f in out if f.kind.is_speech]
    return out


def export_results(items: List[FileItem], config: AppConfig) -> List[str]:
    """Exporta los resultados. Devuelve las rutas creadas."""
    done = exportable(items, config)
    if not done:
        if config.export_format in SUBTITLE_FORMATS:
            raise NothingToExportError(
                "Los subtítulos (SRT/VTT) solo se pueden generar a partir de "
                "audio o video.\n\nElige otro formato de exportación."
            )
        raise NothingToExportError(
            "No hay resultados para exportar.\n\nProcesa los archivos primero."
        )

    # Los subtitulos siempre van uno por archivo: un SRT combinado no tiene sentido.
    merged = config.output_mode == "merged" and config.export_format not in SUBTITLE_FORMATS

    if merged:
        # Un documento combinado no tiene un origen unico: se deja junto al
        # primer archivo del lote, que es el que abre la tanda.
        return [_export_merged(done, config, _ensure_dir(output_dir_for(done[0], config)))]

    return [_export_single(item, config, _ensure_dir(output_dir_for(item, config)))
            for item in done]


def output_dir_for(item: FileItem, config: AppConfig) -> str:
    """Carpeta donde dejar el resultado de ese archivo.

    Junto al original salvo que se haya elegido una carpeta a mano. Si el
    origen esta en un sitio donde no se puede escribir (una unidad de solo
    lectura, una carpeta de red sin permiso), se cae a la carpeta configurada
    en vez de fallar y perder la transcripcion.
    """
    if not config.save_next_to_source:
        return config.save_location

    carpeta = os.path.dirname(os.path.abspath(item.path))
    if os.path.isdir(carpeta) and os.access(carpeta, os.W_OK):
        return carpeta
    return config.save_location


def _ensure_dir(out_dir: str) -> str:
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"No se puede escribir en la carpeta de guardado:\n{out_dir}\n\n"
            f"Detalle: {exc}"
        ) from exc
    return out_dir


# ─────────────────────────────────────────────────────────────────────────────
def _export_single(item: FileItem, config: AppConfig, out_dir: str) -> str:
    path = _unique_path(out_dir, _safe_name(item.stem), config.export_format)
    content = _render(item, config)
    _write(content, path, config.export_format, title=item.name)
    return path


def _export_merged(items: List[FileItem], config: AppConfig, out_dir: str) -> str:
    path = _unique_path(out_dir, "Lexa - resultado combinado", config.export_format)

    if config.export_format == "md":
        parts = [f"# Resultado combinado\n\n{len(items)} archivo(s) procesado(s).\n"]
        for item in items:
            parts.append(f"\n---\n\n## {item.name}\n\n{_body(item, config)}")
        content = "\n".join(parts)
    else:
        parts = []
        for item in items:
            # ASCII a propósito: los caracteres de dibujo de caja no existen en
            # las fuentes que se embeben en el PDF y saldrían como cuadros.
            rule = "=" * max(len(item.name), 30)
            parts.append(f"{rule}\n{item.name}\n{rule}\n\n{_body(item, config)}")
        content = "\n\n\n".join(parts)

    _write(content, path, config.export_format, title="Resultado combinado")
    return path


def _body(item: FileItem, config: AppConfig) -> str:
    return F.to_document(
        item.segments,
        include_timestamps=config.include_timestamps,
        include_speakers=config.include_speakers,
        is_visual=item.kind.is_visual,
    )


def _render(item: FileItem, config: AppConfig) -> str:
    fmt = config.export_format
    if fmt == "srt":
        return F.to_srt(item.segments, include_speakers=config.include_speakers)
    if fmt == "vtt":
        return F.to_vtt(item.segments, include_speakers=config.include_speakers)
    if fmt == "md":
        return F.to_markdown(
            item,
            include_timestamps=config.include_timestamps,
            include_speakers=config.include_speakers,
        )
    return _body(item, config)


def _safe_name(stem: str) -> str:
    """Quita los caracteres que Windows no admite en un nombre de archivo."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return (cleaned or "resultado")[:120]


def _unique_path(out_dir: str, stem: str, ext: str) -> str:
    """Evita pisar un archivo existente anadiendo (2), (3)…"""
    path = os.path.join(out_dir, f"{stem}.{ext}")
    if not os.path.exists(path):
        return path
    for n in range(2, 1000):
        candidate = os.path.join(out_dir, f"{stem} ({n}).{ext}")
        if not os.path.exists(candidate):
            return candidate
    return path


def _write(content: str, path: str, fmt: str, title: str = "") -> None:
    if fmt in ("txt", "srt", "vtt", "md"):
        _write_text(content, path, fmt, title)
    elif fmt == "pdf":
        _write_pdf(content, path, title)
    elif fmt == "docx":
        _write_docx(content, path, title)
    else:
        raise ValueError(f"Formato de exportación desconocido: {fmt}")


def _write_text(content: str, path: str, fmt: str, title: str) -> None:
    # SRT y VTT no llevan encabezado: romperia el formato para los reproductores.
    # Markdown ya trae el suyo desde el formatter.
    header = ""
    if fmt == "txt" and title:
        header = f"{title}\n{'=' * len(title)}\n\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + content)


def _write_pdf(content: str, path: str, title: str) -> None:
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError as exc:
        raise RuntimeError(
            "Falta la librería de PDF.\n\nInstálala con:  pip install fpdf2"
        ) from exc

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    family = _register_unicode_font(pdf)

    # multi_cell deja el cursor en el margen derecho por defecto, con lo que la
    # siguiente llamada se queda sin ancho. Hay que devolverlo al margen izquierdo.
    def line_out(text: str, height: float) -> None:
        pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if title:
        pdf.set_font(family, "B", 15)
        line_out(title, 8)
        pdf.ln(2)
        pdf.set_draw_color(190, 190, 190)
        y = pdf.get_y()
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(6)

    for block in content.split("\n"):
        stripped = block.strip()
        if not stripped:
            pdf.ln(3.5)
            continue
        # Los encabezados de hablante y los separadores de página van en negrita.
        is_heading = bool(
            re.fullmatch(r"Hablante \d+:", stripped)
            or re.fullmatch(r"[—-]\s*Página \d+\s*[—-]", stripped)
            or re.fullmatch(r"=+", stripped)
        )
        pdf.set_font(family, "B" if is_heading else "", 11)
        line_out(block, 6.5)

    pdf.output(path)


def _register_unicode_font(pdf) -> str:
    """Registra una fuente TrueType para que los acentos y la ñ salgan bien.

    Las fuentes internas de PDF solo cubren latin-1, que destruye el texto en
    español. Se prueba primero la fuente que viaja con la app y, si falta, las
    del sistema. Solo si no hay ninguna se cae a Helvetica.
    """
    candidates = [
        ("Noto", resource("fonts", "NotoSans-Regular.ttf"),
                 resource("fonts", "NotoSans-Bold.ttf")),
        ("DejaVu", r"C:\Windows\Fonts\DejaVuSans.ttf",
                   r"C:\Windows\Fonts\DejaVuSans-Bold.ttf"),
        ("Arial", r"C:\Windows\Fonts\arial.ttf",
                  r"C:\Windows\Fonts\arialbd.ttf"),
        ("Calibri", r"C:\Windows\Fonts\calibri.ttf",
                    r"C:\Windows\Fonts\calibrib.ttf"),
        ("DejaVuNix", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for family, regular, bold in candidates:
        if not os.path.isfile(regular):
            continue
        try:
            pdf.add_font(family, "", regular)
            if os.path.isfile(bold):
                pdf.add_font(family, "B", bold)
            else:
                pdf.add_font(family, "B", regular)
            return family
        except Exception:
            continue
    return "Helvetica"


def _write_docx(content: str, path: str, title: str) -> None:
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as exc:
        raise RuntimeError(
            "Falta la librería de Word.\n\nInstálala con:  pip install python-docx"
        ) from exc

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(8)

    if title:
        doc.add_heading(title, level=1)

    # El contenido ya viene separado en parrafos por linea en blanco.
    # Dentro de un parrafo, los saltos simples se conservan como saltos de linea.
    for block in content.split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        para = doc.add_paragraph()
        for i, line in enumerate(lines):
            if i:
                para.add_run().add_break()
            run = para.add_run(line)
            # «Hablante 3:» en su propia linea se marca en negrita.
            if re.fullmatch(r"Hablante \d+:", line.strip()):
                run.bold = True

    doc.save(path)
