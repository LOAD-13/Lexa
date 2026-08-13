"""Descarga de modelos con progreso real en bytes.

Se usa desde el modal de primer arranque. Todas las descargas son reanudables en
el sentido de que un fallo deja el destino sin tocar (se escribe a un .part y se
renombra al final), asi que reintentar nunca deja un modelo corrupto a medias.
"""
from __future__ import annotations
import os
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional

from core.paths import models_dir

# progreso(bytes_descargados, bytes_totales)  — total es 0 si el servidor no lo informa
ProgressFn = Callable[[int, int], None]

_SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
_HF_LATIN = "https://huggingface.co/PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx/resolve/main"

SEGMENTATION_URL = f"{_SHERPA}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL    = f"{_SHERPA}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"

# Modelo de reconocimiento latino. El que trae RapidOCR por defecto esta
# entrenado en chino e ingles y su diccionario no incluye á é í ó ú ñ ü,
# asi que destroza cualquier texto en español.
LATIN_REC_URL = f"{_HF_LATIN}/inference.onnx"
LATIN_YML_URL = f"{_HF_LATIN}/inference.yml"


class DownloadCancelled(Exception):
    """El usuario cancelo la descarga."""


@dataclass
class ModelSpec:
    """Un artefacto descargable."""
    key: str            # identificador interno
    label: str          # texto visible en el modal
    approx_size: str    # tamano legible para mostrar antes de empezar
    kind: str           # "whisper" | "file" | "targz"
    url: str = ""       # solo para kind file/targz
    target: str = ""    # ruta final relativa a models_dir(); solo file/targz
    whisper_name: str = ""   # solo para kind whisper


def diarization_specs() -> List[ModelSpec]:
    return [
        ModelSpec(
            key="seg", label="Segmentación de hablantes", approx_size="7 MB",
            kind="targz", url=SEGMENTATION_URL,
            target=os.path.join("diarization", "sherpa-onnx-pyannote-segmentation-3-0"),
        ),
        ModelSpec(
            key="emb", label="Huella de voz (CAM++)", approx_size="28 MB",
            kind="file", url=EMBEDDING_URL,
            target=os.path.join("diarization", "campplus_sv_zh_en_16k.onnx"),
        ),
    ]


def ocr_spec() -> ModelSpec:
    return ModelSpec(
        key="ocr", label="Reconocimiento de texto (latino)", approx_size="8 MB",
        kind="ocr_latin", url=LATIN_REC_URL,
        target=os.path.join("ocr", "latin_rec.onnx"),
    )


def whisper_spec(model_name: str, label: str, size: str) -> ModelSpec:
    return ModelSpec(
        key=f"whisper:{model_name}", label=f"Modelo de voz {label}",
        approx_size=size, kind="whisper", whisper_name=model_name,
    )


def is_present(spec: ModelSpec) -> bool:
    if spec.kind == "whisper":
        from core.engines.asr import is_model_downloaded
        return is_model_downloaded(spec.whisper_name)
    if spec.kind == "ocr_latin":
        from core.engines.ocr import latin_model_paths
        return all(os.path.isfile(p) for p in latin_model_paths())
    return os.path.exists(os.path.join(models_dir(), spec.target))


