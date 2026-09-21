"""Actualizaciones desde GitHub Releases.

El flujo tiene tres fases separadas a proposito, porque cada una puede fallar
sin arrastrar a las siguientes:

    check()    pregunta que version hay publicada          (red, ligero)
    download() baja el paquete y verifica su SHA-256       (red, pesado)
    stage()    lo deja preparado para el proximo arranque  (disco)

Nada se aplica en caliente. El reemplazo real ocurre en apply_pending() al
arrancar, cuando el ejecutable viejo ya no esta en uso.

Solo funciona sobre la version congelada con PyInstaller: ejecutando desde el
codigo fuente no hay nada que reemplazar y check() lo dice sin mas.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from core.paths import data_dir, is_frozen
from core.version import GITHUB_REPO, VERSION, is_newer

_API = "https://api.github.com/repos/{repo}/releases/latest"
_TIMEOUT = 15
_USER_AGENT = f"Lexa/{VERSION} (+https://github.com/{GITHUB_REPO})"

# Nombre del activo segun lo que reemplaza. Una actualizacion de solo codigo
# son ~19 MB porque PyInstaller mete todo el Python dentro del propio .exe;
# el paquete completo pasa de 200 MB y solo hace falta si cambian las librerias.
ASSET_CODE = "Lexa.exe"
ASSET_FULL_SUFFIX = "-windows-x64.zip"
CHECKSUMS = "SHA256SUMS.txt"


class UpdateError(RuntimeError):
    """Fallo recuperable: se avisa y se sigue usando la version instalada."""


@dataclass
class Update:
    version: str
    notes: str
    url: str            # descarga directa del activo
    size: int           # bytes, 0 si GitHub no lo dice
    sha256: str         # vacio si la release no publico checksums
    full: bool          # True si reemplaza la carpeta entera

    @property
    def size_str(self) -> str:
        if not self.size:
            return "?"
        return f"{self.size / 1024 / 1024:.0f} MB"


def updates_dir() -> str:
    d = os.path.join(data_dir(), "updates")
    os.makedirs(d, exist_ok=True)
    return d


# -- 1. Consultar -------------------------------------------------------------
def check(timeout: int = _TIMEOUT) -> Optional[Update]:
    """Devuelve la actualizacion disponible, o None si ya esta al dia.

    Nunca lanza por problemas de red: no poder comprobar actualizaciones no es
    un error que deba interrumpir a nadie.
    """
    if not is_frozen():
        return None

    try:
        data = _get_json(_API.format(repo=GITHUB_REPO), timeout)
    except Exception:
        return None

    etiqueta = str(data.get("tag_name") or "")
    if not etiqueta or not is_newer(etiqueta):
        return None
    if data.get("draft") or data.get("prerelease"):
        return None

    activos = data.get("assets") or []
    sumas = _read_checksums(activos, timeout)

    # Se prefiere el .exe suelto: mismo resultado, diez veces menos descarga.
    elegido = _find_asset(activos, lambda n: n == ASSET_CODE)
    completo = False
    if elegido is None:
        elegido = _find_asset(activos, lambda n: n.endswith(ASSET_FULL_SUFFIX))
        completo = True
    if elegido is None:
        return None

    nombre = elegido.get("name") or ""
    return Update(
        version=etiqueta.lstrip("vV"),
        notes=str(data.get("body") or "").strip(),
        url=elegido.get("browser_download_url") or "",
        size=int(elegido.get("size") or 0),
        sha256=sumas.get(nombre, ""),
        full=completo,
    )


# -- 2. Descargar -------------------------------------------------------------
def download(update: Update,
             progress: Optional[Callable[[float], None]] = None,
             should_abort: Optional[Callable[[], bool]] = None) -> str:
    """Baja el activo y verifica su SHA-256. Devuelve la ruta del archivo.

    Se escribe a un .part y se renombra al final, de modo que una descarga
    interrumpida nunca queda confundida con una completa.
    """
    if not update.url:
        raise UpdateError("La actualizacion no trae ningun archivo descargable.")

    destino = os.path.join(updates_dir(),
                           f"{update.version}-{os.path.basename(update.url)}")
    parcial = destino + ".part"

    digest = hashlib.sha256()
    try:
        peticion = urllib.request.Request(update.url,
                                          headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=_TIMEOUT,
                                    context=_tls_context()) as respuesta:
            total = int(respuesta.headers.get("Content-Length") or update.size or 0)
            bajado = 0
            with open(parcial, "wb") as f:
                while True:
                    if should_abort is not None and should_abort():
                        raise UpdateError("Descarga cancelada.")
                    trozo = respuesta.read(256 * 1024)
                    if not trozo:
                        break
                    f.write(trozo)
                    digest.update(trozo)
                    bajado += len(trozo)
                    if progress and total:
                        progress(min(0.99, bajado / total))
    except UpdateError:
        _borrar(parcial)
        raise
    except (urllib.error.URLError, OSError) as exc:
        _borrar(parcial)
        raise UpdateError(
            f"No se pudo descargar la actualizacion.\n\nDetalle: {exc}") from exc

    # Sin firma digital, el hash publicado es la unica garantia de que lo
    # descargado es lo que se publico. Si la release no lo trae, se sigue
    # adelante pero queda dicho en el registro.
    if update.sha256 and digest.hexdigest().lower() != update.sha256.lower():
        _borrar(parcial)
        raise UpdateError(
            "El archivo descargado no coincide con el publicado.\n\n"
            "Puede ser una descarga corrupta. Intentalo de nuevo."
        )

    os.replace(parcial, destino)
    if progress:
        progress(1.0)
    return destino


# -- 3. Dejar preparado -------------------------------------------------------
def stage(update: Update, archivo: str) -> None:
    """Coloca lo descargado para que el proximo arranque lo aplique.

    Windows no deja sobrescribir un .exe en ejecucion, pero si renombrarlo. Se
    deja el nuevo como "Lexa.exe.new" junto al actual y se aplica al arrancar,
    cuando el viejo ya no esta en uso.
    """
    if update.full:
        # El paquete completo se deja en su carpeta: reemplazar 500 MB de
        # librerias en caliente es otra historia y la guia el usuario a mano.
        raise UpdateError(
            "Esta actualizacion cambia las librerias internas y hay que "
            "instalarla a mano.\n\nSe ha descargado en:\n" + archivo
        )

    destino = os.path.join(_app_dir(), ASSET_CODE + ".new")
    try:
        shutil.copy2(archivo, destino)
    except OSError as exc:
        raise UpdateError(
            "No se pudo preparar la actualizacion.\n\n"
            "Si Lexa esta en una carpeta protegida (Archivos de programa), "
            "muevela a una carpeta personal.\n\n"
            f"Detalle: {exc}"
        ) from exc


def apply_pending() -> bool:
    """Aplica una actualizacion preparada. True si se reemplazo el binario.

    Se llama al arrancar, antes de montar la interfaz. Los pasos van en un
    orden tal que una interrupcion en cualquier punto deja la app arrancable:
    o con el binario viejo, o con el nuevo, nunca sin ninguno.
    """
    if not is_frozen():
        return False

    carpeta = _app_dir()
    actual = os.path.join(carpeta, ASSET_CODE)
    nuevo = actual + ".new"
    viejo = actual + ".old"

    # Limpieza de la vez anterior: ya no esta en uso y se puede borrar.
    _borrar(viejo)

    if not os.path.isfile(nuevo):
        return False
    try:
        os.replace(actual, viejo)      # renombrar SI se permite en caliente
        os.replace(nuevo, actual)
        _write_flag()
    except OSError:
        # Si algo impide el cambio, se revierte para no dejar la app rota.
        if not os.path.isfile(actual) and os.path.isfile(viejo):
            try:
                os.replace(viejo, actual)
            except OSError:
                pass
        return False
    return True


def consume_applied_flag() -> bool:
    """True una sola vez, en el arranque siguiente a una actualizacion.

    Hace falta una marca en disco porque el proceso que reemplaza el binario
    no puede seguir vivo para contarlo: tiene que morir inmediatamente.
    """
    ruta = os.path.join(updates_dir(), "applied.flag")
    if not os.path.isfile(ruta):
        return False
    _borrar(ruta)
    return True


def _write_flag() -> None:
    try:
        with open(os.path.join(updates_dir(), "applied.flag"), "w") as f:
            f.write(VERSION)
    except OSError:
        pass


# -- Interno ------------------------------------------------------------------
def _app_dir() -> str:
    return os.path.dirname(sys.executable)


def _tls_context() -> Optional[ssl.SSLContext]:
    """Mismo criterio que core.downloader: certifi primero si esta disponible."""
    try:
        from core.downloader import _certifi_context
        return _certifi_context()
    except Exception:
        return None


def _get_json(url: str, timeout: int) -> dict:
    peticion = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(peticion, timeout=timeout,
                                context=_tls_context()) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _find_asset(activos: list, coincide) -> Optional[dict]:
    for activo in activos:
        if coincide(str(activo.get("name") or "")):
            return activo
    return None


def _read_checksums(activos: list, timeout: int) -> dict:
    """Lee SHA256SUMS.txt de la release: lineas "<hash>  <nombre>"."""
    activo = _find_asset(activos, lambda n: n == CHECKSUMS)
    if activo is None:
        return {}
    try:
        peticion = urllib.request.Request(
            activo.get("browser_download_url") or "",
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(peticion, timeout=timeout,
                                    context=_tls_context()) as respuesta:
            texto = respuesta.read().decode("utf-8", errors="replace")
    except Exception:
        return {}

    sumas = {}
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) >= 2 and len(partes[0]) == 64:
            sumas[partes[-1].lstrip("*")] = partes[0]
    return sumas


def _borrar(ruta: str) -> None:
    try:
        if os.path.isfile(ruta):
            os.remove(ruta)
    except OSError:
        pass
