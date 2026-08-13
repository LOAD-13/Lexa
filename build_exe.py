"""Genera dist/Lexa/Lexa.exe con PyInstaller.

Uso:  python build_exe.py        (o doble clic en build.bat)

Se construye en modo «onedir» a proposito: con onefile, Windows descomprime
~400 MB en una carpeta temporal en cada arranque, lo que anade 10-20 segundos
antes de que aparezca la ventana.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")

# Modulos que PyInstaller no detecta porque se importan de forma diferida
# dentro de funciones, para que la app arranque rapido.
HIDDEN_IMPORTS = [
    "faster_whisper",
    "ctranslate2",
    "sherpa_onnx",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "pymupdf",
    "av",
    "fpdf",
    "docx",
    "PIL.Image",
    "PIL.ImageOps",
    "yaml",
]

# Paquetes con datos que hay que copiar enteros (modelos ONNX incluidos,
# archivos de configuracion, tokenizadores).
COLLECT_ALL = [
    "rapidocr_onnxruntime",
    "sherpa_onnx",
    "faster_whisper",
    "onnxruntime",
    "av",
]

# Nada de esto se usa y pesa mucho. numba y llvmlite (~110 MB) son restos de
# openai-whisper, que se reemplazó por faster-whisper; se verificó que ningún
# motor los necesita.
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "tensorflow",
    "matplotlib", "scipy", "pandas", "notebook", "IPython",
    "easyocr", "tkinter", "test", "unittest",
    "numba", "llvmlite",
]

# Archivos que PyInstaller copia por precaución y esta app nunca abre.
# Se borran tras la compilación porque no hay forma de excluir datos sueltos
# desde la línea de comandos.
PRUNE_PATTERNS = [
    # OpenCV llega con RapidOCR, que solo la usa para redimensionar y recortar
    # imágenes. Los códecs de video son ~54 MB que nunca se ejecutan.
    "cv2/opencv_videoio_ffmpeg*.dll",
    "cv2/opencv_videoio_ffmpeg*.dll",
    # Traducciones de Qt: la interfaz está solo en español y usa sus propias cadenas.
    "PyQt6/Qt6/translations/*",
]


def ensure_icon() -> str:
    """Convierte icon.png a un .ico multi-resolucion si hace falta."""
    png = os.path.join(ROOT, "icon.png")
    ico = os.path.join(ROOT, "icon.ico")
    if os.path.isfile(ico) and os.path.getmtime(ico) >= os.path.getmtime(png):
        return ico
    if not os.path.isfile(png):
        raise SystemExit("Falta icon.png en la carpeta del proyecto.")
    from PIL import Image
    image = Image.open(png).convert("RGBA")
    image.save(ico, format="ICO",
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                      (64, 64), (128, 128), (256, 256)])
    print(f"[build] icon.ico generado desde icon.png")
    return ico


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller no está instalado.\n"
            "Instálalo con:  pip install pyinstaller"
        )

    icon = ensure_icon()

    for folder in (DIST, BUILD):
        if os.path.isdir(folder):
            print(f"[build] limpiando {folder}")
            shutil.rmtree(folder, ignore_errors=True)

    separator = ";" if os.name == "nt" else ":"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Lexa",
        "--noconfirm",
        "--clean",
        "--windowed",             # sin consola: no aparece ningún CMD
        "--onedir",
        "--icon", icon,
        "--add-data", f"{os.path.join(ROOT, 'icon.png')}{separator}.",
        "--add-data", f"{os.path.join(ROOT, 'icon.ico')}{separator}.",
        "--add-data", f"{os.path.join(ROOT, 'fonts')}{separator}fonts",
    ]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    for package in COLLECT_ALL:
        command += ["--collect-all", package]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command.append(os.path.join(ROOT, "main.py"))

    print("[build] ejecutando PyInstaller…\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("\n[build] PyInstaller falló.", file=sys.stderr)
        return result.returncode

    exe = os.path.join(DIST, "Lexa", "Lexa.exe")
    if not os.path.isfile(exe):
        print("\n[build] No se generó el ejecutable.", file=sys.stderr)
        return 1

    app_dir = os.path.join(DIST, "Lexa")
    before = _folder_size(app_dir)
    freed = prune(app_dir)
    after = _folder_size(app_dir)

    print(f"\n[build] Listo: {exe}")
    if freed:
        print(f"[build] Podados {freed / 1024 ** 2:.0f} MB de archivos no usados "
              f"({before / 1024 ** 2:.0f} → {after / 1024 ** 2:.0f} MB)")
    print(f"[build] Tamaño de la carpeta: {after / 1024 ** 2:.0f} MB")
    print("[build] Para distribuir, comprime la carpeta dist\\Lexa completa.")
    return 0


def prune(app_dir: str) -> int:
    """Borra los archivos de PRUNE_PATTERNS. Devuelve los bytes liberados."""
    import glob

    internal = os.path.join(app_dir, "_internal")
    freed = 0
    for pattern in PRUNE_PATTERNS:
        for path in glob.glob(os.path.join(internal, pattern.replace("/", os.sep))):
            try:
                if os.path.isdir(path):
                    freed += _folder_size(path)
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    freed += os.path.getsize(path)
                    os.remove(path)
            except OSError:
                pass
    return freed


def _folder_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


if __name__ == "__main__":
    sys.exit(main())
