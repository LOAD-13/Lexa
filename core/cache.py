"""Cache de transcripciones ya calculadas.

Transcribir una clase de veinte minutos cuesta varios minutos de CPU. Volver a
soltar el mismo archivo en la cola no deberia pagarlo otra vez.

La clave incluye TODO lo que cambia el resultado: el archivo y los ajustes con
los que se produjo. Si falta alguno, la cache devolveria texto viejo tras
cambiar una opcion, que es peor que no tener cache.
"""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from typing import List, Optional

from core.models import AppConfig, Segment
from core.paths import data_dir

# Version del formato: si cambia como se generan los segmentos, subir esto
# invalida de golpe lo guardado sin tener que borrar nada a mano.
_FORMAT = 3

# Tamano maximo de la carpeta antes de podar las entradas mas antiguas.
_MAX_BYTES = 200 * 1024 * 1024


def cache_dir() -> str:
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def _file_fingerprint(path: str) -> Optional[str]:
    """Huella del archivo sin leerlo entero.

    Se combinan tamano y fecha con el primer y ultimo megabyte: leer 2 GB de
    video para decidir si hay cache tardaria mas que transcribirlo.
    """
    try:
        stat = os.stat(path)
        h = hashlib.sha256()
        h.update(str(stat.st_size).encode())
        h.update(str(int(stat.st_mtime)).encode())
        with open(path, "rb") as f:
            h.update(f.read(1024 * 1024))
            if stat.st_size > 2 * 1024 * 1024:
                f.seek(-1024 * 1024, os.SEEK_END)
                h.update(f.read(1024 * 1024))
        return h.hexdigest()
    except OSError:
        return None


def key_for(path: str, config: AppConfig) -> Optional[str]:
    """Clave unica de (archivo + ajustes que afectan al resultado).

    Las marcas de tiempo y el formato de exportacion NO entran: solo cambian
    como se presenta el texto, no los segmentos que se guardan.
    """
    fingerprint = _file_fingerprint(path)
    if fingerprint is None:
        return None

    parts = [
        str(_FORMAT),
        fingerprint,
        config.language,
        config.whisper_model,
        config.vocabulary,
        "spk" if config.include_speakers else "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def load(key: Optional[str]) -> Optional[List[Segment]]:
    """Segmentos guardados para esa clave, o None si no hay nada utilizable."""
    if not key:
        return None
    path = os.path.join(cache_dir(), f"{key}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        segments = [
            Segment(
                start=float(d["start"]),
                end=float(d["end"]),
                text=str(d["text"]),
                speaker=d.get("speaker"),
                page=d.get("page"),
            )
            for d in data
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None

    # Marca de uso reciente para que la poda respete lo que se sigue usando.
    try:
        os.utime(path, None)
    except OSError:
        pass
    return segments


def store(key: Optional[str], segments: List[Segment]) -> None:
    """Guarda los segmentos. Nunca lanza: fallar aqui no debe perder el trabajo."""
    if not key or not segments:
        return
    path = os.path.join(cache_dir(), f"{key}.json")
    payload = [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            **({"speaker": s.speaker} if s.speaker else {}),
            **({"page": s.page} if s.page else {}),
        }
        for s in segments
    ]
    try:
        fd, tmp = tempfile.mkstemp(dir=cache_dir(), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return
    except OSError:
        return
    _prune()


def clear() -> int:
    """Borra la cache entera. Devuelve los bytes liberados."""
    freed = 0
    try:
        for name in os.listdir(cache_dir()):
            full = os.path.join(cache_dir(), name)
            try:
                freed += os.path.getsize(full)
                os.unlink(full)
            except OSError:
                pass
    except OSError:
        pass
    return freed


def _prune() -> None:
    """Deja la carpeta por debajo del tope, tirando primero lo mas antiguo."""
    try:
        entries = []
        total = 0
        for name in os.listdir(cache_dir()):
            full = os.path.join(cache_dir(), name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, full))
            total += stat.st_size

        if total <= _MAX_BYTES:
            return
        for _, size, full in sorted(entries):
            try:
                os.unlink(full)
                total -= size
            except OSError:
                continue
            if total <= _MAX_BYTES:
                return
    except OSError:
        pass
