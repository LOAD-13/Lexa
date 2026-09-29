"""Descarga de vídeos de YouTube para transcribirlos.

Tres cosas de YouTube obligan a este diseño, y conviene tenerlas escritas
porque ninguna se adivina leyendo el código:

1. Las URL de los formatos van firmadas con JavaScript. Sin un motor que lo
   ejecute, la descarga del vídeo devuelve 403. Se usa QuickJS —2 MB— en vez
   del Deno que yt-dlp trae de serie, que son 43 MB.

2. El vídeo y el audio llegan separados. Unirlos es cosa de ffmpeg, que los
   usuarios de Lexa no tienen; PyAV trae ffmpeg dentro, así que la unión se
   hace aquí copiando paquetes, sin recodificar.

3. Pedir «el mejor vídeo» devuelve AV1, que ni PyAV ni Windows reproducen. Hay
   que pedir H.264 a las claras.

Los dos formatos se piden en llamadas separadas a propósito: pedidos juntos,
yt-dlp se pone a buscar ffmpeg en el sistema para unirlos él. En una máquina
con ffmpeg instalado eso funciona y esconde el problema; en un equipo limpio,
falla.
"""
from __future__ import annotations
import hashlib
import os
import re
import shutil
import urllib.request
from typing import Callable, Optional

from core import paths

# Publicación fijada del motor de JavaScript. Se comprueba la huella antes de
# usarlo, igual que hace el actualizador con lo que baja.
_QJS_VERSION = "v0.17.0"
_QJS_URL = ("https://github.com/quickjs-ng/quickjs/releases/download/"
            f"{_QJS_VERSION}/qjs-windows-x86_64.exe")
_QJS_SHA256 = "2aeabf0092c3262d6b2609824418f7dd7ed1f1df939f73b2b15645230cac0d77"
QJS_NAME = "qjs.exe"

FORMATO_VIDEO = "bestvideo[ext=mp4][vcodec^=avc1][height<=480]"
FORMATO_AUDIO = "bestaudio[ext=m4a]/bestaudio"

_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com",
          "music.youtube.com", "youtu.be", "www.youtu.be")


class YoutubeError(Exception):
    """Fallo con mensaje ya listo para enseñar al usuario."""


# ── Enlaces ──────────────────────────────────────────────────────────────────
def is_link(texto: str) -> bool:
    """True si el texto es un enlace a un vídeo de YouTube."""
    return video_id(texto) is not None


def video_id(texto: str) -> Optional[str]:
    """Saca el identificador del vídeo, o None si el enlace no vale.

    Se mira el host de verdad y no un simple «contiene youtube», porque
    `ejemplo.com/youtube.com/watch?v=x` no es un enlace de YouTube.
    """
    if not texto:
        return None
    texto = texto.strip().strip("<>\"'")
    if not texto:
        return None
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", texto):
        texto = "https://" + texto
    try:
        from urllib.parse import urlparse, parse_qs
        u = urlparse(texto)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or u.hostname is None:
        return None
    host = u.hostname.lower()
    if host not in _HOSTS:
        return None

    if host.endswith("youtu.be"):
        cand = u.path.lstrip("/").split("/")[0]
    elif u.path == "/watch":
        cand = (parse_qs(u.query).get("v") or [""])[0]
    else:
        partes = [p for p in u.path.split("/") if p]
        # /shorts/ID, /embed/ID, /live/ID, /v/ID
        if len(partes) >= 2 and partes[0] in ("shorts", "embed", "live", "v"):
            cand = partes[1]
        else:
            return None
    return cand if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", cand or "") else None


def normalize_link(texto: str) -> Optional[str]:
    """Enlace canónico, para que dos formas del mismo vídeo no se dupliquen."""
    vid = video_id(texto)
    return f"https://www.youtube.com/watch?v={vid}" if vid else None


# ── Motor de JavaScript ──────────────────────────────────────────────────────
def bundled_runtime() -> Optional[str]:
    """El motor que viene dentro del paquete, si lo hay."""
    p = paths.resource("bin", QJS_NAME)
    return p if os.path.isfile(p) else None


def local_runtime() -> Optional[str]:
    """El motor bajado en el equipo del usuario, si ya está."""
    p = os.path.join(paths.bin_dir(), QJS_NAME)
    return p if os.path.isfile(p) else None


