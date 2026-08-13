"""Ventana principal: marco nativo de Windows con barra de título oscura."""
from __future__ import annotations
import os
import subprocess
import sys
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QSplitter,
    QVBoxLayout, QWidget,
)

from core.models import (
    AppConfig, FileItem, FileStatus, LogEntry, Segment,
    classify_file, expand_paths,
)
from core.config_store import save_config
from core.worker import ProcessingWorker
from core.exporter import export_results, NothingToExportError
from core.paths import resource
from ui import theme as T
from ui.title_bar import TitleBar
from ui.left_panel import LeftPanel
from ui.center_panel import CenterPanel
from ui.right_panel import RightPanel
from ui.footer import Footer
from ui.tour import TourOverlay, build_steps


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config
        self._files: List[FileItem] = []
        self._next_id = 1
        self._worker: Optional[ProcessingWorker] = None
        self._processing = False
        self._tour: Optional[TourOverlay] = None
        self._last_export: List[str] = []

        self.setWindowTitle("Lexa")
        # Mínimo holgado: por debajo de esto los paneles dejan de ser legibles,
        # pero cada uno tiene scroll propio así que nunca se superponen.
        self.setMinimumSize(940, 620)
        self.resize(1320, 860)

        icon_path = resource("icon.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        root_widget = QWidget()
        root_widget.setObjectName("RootWidget")
        root_widget.setStyleSheet(f"QWidget#RootWidget {{ background: {T.BG}; }}")
        self.setCentralWidget(root_widget)

        root = QVBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title_bar = TitleBar()
        self._title_bar.help_requested.connect(self.start_tour)
        root.addWidget(self._title_bar)

        # ── Tres columnas redimensionables ───────────────────────────
        self._left = LeftPanel()
        self._center = CenterPanel(self._config)
        self._right = RightPanel(self._config)

        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._h_splitter.setChildrenCollapsible(False)
        self._h_splitter.setHandleWidth(7)
        self._h_splitter.addWidget(self._left)
        self._h_splitter.addWidget(self._center)
        self._h_splitter.addWidget(self._right)
        self._h_splitter.setStretchFactor(0, 0)
        self._h_splitter.setStretchFactor(1, 1)
        self._h_splitter.setStretchFactor(2, 0)
        self._h_splitter.setSizes([292, 700, 320])

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_lay = QHBoxLayout(content)
        content_lay.setContentsMargins(10, 10, 10, 4)
        content_lay.setSpacing(0)
        content_lay.addWidget(self._h_splitter)

        # ── Contenido / pie, también redimensionable ─────────────────
        self._footer = Footer()

        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._v_splitter.setChildrenCollapsible(False)
        self._v_splitter.setHandleWidth(7)
        self._v_splitter.addWidget(content)
        self._v_splitter.addWidget(self._footer)
        self._v_splitter.setStretchFactor(0, 1)
        self._v_splitter.setStretchFactor(1, 0)
        self._v_splitter.setSizes([640, 150])
        root.addWidget(self._v_splitter, stretch=1)

        self._connect()
        self._restore_layout()

    def _connect(self) -> None:
        self._left.files_added.connect(self._on_files_added)
        self._left.file_selected.connect(self._center.focus_file)
        self._left.file_removed.connect(self._on_file_removed)
        self._left.file_retried.connect(self._on_file_retried)
        self._left.clear_all.connect(self._on_clear_all)

        self._center.copied.connect(lambda msg: self._log("info", msg))

        self._right.config_changed.connect(self._on_config_changed)
        self._right.start_requested.connect(self._on_start_stop)
        self._right.export_requested.connect(lambda: self._export(manual=True))
        self._right.clear_requested.connect(self._on_clear_all)
        self._right.open_folder_requested.connect(self._open_output_folder)

    # ── Barra de título oscura (Windows 10 1809+ / Windows 11) ───────────────
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if sys.platform == "win32":
            self._apply_dark_titlebar()

    def _apply_dark_titlebar(self) -> None:
        try:
            import ctypes
            hwnd = int(self.winId())
            for attribute in (20, 19):   # Windows 11, luego Windows 10
                try:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(ctypes.c_int(1)),
                        ctypes.sizeof(ctypes.c_int),
                    )
                except Exception:
                    pass
        except Exception:
            pass   # cosmético: la app funciona igual con barra clara

    # ── Tour ─────────────────────────────────────────────────────────────────
    def maybe_start_tour(self) -> None:
        if not self._config.tour_completed:
            QTimer.singleShot(350, self.start_tour)

    def start_tour(self) -> None:
        if self._tour is not None and self._tour.isVisible():
            return
        self._tour = TourOverlay(build_steps(self), self.centralWidget())
        self._tour.finished.connect(self._on_tour_finished)
        self._tour.start()

    def _on_tour_finished(self) -> None:
        self._config.tour_completed = True
        save_config(self._config)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._tour is not None and self._tour.isVisible():
            self._tour.setGeometry(self.centralWidget().rect())

    # ── Archivos ─────────────────────────────────────────────────────────────
    def _on_files_added(self, paths: List[str]) -> None:
        known = {f.path for f in self._files}
        added = 0
        skipped = 0

        for path in expand_paths(paths):
            if path in known:
                continue
            kind = classify_file(path)
            if kind is None:
                skipped += 1
                continue
            item = FileItem(id=self._next_id, path=path, kind=kind)
            self._next_id += 1
            self._files.append(item)
            self._left.add_file(item)
            known.add(path)
            added += 1

        if skipped:
            self._log("warn", f"{skipped} archivo(s) de tipo no soportado, omitidos")
        if added:
            self._sync_views()
            self._log("info", f"{added} archivo(s) añadido(s) a la cola")

    def _on_file_removed(self, file_id: int) -> None:
        self._files = [f for f in self._files if f.id != file_id]
        self._left.remove_file(file_id)
        self._sync_views()

    def _on_file_retried(self, file_id: int) -> None:
        item = self._find(file_id)
        if item is None or self._processing:
            return
        item.status = FileStatus.PENDING
        item.progress = 0.0
        item.error = None
        item.stage = ""
        self._left.update_file(item)
        self._sync_views()
        self._start_processing(only=[item])

    def _on_clear_all(self) -> None:
        if self._processing:
            self._stop_worker()
        self._files.clear()
        self._left.clear_files()
        self._footer.clear_logs()
        self._last_export = []
        self._sync_views()
        self._title_bar.set_status("Listo")

    def _sync_views(self) -> None:
        self._center.update_items(self._files)
        self._footer.update_files(self._files)
        count = len(self._files)
        self._title_bar.set_batch_name(
            f"{count} archivo(s)" if count else "Sin archivos"
        )

    # ── Configuración ────────────────────────────────────────────────────────
    def _on_config_changed(self, config: AppConfig) -> None:
        self._config = config
        save_config(config)
        # La vista previa depende de timestamps y hablantes.
        self._center.refresh()

    # ── Procesamiento ────────────────────────────────────────────────────────
    def _on_start_stop(self) -> None:
        if self._processing:
            self._stop_worker()
        else:
            self._start_processing()

    def _start_processing(self, only: Optional[List[FileItem]] = None) -> None:
        pending = only if only is not None else [
            f for f in self._files if f.status != FileStatus.DONE
        ]
        if not pending:
            QMessageBox.information(
                self, "Nada que procesar",
                "Todos los archivos de la cola ya están procesados.\n\n"
                "Añade archivos nuevos o vacía la cola.",
            )
            return

        if not self._ensure_models():
            return

        self._processing = True
        self._right.set_processing(True)
        self._title_bar.set_status("Procesando…", T.WARN)
        self._footer.mark_started()

        for item in pending:
            item.status = FileStatus.PENDING
            item.progress = 0.0
            item.error = None
            self._left.update_file(item)

        self._worker = ProcessingWorker(pending, self._config, self)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_stage.connect(self._on_file_stage)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_error.connect(self._on_file_error)
        self._worker.log_entry.connect(self._footer.add_log)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _ensure_models(self) -> bool:
        """Descarga los modelos que falten. False si el usuario canceló."""
        from ui.setup_dialog import SetupDialog, required_specs
        from PyQt6.QtWidgets import QDialog

        missing = required_specs(self._config)
        if not missing:
            return True

        dialog = SetupDialog(missing, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._log("warn", "Descarga de modelos cancelada")
            return False
        self._log("ok", "Modelos listos")
        return True

    def _stop_worker(self) -> None:
        if self._worker is not None:
            self._worker.abort()
            self._worker.wait(8000)
        self._processing = False
        self._right.set_processing(False)
        self._footer.mark_stopped()
        self._title_bar.set_status("Detenido", T.MUTED)

    def _on_file_started(self, file_id: int) -> None:
        item = self._find(file_id)
        if item is None:
            return
        item.status = FileStatus.PROCESSING
        item.progress = 0.0
        self._left.update_file(item)
        self._sync_views()

    def _on_file_stage(self, file_id: int, stage: str) -> None:
        item = self._find(file_id)
        if item is not None:
            item.stage = stage
            self._left.update_file(item)

    def _on_file_progress(self, file_id: int, progress: float) -> None:
        item = self._find(file_id)
        if item is None:
            return
        item.progress = progress
        self._left.update_file(item)
        self._footer.update_files(self._files)

    def _on_file_done(self, file_id: int, segments: object,
                      text: str, duration: float) -> None:
        item = self._find(file_id)
        if item is None:
            return
        item.status = FileStatus.DONE
        item.progress = 1.0
        item.stage = ""
        item.segments = list(segments)  # type: ignore[arg-type]
        item.result = text
        item.duration = duration
        self._left.update_file(item)
        self._sync_views()

    def _on_file_error(self, file_id: int, error: str) -> None:
        item = self._find(file_id)
        if item is None:
            return
        item.status = FileStatus.ERROR
        item.progress = 0.0
        item.stage = ""
        item.error = error
        self._left.update_file(item)
        self._sync_views()

    def _on_all_done(self, aborted: bool) -> None:
        self._processing = False
        self._right.set_processing(False)
        self._footer.mark_stopped()

        done = sum(1 for f in self._files if f.status == FileStatus.DONE)
        errors = sum(1 for f in self._files if f.status == FileStatus.ERROR)

        if aborted:
            self._title_bar.set_status("Detenido", T.MUTED)
            self._log("warn", "Procesamiento detenido por el usuario")
            return

        if done and self._config.auto_export:
            self._export(manual=False)

        if errors:
            self._title_bar.set_status(f"{errors} error(es)", T.WARN)
        elif done:
            self._title_bar.set_status(f"Listo · {done} archivo(s)", T.ACCENT)
        else:
            self._title_bar.set_status("Sin resultados", T.MUTED)

    # ── Exportación ──────────────────────────────────────────────────────────
    def _export(self, manual: bool) -> None:
        try:
            paths = export_results(self._files, self._config)
        except NothingToExportError as exc:
            if manual:
                QMessageBox.information(self, "Nada que exportar", str(exc))
            else:
                self._log("warn", str(exc).splitlines()[0])
            return
        except Exception as exc:
            if manual:
                QMessageBox.critical(self, "Error al exportar", str(exc))
            self._log("err", f"Error al exportar: {exc}")
            return

        self._last_export = paths
        self._log("ok", f"Guardado: {len(paths)} archivo(s) en {self._config.save_location}")

        if manual:
            box = QMessageBox(self)
            box.setWindowTitle("Exportación completada")
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(f"Se guardaron {len(paths)} archivo(s) en:\n{self._config.save_location}")
            box.setDetailedText("\n".join(paths))
            open_btn = box.addButton("Abrir carpeta", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_output_folder()

    def _open_output_folder(self) -> None:
        folder = self._config.save_location
        try:
            os.makedirs(folder, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)          # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            QMessageBox.warning(
                self, "No se pudo abrir la carpeta",
                f"{folder}\n\nDetalle: {exc}",
            )

    # ── Utilidades ───────────────────────────────────────────────────────────
    def _find(self, file_id: int) -> Optional[FileItem]:
        for item in self._files:
            if item.id == file_id:
                return item
        return None

    def _log(self, level: str, message: str) -> None:
        self._footer.add_log(LogEntry(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message,
        ))

    # ── Persistencia del layout ──────────────────────────────────────────────
    def _restore_layout(self) -> None:
        if self._config.h_splitter:
            self._h_splitter.setSizes([int(v) for v in self._config.h_splitter])
        if self._config.v_splitter:
            self._v_splitter.setSizes([int(v) for v in self._config.v_splitter])
        if self._config.window_geometry:
            try:
                from PyQt6.QtCore import QByteArray
                self.restoreGeometry(
                    QByteArray.fromBase64(self._config.window_geometry.encode("ascii"))
                )
            except Exception:
                pass   # una geometría corrupta no debe impedir abrir la app

    def _save_layout(self) -> None:
        self._config.h_splitter = self._h_splitter.sizes()
        self._config.v_splitter = self._v_splitter.sizes()
        try:
            self._config.window_geometry = bytes(
                self.saveGeometry().toBase64()
            ).decode("ascii")
        except Exception:
            self._config.window_geometry = ""
        save_config(self._config)

    def closeEvent(self, event) -> None:
        if self._processing:
            answer = QMessageBox.question(
                self, "Procesamiento en curso",
                "Hay archivos procesándose. ¿Seguro que quieres salir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._stop_worker()
        self._save_layout()
        super().closeEvent(event)
