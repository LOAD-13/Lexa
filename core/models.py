"""Modelos de datos compartidos por toda la aplicacion."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List
import os
import re

from core.paths import default_output_dir


class FileStatus(Enum):
    PENDING    = "pendiente"
    PROCESSING = "procesando"
    DONE       = "completado"
    ERROR      = "error"


class FileKind(Enum):
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE = "imagen"
    PDF   = "pdf"

    @property
    def is_speech(self) -> bool:
        """True si el archivo se procesa con reconocimiento de voz."""
        return self in (FileKind.AUDIO, FileKind.VIDEO)

    @property
    def is_visual(self) -> bool:
        """True si el archivo se procesa con OCR."""
        return self in (FileKind.IMAGE, FileKind.PDF)


@dataclass
class Segment:
    """Unidad comun de salida. La producen tanto el ASR como el OCR."""
    start: float = 0.0            # segundos
    end: float = 0.0
    text: str = ""
    speaker: Optional[str] = None  # "1", "2", ... tras la diarizacion
    page: Optional[int] = None     # numero de pagina (PDF)


@dataclass
class FileItem:
    id: int
    path: str
    kind: FileKind
    status: FileStatus = FileStatus.PENDING
    progress: float = 0.0
    stage: str = ""                                  # etiqueta visible: "Transcribiendo…"
    segments: List[Segment] = field(default_factory=list)
    result: Optional[str] = None                     # texto ya formateado
    error: Optional[str] = None
    duration: float = 0.0                            # segundos de audio/video
    elapsed: float = 0.0                             # segundos que tardo en procesarse

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0]

    @property
    def size_str(self) -> str:
        try:
            s = os.path.getsize(self.path)
        except OSError:
            return "?"
        if s < 1024:
            return f"{s} B"
        if s < 1024 * 1024:
            return f"{s / 1024:.1f} KB"
        if s < 1024 * 1024 * 1024:
            return f"{s / 1024 / 1024:.1f} MB"
        return f"{s / 1024 / 1024 / 1024:.2f} GB"


@dataclass
class LogEntry:
    timestamp: str
    level: str   # info | ok | warn | err
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Configuracion
# ─────────────────────────────────────────────────────────────────────────────
WHISPER_MODELS: list[tuple[str, str, str]] = [
    # (valor, etiqueta, tamano de descarga aproximado)
    ("tiny",             "Tiny",   "75 MB"),
    ("base",             "Base",   "145 MB"),
    ("small",            "Small",  "480 MB"),
    ("medium",           "Medium", "1.5 GB"),
    ("large-v3-turbo",   "Turbo",  "1.6 GB"),
    ("large-v3",         "Large",  "3.1 GB"),
]

LANGUAGES: list[tuple[str, str]] = [
    ("es",   "Español"),
    ("en",   "Inglés"),
    ("pt",   "Portugués"),
    ("fr",   "Francés"),
    ("it",   "Italiano"),
    ("de",   "Alemán"),
    ("auto", "Detectar automáticamente"),
]

EXPORT_FORMATS = ("txt", "md", "pdf", "docx", "srt", "vtt")

# Tope del diccionario de terminos. faster-whisper recorta los hotwords a la
# mitad del contexto del modelo (~223 tokens); pasarse no da error, solo hace
# que se pierdan en silencio los ultimos terminos. Se corta antes y por palabra
# entera para que el usuario no acabe con un termino partido a la mitad.
VOCABULARY_MAX_CHARS = 400


def normalize_vocabulary(text: str) -> str:
    """Deja el diccionario en una linea de terminos separados por comas."""
    if not text:
        return ""
    terms = [t.strip(" \t\r\n,;") for t in re.split(r"[,;\n\r]+", text)]
    terms = [t for t in terms if t]

    out: list[str] = []
    used = 0
    for term in terms:
        extra = len(term) + (2 if out else 0)
        if used + extra > VOCABULARY_MAX_CHARS:
            break
        out.append(term)
        used += extra
    return ", ".join(out)


@dataclass
class AppConfig:
    transcribe_audio: bool = True
    ocr_images: bool = True
    language: str = "es"                      # codigo ISO o "auto"
    vocabulary: str = ""                      # terminos propios del audio
    whisper_model: str = "large-v3-turbo"
    export_format: str = "txt"
    output_mode: str = "per-file"             # per-file | merged
    include_timestamps: bool = False
    include_speakers: bool = False            # diarizacion
    auto_export: bool = True                  # guardar al terminar el lote
    # Por defecto el resultado se deja junto al archivo de origen: es donde lo
    # busca quien acaba de arrastrar un audio, y evita tener que recordar una
    # carpeta comun. Elegir carpeta a mano desactiva este modo.
    save_next_to_source: bool = True
    save_location: str = field(default_factory=default_output_dir)

    # Estado de la interfaz (persistido, no editable desde los ajustes)
    tour_completed: bool = False
    window_geometry: str = ""                 # base64 de QByteArray
    h_splitter: list = field(default_factory=list)
    v_splitter: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        """Construye desde un dict ignorando claves desconocidas u obsoletas."""
        valid = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in valid}
        cfg = cls(**clean)
        cfg._sanitize()
        return cfg

    def _sanitize(self) -> None:
        """Corrige valores invalidos que puedan venir de un config.json viejo o editado."""
        valid_models = {v for v, _, _ in WHISPER_MODELS}
        if self.whisper_model not in valid_models:
            self.whisper_model = "large-v3-turbo"
        valid_langs = {v for v, _ in LANGUAGES}
        if self.language not in valid_langs:
            self.language = "es"
        if self.export_format not in EXPORT_FORMATS:
            self.export_format = "txt"
        if self.output_mode not in ("per-file", "merged"):
            self.output_mode = "per-file"
        if not self.save_location:
            self.save_location = default_output_dir()
        self.vocabulary = normalize_vocabulary(self.vocabulary)


# ─────────────────────────────────────────────────────────────────────────────
# Clasificacion de archivos
# ─────────────────────────────────────────────────────────────────────────────
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma", ".opus",
    ".aiff", ".aif", ".amr", ".mp2", ".wv", ".ape", ".ac3", ".oga", ".weba",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v",
    ".mpg", ".mpeg", ".ts", ".3gp", ".ogv", ".mts",
}
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif", ".ppm",
}
PDF_EXTENSIONS = {".pdf"}

ALL_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | IMAGE_EXTENSIONS | PDF_EXTENSIONS


def classify_file(path: str) -> Optional[FileKind]:
    ext = os.path.splitext(path)[1].lower()
    if ext in AUDIO_EXTENSIONS:
        return FileKind.AUDIO
    if ext in VIDEO_EXTENSIONS:
        return FileKind.VIDEO
    if ext in IMAGE_EXTENSIONS:
        return FileKind.IMAGE
    if ext in PDF_EXTENSIONS:
        return FileKind.PDF
    return None


def file_dialog_filter() -> str:
    """Filtro para QFileDialog construido desde las extensiones soportadas."""
    def pat(exts: set[str]) -> str:
        return " ".join(f"*{e}" for e in sorted(exts))
    return (
        f"Todos los soportados ({pat(ALL_EXTENSIONS)});;"
        f"Audio ({pat(AUDIO_EXTENSIONS)});;"
        f"Video ({pat(VIDEO_EXTENSIONS)});;"
        f"Imágenes ({pat(IMAGE_EXTENSIONS)});;"
        f"PDF ({pat(PDF_EXTENSIONS)});;"
        "Todos los archivos (*)"
    )


def expand_paths(paths: list[str], max_depth: int = 4) -> list[str]:
    """Expande carpetas a los archivos soportados que contienen, recursivamente."""
    out: list[str] = []
    seen: set[str] = set()

    def walk(root: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                walk(entry.path, depth + 1)
            elif classify_file(entry.path) is not None:
                if entry.path not in seen:
                    seen.add(entry.path)
                    out.append(entry.path)

    for p in paths:
        if os.path.isdir(p):
            walk(p, 0)
        elif p not in seen:
            seen.add(p)
            out.append(p)
    return out
