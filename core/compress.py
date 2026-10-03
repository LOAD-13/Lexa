"""Comprimir imagenes y PDF hasta un tamano objetivo.

Buscar solo la calidad no basta. Midiendo una foto de 2100x1400 y 506 KB contra
un objetivo de 75 KB:

    escala 100 %  ->  calidad 30  ->  73 KB, con artefactos visibles
    escala  75 %  ->  calidad 48  ->  74 KB
    escala  50 %  ->  calidad 78  ->  74 KB, limpia

Mismo peso, resultados muy distintos: machacar la calidad a tamano completo es
lo peor de las tres. Asi que primero se busca la calidad por biseccion y, solo
si para llegar al objetivo habria que bajar de un suelo decente, se reduce el
tamano y se vuelve a probar.

El original no se toca nunca: esto es con perdida y no se deshace.
"""
from __future__ import annotations
import io
import os
from dataclasses import dataclass
from typing import Callable, List, Optional

# Calidad por debajo de la cual una foto empieza a verse sucia. Antes de pasar
# de aqui se prefiere reducir el tamano, que a igualdad de peso se ve mejor.
CALIDAD_SUELO = 70
CALIDAD_MIN = 20
CALIDAD_MAX = 95

# Cada vuelta reduce el lado al 85 %: mas agresivo da saltos de calidad feos y
# mas suave multiplica las pruebas sin ganar nada.
PASO_ESCALA = 0.85
LADO_MINIMO = 320

OBJETIVO_POR_DEFECTO_KB = 75

# Vueltas para ajustar el reparto dentro de un PDF. Con tres se llega; mas
# solo alarga la espera en los documentos que no hay forma de encoger.
_VUELTAS_PDF = 3

EXT_IMAGEN = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")
EXT_PDF = (".pdf",)

SUFIJO = " (comprimido)"


class CompressError(Exception):
    """Fallo con mensaje ya listo para ensenar."""


@dataclass
class Resultado:
    origen: str
    destino: Optional[str]
    bytes_antes: int
    bytes_despues: int
    cumplio: bool              # llego al objetivo
    nota: str = ""             # por que no, o que se hizo

    @property
    def ahorro(self) -> int:
        return max(0, self.bytes_antes - self.bytes_despues)

    @property
    def ahorro_pct(self) -> float:
        if self.bytes_antes <= 0:
            return 0.0
        return 100.0 * self.ahorro / self.bytes_antes


def admitido(path: str) -> bool:
    return path.lower().endswith(EXT_IMAGEN + EXT_PDF)


def es_pdf(path: str) -> bool:
    return path.lower().endswith(EXT_PDF)


def destino_para(path: str, formato: Optional[str] = None) -> str:
    """Ruta de la copia, junto al original y sin pisarlo nunca."""
    carpeta, nombre = os.path.split(path)
    raiz, ext = os.path.splitext(nombre)
    if formato:
        ext = "." + formato.lower().replace("jpeg", "jpg")
    candidato = os.path.join(carpeta, f"{raiz}{SUFIJO}{ext}")
    n = 2
    while os.path.exists(candidato):
        candidato = os.path.join(carpeta, f"{raiz}{SUFIJO} ({n}){ext}")
        n += 1
    return candidato


