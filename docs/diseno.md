# Lexa 1.0 — Diseño

Fecha: 2026-08-12
Estado: aprobado por el usuario

## Objetivo

Convertir Lexa en una app de escritorio que un usuario promedio abre con **un clic** y usa
sin instalar nada: transcripción de audio y video, OCR de imágenes y PDFs escaneados,
exportación a múltiples formatos. Sin consola visible, sin scripts previos, sin
dependencias del sistema.

## Decisiones tomadas

| Tema | Decisión | Motivo |
|---|---|---|
| Distribución | `Lexa.exe` autocontenido (PyInstaller onedir, `--noconsole`, `--icon`) | El usuario final no necesita Python |
| Motor ASR | `faster-whisper` (CTranslate2) | 4-8x más rápido, misma precisión, **sin torch** |
| Diarización | `sherpa-onnx` (pyannote-seg-3.0 ONNX + 3D-Speaker) | Diarización real sin torch ni token de HuggingFace |
| OCR | `rapidocr-onnxruntime`, Tesseract opcional | Sin torch, sin binario externo |
| Video / audio | `PyAV` | Trae ffmpeg compilado; elimina la dependencia del sistema |
| PDF | `PyMuPDF` híbrido | Texto embebido + rasterizado→OCR por página |
| Traducción de idioma | No se implementa | El alcance es voz→texto; el foco es mejorar el formato de salida |

**Consecuencia clave:** torch desaparece del proyecto. La instalación baja de ~3 GB a ~350 MB,
lo que hace viable congelar la app en un `.exe` distribuible.

## Arquitectura

```
main.py / Lexa.pyw          Entrada (sin consola)
core/
  models.py                 FileItem, FileKind{AUDIO,VIDEO,IMAGE,PDF}, AppConfig, Segment
  config_store.py           Persistencia JSON en %APPDATA%\Lexa\config.json
  paths.py                  Rutas de modelos, caché, recursos (frozen-aware)
  downloader.py             Descarga de modelos con progreso en bytes
  formatter.py              Segment[] -> párrafos / timestamps / SRT / VTT / JSON
  exporter.py               TXT, MD, PDF (Unicode), DOCX, SRT, VTT
  worker.py                 QThread; despacha por FileKind
  engines/
    media.py                PyAV: audio/video -> PCM float32 16 kHz mono
    asr.py                  faster-whisper -> Segment[]
    diarize.py              sherpa-onnx -> turnos de hablante; merge por solapamiento
    ocr.py                  RapidOCR (primario) / pytesseract (si está instalado)
    pdf.py                  PyMuPDF: texto embebido + OCR por página
ui/
  theme.py, widgets.py      Sistema de diseño
  main_window.py            Splitters, orquestación
  left_panel.py             Dropzone (archivos y carpetas) + cola
  center_panel.py           Vista previa (Formateado / Plano / JSON)
  right_panel.py            Ajustes dentro de QScrollArea
  footer.py                 Progreso global fraccional + ETA + registros
  setup_dialog.py           Modal bloqueante de descarga (solo primer uso)
  tour.py                   Asistente Lexa: overlay con spotlight, 7 pasos
```

Cada engine expone una función pura con firma `(path, opts, progress_cb) -> Segment[] | str`
y no conoce a Qt. El worker es el único puente entre engines y UI.

## Modelo de datos

`Segment` es la unidad común que producen ASR y OCR:

```python
@dataclass
class Segment:
    start: float          # segundos; 0.0 para OCR
    end: float
    text: str
    speaker: str | None   # "1", "2", ... tras la diarización
    page: int | None      # nº de página para PDF
```

`formatter.py` es el único que convierte `Segment[]` a texto. Esto elimina la duplicación
actual entre transcriber (que ya formateaba) y exporter.

## Formato de salida

El problema actual es que se emite una línea por segmento de Whisper, lo que se lee como
subtítulos y no como documento. El nuevo formateo:

- Agrupa segmentos consecutivos en párrafos; corta cuando hay un silencio > 1.2 s
  o un cambio de hablante.
- Con diarización activa, prefija cada turno con `Hablante N:`.
- Los timestamps (opcionales, apagados por defecto) van al inicio del párrafo, no de cada línea.
- SRT y VTT usan los segmentos crudos, sin agrupar (es lo correcto para subtítulos).

## Descarga de modelos

Modal bloqueante centrado, sin botón de cerrar, con barra de progreso real en bytes.
Aparece **solo cuando falta un modelo**. Los modelos viven en
`%LOCALAPPDATA%\Lexa\models\`; la presencia del directorio del modelo es la señal de
"ya descargado". Cambiar de modelo Whisper dispara la descarga solo de ese modelo nuevo.

## Layout

Causa raíz del bug reportado: el panel derecho pide ~800 px de alto fijo y no puede
encogerse, por lo que sus widgets se superponen bajo la altura mínima de ventana.

- `QSplitter` horizontal para las tres columnas (izq. ≥240, centro elástico, der. 300-380).
- `QScrollArea` dentro del panel derecho.
- `QSplitter` vertical entre contenido y footer; footer colapsable (≥110 px).
- Ventana mínima 980×640. Las posiciones de los splitters se persisten.

## Defaults

`modelo = large-v3-turbo`, `idioma = es`, `timestamps = OFF`, `diarización = OFF`,
`formato = txt`, `modo = per-file`.

## Fuera de alcance

- Traducción entre idiomas (solo transcripción).
- Modelos por API (todo corre local y offline tras la primera descarga).
- Edición del texto transcrito dentro de la app.