def fetch(
    spec: ModelSpec,
    progress: Optional[ProgressFn] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> None:
    """Descarga el artefacto si falta. No hace nada si ya esta presente."""
    if is_present(spec):
        if progress:
            progress(1, 1)
        return

    if spec.kind == "whisper":
        _fetch_whisper(spec, progress, should_cancel)
    elif spec.kind == "file":
        dest = os.path.join(models_dir(), spec.target)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _download(spec.url, dest, progress, should_cancel)
    elif spec.kind == "targz":
        _fetch_archive(spec, progress, should_cancel)
    elif spec.kind == "ocr_latin":
        _fetch_latin_ocr(progress, should_cancel)


# ─────────────────────────────────────────────────────────────────────────────
def _fetch_latin_ocr(progress, should_cancel) -> None:
    """Baja el modelo latino y convierte su diccionario al .txt que espera RapidOCR."""
    import yaml
    from core.engines.ocr import latin_model_paths

    onnx_path, keys_path = latin_model_paths()
    os.makedirs(os.path.dirname(onnx_path), exist_ok=True)

    if not os.path.isfile(onnx_path):
        _download(LATIN_REC_URL, onnx_path, progress, should_cancel)

    if not os.path.isfile(keys_path):
        yml_path = keys_path + ".yml"
        _download(LATIN_YML_URL, yml_path, None, should_cancel)
        try:
            with open(yml_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            chars = (config.get("PostProcess", {}).get("character_dict")
                     or config.get("character_dict"))
            if not chars:
                raise RuntimeError("El modelo de OCR no trae diccionario de caracteres.")
            with open(keys_path, "w", encoding="utf-8") as f:
                f.write("\n".join(str(c) for c in chars))
        finally:
            _unlink(yml_path)


# ─────────────────────────────────────────────────────────────────────────────
def _fetch_whisper(spec, progress, should_cancel) -> None:
    """Descarga un modelo Whisper via huggingface_hub, reportando bytes reales.

    huggingface_hub no expone un callback directo, asi que se mide el crecimiento
    del directorio de cache desde un hilo aparte.
    """
    import threading
    from core.engines.asr import ensure_model

    total = _WHISPER_BYTES.get(spec.whisper_name, 0)
    root = models_dir()
    stop = threading.Event()

    # Se mide el crecimiento desde el tamaño actual, no el tamaño absoluto: la
    # carpeta ya contiene el modelo de OCR y los de diarización, que no forman
    # parte de esta descarga.
    baseline = _dir_size(root)

    def watch() -> None:
        while not stop.wait(0.4):
            if progress:
                progress(max(0, _dir_size(root) - baseline), total)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        ensure_model(spec.whisper_name)
    except Exception as exc:
        raise RuntimeError(_net_error(exc)) from exc
    finally:
        stop.set()
        watcher.join(timeout=2)

    if progress:
        progress(total or max(0, _dir_size(root) - baseline), total)


def _fetch_archive(spec, progress, should_cancel) -> None:
    dest_dir = os.path.join(models_dir(), spec.target)
    tmp = dest_dir + ".tar.bz2"
    os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
    _download(spec.url, tmp, progress, should_cancel)

    staging = dest_dir + ".unpack"
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    try:
        with tarfile.open(tmp, "r:*") as tar:
            _safe_extract(tar, staging)
        # El tar trae una carpeta raiz; si es asi, se aplana un nivel.
        entries = os.listdir(staging)
        src = os.path.join(staging, entries[0]) if (
            len(entries) == 1 and os.path.isdir(os.path.join(staging, entries[0]))
        ) else staging
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.move(src, dest_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if os.path.exists(tmp):
            os.unlink(tmp)


def _safe_extract(tar: tarfile.TarFile, path: str) -> None:
    """Extrae rechazando rutas que escapen del destino (path traversal)."""
    base = os.path.realpath(path)
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(path, member.name))
        if not target.startswith(base + os.sep) and target != base:
            raise RuntimeError(f"Archivo comprimido con ruta insegura: {member.name}")
    tar.extractall(path)


def _download(url: str, dest: str, progress, should_cancel) -> None:
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Lexa/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                while True:
                    if should_cancel is not None and should_cancel():
                        raise DownloadCancelled()
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        os.replace(part, dest)
    except DownloadCancelled:
        _unlink(part)
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        _unlink(part)
        raise RuntimeError(_net_error(exc)) from exc


def _unlink(path: str) -> None:
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def _dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _net_error(exc: Exception) -> str:
    return (
        "No se pudo descargar el modelo.\n\n"
        "Comprueba tu conexión a internet y vuelve a intentarlo. "
        "Si usas una red corporativa o VPN, es posible que esté bloqueando "
        "la descarga.\n\n"
        f"Detalle: {exc}"
    )


# Tamano aproximado en disco de cada modelo Whisper, para la barra de progreso.
_WHISPER_BYTES = {
    "tiny":           75_000_000,
    "base":          145_000_000,
    "small":         484_000_000,
    "medium":      1_530_000_000,
    "large-v3-turbo": 1_620_000_000,
    "large-v3":    3_090_000_000,
}