def ensure_runtime(on_notice: Optional[Callable[[str, str], None]] = None) -> Optional[str]:
    """Devuelve la ruta del motor, bajándolo si hace falta. None si no se pudo.

    Sin motor la descarga no se cancela: se cae a solo audio, que es lo que de
    todas formas se transcribe.
    """
    for ruta in (bundled_runtime(), local_runtime()):
        if ruta:
            return ruta

    destino = os.path.join(paths.bin_dir(), QJS_NAME)
    parcial = destino + ".part"
    try:
        if on_notice:
            on_notice("info", "Preparando el motor de vídeo (2 MB, solo la primera vez)")
        req = urllib.request.Request(_QJS_URL, headers={"User-Agent": "Lexa"})
        with urllib.request.urlopen(req, timeout=60) as r, open(parcial, "wb") as f:
            shutil.copyfileobj(r, f)
        huella = hashlib.sha256(open(parcial, "rb").read()).hexdigest()
        if huella != _QJS_SHA256:
            raise YoutubeError("la huella del motor no coincide")
        os.replace(parcial, destino)
        return destino
    except Exception as e:
        if on_notice:
            on_notice("warn", f"No se pudo preparar el motor de vídeo: {e}. "
                              f"Se descargará solo el audio.")
        try:
            os.remove(parcial)
        except OSError:
            pass
        return None


# ── Descarga ─────────────────────────────────────────────────────────────────
def _ydl(opciones: dict, runtime: Optional[str]) -> "object":
    try:
        import yt_dlp
    except ImportError as e:      # pragma: no cover - solo si falta la librería
        raise YoutubeError("Falta yt-dlp, la librería que descarga de YouTube") from e
    base = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "noprogress": True, "consoletitle": False}
    if runtime:
        base["js_runtimes"] = {"quickjs": {"path": runtime}}
    base.update(opciones)
    return yt_dlp.YoutubeDL(base)


def _traducir(err: Exception) -> str:
    """El error crudo de yt-dlp no dice nada útil; se traduce a algo humano."""
    t = str(err)
    b = t.lower()
    if "private video" in b:
        return "El vídeo es privado"
    if "video unavailable" in b or "removed" in b:
        return "El vídeo ya no está disponible"
    if "age" in b and "confirm" in b:
        return "El vídeo tiene restricción de edad"
    if "sign in" in b or "bot" in b:
        return "YouTube pide iniciar sesión para este vídeo"
    if "403" in b:
        return "YouTube rechazó la descarga (403). Vuelve a intentarlo más tarde"
    if "urlopen" in b or "getaddrinfo" in b or "connection" in b:
        return "Sin conexión con YouTube"
    if "unsupported url" in b or "is not a valid url" in b:
        return "Ese enlace no es un vídeo de YouTube"
    return t.replace("ERROR: ", "").strip() or "No se pudo descargar el vídeo"


def probe(url: str, runtime: Optional[str] = None) -> dict:
    """Título, duración e identificador sin descargar nada."""
    limpio = normalize_link(url)
    if not limpio:
        raise YoutubeError("Ese enlace no es un vídeo de YouTube")
    try:
        with _ydl({"skip_download": True}, runtime) as y:
            info = y.extract_info(limpio, download=False)
    except Exception as e:
        raise YoutubeError(_traducir(e)) from e
    if info.get("is_live"):
        raise YoutubeError("Es una retransmisión en directo: no tiene final que transcribir")
    return {"id": info.get("id") or "", "title": info.get("title") or "Vídeo de YouTube",
            "duration": float(info.get("duration") or 0.0), "url": limpio}


def _safe_name(texto: str) -> str:
    """Un título de YouTube puede traer cualquier cosa; el disco no la acepta."""
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", texto)
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")
    return (limpio or "Video de YouTube")[:90]


_INTENTOS = 3
_ESPERA_ENTRE_INTENTOS = 4.0


def _es_pasajero(err: Exception) -> bool:
    """True si vale la pena reintentar.

    YouTube devuelve 403 de vez en cuando aunque el enlace y el motor esten
    bien: pasa al bajar varios videos seguidos. Al segundo intento suele
    funcionar, asi que rendirse a la primera seria tirar una descarga buena.
    """
    b = str(err).lower()
    if "private" in b or "unavailable" in b or "removed" in b or "age" in b:
        return False
    return ("403" in b or "timed out" in b or "temporar" in b
            or "connection" in b or "incomplete" in b or "429" in b)


def _bajar_uno(url: str, formato: str, plantilla: str, runtime: Optional[str],
               gancho) -> str:
    import time
    opciones = {"format": formato, "outtmpl": plantilla}
    if gancho:
        opciones["progress_hooks"] = [gancho]
    ultimo: Optional[Exception] = None
    for intento in range(_INTENTOS):
        try:
            with _ydl(opciones, runtime) as y:
                info = y.extract_info(url, download=True)
            break
        except YoutubeError:
            raise                      # cancelado por el usuario: no insistir
        except Exception as e:
            ultimo = e
            if intento == _INTENTOS - 1 or not _es_pasajero(e):
                raise YoutubeError(_traducir(e)) from e
            time.sleep(_ESPERA_ENTRE_INTENTOS * (intento + 1))
    else:                              # pragma: no cover - el bucle siempre sale
        raise YoutubeError(_traducir(ultimo or Exception()))
    pedidos = info.get("requested_downloads") or []
    if not pedidos or not pedidos[0].get("filepath"):
        raise YoutubeError("La descarga no dejó ningún archivo")
    return pedidos[0]["filepath"]


