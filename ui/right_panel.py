"""Panel derecho: ajustes de procesamiento y exportación + botones de acción.

Todo el contenido vive dentro de un QScrollArea. Sin él los widgets de altura
fija superan el alto de la ventana y Qt los superpone en vez de comprimirlos,
que era la causa del layout roto cuando la ventana no estaba maximizada.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.models import AppConfig, LANGUAGES, WHISPER_MODELS
from ui import theme as T
from ui.widgets import (
    FormatChip, Panel, RadioOption, SectionLabel,
    SettingRow, ToggleSwitch, hdivider, make_btn,
)

_FORMATS = [
    ("txt",  "TXT",  "Texto plano"),
    ("docx", "DOCX", "Word"),
    ("pdf",  "PDF",  "Imprimible"),
    ("md",   "MD",   "Markdown"),
    ("srt",  "SRT",  "Subtítulos"),
    ("vtt",  "VTT",  "Subtítulos web"),
]


class RightPanel(QWidget):
    config_changed   = pyqtSignal(object)
    start_requested  = pyqtSignal()
    export_requested = pyqtSignal()
    clear_requested  = pyqtSignal()
    open_folder_requested = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self.setMinimumWidth(292)
        self.setMaximumWidth(400)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        # ── Zona con scroll ──────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        content = QVBoxLayout(inner)
        content.setContentsMargins(0, 0, 6, 0)   # hueco para la barra de scroll
        content.setSpacing(9)

        content.addWidget(self._build_processing())
        content.addWidget(self._build_export())
        content.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # ── Acciones (siempre visibles, fuera del scroll) ────────────
        root.addWidget(self._build_actions())

    # ── Procesamiento ────────────────────────────────────────────────────────
    def _build_processing(self) -> Panel:
        panel = Panel(padded=True)
        panel.layout().setSpacing(0)
        panel.layout().addWidget(SectionLabel("Procesamiento"))
        self.processing_panel = panel

        cfg = self._config

        self._audio_toggle = ToggleSwitch(cfg.transcribe_audio)
        self._audio_toggle.toggled.connect(self._on_audio_toggle)
        row = SettingRow("Transcribir audio y video",
                         "Convierte la voz en texto", self._audio_toggle)
        panel.layout().addWidget(row)
        panel.layout().addWidget(row.separator())

        self._ocr_toggle = ToggleSwitch(cfg.ocr_images)
        self._ocr_toggle.toggled.connect(self._on_ocr_toggle)
        row = SettingRow("Extraer texto de imágenes y PDF",
                         "OCR, también en documentos escaneados", self._ocr_toggle)
        panel.layout().addWidget(row)
        panel.layout().addWidget(row.separator())

        # Los desplegables van a lo ancho completo debajo de su etiqueta: si se
        # ponen al lado, se comen el espacio y el texto descriptivo se parte en
        # tres líneas cuando el panel es estrecho.
        self._lang_combo = QComboBox()
        for value, label in LANGUAGES:
            self._lang_combo.addItem(label, value)
        self._select_data(self._lang_combo, cfg.language)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_change)
        panel.layout().addWidget(
            _stacked_setting("Idioma", "Del contenido, no de la app", self._lang_combo)
        )
        panel.layout().addWidget(hdivider())

        self._model_combo = QComboBox()
        for value, label, size in WHISPER_MODELS:
            self._model_combo.addItem(f"{label} · {size}", value)
        self._select_data(self._model_combo, cfg.whisper_model)
        self._model_combo.currentIndexChanged.connect(self._on_model_change)
        panel.layout().addWidget(
            _stacked_setting("Calidad", "Se descarga solo la primera vez",
                             self._model_combo)
        )
        panel.layout().addWidget(hdivider())

        self._spk_toggle = ToggleSwitch(cfg.include_speakers)
        self._spk_toggle.toggled.connect(self._on_spk_toggle)
        row = SettingRow("Identificar hablantes",
                         "Separa quién dice qué · más lento", self._spk_toggle)
        panel.layout().addWidget(row)
        panel.layout().addWidget(row.separator())

        self._ts_toggle = ToggleSwitch(cfg.include_timestamps)
        self._ts_toggle.toggled.connect(self._on_ts_toggle)
        row = SettingRow("Marcas de tiempo",
                         "Solo en audio y video", self._ts_toggle)
        panel.layout().addWidget(row)

        return panel

    # ── Exportación ──────────────────────────────────────────────────────────
    def _build_export(self) -> Panel:
        panel = Panel(padded=True)
        panel.layout().setSpacing(0)
        panel.layout().addWidget(SectionLabel("Exportación"))
        self.export_panel = panel

        cfg = self._config

        label = QLabel("Formato")
        label.setStyleSheet(
            f"background: transparent; font-size: 11px; color: {T.MUTED}; "
            f"margin-top: 4px; margin-bottom: 7px;"
        )
        panel.layout().addWidget(label)

        # Rejilla 3x2: se adapta al ancho sin desbordar como haría una fila.
        grid = QGridLayout()
        grid.setSpacing(6)
        self._chips: dict[str, FormatChip] = {}
        for index, (value, title, sub) in enumerate(_FORMATS):
            chip = FormatChip(value, title, sub)
            chip.setActive(value == cfg.export_format)
            chip.clicked.connect(lambda v=value: self._on_format_click(v))
            grid.addWidget(chip, index // 3, index % 3)
            self._chips[value] = chip
        panel.layout().addLayout(grid)

        panel.layout().addSpacing(14)

        label = QLabel("Estructura")
        label.setStyleSheet(
            f"background: transparent; font-size: 11px; color: {T.MUTED}; margin-bottom: 7px;"
        )
        panel.layout().addWidget(label)

        self._radio_per = RadioOption(
            "per-file", "Un archivo por entrada", "Conserva los nombres originales"
        )
        self._radio_per.setActive(cfg.output_mode == "per-file")
        self._radio_per.clicked.connect(lambda: self._on_mode_click("per-file"))
        panel.layout().addWidget(self._radio_per)

        panel.layout().addSpacing(6)

        self._radio_merged = RadioOption(
            "merged", "Documento combinado", "Todo junto en un solo archivo"
        )
        self._radio_merged.setActive(cfg.output_mode == "merged")
        self._radio_merged.clicked.connect(lambda: self._on_mode_click("merged"))
        panel.layout().addWidget(self._radio_merged)

        panel.layout().addSpacing(11)
        panel.layout().addWidget(hdivider())

        loc_btn = make_btn("Cambiar", kind="subtle")
        loc_btn.setFixedHeight(25)
        loc_btn.clicked.connect(self._choose_location)
        self._loc_row = SettingRow(
            "Carpeta de guardado", _short_path(cfg.save_location), loc_btn
        )
        panel.layout().addWidget(self._loc_row)
        panel.layout().addWidget(self._loc_row.separator())

        self._auto_toggle = ToggleSwitch(cfg.auto_export)
        self._auto_toggle.toggled.connect(self._on_auto_toggle)
        row = SettingRow("Guardar automáticamente",
                         "Al terminar de procesar", self._auto_toggle)
        panel.layout().addWidget(row)

        return panel

    # ── Acciones ─────────────────────────────────────────────────────────────
    def _build_actions(self) -> QWidget:
        """Botón principal a lo ancho, secundarios en su propia fila.

        En una sola fila, los tres botones de icono dejan al principal sin
        espacio y su texto se corta cuando el panel está en su ancho mínimo.
        """
        actions = QWidget()
        actions.setStyleSheet("background: transparent;")
        column = QVBoxLayout(actions)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(7)

        self.start_btn = make_btn("▶   Iniciar procesamiento", kind="primary")
        self.start_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self.start_requested)
        column.addWidget(self.start_btn)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)

        self.export_btn = make_btn("↓  Exportar", kind="ghost")
        self.export_btn.setToolTip("Guardar los resultados ahora")
        self.export_btn.setFixedHeight(32)
        self.export_btn.clicked.connect(self.export_requested)
        row.addWidget(self.export_btn, stretch=1)

        self.folder_btn = make_btn("Carpeta", kind="ghost")
        self.folder_btn.setToolTip("Abrir la carpeta de guardado")
        self.folder_btn.setFixedHeight(32)
        self.folder_btn.clicked.connect(self.open_folder_requested)
        row.addWidget(self.folder_btn, stretch=1)

        self.clear_btn = make_btn("Vaciar", kind="danger")
        self.clear_btn.setToolTip("Quitar todos los archivos y limpiar el registro")
        self.clear_btn.setFixedHeight(32)
        self.clear_btn.clicked.connect(self.clear_requested)
        row.addWidget(self.clear_btn, stretch=1)

        column.addLayout(row)
        return actions

    # ── API pública ──────────────────────────────────────────────────────────
    def set_processing(self, active: bool) -> None:
        self.start_btn.setText("■   Detener" if active else "▶   Iniciar procesamiento")
        self.start_btn.setProperty("kind", "danger-solid" if active else "primary")
        self._restyle_start(active)
        # Cambiar ajustes a mitad de un lote produciría resultados inconsistentes.
        for widget in (self._model_combo, self._lang_combo,
                       self._spk_toggle, self._audio_toggle, self._ocr_toggle):
            widget.setEnabled(not active)

    def _restyle_start(self, active: bool) -> None:
        if active:
            self.start_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {T.DANGER}; color: #ffffff;
                    border: 1px solid transparent; border-radius: 9px;
                    font-size: 13px; font-weight: 600; padding: 9px 16px;
                }}
                QPushButton:hover {{ background: #d98080; }}
            """)
        else:
            self.start_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {T.ACCENT}; color: {T.ACCENT_TEXT};
                    border: 1px solid transparent; border-radius: 9px;
                    font-size: 13px; font-weight: 600; padding: 9px 16px;
                }}
                QPushButton:hover {{ background: #7fd9a9; }}
                QPushButton:pressed {{ background: #5ab884; }}
                QPushButton:disabled {{ background: {T.LINE}; color: {T.DIM}; }}
            """)

    # ── Slots ────────────────────────────────────────────────────────────────
    def _emit(self) -> None:
        self.config_changed.emit(self._config)

    def _on_audio_toggle(self, value: bool) -> None:
        self._config.transcribe_audio = value
        self._emit()

    def _on_ocr_toggle(self, value: bool) -> None:
        self._config.ocr_images = value
        self._emit()

    def _on_lang_change(self, _index: int) -> None:
        self._config.language = self._lang_combo.currentData()
        self._emit()

    def _on_model_change(self, _index: int) -> None:
        self._config.whisper_model = self._model_combo.currentData()
        self._emit()

    def _on_format_click(self, value: str) -> None:
        self._config.export_format = value
        for key, chip in self._chips.items():
            chip.setActive(key == value)
        self._emit()

    def _on_mode_click(self, mode: str) -> None:
        self._config.output_mode = mode
        self._radio_per.setActive(mode == "per-file")
        self._radio_merged.setActive(mode == "merged")
        self._emit()

    def _on_ts_toggle(self, value: bool) -> None:
        self._config.include_timestamps = value
        self._emit()

    def _on_spk_toggle(self, value: bool) -> None:
        self._config.include_speakers = value
        self._emit()

    def _on_auto_toggle(self, value: bool) -> None:
        self._config.auto_export = value
        self._emit()

    def _choose_location(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta de guardado", self._config.save_location
        )
        if folder:
            self._config.save_location = folder
            self._loc_row.set_sub(_short_path(folder))
            self._emit()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)


def _stacked_setting(label: str, sub: str, control: QWidget) -> QWidget:
    """Etiqueta y descripción arriba, control a lo ancho completo debajo."""
    wrapper = QWidget()
    wrapper.setStyleSheet("background: transparent;")
    column = QVBoxLayout(wrapper)
    column.setContentsMargins(0, 9, 0, 9)
    column.setSpacing(2)

    title = QLabel(label)
    title.setStyleSheet(
        f"background: transparent; font-size: 12.5px; font-weight: 500; color: {T.FG};"
    )
    column.addWidget(title)

    caption = QLabel(sub)
    caption.setWordWrap(True)
    caption.setStyleSheet(f"background: transparent; font-size: 10.5px; color: {T.MUTED};")
    column.addWidget(caption)

    column.addSpacing(6)
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    column.addWidget(control)
    return wrapper


def _short_path(path: str) -> str:
    import os
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path
