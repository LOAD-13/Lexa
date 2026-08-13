"""Conversion de Segment[] a texto legible.

Es el unico lugar donde se decide como se ve la salida. Antes cada motor
formateaba por su cuenta y el exportador volvia a partir el texto, lo que
producia un unico parrafo gigante en DOCX y lineas sueltas tipo subtitulo en TXT.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import List

from core.models import FileItem, Segment

# Un silencio mayor a esto se interpreta como cambio de parrafo.
_PARAGRAPH_GAP = 1.2

# Un parrafo no crece indefinidamente aunque no haya pausas largas.
_MAX_PARAGRAPH_CHARS = 700


@dataclass
class Paragraph:
    start: float
    end: float
    text: str
    speaker: str | None = None
    page: int | None = None


def group_paragraphs(segments: List[Segment]) -> List[Paragraph]:
    """Agrupa segmentos en parrafos por pausa, cambio de hablante o de pagina."""
    paragraphs: List[Paragraph] = []
    current: List[Segment] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(s.text.strip() for s in current if s.text.strip())
        text = _tidy(text)
        if text:
            paragraphs.append(Paragraph(
                start=current[0].start,
                end=current[-1].end,
                text=text,
                speaker=current[0].speaker,
                page=current[0].page,
            ))
        current.clear()

    for seg in segments:
        if not seg.text.strip():
            continue
        if current:
            prev = current[-1]
            gap = seg.start - prev.end
            length = sum(len(s.text) for s in current)
            if (seg.speaker != prev.speaker
                    or seg.page != prev.page
                    or gap > _PARAGRAPH_GAP
                    or length > _MAX_PARAGRAPH_CHARS):
                flush()
        current.append(seg)

    flush()
    return paragraphs


def _tidy(text: str) -> str:
    """Limpia los artefactos tipicos de unir segmentos de Whisper."""
    text = " ".join(text.split())
    for punct in (".", ",", ";", ":", "!", "?", "…"):
        text = text.replace(f" {punct}", punct)
    text = text.replace("¿ ", "¿").replace("¡ ", "¡")
    return text.strip()


def format_timestamp(seconds: float, millis: bool = False, comma: bool = False) -> str:
    seconds = max(0.0, seconds)
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if not millis:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    ms = int(round((seconds - int(seconds)) * 1000))
    sep = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


# ─────────────────────────────────────────────────────────────────────────────
# Salidas
# ─────────────────────────────────────────────────────────────────────────────
def to_document(
    segments: List[Segment],
    include_timestamps: bool = False,
    include_speakers: bool = False,
    is_visual: bool = False,
) -> str:
    """Texto legible: parrafos separados por linea en blanco.

    Para imagenes y PDFs los segmentos son lineas visuales sin tiempo, asi que se
    respeta el salto de linea original en lugar de agrupar por pausas.
    """
    if not segments:
        return ""

    if is_visual:
        return _visual_document(segments)

    paragraphs = group_paragraphs(segments)
    blocks: List[str] = []
    last_speaker: str | None = None

    for para in paragraphs:
        prefix = ""
        if include_speakers and para.speaker and para.speaker != last_speaker:
            prefix += f"Hablante {para.speaker}:\n"
            last_speaker = para.speaker
        if include_timestamps:
            prefix += f"[{format_timestamp(para.start)}] "
        blocks.append(prefix + para.text)

    return "\n\n".join(blocks)


def _visual_document(segments: List[Segment]) -> str:
    """Documento para OCR: agrupa por pagina y conserva los saltos de linea."""
    pages: dict[int | None, List[str]] = {}
    order: List[int | None] = []
    for seg in segments:
        if seg.page not in pages:
            pages[seg.page] = []
            order.append(seg.page)
        if seg.text.strip():
            pages[seg.page].append(seg.text.strip())

    multi_page = len([p for p in order if p is not None]) > 1
    blocks: List[str] = []
    for page in order:
        body = "\n".join(pages[page])
        if not body.strip():
            continue
        if multi_page and page is not None:
            blocks.append(f"— Página {page} —\n\n{body}")
        else:
            blocks.append(body)
    return "\n\n".join(blocks)


def to_plain(segments: List[Segment]) -> str:
    """Texto corrido sin timestamps, hablantes ni estructura. Para copiar y pegar."""
    return _tidy(" ".join(s.text.strip() for s in segments if s.text.strip()))


def to_json(item: FileItem) -> str:
    payload = {
        "archivo": item.name,
        "tipo": item.kind.value,
        "duracion_segundos": round(item.duration, 2) or None,
        "segmentos": [
            {
                "inicio": round(s.start, 2),
                "fin": round(s.end, 2),
                "texto": s.text,
                **({"hablante": s.speaker} if s.speaker else {}),
                **({"pagina": s.page} if s.page else {}),
            }
            for s in item.segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_srt(segments: List[Segment], include_speakers: bool = False) -> str:
    """Subtitulos SRT. Usa los segmentos crudos, sin agrupar en parrafos."""
    lines: List[str] = []
    index = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        index += 1
        if include_speakers and seg.speaker:
            text = f"[Hablante {seg.speaker}] {text}"
        start = format_timestamp(seg.start, millis=True, comma=True)
        end = format_timestamp(max(seg.end, seg.start + 0.1), millis=True, comma=True)
        lines.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def to_vtt(segments: List[Segment], include_speakers: bool = False) -> str:
    """Subtitulos WebVTT."""
    lines: List[str] = ["WEBVTT", ""]
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if include_speakers and seg.speaker:
            text = f"<v Hablante {seg.speaker}>{text}"
        start = format_timestamp(seg.start, millis=True)
        end = format_timestamp(max(seg.end, seg.start + 0.1), millis=True)
        lines.append(f"{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def to_markdown(
    item: FileItem,
    include_timestamps: bool = False,
    include_speakers: bool = False,
) -> str:
    body = to_document(
        item.segments,
        include_timestamps=include_timestamps,
        include_speakers=include_speakers,
        is_visual=item.kind.is_visual,
    )
    header = [f"# {item.stem}", ""]
    meta = [f"**Archivo:** `{item.name}`"]
    if item.duration:
        meta.append(f"**Duración:** {format_timestamp(item.duration)}")
    words = len(body.split())
    meta.append(f"**Palabras:** {words:,}".replace(",", "."))
    header.append(" · ".join(meta))
    header.extend(["", "---", ""])
    return "\n".join(header) + body + "\n"


def word_count(text: str) -> int:
    return len(text.split())
