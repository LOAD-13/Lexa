<div align="center">

<img src="icon.png" width="96" alt="Lexa">

# Lexa

**Convierte audio, video, imágenes y PDFs en texto. Todo en tu computadora.**

Aplicación de escritorio para Windows. Sin cuentas, sin API keys, sin subir
nada a internet.

</div>

---

## Qué hace

| Entrada | Qué obtienes |
|---|---|
| 🎙️ **Audio** — mp3, wav, m4a, ogg, flac, aac, opus, wma… | Transcripción con puntuación, agrupada en párrafos |
| 🎬 **Video** — mp4, mkv, avi, mov, webm… | Lo mismo, extrayendo la pista de audio |
| 🖼️ **Imágenes** — jpg, png, webp, tiff… | Texto reconocido con OCR, respetando el orden de lectura |
| 📄 **PDF** — nativos y **escaneados** | Texto embebido cuando existe; OCR página a página cuando la letra es una imagen |

Además:

- **Identificación de hablantes** — separa quién dice qué en una conversación.
- **Exporta a TXT, Word, PDF, Markdown, SRT y VTT** — los dos últimos son
  subtítulos listos para un reproductor de video.
- **Funciona sin conexión** una vez descargados los modelos.
- **Arrastra una carpeta entera** y procesa todo lo que haya dentro.

## Instalación

### Opción A — El ejecutable (recomendado para usar)

Descarga la última versión desde [Releases](../../releases), descomprime y haz
doble clic en **`Lexa.exe`**.

No necesitas Python ni instalar nada más. La primera vez que proceses un
archivo, Lexa descargará los modelos de IA (~1.7 GB) mostrando una barra de
progreso. Solo ocurre una vez.

### Opción B — Desde el código (para desarrollar)

```bash
git clone https://github.com/LOAD-13/lexaTranscriptionApp.git
cd lexaTranscriptionApp
pip install -r requirements.txt
python main.py
```

Requiere Python 3.10 o superior. En Windows, `Lexa.pyw` arranca la app sin
que aparezca una ventana de consola.

## Uso

1. Arrastra tus archivos a la zona de entrada (o pulsa **Elegir archivos**).
2. Ajusta idioma, calidad y formato de salida en el panel derecho.
3. Pulsa **Iniciar procesamiento**.

El resultado aparece en el centro y se guarda automáticamente en
`Documentos\Lexa`. La primera vez que abras la app, el asistente **Lexa** te da
un tour guiado; puedes repetirlo desde el botón **?** de la barra superior.

## Modelos de calidad

| Modelo | Descarga | Cuándo usarlo |
|---|---|---|
| Tiny | 75 MB | Pruebas rápidas, audio muy claro |
| Base | 145 MB | Notas de voz cortas |
| Small | 480 MB | Buen equilibrio en equipos modestos |
| Medium | 1.5 GB | Audio con ruido de fondo |
| **Turbo** ⭐ | 1.6 GB | **Por defecto.** Casi la calidad de Large a bastante más velocidad |
| Large | 3.1 GB | Máxima precisión, audio difícil o acentos marcados |

Cada modelo se descarga solo la primera vez que lo eliges y queda guardado en
`%LOCALAPPDATA%\Lexa\models`.

Si tienes una **GPU NVIDIA**, Lexa la detecta y la usa automáticamente
(`float16`); si no, corre en CPU con cuantización `int8`.

## Cómo está construido

```
main.py               Punto de entrada
core/
  models.py           FileItem, FileKind, AppConfig, Segment
  paths.py            Rutas de modelos y configuración (compatible con el .exe)
  config_store.py     Persistencia en %APPDATA%\Lexa\config.json
  downloader.py       Descarga de modelos con progreso en bytes
  formatter.py        Segment[] → párrafos / SRT / VTT / JSON
  exporter.py         TXT, MD, PDF, DOCX, SRT, VTT
  worker.py           Hilo de procesamiento (QThread)
  engines/
    media.py          PyAV: audio y video → PCM 16 kHz mono
    asr.py            faster-whisper
    diarize.py        sherpa-onnx
    ocr.py            RapidOCR (Tesseract opcional)
    pdf.py            PyMuPDF, con OCR por página cuando hace falta
ui/                   PyQt6: paneles, tour guiado, modal de descarga
```

Los motores no conocen Qt y devuelven siempre `Segment[]`; el worker es el
único puente con la interfaz. `formatter.py` es el único módulo que decide cómo
se ve el texto final.

### Por qué estas librerías

| Se usa | En lugar de | Motivo |
|---|---|---|
| `faster-whisper` | `openai-whisper` | 4-8× más rápido y **sin PyTorch**: ~2.5 GB menos |
| `sherpa-onnx` | `pyannote.audio` | Diarización equivalente sobre ONNX, sin PyTorch ni token de HuggingFace |
| `rapidocr-onnxruntime` | `easyocr` | No arrastra PyTorch y arranca al instante |
| `PyAV` | `ffmpeg` del sistema | Trae ffmpeg dentro del paquete: cero dependencias externas |

El resultado es que la app completa cabe en ~400 MB y no requiere instalar
absolutamente nada en el sistema.

> **Nota sobre el OCR en español:** el modelo por defecto de RapidOCR está
> entrenado en chino e inglés y su diccionario no incluye `á é í ó ú ñ ü`, así
> que devuelve «traduccion» en vez de «traducción». Lexa descarga y usa
> `latin_PP-OCRv5_mobile_rec`, que sí cubre el alfabeto latino completo.

## Generar el ejecutable

```bash
pip install pyinstaller
python build_exe.py       # o doble clic en build.bat
```

Genera `dist\Lexa\Lexa.exe` en modo *onedir*, sin consola y con el icono
aplicado. Para distribuirlo, comprime la carpeta `dist\Lexa` completa.

## Dónde guarda las cosas

| Qué | Dónde |
|---|---|
| Modelos de IA | `%LOCALAPPDATA%\Lexa\models` |
| Configuración | `%APPDATA%\Lexa\config.json` |
| Log de errores de arranque | `%APPDATA%\Lexa\error.log` |
| Resultados | `Documentos\Lexa` (configurable) |

Borrar la carpeta de modelos fuerza una descarga limpia; borrar `config.json`
devuelve todos los ajustes a sus valores por defecto.

## Problemas conocidos

- **La primera transcripción tarda más de lo normal.** El modelo se carga en
  memoria una sola vez; a partir del segundo archivo va a velocidad normal.
- **Activar «Identificar hablantes» añade un 30-40 % al tiempo de proceso.**
  Por eso viene desactivado.
- **Un video sin pista de audio** produce un error explícito en vez de un
  resultado vacío.

## Licencia

MIT.

Los modelos que descarga son de terceros y mantienen sus propias licencias:
Whisper (MIT, OpenAI), pyannote-segmentation-3.0 (MIT), 3D-Speaker CAM++
(Apache 2.0), PP-OCRv5 (Apache 2.0). Las fuentes Noto Sans incluidas están bajo
SIL Open Font License 1.1.
