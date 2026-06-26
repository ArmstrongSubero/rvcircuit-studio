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

_IDE_ROOT = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

def _icon(name):
    """Load icon from icons/ directory, preferring SVG for consistency."""
    base = os.path.join(_IDE_ROOT, "icons")
    stem = os.path.splitext(name)[0]
    for ext in (".svg", ".png"):
        path = os.path.join(base, stem + ext)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()

class ToolbarManager:
    def __init__(self, parent: QWidget, editor, window: QMainWindow):
        self.toolbar = QToolBar("Circuit Studio Toolbar", parent)
        _is_mac = platform.system() == "Darwin"
        _icon_sz = 28 if _is_mac else 24
        self.toolbar.setIconSize(QSize(_icon_sz, _icon_sz))
        self.toolbar.setMovable(False)
        self.editor = editor
        self.window = window

        self._create_actions()
        self._create_serial_widgets()
        self._add_actions_to_toolbar()
        self._add_accent_line(parent)
        self._connect_actions()

    def _create_actions(self):
        self.new_project_action = QAction(_icon("new_project.png"),  "New Project",  self.toolbar)
        self.open_project_action = QAction(_icon("open_project.png"), "Open Project", self.toolbar)
        self.new_tab_action      = QAction(_icon("new_icon.png"),     "New File",     self.toolbar)
        self.save_action         = QAction(_icon("save_icon.png"),    "Save",         self.toolbar)
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_as_action      = QAction(_icon("save_as_icon.png"), "Save As",      self.toolbar)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.close_action        = QAction(_icon("close.png"),        "Close",        self.toolbar)

        self.toggle_explorer_action = QAction(_icon("explorer.svg"), "Explorer", self.toolbar)
        self.toggle_explorer_action.setToolTip("Toggle Explorer")
        self.toggle_explorer_action.setCheckable(True)

        self.toggle_snippets_action = QAction(_icon("snippets.svg"), "Snippets", self.toolbar)
        self.toggle_snippets_action.setToolTip("Toggle Snippets")
        self.toggle_snippets_action.setCheckable(True)

        self.toggle_editor_action = QAction(_icon("code_panel.svg"), "Code", self.toolbar)
        self.toggle_editor_action.setToolTip("Toggle Code Panel")
        self.toggle_editor_action.setCheckable(True)

        self.toggle_repl_action = QAction(_icon("terminal.svg"), "Terminal", self.toolbar)
        self.toggle_repl_action.setToolTip("Toggle REPL Terminal")
        self.toggle_repl_action.setCheckable(True)

        self.toggle_debug_panel_action = QAction(_icon("debug_panel.svg"), "Debug", self.toolbar)
        self.toggle_debug_panel_action.setToolTip("Toggle Debug Panel (watches, config)")
        self.toggle_debug_panel_action.setCheckable(True)

        self.run_action = QAction(_icon("run.png"), "Run (Save to Board)", self.toolbar)
        self.run_action.setToolTip("Save code.py to CIRCUITPY drive - board auto-reloads")

        self.start_debug_action = QAction(_icon("debug_start.png"), "Start Debugging", self.toolbar)
        self.start_debug_action.setToolTip("Start a step-through debug session on the board")

        self.format_action = QAction(_icon("format.svg"), "Format", self.toolbar)
        self.format_action.setToolTip("Format code with Black")

        self.serial_action = QAction(_icon("serial.svg"), "REPL", self.toolbar)
        self.serial_action.setToolTip("Open REPL and connect to board")
        self.serial_action.setCheckable(True)

        self.plotter_action = QAction(_icon("run_script.png"), "Plotter", self.toolbar)
        self.plotter_action.setToolTip("Toggle serial data plotter")
        self.plotter_action.setCheckable(True)

        self.libraries_action = QAction(_icon("libraries_128.png"), "Libraries", self.toolbar)
        self.libraries_action.setToolTip("Manage CIRCUITPY/lib/ library files")

        self.find_replace_action = QAction(_icon("find_replace.png"), "Find && Replace", self.toolbar)
        self.settings_action     = QAction(_icon("settings.png"),     "Settings",        self.toolbar)
        self.about_action        = QAction(_icon("rovari_logo.svg"),  "About",           self.toolbar)

    def _create_serial_widgets(self):
        """Port + baud dropdowns - same as RV Circuit Studio."""
        self.port_label = QLabel(" Port ")
        self.port_label.setStyleSheet(
            f"font-size:10px;color:{CS_TEXT_MUTED};font-family:'JetBrains Mono';"
            "letter-spacing:0.5px;"
        )

        self.port_combo = QComboBox()
        self.port_combo.setFixedWidth(150)
        self.port_combo.setToolTip("Serial / REPL port")

        self.port_refresh_btn = QPushButton()
        _refresh_icon = _icon("refresh.svg")
        self.port_refresh_btn.setIcon(_refresh_icon)
        self.port_refresh_btn.setIconSize(QSize(18, 18))
        self.port_refresh_btn.setFixedSize(32, 32)
        self.port_refresh_btn.setToolTip("Refresh ports")
        self.port_refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid transparent;
                border-radius: 6px; padding: 0;
            }}
            QPushButton:hover {{
                background: rgba(88,166,255,0.12);
                border: 1px solid rgba(88,166,255,0.2);
            }}
        """)
        self.port_refresh_btn.clicked.connect(self._refresh_ports)

        self.baud_label = QLabel(" Baud ")
        self.baud_label.setStyleSheet(
            f"font-size:10px;color:{CS_TEXT_MUTED};font-family:'JetBrains Mono';"
        )

        self.baud_combo = QComboBox()
        self.baud_combo.setFixedWidth(120)
        for baud in ["9600","19200","38400","57600","115200","230400","460800","921600"]:
            self.baud_combo.addItem(baud)
        idx = self.baud_combo.findText("115200")
        if idx >= 0:
            self.baud_combo.setCurrentIndex(idx)

        self.port_combo.currentTextChanged.connect(self._on_port_changed)
        self.baud_combo.currentTextChanged.connect(self._on_baud_changed)

    def _add_accent_line(self, parent):
        self.accent_line = QFrame(parent)
        self.accent_line.setFixedHeight(2)
        self.accent_line.setStyleSheet(f"""
            background: qlineargradient(x1:0, x2:1,
                stop:0 {CS_PRIMARY}, stop:0.4 {CS_ACCENT},
                stop:0.7 rgba(88,166,255,0.3), stop:1 transparent);
        """)

    def _add_actions_to_toolbar(self):
        self.toolbar.addAction(self.new_project_action)
        self.toolbar.addAction(self.open_project_action)
        self.toolbar.addAction(self.new_tab_action)
        self.toolbar.addAction(self.save_action)
        self.toolbar.addAction(self.save_as_action)
        self.toolbar.addAction(self.close_action)
        self.toolbar.addSeparator()

        self.toolbar.addAction(self.toggle_explorer_action)
        self.toolbar.addAction(self.toggle_snippets_action)
        self.toolbar.addAction(self.toggle_editor_action)
        self.toolbar.addAction(self.toggle_repl_action)
        self.toolbar.addAction(self.toggle_debug_panel_action)
        self.toolbar.addSeparator()

        self.toolbar.addAction(self.run_action)
        self.toolbar.addAction(self.start_debug_action)
        self.toolbar.addAction(self.format_action)
        self.toolbar.addAction(self.plotter_action)
        self.toolbar.addAction(self.libraries_action)
        self.toolbar.addSeparator()

        self.toolbar.addWidget(self.port_label)
        self.toolbar.addWidget(self.port_combo)
        self.toolbar.addWidget(self.port_refresh_btn)
        self.toolbar.addWidget(self.baud_label)
        self.toolbar.addWidget(self.baud_combo)
        self.toolbar.addSeparator()

        self.save_status_label = QLabel("● Safe to remove")
        self.save_status_label.setFixedWidth(180)
        self.save_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.save_status_label.setStyleSheet(f"font-size: 10pt; padding: 0 8px; color: {CS_SUCCESS};")
        self.toolbar.addWidget(self.save_status_label)
        self.toolbar.addSeparator()

        self.toolbar.addAction(self.find_replace_action)
        self.toolbar.addAction(self.settings_action)
        self.toolbar.addAction(self.about_action)

    def _connect_actions(self):
        self.new_project_action.triggered.connect(self.editor.create_new_project)
        self.open_project_action.triggered.connect(self.editor.open_existing_project)
        self.new_tab_action.triggered.connect(self.editor.add_new_tab)
        self.save_action.triggered.connect(self.editor.on_save)
        self.save_as_action.triggered.connect(self.editor.on_save_as)
        self.window.addAction(self.save_action)
        self.window.addAction(self.save_as_action)
        self.close_action.triggered.connect(
            lambda: self.editor.close_tab(self.editor.editor_tab_widget.currentIndex())
        )

        self.toggle_explorer_action.triggered.connect(self.editor.toggle_snippets_top)
        self.toggle_snippets_action.triggered.connect(self.editor.toggle_snippets_bottom)
        self.toggle_editor_action.triggered.connect(self.editor.toggle_editor_tab)
        self.toggle_repl_action.triggered.connect(self.editor.toggle_terminal)
        self.toggle_debug_panel_action.triggered.connect(self.editor._on_debug_tab_clicked)

        self.run_action.triggered.connect(self.editor.run_on_board)
        self.start_debug_action.triggered.connect(self.editor.start_cp_debugging)
        self.format_action.triggered.connect(self.editor.format_code)
        self.serial_action.triggered.connect(self.editor.toggle_serial)
        self.plotter_action.triggered.connect(self.editor.toggle_plotter)
        self.libraries_action.triggered.connect(self.editor.show_library_manager)

        self.find_replace_action.triggered.connect(self.editor.show_find_replace_dialog)
        self.settings_action.triggered.connect(self.editor.show_settings)
        self.about_action.triggered.connect(self._show_about)

    def show_save_status(self, success: bool):
        if success:
            self.save_status_label.setText("● Saved to board")
            self.save_status_label.setStyleSheet(
                f"font-size: 10pt; padding: 0 8px; color: {CS_SUCCESS};"
            )
            QTimer.singleShot(3000, self._show_safe_to_remove)
        else:
            self.save_status_label.setText("● Write error")
            self.save_status_label.setStyleSheet(
                f"font-size: 10pt; padding: 0 8px; color: {CS_DANGER};"
            )

    def show_saving_in_progress(self):
        self.save_status_label.setText("● Do not remove")
        self.save_status_label.setStyleSheet(
            f"font-size: 10pt; padding: 0 8px; color: {CS_DANGER};"
        )

    def _show_safe_to_remove(self):
        self.save_status_label.setText("● Safe to remove")
        self.save_status_label.setStyleSheet(
            f"font-size: 10pt; padding: 0 8px; color: {CS_SUCCESS};"
        )

    def initial_port_scan(self):
        self._refresh_ports()

    def _refresh_ports(self):
        try:
            import serial.tools.list_ports
            current = self.port_combo.currentText()
            self.port_combo.clear()
            ports = [p.device for p in serial.tools.list_ports.comports()]
            for p in ports:
                self.port_combo.addItem(p)
            idx = self.port_combo.findText(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
            elif self.port_combo.count() > 0:
                self.port_combo.setCurrentIndex(0)
        except ImportError:
            pass

    def _on_port_changed(self, port):
        if hasattr(self.editor, 'repl_panel'):
            self.editor.repl_panel._port = port

    def _on_baud_changed(self, baud_str):
        try:
            baud = int(baud_str)
            if hasattr(self.editor, 'repl_panel'):
                self.editor.repl_panel._baud = baud
        except ValueError:
            pass

    def get_toolbar(self):
        return self.toolbar

    def get_accent_line(self):
        return self.accent_line

    def _show_about(self):
        dlg = QDialog(self.toolbar)
        dlg.setWindowTitle("About RV Circuit Studio")
        dlg.setFixedSize(360, 340)
        dlg.setStyleSheet(f"QDialog {{ background: {CS_SURFACE}; }} QLabel {{ color: {CS_TEXT}; background: transparent; }}")

        layout = QVBoxLayout(dlg)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        title = QLabel("RV Circuit Studio")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size:20px;font-weight:bold;color:{CS_ACCENT};font-family:'JetBrains Mono';")
        layout.addWidget(title)

        sub = QLabel("CircuitPython IDE")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-size:12px;color:{CS_SUCCESS};font-family:'JetBrains Mono';")
        layout.addWidget(sub)

        from ._version import __version__
        ver = QLabel(f"v{__version__}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(f"font-size:11px;color:{CS_TEXT_MUTED};")
        layout.addWidget(ver)

        tag = QLabel("The Mu Editor replacement.\nBuilt on PySide6 + qutepart.")
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet(f"font-size:11px;color:{CS_TEXT_MUTED};font-style:italic;")
        layout.addWidget(tag)

        layout.addSpacing(8)

        author = QLabel("Created by Armstrong Subero")
        author.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(author)

        url = QLabel(f'<a href="https://rvembedded.com" style="color:{CS_ACCENT};">rvembedded.com</a>')
        url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url.setOpenExternalLinks(True)
        layout.addWidget(url)

        layout.addSpacing(8)

        copy = QLabel("© 2026 Armstrong Subero. Apache License 2.0.")
        copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copy.setStyleSheet(f"font-size:9px;color:{CS_TEXT_MUTED};")
        layout.addWidget(copy)

        btn = QPushButton("OK")
        btn.setFixedWidth(80)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        dlg.exec()