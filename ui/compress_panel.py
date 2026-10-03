"""Pantalla de comprimir: su zona de arrastre, su lista y su objetivo en KB.

Comprimir no es transcribir. Mezclarlos obligaria a pasar una foto por el OCR
solo para encogerla, asi que vive en su propio modo, con los mismos
componentes y el mismo aspecto que el resto de Lexa.

Los minimos que declara son los minimos de verdad, no los comodos: es la
leccion de la 2.0.1, donde declarar el tamano comodo hacia que en pantallas
pequenas el contenido se saliera en vez de encogerse.
"""
from __future__ import annotations
import os
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core import compress as C
from ui import theme as T
from ui.widgets import Panel, SectionLabel, make_btn

_OBJETIVO_MIN = 5
_OBJETIVO_MAX = 10000


class _Trabajo(QThread):
    """Comprime fuera del hilo de la ventana, que si no se queda congelada."""

    avance = pyqtSignal(int, int, str)       # hecho, total, nombre
    listo_uno = pyqtSignal(object)          # Resultado
    terminado = pyqtSignal()

    def __init__(self, rutas: List[str], objetivo_kb: int, parent=None):
        super().__init__(parent)
        self._rutas = list(rutas)
        self._objetivo = objetivo_kb
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        total = len(self._rutas)
        for i, ruta in enumerate(self._rutas):
            if self._abort:
                break
            self.avance.emit(i, total, os.path.basename(ruta))
            try:
                self.listo_uno.emit(C.comprimir(ruta, self._objetivo))
            except C.CompressError as e:
                self.listo_uno.emit(
                    C.Resultado(ruta, None, C._tamano(ruta), C._tamano(ruta),
                                False, str(e)))
            except Exception as e:          # pragma: no cover - red de seguridad
                self.listo_uno.emit(
                    C.Resultado(ruta, None, C._tamano(ruta), C._tamano(ruta),
                                False, f"error inesperado: {e}"))
        self.avance.emit(total, total, "")
        self.terminado.emit()


class _Zona(QWidget):
    """Zona de arrastre propia: aqui solo entran imagenes y PDF."""

    soltados = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._encima = False
        self.setMinimumHeight(108)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        # Centrado con espaciadores y no con setAlignment(AlignCenter): con el
        # alineado del layout, una etiqueta con ajuste de linea recibe el ancho
        # de su sizeHint, calcula mal su alto y acaba pisando al icono.
        lay.addStretch()

        icono = QLabel("↓")
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setFixedSize(36, 36)
        icono.setStyleSheet(
            f"background: {T.ELEV}; border: 1px solid {T.LINE}; border-radius: 10px;"
            f" color: {T.FG2}; font-size: 17px; font-weight: 300;")
        lay.addWidget(icono, alignment=Qt.AlignmentFlag.AlignCenter)

        titulo = QLabel("Arrastra imágenes o PDF aquí")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulo.setWordWrap(True)
        titulo.setStyleSheet(
            f"background: transparent; font-size: 13px; font-weight: 500; color: {T.FG};")
        lay.addWidget(titulo)

        pista = QLabel("JPG · PNG · WebP · TIFF · PDF")
        pista.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pista.setWordWrap(True)
        pista.setStyleSheet(
            f"background: transparent; font-size: 10.5px; color: {T.MUTED};")
        lay.addWidget(pista)

        self._btn = make_btn("Elegir archivos", kind="ghost_sm")
        self._btn.setFixedHeight(28)
        self._btn.clicked.connect(self._dialogo)
        lay.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addStretch()

        self._estilo()

    def minimumSizeHint(self):
        """El minimo de verdad: el ancho que el boton necesita para leerse."""
        base = super().minimumSizeHint()
        m = self.layout().contentsMargins()
        base.setWidth(self._btn.sizeHint().width() + m.left() + m.right())
        return base

    def _estilo(self) -> None:
        borde = T.ACCENT if self._encima else T.LINE
        fondo = T.ACCENT_SOFT if self._encima else T.PANEL2
        self.setStyleSheet(f"""
            _Zona {{
                background: {fondo};
                border: 1.5px dashed {borde};
                border-radius: {T.R_LG}px;
            }}
        """)

    def _dialogo(self) -> None:
        patron = "Imágenes y PDF (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif *.pdf)"
        rutas, _ = QFileDialog.getOpenFileNames(self, "Elegir archivos", "", patron)
        if rutas:
            self.soltados.emit(rutas)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            self._encima = True
            self._estilo()
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, _) -> None:
        self._encima = False
        self._estilo()

    def dropEvent(self, e: QDropEvent) -> None:
        self._encima = False
        self._estilo()
        rutas = []
        for u in e.mimeData().urls():
            if not u.isLocalFile():
                continue
            ruta = u.toLocalFile()
            if os.path.isdir(ruta):
                # Soltar una carpeta trae lo que haya dentro, como en la cola.
                for raiz, _, archivos in os.walk(ruta):
                    rutas += [os.path.join(raiz, n) for n in archivos]
            else:
                rutas.append(ruta)
        if rutas:
            self.soltados.emit(rutas)
        e.acceptProposedAction()


