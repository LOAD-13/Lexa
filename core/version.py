"""Version de la aplicacion.

Vive sola en su propio modulo a proposito: la leen la interfaz, el actualizador
y el script de compilacion, y no debe haber dos sitios donde cambiarla.

Formato MAJOR.MINOR.PATCH. El actualizador compara las tres cifras como enteros,
asi que 1.10.0 es posterior a 1.9.0 y no al reves, que es lo que pasaria
comparando el texto tal cual.
"""
from __future__ import annotations

VERSION = "1.3.1"

# Repositorio del que se descargan las actualizaciones.
GITHUB_REPO = "LOAD-13/Lexa"


def version_tuple(text: str) -> tuple:
    """Convierte «1.3.0» en (1, 3, 0) para poder comparar versiones.

    Tolera basura: una etiqueta como «v1.3.0-beta» da (1, 3, 0), y algo
    ilegible da (0, 0, 0), que nunca se considera mas nuevo que lo instalado.
    """
    limpio = text.strip().lstrip("vV").split("-")[0].split("+")[0]
    partes = []
    for trozo in limpio.split("."):
        digitos = "".join(c for c in trozo if c.isdigit())
        partes.append(int(digitos) if digitos else 0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:3])


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """True si `candidate` es una version posterior a la instalada."""
    return version_tuple(candidate) > version_tuple(current)
