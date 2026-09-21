"""Lexa — transcripción de audio, video, imágenes y PDF. Punto de entrada."""
from __future__ import annotations
import os
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


def apply_pending_update() -> bool:
    """Termina una actualizacion descargada en la sesion anterior.

    Va lo primero de todo, antes de que exista ninguna ventana: reemplaza el
    ejecutable aprovechando que el binario viejo todavia no esta en uso en
    este arranque. Un fallo aqui no impide usar la version instalada.
    """
    try:
        from core.updater import apply_pending
        return apply_pending()
    except Exception:
        return False


def main() -> int:
    applied = apply_pending_update()

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