def _remux(video: str, audio: str, salida: str) -> None:
    """Mete las dos pistas en un mp4 copiando paquetes, sin recodificar."""
    import av
    out = av.open(salida, "w")
    abiertos, mapa = [], []
    try:
        for origen in (video, audio):
            c = av.open(origen)
            abiertos.append(c)
            for s in c.streams:
                if s.type in ("video", "audio"):
                    mapa.append((c, s, out.add_stream_from_template(s)))
        for c, s, destino in mapa:
            for paquete in c.demux(s):
                if paquete.dts is None:
                    continue
                paquete.stream = destino
                out.mux(paquete)
    finally:
        out.close()
        for c in abiertos:
            try:
                c.close()
            except Exception:
                pass


def download(url: str, with_video: bool = True,
             progress_callback: Optional[Callable[[float, str], None]] = None,
             should_abort: Optional[Callable[[], bool]] = None,
             on_notice: Optional[Callable[[str, str], None]] = None) -> str:
    """Descarga el vídeo y devuelve la ruta del archivo listo para transcribir."""
    # El motor se consigue siempre, no solo para el video. Bajar solo el audio
    # funcionaba sin el, pero YouTube empezo a pedir el reto tambien ahi: sin
    # motor la descarga falla con 403 unas veces si y otras no. Con el, va
    # siempre. Si no se consigue, se intenta igual: puede que ese video no lo
    # pida, y fallar del todo seria peor que probar.
    runtime = ensure_runtime(on_notice)
    if with_video and runtime is None:
        with_video = False

    info = probe(url, runtime)
    carpeta = paths.youtube_dir()
    base = f"{_safe_name(info['title'])} [{info['id']}]"

    def avisar(fraccion: float, texto: str) -> None:
        if progress_callback:
            progress_callback(max(0.0, min(1.0, fraccion)), texto)

    def gancho_factory(desde: float, hasta: float, etiqueta: str):
        def gancho(d):
            if should_abort and should_abort():
                raise YoutubeError("Descarga cancelada")
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            hecho = d.get("downloaded_bytes") or 0
            parte = (hecho / total) if total else 0.0
            avisar(desde + (hasta - desde) * parte, etiqueta)
        return gancho

    if should_abort and should_abort():
        raise YoutubeError("Descarga cancelada")

    if not with_video:
        destino = os.path.join(carpeta, base + ".%(ext)s")
        avisar(0.02, "Descargando el audio")
        ruta = _bajar_uno(info["url"], FORMATO_AUDIO, destino, runtime,
                          gancho_factory(0.02, 0.98, "Descargando el audio"))
        avisar(1.0, "Descarga terminada")
        return ruta

    # Dos llamadas separadas: ver la explicación de arriba.
    avisar(0.02, "Descargando el vídeo")
    v = _bajar_uno(info["url"], FORMATO_VIDEO,
                   os.path.join(carpeta, base + ".video.%(ext)s"), runtime,
                   gancho_factory(0.02, 0.70, "Descargando el vídeo"))
    if should_abort and should_abort():
        raise YoutubeError("Descarga cancelada")
    avisar(0.70, "Descargando el audio")
    a = _bajar_uno(info["url"], FORMATO_AUDIO,
                   os.path.join(carpeta, base + ".audio.%(ext)s"), runtime,
                   gancho_factory(0.70, 0.94, "Descargando el audio"))

    avisar(0.95, "Juntando vídeo y audio")
    salida = os.path.join(carpeta, base + ".mp4")
    try:
        _remux(v, a, salida)
    except Exception as e:
        # Sin unión todavía queda algo transcribible: el audio suelto.
        if on_notice:
            on_notice("warn", f"No se pudo juntar vídeo y audio: {e}. Se usa solo el audio.")
        for sobra in (v,):
            try:
                os.remove(sobra)
            except OSError:
                pass
        avisar(1.0, "Descarga terminada")
        return a
    for sobra in (v, a):
        try:
            os.remove(sobra)
        except OSError:
            pass
    avisar(1.0, "Descarga terminada")
    return salida


# ── Limpieza ─────────────────────────────────────────────────────────────────
def cache_size() -> int:
    """Bytes ocupados por las descargas."""
    total = 0
    carpeta = paths.youtube_dir()
    for raiz, _, archivos in os.walk(carpeta):
        for n in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, n))
            except OSError:
                pass
    return total


def clear_cache() -> int:
    """Borra las descargas y devuelve los bytes liberados de verdad.

    Un video que este abierto —porque esta en la cola o se esta viendo en el
    editor de recorte— Windows no deja borrarlo. No es un error: se salta y lo
    que queda se cuenta con cache_size(), para poder decirlo en vez de mentir
    con un «listo» que no borro nada.
    """
    antes = cache_size()
    carpeta = paths.youtube_dir()
    for raiz, _, archivos in os.walk(carpeta):
        for n in archivos:
            try:
                os.remove(os.path.join(raiz, n))
            except OSError:
                pass
    return antes - cache_size()
