"""Persistencia de AppConfig en un JSON del perfil del usuario."""
from __future__ import annotations
import json
import os
import tempfile

from core.models import AppConfig
from core.paths import config_file


def load_config() -> AppConfig:
    """Lee la configuracion guardada. Ante cualquier problema devuelve los defaults."""
    path = config_file()
    if not os.path.isfile(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return AppConfig()
        return AppConfig.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Guarda de forma atomica: escribe a un temporal y reemplaza.

    Evita dejar un config.json truncado si la app se cierra a mitad de escritura.
    Nunca lanza: perder los ajustes no debe tumbar la aplicacion.
    """
    path = config_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError:
        pass
