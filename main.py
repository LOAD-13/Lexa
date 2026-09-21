"""Lexa — transcripción de audio, video, imágenes y PDF. Punto de entrada."""
from __future__ import annotations
import os
import subprocess       # se importa aqui a proposito: ver apply_pending_update
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon
from PyQt6.QtCore import Qt

from core.config_store import load_config, save_config
from core.paths import resource
from ui.theme import GLOBAL_QSS, BG, FG, PANEL, ACCENT


def setup_palette(app: QApplication) -> None:
    """Paleta oscura para que los diálogos nativos combinen con el tema."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(FG))
    palette.setColor(QPalette.ColorRole.Base,            QColor(PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor("#111316"))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(FG))
    palette.setColor(QPalette.ColorRole.Text,            QColor(FG))
    palette.setColor(QPalette.ColorRole.Button,          QColor(PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(FG))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a1610"))
    app.setPalette(palette)


def set_windows_app_id() -> None:
    """Agrupa la ventana bajo su propio icono en la barra de tareas de Windows.

    Sin esto, Windows la agrupa bajo el icono genérico de Python.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lexa.App.1")
    except Exception:
        pass


def apply_pending_update() -> None:
    """Termina una actualizacion descargada en la sesion anterior.

    Va lo primero de todo, antes de que exista ninguna ventana.

    Si reemplaza el binario, este proceso NO puede continuar. PyInstaller lee
    los modulos del PYZ embebido en el propio .exe de forma perezosa, segun
    hacen falta. Tras el intercambio, los desplazamientos calculados para el
    binario viejo apuntan a datos del nuevo y el primer import que llegue
    revienta con «zlib.error: incorrect header check». Por eso se arranca el
    binario nuevo y se sale de inmediato, sin importar nada mas.

    subprocess se importa arriba del modulo por lo mismo: tiene que estar ya
    cargado antes de que el archivo cambie bajo los pies.
    """
    try:
        from core.updater import apply_pending
        if not apply_pending():
            return
    except Exception:
        return

    try:
        subprocess.Popen([sys.executable],
                         cwd=os.path.dirname(sys.executable))
    except Exception:
        pass
    # os._exit y no sys.exit: el cierre ordenado del interprete todavia importa
    # modulos, y este proceso ya no puede leer su propio archivo.
    os._exit(0)


def main() -> int:
    apply_pending_update()     # si actualiza, no vuelve de aqui

    from core.updater import consume_applied_flag
    applied = consume_applied_flag()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName("Lexa")
    app.setApplicationDisplayName("Lexa")
    app.setOrganizationName("Lexa")

    icon_path = resource("icon.png")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    setup_palette(app)
    app.setStyleSheet(GLOBAL_QSS)
    app.setFont(QFont("Segoe UI", 9))

    config = load_config()

    from ui.main_window import MainWindow
    window = MainWindow(config)
    window.show()
    if applied:
        window.announce_update_applied()
    window.maybe_start_tour()
    window.check_for_updates()

    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # En el .exe no hay consola donde ver el traceback: mostrarlo en un diálogo
        # y dejarlo en un log junto a la configuración del usuario.
        import traceback
        detail = traceback.format_exc()
        try:
            from core.paths import config_dir
            with open(os.path.join(config_dir(), "error.log"), "w", encoding="utf-8") as f:
                f.write(detail)
        except Exception:
            pass
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None, "Lexa no pudo iniciarse",
                "Ocurrió un error inesperado al arrancar.\n\n"
                + detail.strip().splitlines()[-1],
            )
        except Exception:
            print(detail, file=sys.stderr)
        sys.exit(1)