class _Fila(QWidget):
    """Una fila por archivo: nombre, antes, después y lo que se ahorró."""

    quitar = pyqtSignal(str)

    def __init__(self, ruta: str, parent=None):
        super().__init__(parent)
        self._ruta = ruta
        self.setStyleSheet(
            f"_Fila {{ background: {T.PANEL2}; border: 1px solid {T.LINE};"
            f" border-radius: {T.R_MD}px; }}")
        fila = QHBoxLayout(self)
        fila.setContentsMargins(11, 8, 9, 8)
        fila.setSpacing(9)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._nombre = QLabel(os.path.basename(ruta))
        self._nombre.setToolTip(ruta)
        self._nombre.setMinimumWidth(1)      # puede encogerse: no empuja a nadie
        self._nombre.setStyleSheet(
            f"background: transparent; color: {T.FG}; font-size: 12.5px;")
        col.addWidget(self._nombre)

        self._detalle = QLabel(C.humano(C._tamano(ruta)))
        self._detalle.setMinimumWidth(1)
        self._detalle.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 10.5px;")
        col.addWidget(self._detalle)
        fila.addLayout(col, stretch=1)

        self._chapa = QLabel("")
        self._chapa.setVisible(False)
        fila.addWidget(self._chapa)

        quitar = make_btn("×", kind="subtle")
        quitar.setFixedSize(24, 24)
        quitar.setToolTip("Quitar de la lista")
        quitar.clicked.connect(lambda: self.quitar.emit(self._ruta))
        fila.addWidget(quitar)

    def ruta(self) -> str:
        return self._ruta

    def marcar_en_curso(self) -> None:
        self._detalle.setText("Comprimiendo…")

    def mostrar(self, r) -> None:
        if r.destino is None and not r.cumplio:
            self._detalle.setText(r.nota or "No se pudo comprimir")
            self._chapa.setText("sin cambios")
            self._pintar_chapa(T.DANGER, T.DANGER_SOFT)
        elif r.destino is None:
            self._detalle.setText(r.nota or "ya estaba por debajo del objetivo")
            self._chapa.setText("sin cambios")
            self._pintar_chapa(T.MUTED, T.PANEL)
        else:
            texto = f"{C.humano(r.bytes_antes)} → {C.humano(r.bytes_despues)}"
            if r.nota:
                texto += f" · {r.nota}"
            self._detalle.setText(texto)
            self._chapa.setText(f"−{r.ahorro_pct:.0f} %")
            if r.cumplio:
                self._pintar_chapa(T.ACCENT, T.ACCENT_SOFT)
            else:
                self._pintar_chapa(T.WARN, T.WARN_SOFT)
        self._chapa.setVisible(True)

    def _pintar_chapa(self, color: str, fondo: str) -> None:
        self._chapa.setStyleSheet(
            f"background: {fondo}; color: {color}; border-radius: {T.R_SM}px;"
            f" font-size: 11px; font-weight: 600; padding: 3px 8px;")


