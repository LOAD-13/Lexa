"""Rutas de la aplicacion — funcionan igual en desarrollo y congelado con PyInstaller."""
from __future__ import annotations
import os
import sys


def is_frozen() -> bool:
    """True cuando la app corre dentro de un ejecutable de PyInstaller."""
    return getattr(sys, "frozen", False)


def resource_dir() -> str:
    """Carpeta con los recursos empaquetados (icono, fuentes)."""
    if is_frozen():
        # PyInstaller onedir: los datos quedan junto al ejecutable (_MEIPASS en onefile)
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource(*parts: str) -> str:
    return os.path.join(resource_dir(), *parts)


def _local_app_data() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return base


def _roaming_app_data() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return base


def data_dir() -> str:
    """Carpeta de datos pesados: modelos descargados."""
    d = os.path.join(_local_app_data(), "Lexa")
    os.makedirs(d, exist_ok=True)
    return d


def models_dir() -> str:
    d = os.path.join(data_dir(), "models")
    os.makedirs(d, exist_ok=True)
    return d


def config_dir() -> str:
    """Carpeta de configuracion ligera."""
    d = os.path.join(_roaming_app_data(), "Lexa")
    os.makedirs(d, exist_ok=True)
    return d


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


def default_output_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", "Lexa")
