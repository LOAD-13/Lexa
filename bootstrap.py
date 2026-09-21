"""Arranque de un clic desde el código fuente.

Comprueba las dependencias, instala las que falten mostrando una barra de
progreso, y lanza la aplicación. Usa solo tkinter, que viene con Python, para
poder dibujar la ventana antes de que exista ninguna otra librería.

Este archivo es para quien clona el repositorio. El usuario final descarga el
.exe desde Releases y no pasa por aquí.
"""
from __future__ import annotations
import os
import subprocess
import sys
import threading

# (módulo que se importa, paquete que hay que instalar, texto visible)
REQUIREMENTS = [
    ("PyQt6",                 "PyQt6>=6.6.0",                 "Interfaz gráfica"),
    ("faster_whisper",        "faster-whisper>=1.1.0",        "Reconocimiento de voz"),
    ("av",                    "av>=13.0.0",                   "Lector de audio y video"),
    ("sherpa_onnx",           "sherpa-onnx>=1.10.0",          "Identificación de hablantes"),
    ("rapidocr_onnxruntime",  "rapidocr-onnxruntime>=1.3.0",  "Lectura de texto en imágenes"),
    ("fitz",                  "PyMuPDF>=1.24.0",              "Lectura de PDF"),
    ("PIL",                   "Pillow>=10.0.0",               "Tratamiento de imágenes"),
    ("yaml",                  "PyYAML>=6.0",                  "Archivos de configuración"),
    ("fpdf",                  "fpdf2>=2.7.0",                 "Exportación a PDF"),
    ("docx",                  "python-docx>=1.1.0",           "Exportación a Word"),
]

MIN_PYTHON = (3, 10)


def missing_packages() -> list[tuple[str, str, str]]:
    """Devuelve las dependencias que no están instaladas."""
    import importlib.util

    missing = []
    for module, package, label in REQUIREMENTS:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append((module, package, label))
        except (ImportError, ValueError):
            missing.append((module, package, label))
    return missing


def launch_app() -> int:
    """Arranca Lexa en este mismo proceso."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from main import main
    return main()


# ─────────────────────────────────────────────────────────────────────────────
def run_installer(pending: list[tuple[str, str, str]]) -> bool:
    """Ventana con barra de progreso que instala lo que falta.

    Devuelve True si todo quedó instalado.
    """
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title("Preparando Lexa")
    root.configure(bg="#16181c")
    root.resizable(False, False)

    width, height = 460, 210
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    if os.path.isfile(icon):
        try:
            root.iconphoto(True, tk.PhotoImage(file=icon))
        except Exception:
            pass

    tk.Label(root, text="Preparando Lexa", bg="#16181c", fg="#e6e7e9",
             font=("Segoe UI", 16, "bold")).pack(pady=(26, 4))
    tk.Label(root,
             text=f"Instalando {len(pending)} componente(s). Solo ocurre la primera vez.",
             bg="#16181c", fg="#7d8089", font=("Segoe UI", 9)).pack()

    status = tk.Label(root, text="Iniciando…", bg="#16181c", fg="#b8bbc1",
                      font=("Segoe UI", 9))
    status.pack(pady=(22, 6))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Lexa.Horizontal.TProgressbar",
                    troughcolor="#0d0e10", background="#6ec99a",
                    bordercolor="#0d0e10", lightcolor="#6ec99a",
                    darkcolor="#6ec99a", thickness=8)

    bar = ttk.Progressbar(root, style="Lexa.Horizontal.TProgressbar",
                          length=380, maximum=len(pending))
    bar.pack()

    counter = tk.Label(root, text=f"0 / {len(pending)}", bg="#16181c",
                       fg="#54575e", font=("Consolas", 8))
    counter.pack(pady=(6, 0))

    state = {"ok": False, "error": ""}

    def worker() -> None:
        for index, (_module, package, label) in enumerate(pending):
            root.after(0, lambda l=label: status.config(text=f"Instalando {l}…"))
            try:
                # Sin ventana de consola emergente en Windows.
                creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--quiet",
                     "--disable-pip-version-check", package],
                    capture_output=True, text=True, creationflags=creation,
                )
                if result.returncode != 0:
                    state["error"] = (
                        f"No se pudo instalar «{package}».\n\n"
                        f"{(result.stderr or result.stdout or '').strip()[-600:]}"
                    )
                    root.after(0, root.quit)
                    return
            except Exception as exc:
                state["error"] = f"No se pudo instalar «{package}».\n\n{exc}"
                root.after(0, root.quit)
                return

            done = index + 1
            root.after(0, lambda d=done: (bar.config(value=d),
                                          counter.config(text=f"{d} / {len(pending)}")))

        state["ok"] = True
        root.after(0, lambda: status.config(text="Todo listo, abriendo Lexa…"))
        root.after(500, root.quit)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()

    if not state["ok"] and state["error"]:
        messagebox.showerror("Error al preparar Lexa", state["error"])
    root.destroy()
    return state["ok"]


def show_python_error() -> None:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Python demasiado antiguo",
        f"Lexa necesita Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} o superior.\n\n"
        f"Tienes la versión {sys.version_info.major}.{sys.version_info.minor}.\n\n"
        "Descárgalo desde https://www.python.org/downloads/",
    )
    root.destroy()


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        show_python_error()
        return 1

    pending = missing_packages()
    if pending and not run_installer(pending):
        return 1

    return launch_app()


if __name__ == "__main__":
    sys.exit(main())