class CompressPanel(QWidget):
    """La pantalla entera de comprimir."""

    log = pyqtSignal(str, str)          # nivel, mensaje
    avance = pyqtSignal(float, str)     # 0..1, etiqueta
    trabajando = pyqtSignal(bool)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._filas: Dict[str, _Fila] = {}
        self._hilo: Optional[_Trabajo] = None

        fuera = QVBoxLayout(self)
        fuera.setContentsMargins(0, 0, 0, 0)
        fuera.setSpacing(9)

        entrada = Panel(padded=True)
        entrada.layout().addWidget(SectionLabel("Comprimir"))
        entrada.layout().addSpacing(6)
        self._zona = _Zona()
        self._zona.soltados.connect(self.anadir)
        entrada.layout().addWidget(self._zona)
        entrada.layout().addSpacing(10)
        entrada.layout().addWidget(self._build_objetivo())
        fuera.addWidget(entrada)

        lista = Panel(padded=True)
        lista.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._vaciar_btn = make_btn("Vaciar", kind="subtle")
        self._vaciar_btn.setFixedHeight(22)
        self._vaciar_btn.clicked.connect(self.vaciar)
        self._cabecera = SectionLabel("Archivos · 0", self._vaciar_btn)
        lista.layout().addWidget(self._cabecera)
        self._cab_lbl = self._cabecera.findChild(QLabel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        interior = QWidget()
        interior.setStyleSheet("background: transparent;")
        self._filas_lay = QVBoxLayout(interior)
        self._filas_lay.setContentsMargins(0, 4, 4, 0)
        self._filas_lay.setSpacing(5)

        self._vacio = QLabel("Aún no hay archivos.\nArrástralos arriba para empezar.")
        self._vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vacio.setWordWrap(True)
        self._vacio.setStyleSheet(
            f"background: transparent; font-size: 11.5px; color: {T.DIM};"
            f" padding: 24px 8px;")
        self._filas_lay.addWidget(self._vacio)
        self._filas_lay.addStretch()
        scroll.setWidget(interior)
        lista.layout().addWidget(scroll, stretch=1)
        fuera.addWidget(lista, stretch=1)

        self._accion = make_btn("Comprimir", kind="primary")
        self._accion.setFixedHeight(38)
        self._accion.clicked.connect(self._empezar_o_parar)
        fuera.addWidget(self._accion)
        self._refrescar()

    # -- Construccion ---------------------------------------------------------
    def _build_objetivo(self) -> QWidget:
        caja = QWidget()
        caja.setStyleSheet("background: transparent;")
        rejilla = QGridLayout(caja)
        rejilla.setContentsMargins(0, 0, 0, 0)
        rejilla.setSpacing(6)

        etiqueta = QLabel("Tamaño objetivo")
        etiqueta.setStyleSheet(
            f"background: transparent; color: {T.FG}; font-size: 12.5px;"
            f" font-weight: 500;")
        rejilla.addWidget(etiqueta, 0, 0)

        self._campo = QLineEdit(str(int(getattr(self._config, "compress_target_kb",
                                                C.OBJETIVO_POR_DEFECTO_KB))))
        self._campo.setFixedWidth(74)
        self._campo.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._campo.editingFinished.connect(self._guardar_objetivo)
        rejilla.addWidget(self._campo, 0, 1)

        kb = QLabel("KB")
        kb.setStyleSheet(f"background: transparent; color: {T.MUTED}; font-size: 12px;")
        rejilla.addWidget(kb, 0, 2)

        sub = QLabel("Cada archivo se comprime hasta caber en este tamaño. "
                     "El original no se toca: se guarda una copia al lado.")
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"background: transparent; color: {T.MUTED}; font-size: 10.5px;")
        rejilla.addWidget(sub, 1, 0, 1, 3)
        rejilla.setColumnStretch(0, 1)
        return caja

    # -- API ------------------------------------------------------------------
    def objetivo_kb(self) -> int:
        try:
            valor = int(float(self._campo.text().strip().replace(",", ".")))
        except ValueError:
            valor = C.OBJETIVO_POR_DEFECTO_KB
        return max(_OBJETIVO_MIN, min(_OBJETIVO_MAX, valor))

    def anadir(self, rutas: List[str]) -> None:
        nuevos = 0
        omitidos = 0
        for ruta in rutas:
            ruta = os.path.abspath(ruta)
            if ruta in self._filas:
                continue
            if not C.admitido(ruta):
                omitidos += 1
                continue
            fila = _Fila(ruta)
            fila.quitar.connect(self.quitar)
            self._filas[ruta] = fila
            self._filas_lay.insertWidget(self._filas_lay.count() - 1, fila)
            nuevos += 1
        if omitidos:
            self.log.emit("warn", f"{omitidos} archivo(s) que no son imagen ni PDF, omitidos")
        if nuevos:
            self.log.emit("info", f"{nuevos} archivo(s) listos para comprimir")
        self._refrescar()

    def quitar(self, ruta: str) -> None:
        fila = self._filas.pop(ruta, None)
        if fila is not None:
            self._filas_lay.removeWidget(fila)
            fila.setParent(None)
            fila.deleteLater()
        self._refrescar()

    def vaciar(self) -> None:
        for fila in list(self._filas.values()):
            self._filas_lay.removeWidget(fila)
            fila.setParent(None)
            fila.deleteLater()
        self._filas.clear()
        self._refrescar()

    def ocupado(self) -> bool:
        return self._hilo is not None and self._hilo.isRunning()

    def detener(self) -> None:
        if self._hilo is not None:
            self._hilo.abort()
            self._hilo.wait(5000)

    # -- Interno --------------------------------------------------------------
    def _guardar_objetivo(self) -> None:
        valor = self.objetivo_kb()
        self._campo.setText(str(valor))
        self._config.compress_target_kb = valor

    def _refrescar(self) -> None:
        n = len(self._filas)
        if self._cab_lbl is not None:
            self._cab_lbl.setText(f"ARCHIVOS · {n}")
        self._vacio.setVisible(n == 0)
        if not self.ocupado():
            self._accion.setEnabled(n > 0)
            self._accion.setText("Comprimir" if n != 1 else "Comprimir 1 archivo")
            if n > 1:
                self._accion.setText(f"Comprimir {n} archivos")

    def _empezar_o_parar(self) -> None:
        if self.ocupado():
            self.detener()
            return
        rutas = list(self._filas)
        if not rutas:
            return
        self._guardar_objetivo()
        objetivo = self.objetivo_kb()
        for fila in self._filas.values():
            fila.marcar_en_curso()

        self._hilo = _Trabajo(rutas, objetivo, self)
        self._hilo.avance.connect(self._on_avance)
        self._hilo.listo_uno.connect(self._on_uno)
        self._hilo.terminado.connect(self._on_fin)
        self._hilo.start()

        self._accion.setText("Detener")
        self._accion.setEnabled(True)
        self.trabajando.emit(True)
        self.log.emit("info", f"Comprimiendo {len(rutas)} archivo(s) a {objetivo} KB")

    def _on_avance(self, hecho: int, total: int, nombre: str) -> None:
        fraccion = hecho / total if total else 1.0
        etiqueta = f"Comprimiendo {hecho + 1} de {total}" if nombre else "Comprimiendo"
        self.avance.emit(fraccion, etiqueta)

    def _on_uno(self, r) -> None:
        fila = self._filas.get(os.path.abspath(r.origen))
        if fila is not None:
            fila.mostrar(r)
        if r.destino:
            nivel = "ok" if r.cumplio else "warn"
            self.log.emit(nivel, f"{os.path.basename(r.origen)}: "
                                 f"{C.humano(r.bytes_antes)} → {C.humano(r.bytes_despues)}"
                                 + (f" · {r.nota}" if r.nota else ""))
        else:
            self.log.emit("warn", f"{os.path.basename(r.origen)}: {r.nota}")

    def _on_fin(self) -> None:
        self._hilo = None
        self.trabajando.emit(False)
        self.avance.emit(1.0, "Compresión terminada")
        self._refrescar()