def humano(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


# ── Imagenes ─────────────────────────────────────────────────────────────────
def _tiene_alfa(img) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def _codificar(img, formato: str, calidad: int) -> bytes:
    buf = io.BytesIO()
    if formato == "JPEG":
        img.save(buf, "JPEG", quality=calidad, optimize=True, progressive=True)
    else:   # WEBP, que conserva la transparencia
        img.save(buf, "WEBP", quality=calidad, method=6)
    return buf.getvalue()


def _mejor_calidad(img, formato: str, objetivo: int):
    """Calidad mas alta que cabe en el objetivo, por biseccion. None si ninguna.

    Seis pruebas bastan para el rango 20-95, en vez de las setenta y seis que
    costaria ir de una en una.
    """
    lo, hi = CALIDAD_MIN, CALIDAD_MAX
    mejor = None
    while lo <= hi:
        q = (lo + hi) // 2
        datos = _codificar(img, formato, q)
        if len(datos) <= objetivo:
            mejor = (q, datos)
            lo = q + 1
        else:
            hi = q - 1
    return mejor


def _apretar(original, formato: str, objetivo: int):
    """Mejores bytes que caben en el objetivo, ajustando calidad y tamano.

    Devuelve (datos, calidad, cumplio). Buscar solo la calidad no basta: a
    igualdad de peso, media resolucion con calidad 78 se ve mucho mejor que
    resolucion completa con calidad 30.
    """
    from PIL import Image
    ancho0, alto0 = original.size
    escala = 1.0
    mejor = None            # cumple el objetivo
    respaldo = None         # lo mas ligero que se consiguio, aunque no cumpla

    while True:
        if escala >= 1.0:
            img = original
        else:
            img = original.resize((max(1, int(ancho0 * escala)),
                                   max(1, int(alto0 * escala))), Image.LANCZOS)

        encontrado = _mejor_calidad(img, formato, objetivo)
        if encontrado is not None:
            calidad, datos = encontrado
            mejor = (datos, calidad)
            # Si la calidad ya es decente, no hace falta encoger mas.
            if calidad >= CALIDAD_SUELO or min(img.size) <= LADO_MINIMO:
                break
        else:
            crudo = _codificar(img, formato, CALIDAD_MIN)
            if respaldo is None or len(crudo) < len(respaldo):
                respaldo = crudo

        if min(img.size) <= LADO_MINIMO:
            break
        escala *= PASO_ESCALA

    if mejor is not None:
        return mejor[0], mejor[1], True
    return respaldo, CALIDAD_MIN, False


def comprimir_imagen(path: str, objetivo_bytes: int,
                     destino: Optional[str] = None) -> Resultado:
    """Comprime una imagen hasta el objetivo guardando una copia nueva."""
    try:
        from PIL import Image, ImageOps
    except ImportError as e:        # pragma: no cover - Pillow viene con Lexa
        raise CompressError("Falta Pillow, la libreria que trata las imagenes") from e

    try:
        antes = os.path.getsize(path)
    except OSError as e:
        raise CompressError(f"No se pudo leer el archivo: {e}") from e

    try:
        original = Image.open(path)
        original.load()
    except Exception as e:
        raise CompressError(f"No se pudo abrir la imagen: {e}") from e

    # Las fotos de movil traen la orientacion en los metadatos; sin esto, la
    # copia sale girada.
    original = ImageOps.exif_transpose(original) or original

    alfa = _tiene_alfa(original)
    formato = "WEBP" if alfa else "JPEG"
    if alfa:
        original = original.convert("RGBA")
    elif original.mode != "RGB":
        original = original.convert("RGB")

    datos, mejor_calidad, _ = _apretar(original, formato, objetivo_bytes)
    if datos is None:               # pragma: no cover - siempre deja algo
        raise CompressError("No se pudo comprimir la imagen")

    cumplio = len(datos) <= objetivo_bytes
    salida = destino or destino_para(path, "webp" if formato == "WEBP" else "jpg")

    # Comprimir una imagen ya pequena puede dejarla mas grande: el objetivo es
    # que ocupe menos, asi que en ese caso no se toca.
    if len(datos) >= antes and cumplio:
        return Resultado(path, None, antes, antes, True,
                         "ya pesaba menos que el objetivo")
    try:
        with open(salida, "wb") as f:
            f.write(datos)
    except OSError as e:
        raise CompressError(f"No se pudo guardar la copia: {e}") from e

    nota = ""
    if not cumplio:
        nota = (f"no baja de {humano(objetivo_bytes)} ni al minimo; "
                f"se dejo en {humano(len(datos))}")
    elif formato == "WEBP":
        nota = "guardada como WebP para conservar la transparencia"
    elif mejor_calidad < CALIDAD_SUELO:
        nota = f"calidad {mejor_calidad}: el objetivo obliga a apretar mucho"
    return Resultado(path, salida, antes, len(datos), cumplio, nota)


# ── PDF ──────────────────────────────────────────────────────────────────────
def _pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz
            return fitz                     # nombre antiguo de la libreria
        except ImportError as e:            # pragma: no cover - viene con Lexa
            raise CompressError("Falta PyMuPDF, la libreria que trata los PDF") from e


def _recomprimir_pdf(path: str, por_imagen: int, salida: str) -> int:
    """Una pasada: abre el original, aprieta sus imagenes y guarda. Devuelve el peso.

    Parte siempre del original y no del intento anterior. Reutilizar el mismo
    documento abierto entre pasadas da «bad xref»: al guardar con recoleccion
    de basura, las referencias internas cambian y las de antes dejan de valer.
    """
    from PIL import Image
    pymupdf = _pymupdf()
    doc = pymupdf.open(path)
    try:
        for pagina in doc:
            for datos_img in pagina.get_images(full=True):
                xref = datos_img[0]
                try:
                    info = doc.extract_image(xref)
                    img = Image.open(io.BytesIO(info["image"]))
                    img.load()
                    if _tiene_alfa(img):
                        continue        # recomprimir mascaras rompe el montaje
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    nuevos, _, _ = _apretar(img, "JPEG", por_imagen)
                    if nuevos and len(nuevos) < len(info["image"]):
                        # replace_image y no update_stream: el helper puede
                        # devolver la imagen mas pequena, y cambiar solo los
                        # bytes dejaria el ancho y el alto antiguos.
                        pagina.replace_image(xref, stream=nuevos)
                except Exception:
                    continue            # una imagen rara no tumba el documento
        doc.save(salida, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    return os.path.getsize(salida)


def comprimir_pdf(path: str, objetivo_bytes: int,
                  destino: Optional[str] = None) -> Resultado:
    """Recomprime las imagenes de dentro del PDF, que es lo que pesa."""
    pymupdf = _pymupdf()
    try:
        antes = os.path.getsize(path)
    except OSError as e:
        raise CompressError(f"No se pudo leer el archivo: {e}") from e

    try:
        doc = pymupdf.open(path)
        cuantas = len({x[0] for pagina in doc for x in pagina.get_images(full=True)})
        doc.close()
    except Exception as e:
        raise CompressError(f"No se pudo abrir el PDF: {e}") from e

    if not cuantas:
        return Resultado(path, None, antes, antes, antes <= objetivo_bytes,
                         "es un PDF de solo texto: ya esta en su minimo")

    salida = destino or destino_para(path)
    # Repartir el objetivo entre las imagenes no basta: el propio PDF pesa
    # —texto, fuentes, estructura— y ese margen no se sabe de antemano. Se mide
    # el resultado y se vuelve a repartir descontando lo que se paso.
    reparto = objetivo_bytes * 0.8 / cuantas
    logrado = antes
    try:
        for _ in range(_VUELTAS_PDF):
            logrado = _recomprimir_pdf(path, max(4 * 1024, int(reparto)), salida)
            if logrado <= objetivo_bytes:
                break
            exceso = logrado - objetivo_bytes
            siguiente = reparto - exceso / cuantas
            if siguiente < 4 * 1024:
                break               # ya no hay de donde sacar mas
            reparto = siguiente
    except CompressError:
        raise
    except Exception as e:
        raise CompressError(f"No se pudo comprimir el PDF: {e}") from e

    if logrado >= antes:
        # No se gano nada: dejar una copia mas gorda no ayuda a nadie.
        try:
            os.remove(salida)
        except OSError:
            pass
        return Resultado(path, None, antes, antes, antes <= objetivo_bytes,
                         "no se pudo reducir mas sin estropearlo")

    cumplio = logrado <= objetivo_bytes
    nota = "" if cumplio else (f"no baja de {humano(objetivo_bytes)}; "
                               f"se dejo en {humano(logrado)}")
    return Resultado(path, salida, antes, logrado, cumplio, nota)


def comprimir(path: str, objetivo_kb: int = OBJETIVO_POR_DEFECTO_KB) -> Resultado:
    """Comprime lo que sea, segun su tipo."""
    objetivo = max(1, int(objetivo_kb)) * 1024
    if es_pdf(path):
        return comprimir_pdf(path, objetivo)
    return comprimir_imagen(path, objetivo)


def comprimir_varios(rutas: List[str], objetivo_kb: int,
                     progreso: Optional[Callable[[int, int, str], None]] = None,
                     cancelado: Optional[Callable[[], bool]] = None) -> List[Resultado]:
    """Comprime una lista. Un fallo no detiene a los demas."""
    salida: List[Resultado] = []
    total = len(rutas)
    for i, ruta in enumerate(rutas):
        if cancelado and cancelado():
            break
        if progreso:
            progreso(i, total, os.path.basename(ruta))
        try:
            salida.append(comprimir(ruta, objetivo_kb))
        except CompressError as e:
            salida.append(Resultado(ruta, None, _tamano(ruta), _tamano(ruta),
                                    False, str(e)))
    if progreso:
        progreso(total, total, "")
    return salida


def _tamano(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
