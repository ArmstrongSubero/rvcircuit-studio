# Copyright 2026 Armstrong Subero
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .common import *
from .filesystem import CustomFileSystemModel, WorkspaceFilterProxy
from .toolbar import ToolbarManager
from .snippets import SnippetManager
from .editor_ui import EditorWidget
from .findreplace import FindReplaceWidget
from .circuitpython_mode import BoardWatcher, BoardStatus, safe_write, save_to_board, detect_circuitpy, read_boot_out, check_cp_version_async
from .repl_widget import REPLWidget
from .settings import SettingsDialog
from .plotter import SerialPlotter
from .debugger_panel import DebuggerPanel

_CP_STARTER_TEMPLATE = """# code.py - CircuitPython Starter
# RV Circuit Studio

import board
import digitalio
import time

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

while True:
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.5)
"""

def _strip_dirty(title: str) -> str:
    """Drop the trailing " *" dirty marker without eating asterisks that are
    part of the filename. rstrip(" *") removed every trailing star."""
    return title[:-2] if title.endswith(" *") else title


class CircuitStudioEditor(QWidget):
    """
    Main editor widget for RV Circuit Studio.
    Layout:
        ┌────────────────────────────────────────┐
        │  Toolbar                               │
        ├──────────┬─────────────────────────────┤
        │ Explorer │  Editor tabs                │
        │          │                             │
        │ Snippets ├─────────────────────────────┤
        │          │  REPL / Plotter tabs        │
        └──────────┴─────────────────────────────┘
    """

    # Emitted from the auto-install worker thread; Qt queues it onto the UI
    # thread (QTimer.singleShot from a worker thread does NOT fire reliably).
    _autoinstall_done = Signal(object, object)  # installed, skipped
    # Emitted from the CP-version-check worker thread (same threading rule).
    _cp_update_found = Signal(str, str, str)    # board_ver, latest_ver, url

    def __init__(self, window: QMainWindow, project_dir=None):
        super().__init__()
        self.window = window
        self.current_project_directory = project_dir
        self._board_drive = None
        self._repl_port   = None
        self._repl_running = True  # assume code is running when connected
        self._autoinstall_done.connect(self._on_autoinstall_done)
        self._cp_update_found.connect(self._on_cp_update_found)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.toolbar_manager = ToolbarManager(self, self, self.window)
        self.main_layout.addWidget(self.toolbar_manager.get_toolbar())
        self.main_layout.addWidget(self.toolbar_manager.get_accent_line())

        self._build_board_status_bar()

        # Inline debug bar - shown only during debug sessions, matching
        self._debug_bar = self._build_debug_bar()
        self._debug_bar.setVisible(False)
        self.main_layout.addWidget(self._debug_bar)

        self.main_splitter    = QSplitter(Qt.Orientation.Vertical)
        self.central_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.snippets_window_top    = QWidget()
        self.snippets_window_bottom = QWidget()
        self.snippets_splitter      = QSplitter(Qt.Orientation.Vertical)

        self.fileSystemModel = CustomFileSystemModel()
        self.fileSystemModel.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllEntries)

        self.proxyModel = WorkspaceFilterProxy()
        self.proxyModel.setSourceModel(self.fileSystemModel)

        self.fileView = QTreeView(self.snippets_window_top)
        self.fileView.setModel(self.proxyModel)
        self.fileView.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileView.customContextMenuRequested.connect(self.show_context_menu)
        self.fileView.setRootIsDecorated(True)
        _init_root = self.current_project_directory
        if not _init_root or not os.path.isdir(_init_root):
            _init_root = (
                os.path.join(os.path.expanduser("~"), "Documents")
                if os.path.isdir(os.path.join(os.path.expanduser("~"), "Documents"))
                else os.path.expanduser("~")
            )
        _src = self.fileSystemModel.setRootPath(_init_root)
        self.fileView.setRootIndex(self.proxyModel.mapFromSource(_src))

        for i in range(1, self.fileSystemModel.columnCount()):
            self.fileView.hideColumn(i)

        self.fileView.header().setStyleSheet(
            f"QHeaderView::section {{ background-color: {CS_BG_TOOLBAR}; color: {CS_TEXT}; }}"
        )

        top_layout = QVBoxLayout(self.snippets_window_top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.fileView)

        self.snippets_splitter.addWidget(self.snippets_window_top)
        self.snippets_splitter.addWidget(self.snippets_window_bottom)
        self.central_splitter.addWidget(self.snippets_splitter)
        self.fileView.doubleClicked.connect(self.open_file_from_tree)

        self.editor_tab_widget = QTabWidget(self)
        self.editor_tab_widget.setTabsClosable(True)
        self.editor_tab_widget.tabCloseRequested.connect(self.close_tab)
        self.central_splitter.addWidget(self.editor_tab_widget)

        self._debug_side_panel = QWidget()
        self._debug_side_panel.setMinimumWidth(280)
        self._debug_side_panel.setStyleSheet(f"background: {CS_BG_DEEP};")
        self._debug_side_panel.setVisible(False)
        self.central_splitter.addWidget(self._debug_side_panel)

        self.central_splitter.setSizes([220, 900, 0])

        self.snippet_manager = SnippetManager(self.snippets_window_bottom, self.editor_tab_widget)

        self.bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        tab_bar = QWidget()
        tab_bar.setFixedHeight(32)
        tab_bar.setStyleSheet(f"background: #1e1e2e; border-top: 1px solid #3a3a5c;")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(4, 0, 4, 0)
        tab_bar_layout.setSpacing(2)

        _btn_style_active   = f"QPushButton {{ background: {CS_ACCENT}; color: #fff; border: none; padding: 4px 14px; border-radius: 3px; font-weight: bold; }}"
        _btn_style_inactive = f"QPushButton {{ background: transparent; color: #aaa; border: none; padding: 4px 14px; border-radius: 3px; }} QPushButton:hover {{ background: #2a2a4a; color: #fff; }}"

        self.repl_tab_btn    = QPushButton("REPL")
        self.plotter_tab_btn = QPushButton("Plotter")
        self.repl_tab_btn.setStyleSheet(_btn_style_active)
        self.plotter_tab_btn.setStyleSheet(_btn_style_inactive)
        self.repl_tab_btn.setCheckable(True)
        self.repl_tab_btn.setChecked(False)

        self.camera_tab_btn = QPushButton("Camera")
        self.camera_tab_btn.setStyleSheet(_btn_style_inactive)

        tab_bar_layout.addWidget(self.repl_tab_btn)
        tab_bar_layout.addWidget(self.plotter_tab_btn)
        tab_bar_layout.addWidget(self.camera_tab_btn)
        tab_bar_layout.addStretch()

        _btn_style_clear = (
            f"QPushButton {{ background: transparent; color: {CS_TEXT_MUTED}; "
            f"border: none; padding: 4px 10px; border-radius: 3px; font-size: 9pt; }}"
            f"QPushButton:hover {{ background: {CS_DANGER}; color: #fff; }}"
        )
        self.repl_clear_btn = QPushButton("✕ Clear")
        self.repl_clear_btn.setStyleSheet(_btn_style_clear)
        self.repl_clear_btn.setToolTip("Clear REPL output")
        self.repl_clear_btn.clicked.connect(self._on_repl_clear)
        tab_bar_layout.addWidget(self.repl_clear_btn)

        self.bottom_stack = QStackedWidget()
        self.repl_panel   = REPLWidget()
        self.plotter_panel = self._build_plotter_panel()
        self.bottom_stack.addWidget(self.repl_panel)      # index 0
        self.bottom_stack.addWidget(self.plotter_panel)   # index 1
        from .camera_panel import CameraPanel
        self.camera_panel = CameraPanel()
        self.bottom_stack.addWidget(self.camera_panel)    # index 2

        self.debugger_panel = DebuggerPanel(repl_widget=None, parent=self)
        self.debugger_panel.set_main_editor(self)
        self.debugger_panel.setVisible(False)

        _dsp_layout = QVBoxLayout(self._debug_side_panel)
        _dsp_layout.setContentsMargins(0, 0, 0, 0)
        _dsp_layout.setSpacing(0)
        _dsp_header = QLabel("  Advanced Debugger")
        _dsp_header.setFixedHeight(28)
        _dsp_header.setStyleSheet(
            f"background: {CS_BG_TOOLBAR}; color: {CS_ACCENT}; "
            f"font-weight: bold; font-size: 11px; border-bottom: 1px solid {CS_ACCENT_SOFT};"
        )
        _dsp_layout.addWidget(_dsp_header)
        self.debugger_panel._config_page.setParent(self._debug_side_panel)
        self.debugger_panel._config_page.setVisible(True)
        _dsp_layout.addWidget(self.debugger_panel._config_page)
        _watch_lbl = QLabel("  Watch Values:")
        _watch_lbl.setStyleSheet(f"color: {CS_ACCENT}; font-weight: bold; font-size: 11px; padding: 4px 0;")
        _dsp_layout.addWidget(_watch_lbl)
        self.debugger_panel._watch_display.setParent(self._debug_side_panel)
        self.debugger_panel._watch_display.setVisible(True)
        _dsp_layout.addWidget(self.debugger_panel._watch_display)

        bottom_layout.addWidget(tab_bar)
        bottom_layout.addWidget(self.bottom_stack)

        self.bottom_panel.setMinimumHeight(32)
        self.bottom_panel.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Preferred)

        self.repl_panel.data_received.connect(self._on_serial_data)
        self.repl_panel.data_received.connect(self.debugger_panel.feed_serial)
        self.debugger_panel.sig_session_ended.connect(self._teardown_debug_ui)
        self.debugger_panel.sig_status.connect(self._show_debug_status)

        self.repl_tab_btn.clicked.connect(self._on_repl_tab_clicked)
        self.plotter_tab_btn.clicked.connect(lambda: self._switch_bottom_tab(1))
        self.camera_tab_btn.clicked.connect(self._on_camera_tab_clicked)

        self.bottom_panel.setVisible(False)

        self.main_splitter.addWidget(self.central_splitter)
        self.main_splitter.addWidget(self.bottom_panel)
        self.main_splitter.setSizes([600, 250])
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)

        self.main_layout.addWidget(self.main_splitter, 1)

        self.board_watcher = BoardWatcher(self)
        self.board_watcher.board_connected.connect(self._on_board_connected)
        self.board_watcher.board_disconnected.connect(self._on_board_disconnected)
        self.board_watcher.board_status_changed.connect(self._on_board_status_changed)
        self.board_watcher.start()

        # Global stop shortcut. Ctrl+C can't be used app-wide (it's Copy), so
        # Ctrl+. sends Ctrl+C (0x03) to the board from any focused pane.
        self._stop_shortcut = QShortcut(QKeySequence("Ctrl+."), self.window)
        self._stop_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._stop_shortcut.activated.connect(self._global_interrupt)

        self.toolbar_manager.initial_port_scan()
        if project_dir:
            self._open_project(project_dir)

        # Apply font sizes from config on startup.
        config = self._load_config()
        editor_fs = int(config.get("editor", {}).get("font_size", 10))
        self.apply_font_size_to_all_tabs(editor_fs)
        self.apply_editor_settings()
        ui_fs = int(config.get("ui", {}).get("font_size", 10))
        self.apply_ui_font_size(ui_fs)

    def _build_board_status_bar(self):
        self.board_status_widget = QWidget()
        self.board_status_widget.setFixedHeight(24)
        self.board_status_widget.setStyleSheet(
            f"background-color: {CS_BG_TOOLBAR}; border-bottom: 1px solid {CS_ACCENT_SOFT};"
        )
        row = QHBoxLayout(self.board_status_widget)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(8)

        self.board_dot = QLabel("●")
        self.board_dot.setStyleSheet(f"color: {CS_DANGER}; font-size: 10px;")
        row.addWidget(self.board_dot)

        self.board_label = QLabel("No board connected")
        self.board_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        row.addWidget(self.board_label)

        row.addStretch()

        self.drive_label = QLabel("")
        self.drive_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        row.addWidget(self.drive_label)

        self.port_label = QLabel("")
        self.port_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")
        row.addWidget(self.port_label)

        self.main_layout.addWidget(self.board_status_widget)

    def _set_board_status_ui(self, status: str, drive: str = "", port: str = ""):
        if status == BoardStatus.CONNECTED:
            self.board_dot.setStyleSheet(f"color: {CS_SUCCESS}; font-size: 10px;")
            self.board_label.setText("Board connected")
            self.board_label.setStyleSheet(f"color: {CS_SUCCESS}; font-size: 9pt;")
        elif status == BoardStatus.PARTIAL:
            self.board_dot.setStyleSheet(f"color: {CS_WARNING}; font-size: 10px;")
            self.board_label.setText("Drive found (no REPL)")
            self.board_label.setStyleSheet(f"color: {CS_WARNING}; font-size: 9pt;")
        else:
            self.board_dot.setStyleSheet(f"color: {CS_DANGER}; font-size: 10px;")
            self.board_label.setText("No board connected")
            self.board_label.setStyleSheet(f"color: {CS_TEXT_MUTED}; font-size: 9pt;")

        self.drive_label.setText(f"Drive: {drive}" if drive else "")
        self.port_label.setText(f"  Port: {port}" if port else "")

    def _on_board_connected(self, drive: str, port: str):
        self._board_drive = drive
        self._repl_port   = port

        # Clean up any stale debug instrumentation files left from a
        # previous session. If these are on the board when it reloads,
        # CircuitPython crashes trying to run them without the IDE.
        try:
            from .cp_debugger import cleanup_debug_files
            cleanup_debug_files(drive)
        except Exception:
            pass

        boot = read_boot_out(drive)
        self._cp_version  = boot.get("version", "9")
        # read_boot_out returns "" when nothing parsed. Fall back here rather
        # than inside it, so callers can tell "unknown" from a real 9.x board.
        self._cp_major    = boot.get("major") or "9"
        self._board_name  = boot.get("board", "")

        if boot.get("version"):
            status_msg = (
                f"Board connected: {self._board_name}  |  "
                f"CircuitPython {self._cp_version}  |  "
                f"Drive: {drive}  Port: {port}"
            )
        else:
            status_msg = f"Board connected - Drive: {drive}  Port: {port}"
        self._set_board_status_ui(BoardStatus.CONNECTED, drive, port)
        self.window.statusBar().showMessage(status_msg, 8000)

        if boot.get("version") and boot.get("board_id"):
            # The callback fires on a worker thread; emit a signal so Qt
            # marshals the dialog onto the UI thread (a QTimer from the worker
            # thread would not fire reliably).
            check_cp_version_async(
                boot["version"], boot.get("board_id", ""),
                lambda bv, lv, url: self._cp_update_found.emit(bv, lv, url)
            )

        self._pre_board_project_dir = self.current_project_directory
        source_idx = self.fileSystemModel.setRootPath(drive)
        proxy_idx  = self.proxyModel.mapFromSource(source_idx)
        self.fileView.setRootIndex(proxy_idx)

        config = self._load_config()
        if config.get("board", {}).get("auto_connect", True) and port:
            baud = int(self.toolbar_manager.baud_combo.currentText() or "115200")
            self.repl_panel.connect(port, baud)
            self._update_repl_btn(connected=True)
            self.bottom_panel.setVisible(True)
            self._switch_bottom_tab(0)

            # Soft-reboot to start code.py on connect.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: self.repl_panel._write_bytes(b'\x04'))
            self._repl_running = True
            self._set_run_btn_state(running=True)

            idx = self.toolbar_manager.port_combo.findText(port)
            if idx < 0:
                self.toolbar_manager.port_combo.addItem(port)
                idx = self.toolbar_manager.port_combo.findText(port)
            self.toolbar_manager.port_combo.setCurrentIndex(idx)

        self.debugger_panel.set_drive(drive)
        self.debugger_panel.set_repl(self.repl_panel)

    def _on_cp_update_found(self, board_ver, latest_ver, url):
        """Runs on the UI thread (via signal) when a newer CircuitPython is
        available, so the dialog is created safely on the GUI thread."""
        reply = QMessageBox.question(
            self.window,
            "CircuitPython Update Available",
            f"Your board is running CircuitPython {board_ver}.\n"
            f"The latest stable release is {latest_ver}.\n\n"
            f"Would you like to open the download page for\n"
            f"{getattr(self, '_board_name', '') or 'your board'}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))

    def _on_board_disconnected(self):
        self._board_drive = None
        self._repl_port   = None
        self._set_board_status_ui(BoardStatus.DISCONNECTED)
        if self.repl_panel.is_connected:
            self.repl_panel.disconnect()
        self._update_repl_btn(connected=False)
        self._repl_running = False
        self._set_run_btn_state(running=False)
        self.debugger_panel.set_drive(None)
        restore_dir = getattr(self, '_pre_board_project_dir', None)
        if restore_dir and os.path.isdir(restore_dir):
            self._open_project(restore_dir)
        else:
            fallback = (
                os.path.join(os.path.expanduser("~"), "Documents")
                if os.path.isdir(os.path.join(os.path.expanduser("~"), "Documents"))
                else os.path.expanduser("~")
            )
            source_idx = self.fileSystemModel.setRootPath(fallback)
            proxy_idx  = self.proxyModel.mapFromSource(source_idx)
            self.fileView.setRootIndex(proxy_idx)
            self.current_project_directory = fallback

    def _on_board_status_changed(self, status: str):
        drive = self.board_watcher.drive_path or ""
        port  = self.board_watcher.repl_port  or ""
        self._set_board_status_ui(status, drive, port)

    def _global_interrupt(self):
        """Stop the running program from anywhere (Ctrl+.). Sends Ctrl+C to the
        board and makes the REPL visible so the user sees it halt."""
        if getattr(self.repl_panel, "is_connected", False):
            self.repl_panel.send_interrupt()
            self._repl_running = False
            self._set_run_btn_state(running=False)
            self.bottom_panel.setVisible(True)
            self._switch_bottom_tab(0)
            self.repl_panel.setFocus()
            self.window.statusBar().showMessage("■ Sent Ctrl+C - stopped", 3000)
        else:
            self.window.statusBar().showMessage("No board connected to stop.", 3000)

    def run_on_board(self):
        """Run button toggle: if running → stop (Ctrl+C), if stopped → save and run."""
        if self._repl_running:
            if self.repl_panel.is_connected:
                self.repl_panel._write_bytes(b'\x03')
            self._repl_running = False
            self._set_run_btn_state(running=False)
            self.window.statusBar().showMessage("■ Stopped", 3000)
        else:
            drive = self._board_drive or detect_circuitpy()
            if not drive:
                QMessageBox.warning(self.window, "No Board",
                                    "No CIRCUITPY drive detected.\n\n"
                                    "Connect a CircuitPython board and try again.")
                return
            code = self._get_current_editor_text()
            if code is None:
                return
            config   = self._load_config()
            filename = config.get("board", {}).get("filename", "code.py")

            # The current tab's text is what gets written to the entry point.
            # Running while a helper module has focus would silently overwrite
            # code.py with that module, so confirm when the names disagree.
            idx = self.editor_tab_widget.currentIndex()
            widget = self.editor_tab_widget.widget(idx) if idx >= 0 else None
            cur_path = getattr(widget, '_file_path', None)
            cur_name = os.path.basename(cur_path) if cur_path else None
            if cur_name and cur_name != filename:
                reply = QMessageBox.question(
                    self.window, "Overwrite Board Entry Point?",
                    f"The current tab is {cur_name}, but Run writes to "
                    f"{filename} on the board.\n\n"
                    f"This will replace {filename} with the contents of "
                    f"{cur_name}.\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            ok = save_to_board(code, drive, filename)
            if ok:
                # "save locally as well as on the board so code isn't lost if
                # the board breaks or corrupts").
                try:
                    proj = self.current_project_directory
                    if proj:
                        backup_path = os.path.join(proj, filename)
                        from .cp_debugger import _safe_write
                        _safe_write(backup_path, code)
                except Exception:
                    pass
                self._repl_running = True
                self._set_run_btn_state(running=True)
                self.window.statusBar().showMessage(
                    f"  Running - saved to {drive}{filename}", 3000)
                if self.repl_panel.is_connected:
                    self.repl_panel.send_soft_reboot()
            else:
                QMessageBox.critical(self.window, "Save Failed",
                                     f"Could not write to {drive}.\n\n"
                                     "Possible causes:\n"
                                     "- Board filesystem is read-only (check boot.py\n"
                                     "  for storage.remount() calls)\n"
                                     "- Board is in safe mode\n\n"
                                     "Try: double-tap reset, or remove boot.py.")

    def format_code(self):
        """Format current file with black."""
        code = self._get_current_editor_text()
        if code is None:
            return
        try:
            import black
            mode = black.Mode(line_length=79)
            formatted = black.format_str(code, mode=mode)
            idx = self.editor_tab_widget.currentIndex()
            widget = self.editor_tab_widget.widget(idx)
            if hasattr(widget, 'set_text'):
                widget.set_text(formatted)
            self.window.statusBar().showMessage("Code formatted.", 2000)
        except ImportError:
            QMessageBox.warning(self.window, "Black not installed",
                                "Run: pip install black")
        except Exception as e:
            self.window.statusBar().showMessage(f"Format error: {e}", 4000)

    def stop_board(self):
        """Legacy stop - now handled by run_on_board toggle."""
        self.run_on_board()

    def _set_run_btn_state(self, running: bool):
        """Update run button appearance: purple bg when at REPL (stopped), normal when running."""
        btn = self.toolbar_manager.run_action
        w = self.toolbar_manager.toolbar.widgetForAction(btn)
        if running:
            btn.setText("  Stop")
            btn.setToolTip("Stop running code (Ctrl+C)")
            if w:
                w.setStyleSheet("")
        else:
            btn.setText("  Run")
            btn.setToolTip("Save and run on board")
            if w:
                w.setStyleSheet("background: #6c3fc4; border-radius: 4px; padding: 2px 4px;")

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #

    def _build_debug_bar(self):
        """Inline debug controls, shown during a debug session."""
        _IDE_ROOT = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

        def _dbg_icon(name):
            for ext in (".svg", ".png"):
                p = os.path.join(_IDE_ROOT, "icons", name.replace(".png", ext))
                if os.path.exists(p):
                    return QIcon(p)
            return QIcon()

        bar = QWidget(self)
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background: {CS_BG_TOOLBAR}; border-bottom: 1px solid {CS_ACCENT_SOFT};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(5)

        status = QLabel("Debugging")
        status.setStyleSheet(f"color: {CS_ACCENT}; font-weight: bold; padding-right: 8px;")
        layout.addWidget(status)
        self._dbg_status_label = status

        _btn_css = (
            f"QPushButton {{ background: {CS_SURFACE}; "
            f"border: 1px solid {CS_ACCENT_SOFT}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {CS_ACCENT_SOFT}; }}"
        )

        controls = [
            ("debug_continue.png", "Run (visual line tracking)", self._cp_dbg_run),
            ("debug_step_over.png", "Step to next line",         self._cp_dbg_step),
            ("return.png",          "Restart from the top",      self._cp_dbg_restart),
            ("debug_stop.png",      "Stop debugging",            self._cp_dbg_stop),
        ]
        for icon_name, tip, handler in controls:
            btn = QPushButton(bar)
            btn.setIcon(_dbg_icon(icon_name))
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(tip)
            btn.setFixedSize(32, 28)
            btn.setStyleSheet(_btn_css)
            btn.clicked.connect(handler)
            layout.addWidget(btn)

        # File:line indicator
        self._dbg_line_label = QLabel("")
        self._dbg_line_label.setStyleSheet(
            f"color: {CS_TEXT_MUTED}; font-size: 10px; padding: 0 8px;"
        )
        layout.addWidget(self._dbg_line_label)

        # Watch values display
        self._dbg_watches_label = QLabel("")
        self._dbg_watches_label.setStyleSheet(
            f"color: {CS_SUCCESS}; font-size: 10px; padding: 0 4px;"
        )
        layout.addWidget(self._dbg_watches_label)

        layout.addStretch()

        full_btn = QPushButton("Advanced Debugger", bar)
        full_btn.setToolTip("Open the full debugger panel with watches and config")
        full_btn.setFixedHeight(28)
        full_btn.setStyleSheet(
            f"QPushButton {{ color: {CS_TEXT}; background: {CS_SURFACE}; "
            f"border: 1px solid {CS_ACCENT_SOFT}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ background: {CS_ACCENT_SOFT}; color: #FFFFFF; }}"
        )
        full_btn.clicked.connect(self._on_debug_tab_clicked)
        layout.addWidget(full_btn)

        return bar

    def start_cp_debugging(self):
        """Start a CircuitPython debug session. Shows the inline debug bar
        and delegates to the debugger panel for instrumentation."""
        # Kick the debugger panel's start flow (handles drive/REPL checks,
        # instrumentation, and serial start sequence).
        self._debug_bar.setVisible(True)
        self.debugger_panel._on_start_clicked()
        if self.debugger_panel._debugger_running:
            self._debug_bar.setVisible(True)
            self._dbg_status_label.setText("Debugging")
            self._dbg_status_label.setStyleSheet(
                f"color: {CS_ACCENT}; font-weight: bold; padding-right: 8px;"
            )
            self.repl_panel._debug_mode = True

    def _cp_dbg_run(self):
        """Continue with visual line tracking (CW)."""
        if not self._dbg_active():
            return
        self.debugger_panel._on_continue_log()

    def _cp_dbg_step(self):
        """Step one line."""
        if not self._dbg_active():
            return
        self.debugger_panel._on_step()

    def _dbg_active(self) -> bool:
        """True while a session is live and accepting signals. Sending [S] to
        a bare REPL raises NameError on the board, so every control checks
        first. A start handshake in flight is not yet accepting signals."""
        panel = self.debugger_panel
        if panel._pending_start is not None:
            return False
        if panel._debugger_running:
            return True
        self._teardown_debug_ui()
        return False

    def _cp_dbg_restart(self):
        """Restart the debug session from the top."""
        self.debugger_panel._on_restart()
        if self.debugger_panel._debugger_running:
            self._debug_bar.setVisible(True)
            self.repl_panel._debug_mode = True

    def _cp_dbg_stop(self):
        """Stop the debug session and hide the inline bar."""
        self.debugger_panel._on_stop()
        self._teardown_debug_ui()

    def _show_debug_status(self, text: str, color: str):
        """Mirror the debugger's status onto the inline bar, which is the only
        place the user can see it."""
        try:
            self._dbg_status_label.setText(text)
            self._dbg_status_label.setStyleSheet(
                f"color: {color}; font-weight: bold; padding-right: 8px;")
        except Exception:
            pass

    def _teardown_debug_ui(self):
        """Return the UI to its normal state. Shared by the Stop button and
        by the program ending on its own."""
        self._debug_bar.setVisible(False)
        self._clear_all_debug_highlights()
        self.clear_error_highlights()
        self.repl_panel._debug_mode = False
        self.repl_panel._dbg_hold = ""

    def highlight_debug_line(self, filename, line_number):
        """Highlight the executing line in the editor tab."""
        if not filename or not line_number:
            return
        target_base = os.path.basename(filename)

        # Find the open tab whose file matches by basename.
        match_widget = None
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            cf = getattr(w, "current_file", None) or getattr(w, "_file_path", None)
            if cf and os.path.basename(cf) == target_base:
                match_widget = w
                self.editor_tab_widget.setCurrentIndex(i)
                break

        # If not open, try to open it from the board drive.
        if match_widget is None and self._board_drive:
            path = os.path.join(self._board_drive, filename)
            if os.path.isfile(path):
                self._open_file(path)
                match_widget = self.editor_tab_widget.currentWidget()

        if match_widget is None or not hasattr(match_widget, "qpart"):
            return

        qpart = match_widget.qpart
        block = qpart.document().findBlockByNumber(max(0, line_number - 1))
        if not block.isValid():
            return
        cursor = qpart.textCursor()
        cursor.setPosition(block.position())
        qpart.setTextCursor(cursor)
        qpart.ensureCursorVisible()

        # Paint a highlight bar on the stopped line using qutepart's
        # setExtraSelections (takes (absolutePosition, length) tuples).
        # Go through the editor wrapper so this selection lives alongside the
        # word and error highlights instead of replacing them. Writing
        # qpart.setExtraSelections directly meant the next click erased the
        # executing-line bar mid-halt.
        try:
            match_widget.set_debug_line(line_number)
            self._debug_highlight_editor = match_widget
        except Exception:
            pass

    def _clear_all_debug_highlights(self):
        """Remove the debug line highlight from any editor."""
        ed = getattr(self, "_debug_highlight_editor", None)
        if ed is not None:
            try:
                ed.set_debug_line(None)
            except Exception:
                pass
            self._debug_highlight_editor = None

    def update_debug_info(self, filename: str, line_num: int, watches: dict):
        """Update the inline debug bar with current file:line and watch values."""
        if hasattr(self, '_dbg_line_label'):
            self._dbg_line_label.setText(f"{filename}:{line_num}")
        if hasattr(self, '_dbg_watches_label') and watches:
            parts = [f"{k} = {v}" for k, v in watches.items()]
            self._dbg_watches_label.setText("  |  ".join(parts))
        elif hasattr(self, '_dbg_watches_label'):
            self._dbg_watches_label.setText("")

    def _on_repl_tab_clicked(self):
        """REPL tab button: switch to REPL and give it keyboard focus so keys
        (including Ctrl+C) are routed to the board."""
        self._switch_bottom_tab(0)
        self.repl_panel.setFocus()

    def _on_debug_tab_clicked(self):
        """Toggle the advanced debugger side panel (config + watch values)."""
        self.debugger_panel.set_repl(self.repl_panel)
        if self._board_drive:
            self.debugger_panel.set_drive(self._board_drive)
        visible = self._debug_side_panel.isVisible()
        self._debug_side_panel.setVisible(not visible)
        if not visible:
            self.central_splitter.setSizes([220, 600, 350])

    def _on_camera_tab_clicked(self):
        """Camera tab button: show the live camera panel."""
        self.bottom_panel.setVisible(True)
        self._switch_bottom_tab(2)

    def _on_repl_clear(self):
        """Clear the REPL output."""
        self.repl_panel.clear_output()
        self._switch_bottom_tab(0)  # make sure REPL tab is visible

    def _switch_bottom_tab(self, index: int):
        """Switch the bottom stack to a tab index and update button styles."""
        self.bottom_stack.setCurrentIndex(index)
        _active   = f"QPushButton {{ background: {CS_ACCENT}; color: #fff; border: none; padding: 4px 14px; border-radius: 3px; font-weight: bold; }}"
        _inactive = f"QPushButton {{ background: transparent; color: #aaa; border: none; padding: 4px 14px; border-radius: 3px; }} QPushButton:hover {{ background: #2a2a4a; color: #fff; }}"
        self.repl_tab_btn.setStyleSheet(_active   if index == 0 else _inactive)
        self.plotter_tab_btn.setStyleSheet(_active if index == 1 else _inactive)
        self.camera_tab_btn.setStyleSheet(_active if index == 2 else _inactive)

    def _update_repl_btn(self, connected: bool):
        """Update REPL tab button text to reflect connection state."""
        if connected:
            self.repl_tab_btn.setText("■ REPL")
            self.repl_tab_btn.setToolTip("Click to disconnect REPL")
        else:
            self.repl_tab_btn.setText("REPL")
            self.repl_tab_btn.setToolTip("Click to connect REPL")

    def toggle_serial(self):
        """Toolbar REPL button: show panel and connect if not connected, else just show."""
        self.bottom_panel.setVisible(True)
        self._switch_bottom_tab(0)
        port = self.toolbar_manager.port_combo.currentText()
        baud = int(self.toolbar_manager.baud_combo.currentText() or "115200")
        if port and not self.repl_panel.is_connected:
            self.repl_panel.connect(port, baud)

    def toggle_repl(self):
        """Toggle bottom panel visibility."""
        self.bottom_panel.setVisible(not self.bottom_panel.isVisible())

    def toggle_plotter(self):
        """Toggle plotter tab."""
        self._switch_bottom_tab(1)
        self.bottom_panel.setVisible(not self.bottom_panel.isVisible())

    def show_library_manager(self):
        """Open library manager dialog."""
        from .library_manager import LibraryManagerDialog
        drive = self._board_drive or detect_circuitpy()
        cp_version = getattr(self, '_cp_version', '9')
        if hasattr(self, '_board_name') and self._board_name:
            self.window.statusBar().showMessage(
                f"Library Manager - targeting CircuitPython {cp_version} bundle", 4000
            )
        dlg = LibraryManagerDialog(
            drive,
            cp_version=cp_version,
            project_dir=getattr(self, "current_project_directory", None),
            parent=self.window,
        )
        dlg.exec()

    def _build_plotter_panel(self):
        """Real-time pyqtgraph serial plotter."""
        self._serial_plotter = SerialPlotter()
        return self._serial_plotter

    def _on_serial_data(self, text: str):
        """Forward raw serial data to the plotter and parse tracebacks."""
        self._serial_plotter.feed(text)
        self._traceback_buf = getattr(self, '_traceback_buf', '') + text
        self._traceback_buf = self._traceback_buf[-2048:]
        self._parse_traceback(self._traceback_buf)

    def clear_error_highlights(self):
        """Drop the red error line from every tab and forget the traceback."""
        self._traceback_buf = ''
        self._last_traceback = None
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            if hasattr(w, 'clear_error_highlight'):
                try:
                    w.clear_error_highlight()
                except Exception:
                    pass

    def _parse_traceback(self, text: str):
        """Parse CircuitPython traceback and highlight the offending line."""
        import re
        matches = list(re.finditer(
            r'File "([^"]+)", line (\d+)',
            text
        ))
        if not matches:
            return
        last_tb = text.rfind('Traceback (most recent call last)')
        if last_tb == -1:
            return
        matches = [m for m in matches if m.start() > last_tb]
        if not matches:
            return
        # Prefer the deepest frame that belongs to a file the user can see.
        # Frames from the instrumented copies carry line numbers that do not
        # correspond to anything in the original source, and <stdin> is the
        # REPL itself.
        frame = None
        for m in reversed(matches):
            name = os.path.basename(m.group(1))
            if name.startswith('ide_debug_') or name.startswith('<'):
                continue
            if name in ('code.py', 'main.py'):
                frame = (name, int(m.group(2)))
                break
        if frame is None:
            return

        # The rolling buffer keeps the last 2 KB of serial, and this runs on
        # every chunk, so without this the same traceback is re-applied on
        # every byte the board sends and the red line can never be cleared.
        # The signature is the frame alone: anything derived from the buffer
        # text keeps changing as more output arrives.
        if frame == getattr(self, '_last_traceback', None):
            return
        self._last_traceback = frame

        self._highlight_editor_line(*frame)

    def _highlight_editor_line(self, filename: str, line_num: int):
        """Find the open tab matching filename and highlight line_num.
        If the file isn't open yet, open it first."""
        for i in range(self.editor_tab_widget.count()):
            widget = self.editor_tab_widget.widget(i)
            fp = getattr(widget, '_file_path', None) or getattr(widget, 'current_file', None)
            if fp and os.path.basename(fp) == filename:
                if hasattr(widget, 'highlight_error_line'):
                    # A stale or mismatched traceback can name a line past the
                    # end of the file. Painting it would put the marker on an
                    # arbitrary line.
                    # Drop any previous mark first, so a rejected line does
                    # not leave the old one painted.
                    try:
                        widget.clear_error_highlight()
                        if line_num > widget.qpart.document().blockCount():
                            return
                    except Exception:
                        pass
                    self.editor_tab_widget.setCurrentIndex(i)
                    widget.highlight_error_line(line_num)
                return
        if self._board_drive:
            path = os.path.join(self._board_drive, filename)
            if os.path.isfile(path):
                self._open_file(path)
                for i in range(self.editor_tab_widget.count()):
                    widget = self.editor_tab_widget.widget(i)
                    fp = getattr(widget, '_file_path', None) or getattr(widget, 'current_file', None)
                    if fp and os.path.basename(fp) == filename:
                        if hasattr(widget, 'highlight_error_line'):
                            widget.highlight_error_line(line_num)
                        return

    def _get_current_editor_text(self):
        idx = self.editor_tab_widget.currentIndex()
        if idx < 0:
            return None
        widget = self.editor_tab_widget.widget(idx)
        if hasattr(widget, 'qpart'):
            return widget.qpart.toPlainText()
        if hasattr(widget, 'toPlainText'):
            return widget.toPlainText()
        return None

    def _check_missing_libraries(self, silent_if_none=True, saved_path=None):
        """
        Auto-detect: scan the current code for imports that aren't on the board
        and offer to install them in one click, without opening the Library
        Manager. Uses the already-downloaded bundle cache; if the bundle hasn't
        been downloaded yet, this quietly does nothing.
        """
        from . import bundle_logic as bl
        from . import library_manager as lm

        drive = getattr(self, "_board_drive", None)

        # If we know the saved file's path, only proceed when it's actually on
        # the board. Normalise so D:\, D:, d:\ all compare equal on Windows.
        if saved_path and drive:
            try:
                np = os.path.normcase(os.path.abspath(saved_path))
                nd = os.path.normcase(os.path.abspath(drive))
                if not np.startswith(nd):
                    return
            except Exception:
                pass

        if not drive:
            return
        lib_dir = os.path.join(drive, "lib")

        code = self._get_current_editor_text()
        if not code:
            return

        cp_major = getattr(self, "_cp_major", "9") or "9"
        cached = lm.load_cached_bundle(cp_major)
        if not cached:
            return  # bundle not downloaded yet; nothing to check against
        zip_path, index, manifest = cached

        missing = bl.find_missing_libraries(code, lib_dir, index, manifest)
        if not missing:
            if not silent_if_none:
                self.window.statusBar().showMessage(
                    "All imported libraries are present on the board.", 3000
                )
            return

        # Don't nag about the exact same set twice in a row.
        sig = tuple(missing)
        if getattr(self, "_last_missing_sig", None) == sig:
            return
        self._last_missing_sig = sig

        # Expand to include dependencies for an accurate count/preview.
        targets = bl.resolve_dependencies(manifest, missing) if manifest else missing
        deps_only = [t for t in targets if t not in missing]

        names = ", ".join(missing)
        detail = f"Your code imports {len(missing)} librar" \
                 f"{'y' if len(missing) == 1 else 'ies'} not on the board:\n\n  {names}"
        if deps_only:
            detail += "\n\nDependencies that will come along:\n  " + ", ".join(deps_only)
        detail += "\n\nInstall now?"

        reply = QMessageBox.question(
            self.window, "Missing Libraries", detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Installing unzips files and writes them to the USB drive, which can
        # take a noticeable moment for packages or a slow board. Do it on a
        # worker thread so the IDE stays responsive, then hand results back via
        # a queued signal (a QTimer started from a worker thread won't fire).
        self.window.statusBar().showMessage("Installing libraries…", 0)

        def _worker():
            installed, skipped = lm.install_libraries(zip_path, index, targets, lib_dir)
            self._autoinstall_done.emit(installed, skipped)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_autoinstall_done(self, installed, skipped):
        """Runs on the UI thread after a background auto-install finishes."""
        if installed:
            self._last_missing_sig = None  # they're present now; allow future checks
            self.window.statusBar().showMessage(
                f"Installed {len(installed)} librar"
                f"{'y' if len(installed) == 1 else 'ies'} to the board - reloading…", 4000
            )
            # The previous run failed on a missing import; that error is now
            # resolved, so clear the stale red highlight and reboot to re-run.
            try:
                self._traceback_buf = ''
                for i in range(self.editor_tab_widget.count()):
                    w = self.editor_tab_widget.widget(i)
                    if hasattr(w, "clear_error_highlight"):
                        w.clear_error_highlight()
            except Exception:
                pass
            try:
                if getattr(self.repl_panel, "is_connected", False):
                    # Ctrl+D only reloads from the REPL prompt. If code is
                    # running (e.g. a while True loop), interrupt first with
                    # Ctrl+C, then reboot after the board reaches the prompt.
                    self.repl_panel.send_interrupt()
                    QTimer.singleShot(300, self.repl_panel.send_soft_reboot)
            except Exception:
                pass
        if skipped:
            self.window.statusBar().showMessage(
                f"Could not install: {', '.join(skipped)}", 5000
            )

    def _connect_editor_signals(self, editor: "EditorWidget", idx_getter):
        """Wire up modified-flag and dirty-tab-title for an editor."""
        def on_modified():
            if not editor._modified:
                return
            for i in range(self.editor_tab_widget.count()):
                if self.editor_tab_widget.widget(i) is editor:
                    title = self.editor_tab_widget.tabText(i)
                    if not title.endswith(" *"):
                        self.editor_tab_widget.setTabText(i, title + " *")
                    break
        editor.qpart.textChanged.connect(on_modified)

    def add_new_tab(self):
        editor = EditorWidget()
        editor.qpart.setPlainText("# New file\n")
        editor._modified = False  # reset after setPlainText
        try:
            editor.qpart.detectSyntax(language='Python')
        except Exception:
            pass
        idx = self.editor_tab_widget.addTab(editor, "untitled.py")
        self.editor_tab_widget.setCurrentIndex(idx)
        self._connect_editor_signals(editor, lambda: idx)
        self.debugger_panel.install_gutter(editor.qpart, "untitled.py")
        return editor

    def on_save(self) -> bool:
        """Save current tab. Returns True only if the file was actually written.

        close_tab and the app exit handler rely on the return value: a
        cancelled Save As must not let the tab close and lose the work.
        """
        idx = self.editor_tab_widget.currentIndex()
        if idx < 0:
            return False
        widget    = self.editor_tab_widget.widget(idx)
        code      = self._get_current_editor_text()
        if code is None:
            return False

        config    = self._load_config()
        auto_save = config.get("board", {}).get("auto_save", True)
        filename  = config.get("board", {}).get("filename", "code.py")
        drive     = self._board_drive

        current_path = getattr(widget, '_file_path', None)
        if not current_path:
            return self.on_save_as()

        try:
            self.toolbar_manager.show_saving_in_progress()
            safe_write(current_path, code)
            widget._file_path = current_path
            widget.current_file = current_path
            widget._modified = False
            if hasattr(widget, 'clear_error_highlight'):
                widget.clear_error_highlight()
            self._traceback_buf = ''
            self.editor_tab_widget.setTabText(idx, os.path.basename(current_path))
            self.window.statusBar().showMessage(f"Saved: {current_path}", 2000)
            self.toolbar_manager.show_save_status(True)

            if drive and current_path.startswith(drive):
                self.window.statusBar().showMessage(
                    f"✓ Saved to board - reloading…", 3000
                )
            # Auto-detect runs after every save; it decides internally whether
            # this file lives on the board before doing anything.
            QTimer.singleShot(400, lambda p=current_path: self._check_missing_libraries(saved_path=p))
            return True
        except Exception as e:
            self.toolbar_manager.show_save_status(False)
            QMessageBox.critical(self.window, "Save Error", str(e))
            return False

    def on_save_as(self) -> bool:
        """Returns True only if a path was chosen and the write succeeded."""
        idx = self.editor_tab_widget.currentIndex()
        if idx < 0:
            return False
        widget = self.editor_tab_widget.widget(idx)
        code   = self._get_current_editor_text()
        if code is None:
            return False

        start_dir = self._board_drive or (self.current_project_directory or "")
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Save As", start_dir, "Python Files (*.py);;All Files (*)"
        )
        if path:
            try:
                safe_write(path, code)
                widget._file_path = path
                widget.current_file = path
                widget._modified = False
                self.editor_tab_widget.setTabText(idx, os.path.basename(path))
                self.window.statusBar().showMessage(f"Saved: {path}", 2000)

                save_dir = os.path.dirname(path)
                if save_dir != self.current_project_directory:
                    self._open_project(save_dir)
                src_idx   = self.fileSystemModel.index(path)
                proxy_idx = self.proxyModel.mapFromSource(src_idx)
                self.fileView.scrollTo(proxy_idx)
                self.fileView.setCurrentIndex(proxy_idx)
                self._repoint_gutter(widget, path)
                return True
            except Exception as e:
                QMessageBox.critical(self.window, "Save Error", str(e))
                return False
        return False

    def _repoint_gutter(self, widget, new_path: str):
        """Re-register a tab's gutter under its new filename.

        install_gutter captures the filename for the life of the tab, so a
        tab created as untitled.py kept reporting breakpoints under that name
        after Save As and they never matched a file on the drive.
        """
        qpart = getattr(widget, 'qpart', None)
        if qpart is None:
            return
        try:
            marks = set()
            mark_area = qpart._margins[1]
            block = qpart.document().begin()
            while block.isValid():
                if mark_area.getBlockValue(block):
                    marks.add(block.blockNumber())
                block = block.next()
            self.debugger_panel.uninstall_gutter(qpart)
            self.debugger_panel.install_gutter(qpart, new_path)
            for n in marks:
                mark_area.setBlockValue(qpart.document().findBlockByNumber(n), 1)
            mark_area.update()
        except Exception:
            pass

    def close_tab(self, idx):
        widget = self.editor_tab_widget.widget(idx)
        if widget and getattr(widget, '_modified', False):
            name = _strip_dirty(self.editor_tab_widget.tabText(idx))
            reply = QMessageBox.question(
                self.window, "Unsaved Changes",
                f"{name} has unsaved changes.\nSave before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self.editor_tab_widget.setCurrentIndex(idx)
                if not self.on_save():
                    return   # Save As cancelled or write failed; keep the tab
        if widget and hasattr(widget, 'qpart'):
            self.debugger_panel.uninstall_gutter(widget.qpart)
            try:
                widget.qpart.terminate()
            except Exception:
                pass
        self.editor_tab_widget.removeTab(idx)
        # removeTab does not destroy the widget. Without this, every closed tab
        # leaks an EditorWidget whose autosave QTimer keeps firing forever.
        if widget is not None:
            try:
                if hasattr(widget, 'autosave_timer'):
                    widget.autosave_timer.stop()
            except Exception:
                pass
            widget.deleteLater()

    def open_file_from_tree(self, index):
        source_idx = self.proxyModel.mapToSource(index)
        path = self.fileSystemModel.filePath(source_idx)
        if os.path.isfile(path):
            self._open_file(path)

    def _open_untitled_tab(self, content: str, title: str = "Untitled"):
        """Open a new editor tab with the given content (no file on disk).
        Used by snippets to show complete samples in their own tab."""
        editor = EditorWidget()
        editor.qpart.setPlainText(content)
        try:
            editor.qpart.detectSyntax(language='Python')
        except Exception:
            pass
        editor._file_path = None
        editor.current_file = None
        editor._modified = False
        idx = self.editor_tab_widget.addTab(editor, title)
        self.editor_tab_widget.setCurrentIndex(idx)

    def _open_file(self, path: str):
        norm_path = os.path.normcase(os.path.abspath(path))
        basename  = os.path.basename(path)
        for i in range(self.editor_tab_widget.count()):
            w  = self.editor_tab_widget.widget(i)
            fp = getattr(w, '_file_path', None) or getattr(w, 'current_file', None)
            if fp:
                try:
                    if os.path.normcase(os.path.abspath(fp)) == norm_path:
                        # Only re-read from disk when there is nothing to lose.
                        # Reloading unconditionally silently reverted a tab the
                        # user had unsaved edits in.
                        if hasattr(w, 'openFile') and not getattr(w, '_modified', False):
                            w.openFile(path)
                        self.editor_tab_widget.setCurrentIndex(i)
                        return
                except Exception:
                    pass

        editor = EditorWidget()
        editor.openFile(path)
        editor._modified = False  # fresh from disk
        if path.lower().endswith('.py') and not editor.qpart.language():
            try:
                editor.qpart.detectSyntax(language='Python')
            except Exception:
                pass
        editor._file_path   = path
        editor.current_file = path
        idx = self.editor_tab_widget.addTab(editor, basename)
        self.editor_tab_widget.setCurrentIndex(idx)
        self._connect_editor_signals(editor, lambda: idx)
        if path.lower().endswith('.py'):
            self.debugger_panel.install_gutter(editor.qpart, path)

    def show_context_menu(self, pos):
        index = self.fileView.indexAt(pos)
        is_file = index.isValid()
        menu = QMenu(self)

        if is_file:
            source_idx = self.proxyModel.mapToSource(index)
            path = self.fileSystemModel.filePath(source_idx)
            is_dir = os.path.isdir(path)
            parent_dir = path if is_dir else os.path.dirname(path)
        else:
            path = None
            is_dir = False
            parent_dir = self.fileSystemModel.rootPath()

        if is_file and not is_dir:
            open_act = menu.addAction("Open")
            open_act.triggered.connect(lambda: self._open_file(path))
            menu.addSeparator()

        new_file_act = menu.addAction("New File…")
        new_file_act.triggered.connect(lambda: self._tree_new_file(parent_dir))

        new_folder_act = menu.addAction("New Folder…")
        new_folder_act.triggered.connect(lambda: self._tree_new_folder(parent_dir))

        if is_file:
            menu.addSeparator()
            is_project_root = (os.path.normpath(path) == os.path.normpath(self.current_project_directory or ""))
            if not is_project_root:
                rename_act = menu.addAction("Rename…")
                rename_act.triggered.connect(lambda: self._tree_rename(path))

            delete_act = menu.addAction("Delete")
            delete_act.triggered.connect(lambda: self._tree_delete(path))

        if is_file and not is_dir:
            menu.addSeparator()
            copy_act = menu.addAction("Copy to CIRCUITPY/lib/")
            copy_act.triggered.connect(lambda: self._copy_to_lib(path))

        menu.exec(self.fileView.mapToGlobal(pos))

    def _tree_new_file(self, parent_dir: str):
        name, ok = QInputDialog.getText(self.window, "New File", "File name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not os.path.splitext(name)[1]:
            name += ".py"
        path = os.path.join(parent_dir, name)
        if os.path.exists(path):
            QMessageBox.warning(self.window, "New File", f"{name} already exists.")
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            self._open_file(path)
            self.window.statusBar().showMessage(f"Created {name}", 2000)
        except Exception as e:
            QMessageBox.critical(self.window, "New File Error", str(e))

    def _tree_new_folder(self, parent_dir: str):
        name, ok = QInputDialog.getText(self.window, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        path = os.path.join(parent_dir, name.strip())
        if os.path.exists(path):
            QMessageBox.warning(self.window, "New Folder", f"{name} already exists.")
            return
        try:
            os.makedirs(path)
            self.window.statusBar().showMessage(f"Created folder {name}", 2000)
        except Exception as e:
            QMessageBox.critical(self.window, "New Folder Error", str(e))

    def _tree_rename(self, path: str):
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(
            self.window, "Rename", "New name:", text=old_name
        )
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        new_path = os.path.join(os.path.dirname(path), new_name)
        same_item = os.path.normcase(new_path) == os.path.normcase(path)
        if not same_item and os.path.exists(new_path):
            QMessageBox.warning(self.window, "Rename", f"{new_name} already exists.")
            return
        try:
            if same_item and os.name == 'nt':
                import uuid
                tmp = os.path.join(os.path.dirname(path), f"_tmp_{uuid.uuid4().hex}")
                os.rename(path, tmp)
                os.rename(tmp, new_path)
            else:
                os.rename(path, new_path)
            if os.path.normpath(path) == os.path.normpath(self.current_project_directory or ""):
                self._open_project(new_path)
            # Repoint all open tabs whose file lived at or under the old path.
            self._repoint_open_tabs(path, new_path)
            self.window.statusBar().showMessage(f"Renamed {old_name} -> {new_name}", 2000)
        except Exception as e:
            QMessageBox.critical(self.window, "Rename Error", str(e))

    def _tree_delete(self, path: str):
        name = os.path.basename(path)
        kind = "folder" if os.path.isdir(path) else "file"
        reply = QMessageBox.question(
            self.window, "Delete",
            f"Delete {kind}  {name}?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            import shutil
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            # Close any open tabs whose files lived at or under the deleted
            # path so a later save can't silently recreate the deleted file.
            self._close_tabs_under_path(path)
            self.window.statusBar().showMessage(f"Deleted {name}", 2000)
        except Exception as e:
            QMessageBox.critical(self.window, "Delete Error", str(e))

    def _copy_to_lib(self, path: str):
        drive = self._board_drive or detect_circuitpy()
        if not drive:
            QMessageBox.warning(self.window, "No Board", "No CIRCUITPY drive detected.")
            return
        lib_dir = os.path.join(drive, "lib")
        os.makedirs(lib_dir, exist_ok=True)
        dest = os.path.join(lib_dir, os.path.basename(path))
        try:
            import shutil
            shutil.copy2(path, dest)
            self.window.statusBar().showMessage(f"Copied to {dest}", 2000)
        except Exception as e:
            QMessageBox.critical(self.window, "Copy Error", str(e))

    def create_new_project(self):
        workspace = self._load_config().get("workspace_directory", "")
        if not workspace:
            workspace = QFileDialog.getExistingDirectory(self.window, "Select Workspace")
            if not workspace:
                return
        name, ok = QInputDialog.getText(self.window, "New Project", "Project name:")
        if not ok or not name.strip():
            return
        project_dir = os.path.join(workspace, name.strip())
        os.makedirs(project_dir, exist_ok=True)
        starter = os.path.join(project_dir, "code.py")
        if not os.path.exists(starter):
            with open(starter, 'w', encoding='utf-8') as f:
                f.write(_CP_STARTER_TEMPLATE)
        self._open_project(project_dir)
        self._open_file(starter)

    def open_existing_project(self):
        d = QFileDialog.getExistingDirectory(self.window, "Open Project Folder")
        if d:
            self._open_project(d)

    def _open_project(self, path: str):
        """Root the file tree at path, showing it as a named top-level node.

        Strategy:
          - setRootPath(parent)  so QFileSystemModel loads the parent directory
          - setRootIndex(parent) so the tree shows parent's children
          - set_root_filter()    so only `path` is visible at that level
          - expand `path` immediately so its contents are shown
        Drive roots (D:/) are their own parent, so they show without filtering.
        """
        self.current_project_directory = path
        path = os.path.normpath(path)
        parent = os.path.dirname(path)

        is_drive_root = (parent == path)

        if is_drive_root:
            self.proxyModel.clear_root_filter()
            source_idx = self.fileSystemModel.setRootPath(path)
            proxy_idx  = self.proxyModel.mapFromSource(source_idx)
            self.fileView.setRootIndex(proxy_idx)
        else:
            folder_name = os.path.basename(path)
            self.proxyModel.set_root_filter(parent, folder_name)
            source_idx = self.fileSystemModel.setRootPath(parent)
            proxy_idx  = self.proxyModel.mapFromSource(source_idx)
            self.fileView.setRootIndex(proxy_idx)
            QTimer.singleShot(100, lambda: self._expand_project_node(path))

        self.window.setWindowTitle(f"RV Circuit Studio - {os.path.basename(path)}")

    def _expand_project_node(self, path: str):
        proj_src   = self.fileSystemModel.index(path)
        proj_proxy = self.proxyModel.mapFromSource(proj_src)
        if proj_proxy.isValid():
            self.fileView.expand(proj_proxy)
            self.fileView.scrollTo(proj_proxy)

    def _refresh_explorer(self):
        if self.current_project_directory:
            self._open_project(self.current_project_directory)

    def toggle_snippets_top(self):
        self.snippets_window_top.setVisible(not self.snippets_window_top.isVisible())

    def toggle_snippets_bottom(self):
        self.snippets_window_bottom.setVisible(not self.snippets_window_bottom.isVisible())

    def toggle_editor_tab(self):
        self.editor_tab_widget.setVisible(not self.editor_tab_widget.isVisible())

    def toggle_terminal(self):
        self.toggle_repl()

    def apply_font_size_to_all_tabs(self, font_size: int):
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            if hasattr(w, "qpart"):
                w.qpart.zoom_level = font_size
                w.qpart.set_zoom_font()

    def apply_ui_font_size(self, size: int):
        self.repl_panel.set_font_size(size)
        font_css = f"font-size: {size}pt;"
        self.fileView.setStyleSheet(f"QTreeView {{ {font_css} }}")
        if hasattr(self, 'snippet_manager') and self.snippet_manager:
            self.snippet_manager.tree_widget.setStyleSheet(f"QTreeWidget {{ {font_css} }}")
        self.bottom_panel.setStyleSheet(
            f"QTabWidget::pane {{ border-top: 1px solid {CS_ACCENT_SOFT}; }}\n"
            f"QTabBar::tab {{ {font_css} }}"
        )

    def apply_editor_settings(self, config: dict = None):
        """Apply the editor settings the dialog writes.

        tab_width, autocomplete, line_numbers and vim_mode were round tripped
        through the config and never read by anything.
        """
        cfg = (config or self._load_config()).get("editor", {})
        width  = int(cfg.get("tab_width", 4))
        auto   = bool(cfg.get("autocomplete", True))
        nums   = bool(cfg.get("line_numbers", True))
        vim    = bool(cfg.get("vim_mode", False))
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            q = getattr(w, "qpart", None)
            if q is None:
                continue
            try:
                q.indentWidth = width
                q.completionEnabled = auto
                if hasattr(q, "_margins") and q._margins:
                    q._margins[0].setVisible(nums)
                    q.updateViewport()
                if hasattr(q, "vimModeEnabled"):
                    q.vimModeEnabled = vim
            except Exception:
                pass

    def show_settings(self):
        dlg = SettingsDialog(self.window)
        dlg.exec()
        config = self._load_config()
        font_size = int(config.get("editor", {}).get("font_size", 10))
        self.apply_font_size_to_all_tabs(font_size)
        ui_font_size = int(config.get("ui", {}).get("font_size", 10))
        self.apply_ui_font_size(ui_font_size)
        self.apply_editor_settings(config)

    def show_find_replace_dialog(self):
        idx = self.editor_tab_widget.currentIndex()
        if idx < 0:
            return
        widget = self.editor_tab_widget.widget(idx)
        if hasattr(widget, 'qpart'):
            self._find_replace_dlg = FindReplaceWidget(widget)
            self._find_replace_dlg.show()

    def _load_config(self):
        from .app import CONFIG_FILE
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _repoint_open_tabs(self, old_path: str, new_path: str):
        """After a rename, update every open tab whose file lived at or under
        old_path so that future saves go to the new location."""
        old_norm = os.path.normcase(os.path.abspath(old_path))
        sep = os.sep
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            fp = getattr(w, '_file_path', None) or getattr(w, 'current_file', None)
            if not fp:
                continue
            fp_norm = os.path.normcase(os.path.abspath(fp))
            if fp_norm == old_norm:
                # Exact match (file renamed directly)
                w._file_path = new_path
                w.current_file = new_path
                self.editor_tab_widget.setTabText(i, os.path.basename(new_path))
            elif fp_norm.startswith(old_norm + sep):
                # Child of a renamed folder
                rel = fp[len(old_path):]
                updated = new_path + rel
                w._file_path = updated
                w.current_file = updated
                # Tab title (filename) doesn't change for folder renames.

    def _close_tabs_under_path(self, path: str):
        """After a delete, close every open tab whose file lived at or under
        path. Iterate from the end so indices don't shift."""
        norm = os.path.normcase(os.path.abspath(path))
        sep = os.sep
        for i in range(self.editor_tab_widget.count() - 1, -1, -1):
            w = self.editor_tab_widget.widget(i)
            fp = getattr(w, '_file_path', None) or getattr(w, 'current_file', None)
            if not fp:
                continue
            fp_norm = os.path.normcase(os.path.abspath(fp))
            if fp_norm == norm or fp_norm.startswith(norm + sep):
                if w and hasattr(w, 'qpart'):
                    self.debugger_panel.uninstall_gutter(w.qpart)
                    try:
                        w.qpart.terminate()
                    except Exception:
                        pass
                if hasattr(w, 'autosave_timer'):
                    try:
                        w.autosave_timer.stop()
                    except Exception:
                        pass
                self.editor_tab_widget.removeTab(i)
                if w is not None:
                    w.deleteLater()

    def confirm_close(self) -> bool:
        """Prompt for unsaved tabs before the app quits.

        Returns False if the user cancels, in which case the window must stay
        open. Previously the app exited without ever checking _modified.
        """
        dirty = []
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            if getattr(w, '_modified', False):
                dirty.append((i, _strip_dirty(self.editor_tab_widget.tabText(i))))
        if not dirty:
            return True

        names = "\n".join("  " + n for _, n in dirty)
        reply = QMessageBox.question(
            self.window, "Unsaved Changes",
            f"These files have unsaved changes:\n\n{names}\n\nSave before quitting?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Discard:
            return True
        for i, _ in dirty:
            self.editor_tab_widget.setCurrentIndex(i)
            if not self.on_save():
                return False
        return True

    def terminate_editors(self):
        """qutepart requires terminate() before the app stops or its
        highlighter and completer threads can crash on shutdown. close_tab
        does this per tab; tabs still open at quit were being skipped."""
        for i in range(self.editor_tab_widget.count()):
            w = self.editor_tab_widget.widget(i)
            try:
                if hasattr(w, 'qpart'):
                    w.qpart.terminate()
            except Exception:
                pass

    def save_editor_state(self):
        pass  # Extend later to persist open tabs