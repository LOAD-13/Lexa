"""Lo que pasa cuando el equipo se suspende mientras Lexa trabaja.

Son dos problemas distintos y el que mas molesta no es el evidente.

El primero: transcribir no cuenta como actividad para Windows. Sin tocar raton
ni teclado, el equipo se suspende a los quince minutos aunque este a pleno
rendimiento, que es justo lo que hace quien deja una clase de dos horas y se va.
Mientras haya trabajo se le pide a Windows que no suspenda el sistema.

El segundo: si aun asi se suspende —tapa cerrada, politica de bateria—, las
cuentas se falsean. En Windows, `time.monotonic()` de Python es GetTickCount64,
que SI cuenta el tiempo dormido. Un archivo de tres minutos atravesado por dos
horas de suspension diria «2 h 03 m», el ritmo se desplomaria y el tiempo
restante se dispararia. QueryUnbiasedInterruptTime no cuenta lo dormido, y esta
en kernel32: ninguna dependencia nueva.

Fuera de Windows se usa `time.monotonic()`, que alli si excluye la suspension.
"""
from __future__ import annotations
import ctypes
import os
import time
from typing import Optional

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001

_ES_SOLO_TRABAJO = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
# A proposito no se pide ES_DISPLAY_REQUIRED: que la pantalla se apague esta
# bien y ahorra bateria. Lo que no puede es dormirse el equipo entero.

_kernel32 = None
if os.name == "nt":
    try:
        _kernel32 = ctypes.windll.kernel32
    except Exception:       # pragma: no cover - solo si Windows esta roto
        _kernel32 = None

_despierto = False


def ahora() -> float:
    """Segundos de reloj que NO cuentan el tiempo suspendido.

    Para medir cuanto se ha trabajado. Si lo que se quiere es saber que hora es,
    esta no es la funcion.
    """
    if _kernel32 is not None:
        contador = ctypes.c_ulonglong()
        try:
            if _kernel32.QueryUnbiasedInterruptTime(ctypes.byref(contador)):
                # Viene en unidades de 100 ns.
                return contador.value / 1e7
        except Exception:
            pass
    return time.monotonic()


def mantener_despierto(activo: bool) -> bool:
    """Pide a Windows no suspender el sistema, o suelta esa peticion.

    Devuelve True si la peticion se acepto. En otros sistemas devuelve False sin
    hacer nada: no es un error, es que ahi no aplica.
    """
    global _despierto
    if _kernel32 is None:
        _despierto = False
        return False
    try:
        estado = _ES_SOLO_TRABAJO if activo else _ES_CONTINUOUS
        if _kernel32.SetThreadExecutionState(estado) == 0:
            return False
    except Exception:
        return False
    _despierto = bool(activo)
    return True


def esta_despierto() -> bool:
    """True si ahora mismo se esta pidiendo que el equipo no se suspenda."""
    return _despierto


class Vigilia:
    """Mantiene el equipo despierto mientras dure el bloque.

    Se puede anidar sin miedo: solo la primera entrada pide la vigilia y solo la
    ultima salida la suelta. Hace falta porque transcribir y descargar de
    YouTube pueden solaparse, y que uno termine no significa que el otro haya
    acabado.
    """

    _cuenta = 0

    def __enter__(self) -> "Vigilia":
        Vigilia.abrir()
        return self

    def __exit__(self, *_) -> None:
        Vigilia.cerrar()

    @classmethod
    def abrir(cls) -> None:
        cls._cuenta += 1
        if cls._cuenta == 1:
            mantener_despierto(True)

    @classmethod
    def cerrar(cls) -> None:
        if cls._cuenta == 0:
            return
        cls._cuenta -= 1
        if cls._cuenta == 0:
            mantener_despierto(False)

    @classmethod
    def soltar_todo(cls) -> None:
        """Suelta la vigilia pase lo que pase. Para cerrar la aplicacion."""
        cls._cuenta = 0
        mantener_despierto(False)
