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

    def __init__(self, window: QMainWindow, project_dir=None):
        super().__init__()
        self.window = window
        self.current_project_directory = project_dir
        self._board_drive = None
        self._repl_port   = None
        self._repl_running = True  # assume code is running when connected

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.toolbar_manager = ToolbarManager(self, self, self.window)
        self.main_layout.addWidget(self.toolbar_manager.get_toolbar())
        self.main_layout.addWidget(self.toolbar_manager.get_accent_line())

        self._build_board_status_bar()

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
        self.central_splitter.setSizes([220, 900])

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

        self.debug_tab_btn = QPushButton("Debug")
        self.debug_tab_btn.setStyleSheet(_btn_style_inactive)

        tab_bar_layout.addWidget(self.repl_tab_btn)
        tab_bar_layout.addWidget(self.plotter_tab_btn)
        tab_bar_layout.addWidget(self.debug_tab_btn)
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
        self.debugger_panel = DebuggerPanel(repl_widget=None, parent=self)
        self.bottom_stack.addWidget(self.repl_panel)      # index 0
        self.bottom_stack.addWidget(self.plotter_panel)   # index 1
        self.bottom_stack.addWidget(self.debugger_panel)  # index 2

        bottom_layout.addWidget(tab_bar)
        bottom_layout.addWidget(self.bottom_stack)

        self.bottom_panel.setMinimumHeight(32)
        self.bottom_panel.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Preferred)

        self.repl_panel.data_received.connect(self._on_serial_data)
        self.repl_panel.data_received.connect(self.debugger_panel.feed_serial)

        self.repl_tab_btn.clicked.connect(self._on_repl_tab_clicked)
        self.plotter_tab_btn.clicked.connect(lambda: self._switch_bottom_tab(1))
        self.debug_tab_btn.clicked.connect(self._on_debug_tab_clicked)

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

        self.toolbar_manager.initial_port_scan()
        if project_dir:
            self._open_project(project_dir)

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

        boot = read_boot_out(drive)
        self._cp_version  = boot.get("version", "9")
        self._cp_major    = boot.get("major", "9")
        self._board_name  = boot.get("board", "")

        if boot.get("version"):
            status_msg = (
                f"Board connected: {self._board_name}  |  "
                f"CircuitPython {self._cp_version}  |  "
                f"Drive: {drive}  Port: {port}"
            )
        else:
            status_msg = f"Board connected — Drive: {drive}  Port: {port}"
        self._set_board_status_ui(BoardStatus.CONNECTED, drive, port)
        self.window.statusBar().showMessage(status_msg, 8000)

        if boot.get("version") and boot.get("board_id"):
            def _on_update_found(board_ver, latest_ver, url,
                                 _win=self.window, _bname=self._board_name):
                def _show():
                    reply = QMessageBox.question(
                        _win,
                        "CircuitPython Update Available",
                        f"Your board is running CircuitPython {board_ver}.\n"
                        f"The latest stable release is {latest_ver}.\n\n"
                        f"Would you like to open the download page for\n"
                        f"{_bname}?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        from PySide6.QtGui import QDesktopServices
                        from PySide6.QtCore import QUrl
                        QDesktopServices.openUrl(QUrl(url))
                QTimer.singleShot(0, _show)
            check_cp_version_async(
                boot["version"], boot.get("board_id", ""), _on_update_found
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

            idx = self.toolbar_manager.port_combo.findText(port)
            if idx < 0:
                self.toolbar_manager.port_combo.addItem(port)
                idx = self.toolbar_manager.port_combo.findText(port)
            self.toolbar_manager.port_combo.setCurrentIndex(idx)

        self.debugger_panel.set_drive(drive)
        self.debugger_panel.set_repl(self.repl_panel)

    def _on_board_disconnected(self):
        self._board_drive = None
        self._repl_port   = None
        self._repl_running = True  # assume code is running when connected
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
            ok = save_to_board(code, drive, filename)
            if ok:
                self._repl_running = True
                self._set_run_btn_state(running=True)
                self.window.statusBar().showMessage(
                    f"▶ Running — saved to {drive}{filename}", 3000)
                if self.repl_panel.is_connected:
                    self.repl_panel.send_soft_reboot()
            else:
                QMessageBox.critical(self.window, "Save Failed",
                                     f"Could not write to {drive}.\n"
                                     "Check board is not in safe mode.")

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
        """Legacy stop — now handled by run_on_board toggle."""
        self.run_on_board()

    def _set_run_btn_state(self, running: bool):
        """Update run button appearance: purple bg when at REPL (stopped), normal when running."""
        btn = self.toolbar_manager.run_action
        w = self.toolbar_manager.toolbar.widgetForAction(btn)
        if running:
            btn.setText("■ Stop")
            btn.setToolTip("Stop running code (Ctrl+C)")
            if w:
                w.setStyleSheet("")
        else:
            btn.setText("▶ Run")
            btn.setToolTip("Save and run on board")
            if w:
                w.setStyleSheet("background: #6c3fc4; border-radius: 4px; padding: 2px 4px;")

    def _on_repl_tab_clicked(self):
        """REPL tab button: just switch back to REPL tab."""
        self._switch_bottom_tab(0)

    def _on_debug_tab_clicked(self):
        """Debug tab button: show debugger panel and pass drive/repl refs."""
        self.bottom_panel.setVisible(True)
        self.debugger_panel.set_repl(self.repl_panel)
        if self._board_drive:
            self.debugger_panel.set_drive(self._board_drive)
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
        self.debug_tab_btn.setStyleSheet(_active  if index == 2 else _inactive)

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
                f"Library Manager — targeting CircuitPython {cp_version} bundle", 4000
            )
        dlg = LibraryManagerDialog(drive, cp_version=cp_version, parent=self.window)
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
        m = matches[-1]
        filename = m.group(1)
        line_num = int(m.group(2))
        if filename not in ('code.py', 'main.py'):
            return
        self._highlight_editor_line(filename, line_num)

    def _highlight_editor_line(self, filename: str, line_num: int):
        """Find the open tab matching filename and highlight line_num.
        If the file isn't open yet, open it first."""
        for i in range(self.editor_tab_widget.count()):
            widget = self.editor_tab_widget.widget(i)
            fp = getattr(widget, '_file_path', None) or getattr(widget, 'current_file', None)
            if fp and os.path.basename(fp) == filename:
                if hasattr(widget, 'highlight_error_line'):
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

    def on_save(self):
        """Save current tab. If CIRCUITPY is mounted and auto-save is on, save to board."""
        idx = self.editor_tab_widget.currentIndex()
        if idx < 0:
            return
        tab_title = self.editor_tab_widget.tabText(idx)
        widget    = self.editor_tab_widget.widget(idx)
        code      = self._get_current_editor_text()
        if code is None:
            return

        config    = self._load_config()
        auto_save = config.get("board", {}).get("auto_save", True)
        filename  = config.get("board", {}).get("filename", "code.py")
        drive     = self._board_drive

        current_path = getattr(widget, '_file_path', None)
        if not current_path:
            self.on_save_as()
            return

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
                    f"✓ Saved to board — reloading…", 3000
                )
        except Exception as e:
            self.toolbar_manager.show_save_status(False)
            QMessageBox.critical(self.window, "Save Error", str(e))

    def on_save_as(self):
        idx = self.editor_tab_widget.currentIndex()
        if idx < 0:
            return
        widget = self.editor_tab_widget.widget(idx)
        code   = self._get_current_editor_text()
        if code is None:
            return

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
            except Exception as e:
                QMessageBox.critical(self.window, "Save Error", str(e))

    def close_tab(self, idx):
        widget = self.editor_tab_widget.widget(idx)
        if widget and getattr(widget, '_modified', False):
            name = self.editor_tab_widget.tabText(idx).rstrip(" *")
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
                self.on_save()
        if widget and hasattr(widget, 'qpart'):
            self.debugger_panel.uninstall_gutter(widget.qpart)
        self.editor_tab_widget.removeTab(idx)

    def open_file_from_tree(self, index):
        source_idx = self.proxyModel.mapToSource(index)
        path = self.fileSystemModel.filePath(source_idx)
        if os.path.isfile(path):
            self._open_file(path)

    def _open_file(self, path: str):
        norm_path = os.path.normcase(os.path.abspath(path))
        basename  = os.path.basename(path)
        for i in range(self.editor_tab_widget.count()):
            w  = self.editor_tab_widget.widget(i)
            fp = getattr(w, '_file_path', None) or getattr(w, 'current_file', None)
            if fp:
                try:
                    if os.path.normcase(os.path.abspath(fp)) == norm_path:
                        if hasattr(w, 'openFile'):
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
            self.debugger_panel.install_gutter(editor.qpart, basename)

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
            elif hasattr(self, '_file_path') and self._file_path == path:
                self._file_path = new_path
                self.window.setWindowTitle(f"RV Circuit Studio — {new_name}")
            self.window.statusBar().showMessage(f"Renamed {old_name} → {new_name}", 2000)
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
            if hasattr(self, '_file_path') and self._file_path == path:
                self._file_path = None
                self.editor.setPlainText("")
                self.window.setWindowTitle("RV Circuit Studio")
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

        self.window.setWindowTitle(f"RV Circuit Studio — {os.path.basename(path)}")

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

    def show_settings(self):
        dlg = SettingsDialog(self.window)
        dlg.exec()
        config = self._load_config()
        font_size = int(config.get("editor", {}).get("font_size", 10))
        self.apply_font_size_to_all_tabs(font_size)

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
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_editor_state(self):
        pass  # Extend later to persist open tabs

